"""Main generation loop and orchestration.

This module ties everything together: iterates through chapters and scenes,
builds prompts, calls the LLM, post-processes output, writes to file,
updates checkpoints, and handles graceful shutdown.
"""

import os
import signal
import sys
import threading
import time
import traceback

from .characters import auto_detect_characters, load_characters
from .locations import load_locations
from .ollama_client import call_ollama_with_retry, call_summary_model, OllamaError, unload_model
from .postprocess import clean_scene_text, apply_anti_patterns, strip_scene_header
from .prompt_builder import build_system_prompt, build_scene_prompt
from .state import (
    init_state,
    load_checkpoint,
    save_checkpoint,
    should_resume,
    update_after_scene,
    update_word_frequency,
    resumption_point,
    should_compress,
    compress_story_so_far,
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
        emit("log", message=f"Resuming from Chapter {start_ch + 1}, scene index {start_sc}", level="info")
    else:
        state = init_state(config, output_file)
        start_ch, start_sc = 0, 0
        # Clear output file for fresh start
        _init_output_file(output_file, config)

    if args.dry_run:
        _dry_run(config, chapters, state, heritage_defs,
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
    emit("log", message=(
        f"Starting: {config.get('story_title', 'Untitled')} -- "
        f"{total_chapters} chapters, {all_scene_count} scenes | "
        f"Model: {args.model} | Output: {output_file}"
    ), level="info")

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

            # Detect characters -- limit auto-detection to characters that
            # have already appeared so future characters can't leak in via
            # a name mention in the scene YAML.
            scene_text = f"{scene.get('events', '')} {scene.get('notes', '')}"
            explicit_chars = scene.get("characters", [])
            if isinstance(explicit_chars, str):
                explicit_chars = [explicit_chars] if explicit_chars else []
            if explicit_chars:
                present_ids = list(explicit_chars)
            else:
                appeared = set(state.get("character_appearances", {}).keys())
                present_ids = auto_detect_characters(
                    scene_text, all_characters,
                    allowed_ids=appeared if appeared else None)
            setting_ref = scene.get("setting", "")
            if present_ids:
                names = [
                    (all_characters.get(cid, {}).get("Name") or cid)
                    for cid in present_ids
                ]
                print(f"    Characters: {', '.join(names)}")
                _scene_detail = f"Characters: {', '.join(names)}"
            else:
                print(f"    Characters: (none detected)")
                _scene_detail = "Characters: (none detected)"
            if setting_ref:
                print(f"    Setting: {setting_ref}")
                _scene_detail += f" | Setting: {setting_ref}"
            emit("log", message=_scene_detail, level="info")

            # Build system + scene prompts (system prompt is per-scene
            # because the character roster is scoped to known characters)
            try:
                system_prompt = build_system_prompt(
                    config, state=state, scene_char_ids=present_ids,
                )
            except Exception as e:
                tb = traceback.format_exc()
                emit("log",
                     message=(
                         f"Scene {scene_num}: system prompt build failed -- "
                         f"{type(e).__name__}: {e}\n\n{tb}"
                     ),
                     level="error")
                raise
            try:
                user_prompt = build_scene_prompt(
                    config, chapter, scene, state, heritage_defs,
                    all_characters, locations, ch_num,
                )
            except Exception as e:
                tb = traceback.format_exc()
                emit("log",
                     message=(
                         f"Scene {scene_num}: prompt build failed -- "
                         f"{type(e).__name__}: {e}\n\n{tb}"
                     ),
                     level="error")
                raise

            # Call generation model
            emit("model_active", model="generation", name=args.model)
            _scene_gen_t0 = time.time()
            try:
                raw_text = call_ollama_with_retry(
                    args.host,
                    args.model,
                    system_prompt,
                    user_prompt,
                    timeout=args.timeout,
                    retries=args.retries,
                    num_ctx=getattr(args, 'num_ctx', 8192),
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
            _scene_gen_elapsed = round(time.time() - _scene_gen_t0, 1)
            emit("model_active", model="idle", name="")
            print(f"    Generated in {_scene_gen_elapsed}s")
            emit("log", message=f"Scene {scene_num} generated in {_scene_gen_elapsed}s", level="info")

            # Post-process
            text = clean_scene_text(raw_text)
            text = strip_scene_header(text, scene_num)

            # Anti-pattern check
            _, warnings = apply_anti_patterns(text, config.get("anti_patterns"))
            if warnings:
                print(f"    Anti-pattern warnings: {len(warnings)}")
                for pat, match, line in warnings[:3]:
                    print(f"      Line {line}: \"{match}\"")
                emit("log", message=(
                    f"Anti-pattern warnings ({len(warnings)}): "
                    + "; ".join(f'"{m}" (line {ln})' for _, m, ln in warnings[:3])
                ), level="warn")

            # Write to file
            _write_scene(output_file, scene_num, scene_title, text)

            # Print to terminal (unless quiet)
            if not args.quiet:
                _print_scene(text)

            # Track sensory/atmospheric word frequency for variety nudges
            update_word_frequency(state, text)

            # Summarize scene
            summary = ""
            extraction = {"characters": [], "facts": [], "actions": [], "commitments": [], "used_imagery": []}
            _models_differ = args.model != getattr(args, 'summary_model', args.model)
            # Free generation model memory before loading summary model
            if _models_differ:
                unload_model(args.host, args.model, emit)
            emit("model_active", model="summarization", name=getattr(args, 'summary_model', 'gemma3:4b'))
            setting_id = scene.get("setting", "") or ""
            try:
                summary_model = args.summary_model
                char_names = [
                    (all_characters.get(cid, {}).get("Name") or cid)
                    for cid in present_ids
                ]
                all_known_names = [
                    (all_characters.get(cid, {}).get("Name") or cid)
                    for cid in all_characters
                ]
                scene_meta = {
                    "scene_id": str(scene_num),
                    "title": scene_title,
                    "characters": char_names,
                    "setting": setting_id,
                }
                summary, extraction = call_summary_model(
                    args.host, summary_model, text,
                    scene_meta=scene_meta,
                )
                print(f"    Summary: {summary[:100]}...")
                emit("log", message=f"Summary: {summary[:120]}", level="info")
                _exlog = (
                    f"Extracted: {len(extraction.get('facts', []))} fact(s), "
                    f"{len(extraction.get('actions', []))} action(s), "
                    f"{len(extraction.get('commitments', []))} commitment(s), "
                    f"{len(extraction.get('characters', []))} new char(s), "
                    f"{len(extraction.get('used_imagery', []))} imagery"
                )
                print(f"    {_exlog}")
                emit("log", message=_exlog, level="info")
            except OllamaError as e:
                print(f"    Warning: Summary failed — {e}")
                emit("log", message=f"Summary failed: {e}", level="warn")
                # Fall back to first 200 chars
                summary = text[:200].rsplit(" ", 1)[0] + "..."
            emit("model_active", model="idle", name="")
            # Free summary model memory before next generation call
            if _models_differ:
                unload_model(args.host, getattr(args, 'summary_model', args.model), emit)

            # Update state
            try:
                update_after_scene(
                    state, ch_num, scene_num, summary,
                    extraction, present_ids,
                    known_names=all_known_names,
                    setting_id=setting_id if setting_id else None,
                )
            except Exception as e:
                tb = traceback.format_exc()
                emit("log",
                     message=(
                         f"Scene {scene_num}: state update failed — "
                         f"{type(e).__name__}: {e}\n\n{tb}"
                     ),
                     level="error")
                raise

            # Save checkpoint after every scene
            save_checkpoint(state, checkpoint_path)
            scenes_completed += 1

            # Compress story_so_far periodically to stay within token budget
            if should_compress(state):
                try:
                    compress_story_so_far(state, args.host, args.summary_model)
                    save_checkpoint(state, checkpoint_path)
                except Exception as e:
                    emit("log", message=f"Compression skipped: {e}", level="warn")

            pct = int(100 * scenes_completed / all_scene_count) if all_scene_count else 0
            emit("scene_complete", scene_num=str(scene_num), title=scene_title,
                 text=text, summary=summary, chars=len(text),
                 elapsed_s=_scene_gen_elapsed, words=len(text.split()))
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

def _dry_run(config, chapters, state, heritage_defs,
             all_characters, locations, start_ch, start_sc):
    """Print prompts without calling the LLM.

    Useful for inspecting what would be sent to the model.
    """
    print("\n=== DRY RUN — No LLM calls will be made ===\n")

    for ch_idx in range(start_ch, len(chapters)):
        chapter = chapters[ch_idx]
        ch_num = chapter.get("chapter_number", ch_idx + 1)
        scenes = chapter.get("scenes", [])
        sc_start = start_sc if ch_idx == start_ch else 0

        for sc_idx in range(sc_start, len(scenes)):
            scene = scenes[sc_idx]
            scene_num = scene.get(
                "scene_number", f"{ch_num}.{sc_idx + 1}")

            # Detect characters for roster scoping
            scene_text = f"{scene.get('events', '')} {scene.get('notes', '')}"
            explicit_chars = scene.get("characters", [])
            if isinstance(explicit_chars, str):
                explicit_chars = [explicit_chars] if explicit_chars else []
            if explicit_chars:
                present_ids = list(explicit_chars)
            else:
                appeared = set(state.get("character_appearances", {}).keys())
                present_ids = auto_detect_characters(
                    scene_text, all_characters,
                    allowed_ids=appeared if appeared else None)

            system_prompt = build_system_prompt(
                config, state=state, scene_char_ids=present_ids,
            )
            user_prompt = build_scene_prompt(
                config, chapter, scene, state, heritage_defs,
                all_characters, locations, ch_num,
            )

            print(f"--- Scene {scene_num} System Prompt ---")
            print(system_prompt)
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
        f.write(f"\n<!-- chapter:{chapter_num} -->\n")
        f.write(f"## Chapter {chapter_num}: {title}\n\n")


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

    Each scene is wrapped with <!-- scene:ID --> / <!-- /scene:ID -->
    markers so individual scenes can be located and replaced by the
    regeneration feature.  The markers are invisible in rendered Markdown
    and are stripped from the downloaded file for a clean book appearance.
    """
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(f"<!-- scene:{scene_num} -->\n")
        if scene_title:
            f.write(f"### {scene_title}\n\n{text}\n\n")
        else:
            f.write(f"{text}\n\n")
        f.write(f"<!-- /scene:{scene_num} -->\n\n")


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


# ===================================================================
#  Scene / chapter regeneration
# ===================================================================

import re as _re


def _find_scene_in_config(config, scene_id):
    """Locate a scene dict and its parent chapter by scene_id.

    Returns (chapter_dict, scene_dict, chapter_number) or (None, None, None).
    """
    scene_id = str(scene_id)
    for ch_idx, chapter in enumerate(config.get("chapters", [])):
        ch_num = chapter.get("chapter_number", ch_idx + 1)
        for sc_idx, scene in enumerate(chapter.get("scenes", [])):
            sc_id = str(scene.get("scene_number", f"{ch_num}.{sc_idx + 1}"))
            if sc_id == scene_id:
                return chapter, scene, ch_num
    return None, None, None


def _replace_scene_in_file(filepath, scene_id, new_text, scene_title=""):
    """Replace a scene's content in the output markdown file using markers.

    Looks for <!-- scene:ID --> ... <!-- /scene:ID --> and replaces the
    content between them.  Returns the OLD text that was replaced (for
    logging), or None if the markers weren't found.
    """
    if not os.path.exists(filepath):
        return None

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = _re.compile(
        r'(<!-- scene:' + _re.escape(str(scene_id)) + r' -->\n)'
        r'(.*?)'
        r'(<!-- /scene:' + _re.escape(str(scene_id)) + r' -->\n)',
        _re.DOTALL,
    )
    match = pattern.search(content)
    if not match:
        return None

    old_text = match.group(2)
    if scene_title:
        replacement = f"### {scene_title}\n\n{new_text}\n\n"
    else:
        replacement = f"{new_text}\n\n"

    new_content = content[:match.start(2)] + replacement + content[match.end(2):]

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(new_content)

    return old_text


def regenerate_scene(config, args, scene_id, event_callback=None):
    """Regenerate a single scene within an existing story.

    Rebuilds the prompt using current checkpoint state (including any
    user edits to memory), calls the LLM, replaces the scene in the
    output file, re-summarises, and updates the checkpoint.

    Args:
        config: Story configuration dict.
        args: SimpleNamespace with host, model, summary_model, timeout, retries, output, checkpoint_path.
        scene_id: Scene identifier string (e.g., "2.3").
        event_callback: Optional callable(event_type, data_dict).

    Returns:
        Dict with 'ok', 'text', 'old_text', 'summary', 'scene_id', 'title'.
    """
    def emit(event_type, **data):
        if event_callback:
            try:
                event_callback(event_type, data)
            except Exception:
                pass

    scene_id = str(scene_id)
    chapter, scene, ch_num = _find_scene_in_config(config, scene_id)
    if scene is None:
        return {"ok": False, "error": f"Scene {scene_id} not found in story outline"}

    scene_title = scene.get("title", "")
    all_characters = load_characters(config)
    locations = load_locations(config)
    heritage_defs = config.get("heritage", {})

    # Load checkpoint state
    checkpoint_path = getattr(args, 'checkpoint_path', None)
    state = load_checkpoint(checkpoint_path) or {}

    output_file = args.output

    # Detect characters for roster scoping
    scene_text = f"{scene.get('events', '')} {scene.get('notes', '')}"
    explicit_chars = scene.get("characters", [])
    if isinstance(explicit_chars, str):
        explicit_chars = [explicit_chars] if explicit_chars else []
    if explicit_chars:
        present_ids = list(explicit_chars)
    else:
        appeared = set(state.get("character_appearances", {}).keys())
        present_ids = auto_detect_characters(
            scene_text, all_characters,
            allowed_ids=appeared if appeared else None)

    # Build prompts
    system_prompt = build_system_prompt(
        config, state=state, scene_char_ids=present_ids,
    )
    try:
        user_prompt = build_scene_prompt(
            config, chapter, scene, state, heritage_defs,
            all_characters, locations, ch_num,
        )
    except Exception as e:
        return {"ok": False, "error": f"Prompt build failed: {e}"}

    # Call LLM
    emit("model_active", model="generation", name=args.model)
    emit("log", message=f"Regenerating Scene {scene_id}…", level="info")
    try:
        raw_text = call_ollama_with_retry(
            args.host, args.model, system_prompt, user_prompt,
            timeout=args.timeout, retries=args.retries,
            num_ctx=getattr(args, 'num_ctx', 8192),
            emit_callback=emit if event_callback else None,
        )
    except OllamaError as e:
        emit("model_active", model="idle", name="")
        return {"ok": False, "error": f"LLM generation failed: {e}"}
    emit("model_active", model="idle", name="")

    # Post-process
    text = clean_scene_text(raw_text)
    text = strip_scene_header(text, scene_id)

    # Replace in output file
    old_text = _replace_scene_in_file(output_file, scene_id, text, scene_title)

    # Log old text
    if old_text:
        emit("log", message=f"Old Scene {scene_id} text saved to logs ({len(old_text)} chars)", level="info")
        # Send the old text as a special log entry so it's preserved
        emit("log", message=f"--- Old Scene {scene_id} ---\n{old_text.strip()[:2000]}", level="warn")

    # Re-summarise
    summary = ""
    extraction = {"characters": [], "facts": [], "actions": [], "commitments": [], "used_imagery": []}
    setting_id_regen = scene.get("setting", "") or "" if scene else ""
    all_known_names_regen = [
        (cdata.get("Name") or cid)
        for cid, cdata in config.get("characters", {}).items()
    ]
    _models_differ = args.model != getattr(args, 'summary_model', args.model)
    if _models_differ:
        unload_model(args.host, args.model, emit if event_callback else None)
    try:
        emit("model_active", model="summarization", name=getattr(args, 'summary_model', 'gemma3:4b'))
        # Build scene meta for grounding
        char_names = []
        if scene and scene.get("characters"):
            for cid in scene["characters"]:
                cdata = config.get("characters", {}).get(cid, {})
                char_names.append(cdata.get("Name") or cid)
        scene_meta = {
            "scene_id": scene_id,
            "title": scene.get("title", "") if scene else "",
            "characters": char_names,
            "setting": setting_id_regen,
        }
        summary, extraction = call_summary_model(
            args.host, args.summary_model, text,
            scene_meta=scene_meta,
        )
        emit("model_active", model="idle", name="")
    except Exception as e:
        emit("model_active", model="idle", name="")
        summary = text[:200].rsplit(" ", 1)[0] + "..."
        emit("log", message=f"Summary failed for regen: {e}", level="warn")
    if _models_differ:
        unload_model(args.host, getattr(args, 'summary_model', args.model), emit if event_callback else None)

    # Track sensory/atmospheric word frequency for variety nudges
    update_word_frequency(state, text)

    # Update checkpoint — clear stale memory for this scene, then re-merge fresh extraction
    from .state import _merge_story_memory, _sanitize_story_memory, _clear_scene_memory, _MAX_RECENT_SCENES
    state.setdefault("story_memory", {})
    state["story_memory"] = _sanitize_story_memory(state["story_memory"])
    _clear_scene_memory(state, scene_id)
    _merge_story_memory(state, extraction, scene_id,
                        known_names=all_known_names_regen,
                        setting_id=setting_id_regen if setting_id_regen else None,
                        present_char_ids=present_ids)

    # Replace the summary for this scene in recent_scenes so the context
    # fed to future scenes reflects the regenerated version, not the old one.
    if summary:
        recent = state.get("recent_scenes", [])
        replaced = False
        for entry in recent:
            if str(entry.get("scene", "")) == str(scene_id):
                entry["summary"] = summary
                replaced = True
                break
        if not replaced:
            recent.append({"scene": str(scene_id), "summary": summary})
            state["recent_scenes"] = recent[-_MAX_RECENT_SCENES:]
        else:
            state["recent_scenes"] = recent

    save_checkpoint(state, checkpoint_path)

    emit("scene_regenerated", scene_id=scene_id, title=scene_title, text=text, summary=summary)
    emit("log", message=f"✓ Scene {scene_id} regenerated ({len(text)} chars)", level="info")

    return {
        "ok": True,
        "scene_id": scene_id,
        "title": scene_title,
        "text": text,
        "old_text": (old_text or "").strip()[:2000],
        "summary": summary,
    }


def regenerate_chapter(config, args, chapter_num, event_callback=None):
    """Regenerate all scenes in a chapter sequentially.

    Args:
        config: Story configuration dict.
        args: SimpleNamespace (same as regenerate_scene).
        chapter_num: Integer chapter number.
        event_callback: Optional callable.

    Returns:
        Dict with 'ok', 'scenes' (list of per-scene results).
    """
    chapter_num = int(chapter_num)
    chapters = config.get("chapters", [])
    target = None
    for ch in chapters:
        if ch.get("chapter_number") == chapter_num:
            target = ch
            break
    if target is None:
        return {"ok": False, "error": f"Chapter {chapter_num} not found"}

    results = []
    for scene in target.get("scenes", []):
        sc_id = str(scene.get("scene_number", ""))
        if not sc_id:
            continue
        result = regenerate_scene(config, args, sc_id, event_callback)
        results.append(result)
        if not result.get("ok"):
            return {"ok": False, "error": f"Scene {sc_id} failed: {result.get('error', '')}", "scenes": results}

    return {"ok": True, "scenes": results}


def rebuild_memories(config, args, event_callback=None):
    """Rebuild story memory from scratch by re-running the summary model
    over every scene in the existing output file.

    This is useful when:
    - The summary model was poorly calibrated and produced bad extractions
    - The user wants to correct accumulated errors quickly
    - The checkpoint memory is out of sync with the actual story text

    The function reads the .md output file, extracts each scene via its
    HTML-comment markers, re-summarises with the improved prompt, and
    rebuilds story_so_far / recent_scenes / facts / actions / commitments /
    characters from the ground up.  Character appearances and generation
    progress (last_completed_*) are preserved.

    Args:
        config: Story configuration dict.
        args: SimpleNamespace with host, summary_model, checkpoint_path, output.
        event_callback: Optional callable(type, data) for SSE progress.

    Returns:
        Dict with 'ok', 'scenes_processed' count, optional 'error'.
    """
    def emit(etype, **kw):
        if event_callback:
            event_callback(etype, kw)

    output_file = getattr(args, "output", None)
    checkpoint_path = getattr(args, "checkpoint_path", None)

    if not output_file or not os.path.exists(output_file):
        return {"ok": False, "error": "Output file not found — generate the story first."}
    if not checkpoint_path or not os.path.exists(checkpoint_path):
        return {"ok": False, "error": "Checkpoint not found — generate the story first."}

    from .state import load_checkpoint, save_checkpoint, _sanitize_story_memory, compress_story_so_far
    from .characters import load_characters
    from .ollama_client import call_summary_model, OllamaError

    state = load_checkpoint(checkpoint_path)

    # Extract all (scene_id, text) pairs from the output file in order
    with open(output_file, "r", encoding="utf-8") as f:
        content = f.read()

    scene_pattern = _re.compile(
        r'<!--\s*scene:([\w.]+)\s*-->\n(.*?)<!--\s*/scene:[\w.]+\s*-->',
        _re.DOTALL,
    )
    scenes_in_file = [(m.group(1), m.group(2).strip()) for m in scene_pattern.finditer(content)]

    if not scenes_in_file:
        return {"ok": False, "error": "No scene markers found in output file. Re-generate to add markers."}

    emit("log", message=f"Rebuilding memory from {len(scenes_in_file)} scenes…", level="info")

    # Load characters for scene_meta building
    all_characters = {}
    try:
        all_characters = load_characters(config)
    except Exception:
        pass

    # Reset only memory-related fields — preserve generation progress/appearances
    state["story_so_far"] = ""
    state["recent_scenes"] = []
    state["story_memory"] = {
        "characters": {},
        "facts": [],
        "actions": [],
        "commitments": [],
        "used_imagery": [],
    }
    state["_scenes_since_compress"] = 0

    processed = 0
    for scene_id, scene_text in scenes_in_file:
        _, scene_dict, ch_num = _find_scene_in_config(config, scene_id)

        # Build scene_meta for grounding
        scene_meta = {"scene_id": scene_id, "title": "", "characters": [], "setting": ""}
        setting_id = ""
        if scene_dict:
            scene_meta["title"] = scene_dict.get("title", "")
            setting_id = scene_dict.get("setting", "") or ""
            scene_meta["setting"] = setting_id
            for cid in (scene_dict.get("characters") or []):
                cdata = all_characters.get(cid, {})
                scene_meta["characters"].append(cdata.get("Name") or cid)
        all_known_names_rebuild = [
            (all_characters.get(cid, {}).get("Name") or cid)
            for cid in all_characters
        ]

        present_char_ids = (scene_dict.get("characters") or []) if scene_dict else []
        chapter_num = ch_num or 0

        emit("log", message=f"  Summarising scene {scene_id}…", level="info")
        emit("model_active", model="summarization", name=getattr(args, "summary_model", "gemma3:4b"))

        try:
            summary, extraction = call_summary_model(
                args.host, args.summary_model, scene_text,
                scene_meta=scene_meta,
            )
        except OllamaError as e:
            emit("log", message=f"  Scene {scene_id} summary failed: {e}", level="warn")
            summary = scene_text[:200].rsplit(" ", 1)[0] + "..."
            extraction = {"characters": [], "facts": [], "actions": [], "commitments": [], "used_imagery": []}
        finally:
            emit("model_active", model="idle", name="")

        from .state import update_after_scene
        update_after_scene(state, chapter_num, scene_id, summary, extraction, present_char_ids,
                           known_names=all_known_names_rebuild,
                           setting_id=setting_id if setting_id else None)
        processed += 1

    # Compress story_so_far if it's long
    try:
        emit("log", message="Compressing story summary…", level="info")
        emit("model_active", model="summarization", name=getattr(args, "summary_model", "gemma3:4b"))
        compress_story_so_far(state, args.host, args.summary_model)
        emit("model_active", model="idle", name="")
    except Exception as e:
        emit("log", message=f"Compression skipped: {e}", level="warn")
        emit("model_active", model="idle", name="")

    save_checkpoint(state, checkpoint_path)
    emit("log", message=f"Memory rebuilt from {processed} scenes.", level="info")
    emit("memories_rebuilt", scenes_processed=processed)

    return {"ok": True, "scenes_processed": processed}
