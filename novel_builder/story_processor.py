"""Main generation loop and orchestration.

This module ties everything together: iterates through chapters and scenes,
builds prompts, calls the LLM, post-processes output, writes to file,
updates checkpoints, and handles graceful shutdown.
"""

import os
import signal
import sys
import threading

from .characters import auto_detect_characters, load_characters
from .locations import load_locations
from .ollama_client import call_ollama_with_retry, call_summary_model, OllamaError
from .postprocess import clean_scene_text, apply_anti_patterns, strip_scene_header
from .prompt_builder import build_system_prompt, build_scene_prompt
from .state import (
    init_state,
    load_checkpoint,
    save_checkpoint,
    should_resume,
    update_after_scene,
    resumption_point,
)


# Module-level flag for graceful shutdown
_shutdown_requested = False


def _handle_interrupt(signum, frame):
    """Handle Ctrl+C by setting shutdown flag."""
    global _shutdown_requested
    if _shutdown_requested:
        # Second Ctrl+C — force exit
        print("\n\nForce quit.")
        sys.exit(1)
    _shutdown_requested = True
    print("\n\nShutdown requested — finishing current scene, then saving...")


def request_stop():
    """Request graceful stop from outside (e.g., web UI)."""
    global _shutdown_requested
    _shutdown_requested = True


def is_running():
    """Check if generation is currently in progress."""
    return not _shutdown_requested


def generate_story(config, args, event_callback=None):
    """Main entry point for story generation.

    Orchestrates the full generation loop: chapters → scenes → prompts →
    LLM → post-process → write → checkpoint.

    Args:
        config: Story configuration dict from load_config().
        args: Parsed CLI args namespace.
        event_callback: Optional callable(event_type, data_dict) for
            live progress reporting (used by web UI).
    """
    global _shutdown_requested
    _shutdown_requested = False

    # Only register signal handler on the main thread
    if threading.current_thread() is threading.main_thread():
        original_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, _handle_interrupt)
    else:
        original_handler = None

    try:
        _run_generation(config, args, event_callback)
    finally:
        if original_handler is not None:
            signal.signal(signal.SIGINT, original_handler)


