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


def parse_span_segments(text):
    """Parse inline <span data-tts="Name"> tags into TTS segment dicts.

    The generation model wraps spoken dialogue in these spans during scene
    generation.  This function extracts them into a list usable by the TTS
    playback pipeline.

    Args:
        text: Scene text potentially containing data-tts spans.

    Returns:
        List of segment dicts with keys:
            type: "narration" or "dialogue"
            text: The segment text (span inner text for dialogue).
            character: Character name string, or None for narration.
        Returns an empty list if no spans are found.
    """
    if not text or '<span data-tts="' not in text:
        return []

    segments = []
    last_end = 0

    for m in _SPAN_RE.finditer(text):
        # Text before this span is narration
        before = text[last_end:m.start()]
        if before.strip():
            segments.append({
                "type": "narration",
                "text": before,
                "character": None,
            })
        # The span itself is dialogue
        character = m.group(1) or None
        segments.append({
            "type": "dialogue",
            "text": m.group(2),
            "character": character,
        })
        last_end = m.end()

    # Text after the last span
    after = text[last_end:]
    if after.strip():
        segments.append({
            "type": "narration",
            "text": after,
            "character": None,
        })

    return segments
