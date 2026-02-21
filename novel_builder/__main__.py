"""Entry point for `python -m novel_builder`."""

import sys

from .cli import parse_args


def main():
    """Parse arguments, load configuration, and run story generation."""
    args = parse_args()

    # --- Web UI mode ---
    if getattr(args, "web", False):
        from .web import run_server

        run_server(host="0.0.0.0", port=args.port)
        return

    # --- CLI generation mode ---
    from .config import load_config
    from .story_processor import generate_story

    try:
        config = load_config(args)
    except SystemExit:
        raise
    except Exception as e:
        print(f"Error loading story configuration: {e}")
        sys.exit(1)

    print(f"Story: {config.get('story_title', 'Untitled')}")
    chapters = config.get("chapters", [])
    total_scenes = sum(len(ch.get("scenes", [])) for ch in chapters)
    print(f"Chapters: {len(chapters)}, Scenes: {total_scenes}")
    chars = config.get("characters", {})
    print(f"Characters: {len(chars)}")

    generate_story(config, args)


if __name__ == "__main__":
    main()