def _run_generation(config, args, event_callback=None):
    """Internal generation loop."""
    global _shutdown_requested

    def emit(event_type, **data):
        """Send event to callback if registered."""
        if event_callback:
            try:
                event_callback(event_type, data)
            except Exception:
                pass  # Never let callback errors break generation

    # Load story data
    chapters = config.get("chapters", [])
    if not chapters:
        print("Error: No chapters found in story outline.")
        emit("status_change", status="error", message="No chapters found")
        return

    all_characters = load_characters(config)
    locations = load_locations(config)
    heritage_defs = config.get("heritage", {})

    # Output file
    output_file = args.output or _default_output_name(config)

    # Checkpoint/resume
    checkpoint_path = getattr(args, 'checkpoint_path', None)
    checkpoint = load_checkpoint(checkpoint_path)
    state = None

    if should_resume(args, checkpoint):
        state = checkpoint
        start_ch, start_sc = resumption_point(state, chapters)
        print(f"\nResuming from Chapter {start_ch + 1}, "
              f"Scene index {start_sc}...")
    else:
        state = init_state(config, output_file)
        start_ch, start_sc = 0, 0
        # Clear output file for fresh start
        _init_output_file(output_file, config)

    # Build system prompt (consistent across scenes)
    system_prompt = build_system_prompt(config)

    if args.dry_run:
        _dry_run(config, chapters, system_prompt, state, heritage_defs,
                 all_characters, locations, start_ch, start_sc)
        return

    total_chapters = len(chapters)
    all_scene_count = sum(len(ch.get("scenes", [])) for ch in chapters)
    scenes_completed = _count_scenes_before(chapters, start_ch, start_sc)

    print(f"\n{'=' * 60}")
    print(f"  {config.get('story_title', 'Untitled')}")
    print(f"  {total_chapters} chapters to generate")
    print(f"  Model: {args.model}")
    print(f"  Output: {output_file}")
    print(f"{'=' * 60}\n")

    emit("status_change", status="running")
    emit("progress", chapter=start_ch + 1, total_chapters=total_chapters,
         scene=scenes_completed, total_scenes=all_scene_count,
         percent=int(100 * scenes_completed / all_scene_count) if all_scene_count else 0)
    emit("log", message=f"Starting: {config.get('story_title', 'Untitled')} "
         f"— {total_chapters} chapters, {all_scene_count} scenes", level="info")

    for ch_idx in range(start_ch, total_chapters):
        if _shutdown_requested:
            break

        chapter = chapters[ch_idx]
        ch_num = chapter.get("chapter_number", ch_idx + 1)
        ch_title = chapter.get("title", f"Chapter {ch_num}")
        scenes = chapter.get("scenes", [])

        print(f"\n--- Chapter {ch_num}/{total_chapters}: {ch_title} ---")
        emit("log", message=f"Chapter {ch_num}/{total_chapters}: {ch_title}", level="info")

        # Write chapter header to output — only if not already present (guards against re-runs)
        sc_start = start_sc if ch_idx == start_ch else 0
        if sc_start == 0:
            _write_chapter_header_if_needed(output_file, ch_num, ch_title)

        for sc_idx in range(sc_start, len(scenes)):
            if _shutdown_requested:
                break

            scene = scenes[sc_idx]
            scene_num = scene.get(
                "scene_number", f"{ch_num}.{sc_idx + 1}")
            scene_title = scene.get("title", "")

            scene_count_in_ch = len(scenes)
            label = f"Scene {scene_num}"
            if scene_title:
                label += f": {scene_title}"
            print(f"  [{sc_idx + 1}/{scene_count_in_ch}] {label}")
            emit("log", message=f"Scene {scene_num}: {scene_title or 'untitled'}", level="info")
            pct = int(100 * scenes_completed / all_scene_count) if all_scene_count else 0
            emit("progress", chapter=ch_num, total_chapters=total_chapters,
                 scene=scenes_completed, total_scenes=all_scene_count, percent=pct)

            # Detect characters
            scene_text = f"{scene.get('events', '')} {scene.get('notes', '')}"
            explicit_chars = scene.get("characters", [])
            if explicit_chars:
                present_ids = list(explicit_chars)
            else:
                present_ids = auto_detect_characters(
                    scene_text, all_characters)
            if present_ids:
                names = [
                    (all_characters.get(cid, {}).get("Name") or cid)
                    for cid in present_ids
                ]
                print(f"    Characters: {', '.join(names)}")

            # Build scene prompt
            user_prompt = build_scene_prompt(
                config, chapter, scene, state, heritage_defs,
                all_characters, locations, ch_num,
            )

            # Call generation model
            emit("model_active", model="generation", name=args.model)
            try:
                raw_text = call_ollama_with_retry(
                    args.host,
                    args.model,
                    system_prompt,
                    user_prompt,
                    timeout=args.timeout,
                    retries=args.retries,
                    emit_callback=emit,
                )
            except OllamaError as e:
                emit("model_active", model="idle", name="")
                print(f"    ERROR: Generation failed — {e}")
                print("    Saving checkpoint and stopping.")
                emit("log", message=f"Generation failed: {e}", level="error")
                emit("status_change", status="error", message=str(e))
                save_checkpoint(state, checkpoint_path)
                return
            emit("model_active", model="idle", name="")

            # Post-process
            text = clean_scene_text(raw_text)
            text = strip_scene_header(text, scene_num)

            # Anti-pattern check
            _, warnings = apply_anti_patterns(text, config.get("anti_patterns"))
            if warnings:
                print(f"    Anti-pattern warnings: {len(warnings)}")
                for pat, match, line in warnings[:3]:
                    print(f"      Line {line}: \"{match}\"")

            # Write to file
            _write_scene(output_file, scene_num, scene_title, text)

            # Print to terminal (unless quiet)
            if not args.quiet:
                _print_scene(text)

            # Summarize scene
            summary = ""
            extraction = {"characters": [], "facts": [], "commitments": []}
            emit("model_active", model="summarization", name=getattr(args, 'summary_model', 'gemma3:1b'))
            try:
                summary_model = args.summary_model
                summary, extraction = call_summary_model(
                    args.host, summary_model, text,
                )
                print(f"    Summary: {summary[:100]}...")
            except OllamaError as e:
                print(f"    Warning: Summary failed — {e}")
                emit("log", message=f"Summary failed: {e}", level="warn")
                # Fall back to first 200 chars
                summary = text[:200].rsplit(" ", 1)[0] + "..."
            emit("model_active", model="idle", name="")

            # Update state
            update_after_scene(
                state, ch_num, scene_num, summary,
                extraction, present_ids,
            )

            # Save checkpoint after every scene
            save_checkpoint(state, checkpoint_path)
            scenes_completed += 1
            pct = int(100 * scenes_completed / all_scene_count) if all_scene_count else 0
            emit("scene_complete", scene_num=str(scene_num), title=scene_title,
                 text=text, summary=summary, chars=len(text))
            emit("progress", chapter=ch_num, total_chapters=total_chapters,
                 scene=scenes_completed, total_scenes=all_scene_count, percent=pct)
            emit("log", message=f"✓ Scene {scene_num} complete ({len(text)} chars)", level="info")
            print(f"    ✓ Checkpoint saved")

        # Chapter complete
        if not _shutdown_requested:
            print(f"  Chapter {ch_num} complete.")

    # Done
    if _shutdown_requested:
        print(f"\nGeneration paused. Resume with: "
              f"python -m novel_builder --resume")
        emit("status_change", status="stopped")
        emit("log", message="Generation paused — resume available", level="info")
    else:
        print(f"\n{'=' * 60}")
        print(f"  Generation complete!")
        print(f"  Output: {output_file}")
        print(f"{'=' * 60}")
        emit("status_change", status="completed")
        emit("progress", chapter=total_chapters, total_chapters=total_chapters,
             scene=all_scene_count, total_scenes=all_scene_count, percent=100)
        emit("log", message="Generation complete!", level="info")
    emit("model_active", model="idle", name="")


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------

