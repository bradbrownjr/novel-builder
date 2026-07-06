"""CLI argument parsing for Novel Builder."""

import argparse
import os


def parse_args(argv=None):
    """Parse command-line arguments.

    Args:
        argv: Argument list (defaults to sys.argv[1:]).

    Returns:
        argparse.Namespace with all configuration values.
    """
    parser = argparse.ArgumentParser(
        prog="novel-builder",
        description="Generate long-form fiction using local LLMs via Ollama.",
    )

    # --- Connection ---
    parser.add_argument(
        "--host",
        default=os.environ.get("OLLAMA_HOST"),
        help="Ollama host URL (default: $OLLAMA_HOST env variable).",
    )
    parser.add_argument(
        "--model",
        default="gemma4:e4b",
        help="Ollama model for scene generation (default: gemma4:e4b).",
    )
    parser.add_argument(
        "--summary-model",
        default="gemma4:e2b",
        help="Ollama model for summarization (default: gemma4:e2b).",
    )

    # --- Files ---
    parser.add_argument(
        "--outline",
        default=None,
        help="Story outline YAML file (default: auto-discover).",
    )
    parser.add_argument(
        "--characters",
        default=None,
        help="Characters YAML file (default: auto-discover).",
    )
    parser.add_argument(
        "--locations",
        default=None,
        help="Locations/settings YAML file (default: auto-discover).",
    )
    parser.add_argument(
        "--output",
        default="full_story.md",
        help="Output Markdown file (default: full_story.md).",
    )

    # --- Resume / Restart ---
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from checkpoint without prompting.",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Ignore checkpoint and start fresh.",
    )

    # --- Output control ---
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress terminal output of generated scenes.",
    )

    # --- Resilience ---
    parser.add_argument(
        "--retries",
        type=int,
        default=5,
        help="Ollama retry attempts on failure (default: 5).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=900,
        help="Ollama request timeout in seconds (default: 900).",
    )

    # --- Sampling ---
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.9,
        help="Sampling temperature for scene generation (default: 0.9).",
    )
    parser.add_argument(
        "--top-p",
        type=float,
        default=0.95,
        dest="top_p",
        help="Nucleus sampling top-p for scene generation (default: 0.95).",
    )
    parser.add_argument(
        "--repeat-penalty",
        type=float,
        default=1.15,
        dest="repeat_penalty",
        help="Repeat penalty for scene generation (default: 1.15).",
    )
    parser.add_argument(
        "--presence-penalty",
        type=float,
        default=0.2,
        dest="presence_penalty",
        help="Presence penalty for scene generation (default: 0.2).",
    )

    # --- Selective generation ---
    parser.add_argument(
        "--chapter",
        type=int,
        default=None,
        help="Generate only this chapter number.",
    )
    parser.add_argument(
        "--scene",
        default=None,
        help="Generate only this scene (e.g., 3.2 for chapter 3, scene 2).",
    )

    # --- Modes ---
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse YAML and show generation plan without calling Ollama.",
    )

    # --- Web UI ---
    parser.add_argument(
        "--web",
        action="store_true",
        help="Launch the web UI instead of running CLI generation.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port for the web UI server (default: 8080).",
    )

    args = parser.parse_args(argv)

    # Web mode does not require a host upfront
    if not args.web and not args.host:
        print("OLLAMA_HOST environment variable not set.")
        host = input(
            "Enter the Ollama server URL (e.g., http://192.168.1.50:11434): "
        ).strip()
        if not host.startswith("http"):
            host = f"http://{host}:11434"
        args.host = host

    return args
