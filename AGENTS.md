# AGENTS.md — Novel Builder Memory

This file is the persistent memory for the Novel Builder project. Copilot reads this file on every session to recall user directives and project conventions.

## Always/Never Directives

_(Add directives here when the user says "always" or "never" do something.)_

- **Always** write generated scenes to the output file immediately after generation (never buffer full chapters).
- **Always** default to outputting scenes to both file and terminal unless overridden by CLI flags.
- **Never** hardcode style directives in Python — they belong in the YAML outline.
- **Never** include all character bios in every scene prompt — only send characters present in the scene.
- **Always** keep `README.md` as a concise table of contents with a project description. Detailed documentation goes in `docs/`. Keep content scannable and bite-sized for readers.

## Project Conventions

- Code is organized as a Python package: `novel_builder/` with `novel-builder.py` as a thin wrapper.
- YAML is the only data format for story input/configuration.
- Supports both separate YAML files (characters.yaml, locations.yaml, story_outline.yaml) and a single combined `story_data.yaml`.
- Markdown is the output format.
- Ollama is the only supported LLM backend (for now).
- Minimal dependencies: `pyyaml`, `requests`, stdlib only.
- Default generation model: `gemma3:12b`. Default summary model: `gemma3:1b`.
- No word count targets — let the AI decide scene length.
- Interactive mode is deferred (P3). Post-completion rewrite is the near-term alternative.

## Module Tree

```
novel_builder/
├── __init__.py           # Package init, version
├── __main__.py           # Entry point: python -m novel_builder
├── cli.py                # parse_args()
├── config.py             # load_config(), discover_yaml_files()
├── ollama_client.py      # call_ollama(), call_ollama_with_retry()
├── prompt_builder.py     # build_system_prompt(), build_scene_prompt(), build_summary_prompt()
├── state.py              # load_checkpoint(), save_checkpoint(), should_resume()
├── story_processor.py    # generate_story(), process_chapter(), process_scene()
├── characters.py         # load_characters(), filter_for_scene(), auto_detect_characters(), get_evolution_context()
├── locations.py          # load_locations(), resolve_location()
├── yaml_io.py            # load_yaml(), save_yaml()
└── postprocess.py        # clean_scene_text(), apply_anti_patterns()
```

_(Update this tree when functions are added, renamed, or moved.)_

## Known Issues (Active)

- Catch phrases are injected indiscriminately into every scene prompt, causing overuse in output. → Fix: Phase 2.3 (frequency gating)
- Full character bios are sent every scene, inhibiting character growth and adding unnecessary tokens. → Fix: Phase 2.2 (tiered context)
- No retry logic on Ollama timeout — generation stops and progress is lost. → Fix: Phase 1.1
- No checkpoint/resume capability — must restart from chapter 1 on failure. → Fix: Phase 1.2
- `story_so_far` is a raw concatenation of chapter summaries, not a token-efficient AI-generated summary. → Fix: Phase 2.1
- Scene/location models are mixed into character YAML — need separation or clear structure. → Fix: Phase 4.1

## Character Context Strategy

| Context tier | When | Fields sent |
|---|---|---|
| **Full bio** | First appearance in story | Name, summary, role, personality, vibe, voice, habit + merged heritage traits |
| **Reminder** | Subsequent appearances | Name, role, vibe, voice + evolution notes |

- `vibe` is the persistent tonal anchor — always included.
- `voice` (speech patterns) is always included when present — shapes dialogue.
- `personality` and `summary` are dropped after first appearance (now established in narrative).
- `heritage` traits merged on first appearance, dropped after (established in narrative). Character fields override heritage.
- `catchphrase` is probability-gated, not included every scene.
- `secret` is only included when the scene's notes reference tension or subtext.
- `relationships` are included when both characters in the relationship are present in the scene.
- Character appearance history is tracked in `checkpoint.yaml`.
- Story memory (auto-extracted minor characters, facts, commitments) is tracked in `checkpoint.yaml` and injected when relevant.

## Resolved Issues

_(Track fixes here for reference.)_
