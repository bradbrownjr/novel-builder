"""Post-processing: regex cleanup and anti-pattern suppression."""

import re


# Invisible/control characters models occasionally emit: zero-width
# space/joiner/non-joiner, BOM, soft hyphen, word joiner, bidi override and
# isolate marks. These are undetectable to a casual reader but show up in
# plagiarism/AI-detection tooling and can corrupt TTS/text processing.
# Written as explicit \uXXXX escapes rather than literal characters so the
# source stays readable and unambiguous.
_INVISIBLE_CHARS_RE = re.compile(
    "[\u200b\u200c\u200d\u200e\u200f\u2060\ufeff\u00ad"
    "\u202a\u202b\u202c\u202d\u202e"
    "\u2066\u2067\u2068\u2069]"
)

# Emoji / pictographic ranges -- forbidden by the system prompt, but stripped
# here as a backstop in case a model emits one anyway.
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"  # mahjong..symbols & pictographs extended-A
    "\U00002600-\U000027BF"  # misc symbols & dingbats
    "\U0001F1E6-\U0001F1FF"  # regional indicators (flag letters)
    "\uFE0F"                  # variation selector-16 (emoji presentation)
    "]+"
)

# Default anti-patterns — overused AI prose markers.
# Kept in sync with _DEFAULT_PROMPT_ANTI_PATTERNS in prompt_builder.py so
# detection coverage matches what the model is told to avoid. A few prompt
# entries (purple prose, excessive em-dashes, redundant adverbs) aren't
# literal phrases and have no regex equivalent here -- those stay
# prompt-only.
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
    r"\b(?:sent (?:a )?shivers?|a chill ran) down\b",
    r"\bpalpable tension\b",
    r"\bcleared (?:his|her|their|my)?\s*throat\b",
    r"\bcouldn'?t quite\b",
    r"\bdust motes?\b",
    r"\bgrime[- ]coated\b",
    r"\bsomething else entirely\b",
    r"\bcouldn'?t help but\b",
    r"\bseemed to\b",
    r"\bappeared to\b",
    r"\ba (?:mixture|mix) of\b",
    r"\blet out a (?:breath|sigh|laugh)\b",
    r"\bfound (?:himself|herself|themselves|myself)\b",
    r"\bhung (?:in the air|between them)\b",
    r"\bfilled the (?:room|space)\b",
    r"\ba sense of\b",
    r"\bthe sound of\b",
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

    # Strip invisible/control characters and emoji some models emit despite
    # the system prompt forbidding them -- undetectable to a casual read but
    # a known tell for AI-detection tooling.
    text = _INVISIBLE_CHARS_RE.sub("", text)
    text = _EMOJI_RE.sub("", text)
    text = text.replace(" ", " ")  # non-breaking space -> regular space
    text = re.sub(r"[ \t]{2,}", " ", text)  # collapse gaps left by removals

    # Normalize all quote marks to a single consistent style (straight
    # ASCII). Models frequently mix curly and straight quotes within the
    # same document -- that inconsistency itself reads as a machine tell.
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("‘", "'").replace("’", "'")

    # Em-dashes are a well-known AI prose tell. Convert them (and the "--"
    # some models type to mean an em-dash) into commas so pauses/asides read
    # as natural punctuation instead of the machine-generated tic. Numeric
    # ranges (e.g. "1990—2010") keep a plain hyphen since a comma there
    # would change the meaning.
    text = re.sub(r"—{2,}", "—", text)  # collapse doubled em-dashes first
    text = re.sub(r"(?<=\d)\s*—\s*(?=\d)", "-", text)
    text = re.sub(r"\s*—\s*", ", ", text)
    text = re.sub(r"\s*-{2,}\s*", ", ", text)

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

    # Remove plain-text chapter/scene titles (no # marks) that the model
    # may generate at the start or end of output.  These cause TTS to
    # read the title as narration at the wrong time.
    # Matches: "Chapter 3: The Lock-In", "Scene 2.1", "Part IV: Awakening"
    text = re.sub(
        r"^\s*(?:Chapter|Scene|Part|Act|Section)\s+[\d\w.:]+(?:\s*[-—:]\s*.+)?\s*$\n*",
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

    # Fix mis-tagged narrator dialogue -- when the model wraps first-person
    # narrator speech in another character's span.  Detected by the span
    # being immediately followed by first-person attribution like
    # "I said", "I replied", "I whispered", etc.
    text = re.sub(
        r'<span\s+data-tts="[^"]*">("[^"]*")</span>'
        r'(?=\s*(?:,\s*)?I\s+(?:'
        r'said|replied|answered|responded|whispered|murmured|muttered|'
        r'stammered|stuttered|admitted|offered|added|continued|finished|'
        r'agreed|asked|called|shouted|yelled|cried|exclaimed|began|managed|'
        r'started|tried|suggested|explained|insisted|pointed out|confirmed|'
        r'conceded|countered|protested|objected|interrupted|cut in|chimed in'
        r')\b)',
        r'\1',
        text,
        flags=re.IGNORECASE,
    )

    # Fix unclosed <span data-tts> tags. An unclosed span causes the TTS
    # parser's regex to capture everything from that opening tag to the
    # NEXT </span> in the text, which may be many sentences later and
    # belong to a different character -- playing all that narration and
    # other characters' dialogue in the wrong voice.
    # Strategy: walk all span open/close tags as a stack; any open tags
    # still on the stack at the end had no matching close -- strip them.
    tag_re = re.compile(
        r'(<span\s+data-tts="[^"]*">)|(</span>)',
        re.IGNORECASE,
    )
    stack = []  # (start, end) of unclosed opening tags
    for m in tag_re.finditer(text):
        if m.group(1):          # opening tag
            stack.append((m.start(), m.end()))
        elif stack:             # closing tag -- pops the most recent open
            stack.pop()
    # Remove unclosed opens from right to left to preserve positions
    for start, end in reversed(stack):
        text = text[:start] + text[end:]

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