def _dry_run(config, chapters, system_prompt, state, heritage_defs,
             all_characters, locations, start_ch, start_sc):
    """Print prompts without calling the LLM.

    Useful for inspecting what would be sent to the model.
    """
    print("\n=== DRY RUN — No LLM calls will be made ===\n")
    print("--- System Prompt ---")
    print(system_prompt)
    print()

    for ch_idx in range(start_ch, len(chapters)):
        chapter = chapters[ch_idx]
        ch_num = chapter.get("chapter_number", ch_idx + 1)
        scenes = chapter.get("scenes", [])
        sc_start = start_sc if ch_idx == start_ch else 0

        for sc_idx in range(sc_start, len(scenes)):
            scene = scenes[sc_idx]
            scene_num = scene.get(
                "scene_number", f"{ch_num}.{sc_idx + 1}")

            user_prompt = build_scene_prompt(
                config, chapter, scene, state, heritage_defs,
                all_characters, locations, ch_num,
            )

            print(f"--- Scene {scene_num} User Prompt ---")
            print(user_prompt)
            print()

    print("=== End Dry Run ===")


def _count_scenes_before(chapters, start_ch, start_sc):
    """Count how many scenes were completed before the resume point."""
    count = 0
    for ch_idx in range(start_ch):
        count += len(chapters[ch_idx].get("scenes", []))
    count += start_sc
    return count


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _default_output_name(config):
    """Generate a default output filename from the story title."""
    title = config.get("story_title", "story")
    # Sanitize for filename
    safe = "".join(
        c if c.isalnum() or c in " -_" else ""
        for c in title
    ).strip().replace(" ", "_").lower()
    return f"{safe or 'story'}_output.md"


def _init_output_file(filepath, config):
    """Initialize the output file with a title header."""
    title = config.get("story_title", "Untitled")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n")


def _write_chapter_header(filepath, chapter_num, title):
    """Append a chapter header to the output file."""
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(f"\n## Chapter {chapter_num}: {title}\n\n")


def _write_chapter_header_if_needed(filepath, chapter_num, title):
    """Append a chapter header only if it does not already exist in the file.

    Prevents duplicate headers when resuming a run that stopped at the
    beginning of a chapter (sc_start == 0 but header already written).
    """
    header = f"## Chapter {chapter_num}: {title}"
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        if header in content:
            return  # Already written — skip
    _write_chapter_header(filepath, chapter_num, title)


def _write_scene(filepath, scene_num, scene_title, text):
    """Append a scene to the output file.

    Titled scenes get a heading. Untitled scenes get a blank line separator
    only — no heading, no divider — so the output reads like prose.
    """
    with open(filepath, "a", encoding="utf-8") as f:
        if scene_title:
            f.write(f"### {scene_title}\n\n{text}\n\n")
        else:
            f.write(f"{text}\n\n")


def _print_scene(text):
    """Print scene text to terminal with visual separation."""
    print()
    print("─" * 40)
    # Print first ~500 chars to avoid flooding terminal
    preview = text[:500]
    if len(text) > 500:
        preview += "\n  [...continued in output file]"
    print(preview)
    print("─" * 40)
