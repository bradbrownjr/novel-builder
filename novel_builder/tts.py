"""Text-to-speech segmentation utilities.

Parses inline voice-attribution spans (<span data-tts="Name">) produced by
the generation model and converts them into segment dicts for multi-voice
audiobook playback.
"""

import re

# Regex for any quoted text (curly or straight quotes)
_QUOTE_RE = re.compile(r'\u201c[^\u201d]*\u201d|"[^"]*"')

# Regex for <span data-tts="Name">...</span> tags
_SPAN_RE = re.compile(
    r'<span\s+data-tts="([^"]*)">([\s\S]*?)</span>',
    re.IGNORECASE,
)

# Regex for markdown header lines (e.g., "# Title", "## Subtitle")
# Matches: optional whitespace, one or more #, whitespace, then anything to end of line
_MARKDOWN_HEADER_RE = re.compile(r'^\s*#+\s')


def _has_spoken_dialogue(paragraph):
    """True if the paragraph contains actual spoken dialogue, not scare quotes.

    Scare quotes (e.g. ``"shrinkage"``, ``"obsolete stock"``) are short
    quoted phrases embedded in narration, typically lowercase.  Spoken
    dialogue almost always starts with an uppercase letter or is long
    enough to be a sentence fragment.

    Returns True if any quoted span looks like speech.
    """
    quotes = _QUOTE_RE.findall(paragraph)
    if not quotes:
        return False
    for q in quotes:
        inner = q[1:-1].strip()
        if not inner:
            continue
        # 4+ words -> almost certainly dialogue
        if len(inner.split()) >= 4:
            return True
        # Shorter quote starting with uppercase -> likely dialogue
        if inner[0].isupper():
            return True
    return False


def _split_on_headers(text):
    """Split narration text into alternating title and narration segments.

    Separates markdown header lines (e.g., "# Chapter 1") from body text
    so they can be emitted as distinct TTS segments with a post-title pause.
    Header `#` symbols are stripped; only the clean title text is kept.

    Args:
        text: Multi-line text possibly containing markdown headers.

    Returns:
        List of (is_title: bool, text: str) pairs. Empty strings are excluded.
    """
    parts = []
    current_lines = []
    for line in text.split('\n'):
        if _MARKDOWN_HEADER_RE.match(line):
            if current_lines:
                block = '\n'.join(current_lines)
                if block.strip():
                    parts.append((False, block))
                current_lines = []
            # Strip leading # symbols and surrounding whitespace
            title_text = _MARKDOWN_HEADER_RE.sub('', line).strip()
            if title_text:
                parts.append((True, title_text))
        else:
            current_lines.append(line)
    if current_lines:
        block = '\n'.join(current_lines)
        if block.strip():
            parts.append((False, block))
    return parts


def _text_to_segments(text):
    """Convert a narration text block into one or more segment dicts.

    Headers become type="title" segments. Remaining text becomes type="narration".
    Yields each segment dict in document order.
    """
    for is_title, part in _split_on_headers(text):
        yield {
            "type": "title" if is_title else "narration",
            "text": part,
            "character": None,
        }


def parse_span_segments(text):
    """Parse inline <span data-tts="Name"> tags into TTS segment dicts.

    The generation model wraps spoken dialogue in these spans during scene
    generation.  This function extracts them into a list usable by the TTS
    playback pipeline.

    Markdown header lines (e.g., "# Chapter Title") are extracted as
    type="title" segments so the playback layer can insert a dramatic pause
    after speaking the title before the scene content begins.

    Args:
        text: Scene text potentially containing data-tts spans.

    Returns:
        List of segment dicts with keys:
            type: "title", "narration", or "dialogue"
            text: The segment text (span inner text for dialogue).
            character: Character name string, or None for title/narration.
        Returns an empty list if no spans are found.
    """
    if not text or '<span data-tts="' not in text:
        return []

    segments = []
    last_end = 0

    for m in _SPAN_RE.finditer(text):
        # Text before this span may contain headers -- emit as title/narration sub-segments
        before = text[last_end:m.start()]
        segments.extend(_text_to_segments(before))

        # The span itself is attributed dialogue
        character = m.group(1) or None
        segments.append({
            "type": "dialogue",
            "text": m.group(2),
            "character": character,
        })
        last_end = m.end()

    # Text after the last span may also contain headers
    after = text[last_end:]
    segments.extend(_text_to_segments(after))

    return segments

