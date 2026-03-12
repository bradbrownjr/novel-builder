"""Post-processing: regex cleanup and anti-pattern suppression."""

import re


# Default anti-patterns — overused AI prose markers
_DEFAULT_ANTI_PATTERNS = [
    r"\bdelve\b",
    r"\btapestry\b",
    r"\bunbeknownst\b",
    r"\bwhispered? (?:softly|quietly)\b",
    r"\ba (?:single|lone) tear\b",
    r"\blet out a breath (?:they|he|she|I) didn'?t (?:know|realize)\b",
    r"\bthe weight of\b.*\bsettled\b",
    r"\beverything changed\b",
    r"\blittle did (?:they|he|she|I) know\b",
    r"\btime seemed to (?:stop|stand still|slow)\b",
    r"\bin that moment\b",
    r"\bsent (?:a )?shivers? down\b",
    r"\bpalpable tension\b",
]


def clean_scene_text(text):
    """Apply general cleanup to generated scene text.

    Fixes common formatting issues without altering content.

    Args:
        text: Raw generated text from the model.

    Returns:
        Cleaned text string.
    """
    if not text:
        return ""

    # Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Remove leading/trailing whitespace
    text = text.strip()

    # Fix double em-dashes (some models output ———— or -- instead of —)
    text = re.sub(r"—{2,}", "—", text)
    text = re.sub(r"(?<!\-)--(?!\-)", "—", text)

    # Collapse triple+ newlines into double
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Remove bare divider lines (---, ==, etc.) — no scene dividers in book-like output
    text = re.sub(r"^\s*(?:---+|===+|\*\*\*+)\s*$", "", text, flags=re.MULTILINE)

    # Remove ALL LLM-generated scene/chapter markdown headers from anywhere in the text.
    # We write our own headers — any the model adds are noise.
    # Matches: ## Chapter 3, ## Chapter 3: Title, ### Scene 1.1, ### Scene 1.1: Title, etc.
    text = re.sub(
        r"^#{1,6}\s*(?:Scene|Chapter|Part|Act|Section)\b.*$\n*",
        "",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )

    # Remove trailing spaces on lines
    text = re.sub(r" +\n", "\n", text)

    # Fix common smart-quote issues from models
    text = re.sub(r"``|''", '"', text)

    # Remove model artifacts — lines like "Scene:", "Output:", etc.
    text = re.sub(
        r"^(?:Scene|Output|Response|Here (?:is|are)|Sure[,!]|Certainly).*?:\s*\n",
        "",
        text,
        flags=re.MULTILINE | re.IGNORECASE,
    )

    # Remove markdown code fences that wrap the whole response
    text = re.sub(r"^```(?:markdown|text|md)?\s*\n", "", text)
    text = re.sub(r"\n```\s*$", "", text)

    # Fix TTS voice-tag duplication -- when the model writes dialogue both
    # untagged and tagged, e.g.:
    #   "Hello!" <span data-tts="Name">"Hello!"</span>
    # Collapse to just the tagged version.
    text = re.sub(
        r'"([^"]+)"\s*(<span\s+data-tts="[^"]+">"\1"</span>)',
        r"\2",
        text,
    )

    return text.strip()


def apply_anti_patterns(text, patterns=None):
    """Flag or suppress overused AI patterns in generated text.

    This does NOT delete sentences — it logs warnings about detected patterns
    so the author can review. In the future, this could drive a rewrite pass.

    Args:
        text: Generated scene text.
        patterns: List of regex pattern strings to check.
            If None, uses the default anti-pattern list.

    Returns:
        Tuple of (text, list_of_warnings).
        Text is returned unmodified; warnings list contains
        (pattern, match_text, line_number) tuples.
    """
    if not text:
        return text, []

    # Merge user patterns with defaults so built-in checks always run
    if patterns is None:
        merged = list(_DEFAULT_ANTI_PATTERNS)
    else:
        # Deduplicate: add user patterns that aren't already in defaults
        default_set = set(p.lower() for p in _DEFAULT_ANTI_PATTERNS)
        merged = list(_DEFAULT_ANTI_PATTERNS)
        for p in patterns:
            if p.lower().strip() not in default_set:
                merged.append(p)

    warnings = []
    lines = text.split("\n")

    for pattern_str in merged:
        try:
            pattern = re.compile(pattern_str, re.IGNORECASE)
        except re.error:
            continue

        for line_num, line in enumerate(lines, 1):
            match = pattern.search(line)
            if match:
                warnings.append((pattern_str, match.group(), line_num))

    return text, warnings


def strip_scene_header(text, scene_number=None):
    """Remove auto-generated scene/chapter headers from model output.

    Models often prepend "## Scene 2.1" or "Chapter 3" headers.
    We generate our own headers, so strip these.

    Args:
        text: Generated text.
        scene_number: Expected scene number (for targeted removal).

    Returns:
        Text with leading headers removed.
    """
    if not text:
        return ""

    # Remove leading markdown headers that look like scene/chapter labels
    # Matches: ### Scene 2.1, ## Chapter 3: Title, # Part IV, etc.
    text = re.sub(
        r"^#{1,6}\s*(?:Scene|Chapter|Part|Act|Section)\s*[\d\w.:—-]*\s*(?:[-—:].*?)?\n+",
        "",
        text,
        count=1,
        flags=re.IGNORECASE | re.MULTILINE,
    )

    # Remove specific scene number header if provided
    if scene_number:
        escaped = re.escape(str(scene_number))
        text = re.sub(
            rf"^#{1,6}\s*{escaped}\s*[-—:]?\s*.*?\n+",
            "",
            text,
            count=1,
            flags=re.IGNORECASE | re.MULTILINE,
        )

    # Remove any trailing markdown headers at very end of text
    # (in case the model put a "Next scene" header at the end)
    text = re.sub(
        r"\n#{1,6}\s*(?:Scene|Chapter|Part|Act|Section)\s*[\d\w.:—-]*.*?$",
        "",
        text,
        flags=re.IGNORECASE,
    )

    return text.strip()
