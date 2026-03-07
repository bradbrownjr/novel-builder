"""Text-to-speech segmentation and utilities.

Segments narrative text into paragraph-level blocks with character
voice attribution for multi-voice audiobook playback.
Key behaviours:
  - Markdown headers (chapter/scene titles) are emitted as narrator segments.
  - Paragraphs that mix narration beats with quoted dialogue are split at
    quote boundaries: narration text → narrator voice; quoted spans →
    attributed character voice.
Attribution strategy (applied in priority order):
  1. Verb-based   — "Name said/asked/etc." near quoted text.
  2. Name-near-quotes — character name in the same paragraph as dialogue,
     outside the quoted text, even without an attribution verb.
  3. Conversation-aware alternation — tracks the two most recent speakers
     across both dialogue and narration paragraphs (narration does NOT
     break the speaker chain; only scene separators do).  Three passes
     (forward → backward → forward) propagate attribution from both ends
     and fill remaining gaps.
  4. Adjacent-paragraph proximity (fallback) — an unattributed sibling
     paragraph mentions a character outside its own quotes.  Names
     inside the target's quoted text are excluded (addressee filter).
"""

import re

# ---------------------------------------------------------------------------
# Attribution verbs — used to identify dialogue speakers
# ---------------------------------------------------------------------------

_ATTRIBUTION_VERBS = (
    r'said|asked|replied|whispered|muttered|shouted|exclaimed|called|yelled|'
    r'murmured|spoke|cried|snapped|hissed|growled|sighed|laughed|added|'
    r'continued|told|offered|suggested|admitted|insisted|demanded|announced|'
    r'declared|warned|promised|agreed|noted|observed|remarked|commented|'
    r'mentioned|explained|stated|screamed|gasped|breathed|rumbled|purred|'
    r'cooed|chuckled|giggled|bellowed|moaned|groaned|whimpered|pleaded|'
    r'begged|ordered|commanded|urged|encouraged|answered|responded|countered|'
    r'retorted|interrupted|interjected|conceded|confessed|revealed|wondered|'
    r'mused|drawled|rasped|croaked|wheezed|barked|chirped|quipped|teased|'
    r'taunted|mocked|sneered|scoffed|huffed|grumbled|grunted|stammered|'
    r'stuttered|babbled|rambled|recited|chanted|sang|sobbed|wailed|wept'
)

# Regex for any quoted text (curly or straight quotes)
_QUOTE_RE = re.compile(r'\u201c[^\u201d]*\u201d|"[^"]*"')

# Common English pronouns and articles that should never be treated as proper names
_COMMON_NON_NAMES = frozenset({
    'she', 'he', 'they', 'it', 'we', 'the', 'a', 'an', 'this', 'that',
    'one', 'someone', 'everyone', 'nobody', 'anybody', 'somebody',
})

# Sentinel returned by first-person detection when no pov_character is set.
# Tells the segmenter to narrator-lock the segment while still tracking as
# a distinct speaker in the alternation chain.
_FIRST_PERSON = "__FIRST_PERSON__"


def segment_text_for_tts(text, character_names, pov_character=None):
    """Split text into paragraph-level segments with voice attribution.

    Each paragraph is classified as narration (narrator voice) or dialogue
    (a specific character's voice).  Attribution uses a multi-pass approach:

      Pass 1 — Verb attribution (strongest signal), including first-person
               "I said/asked/etc." → pov_character.
      Pass 2 — Name-near-dialogue fallback (same paragraph).
      Pass 3 — Contextual: adjacent-paragraph proximity + alternation.
               Unattributed dialogue with evidence of a non-roster speaker
               (explicit attribution to an unknown name, or the previous
               paragraph addressed a non-roster character) is locked to
               narrator before alternation runs.

    Args:
        text: The full scene text (may include scene headers, separators).
        character_names: List of character name strings to attempt matching.
        pov_character: Optional name of the first-person POV character.
                       When set, "I said/asked/etc." patterns are attributed
                       to this character instead of falling through to
                       alternation.

    Returns:
        List of dicts with keys:
            type: "narration" or "dialogue"
            text: The paragraph text.
            character: Character name string, or None for narration.
    """
    if not text or not text.strip():
        return []

    paragraphs = re.split(r'\n\s*\n', text.strip())
    segments = []

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # Scene separators — discard
        if re.match(r'^-{3,}$', para):
            continue

        # Markdown headers — extract readable title, skip bare scene/chapter labels
        m_hdr = re.match(r'^(#{1,6})\s+(.*)', para, re.DOTALL)
        if m_hdr:
            clean = m_hdr.group(2).strip()
            # Match "Scene 1", "Scene 1.2", "Chapter 3", etc. with optional ": Title"
            m_label = re.match(
                r'^(?:Scene|Chapter)\s+[\d.]+\s*(?::\s*(.+))?$',
                clean, re.IGNORECASE | re.DOTALL,
            )
            if m_label:
                # Has a label prefix — only skip bare Scene labels with no title
                title = (m_label.group(1) or '').strip()
                kind = clean.split()[0].lower()  # 'scene' or 'chapter'
                if title:
                    # Chapters: "Chapter 2: Dust and Echoes" — read in full
                    # Scenes: "Scene 1.1: The Empire" — read title only
                    text_to_read = clean if kind == 'chapter' else title
                    segments.append({"type": "narration", "text": text_to_read, "character": None})
                elif kind == 'chapter':
                    # Bare "Chapter 3" — read it
                    segments.append({"type": "narration", "text": clean, "character": None})
                # else bare "Scene 1.1" with no title — skip silently
            elif clean:
                # Plain header with no scene/chapter prefix — emit as-is
                segments.append({"type": "narration", "text": clean, "character": None})
            continue

        has_dialogue = _has_spoken_dialogue(para)
        speaker = None

        if has_dialogue and character_names:
            # Pass 1: verb-based attribution (highest confidence)
            speaker = _find_speaker_by_verb(para, character_names, pov_character=pov_character)

            # Pass 2: name-near-dialogue fallback
            if speaker is None:
                speaker = _find_speaker_by_proximity(para, character_names)

        # Resolve _FIRST_PERSON sentinel → narrator-locked segment
        first_person = (speaker == _FIRST_PERSON)
        if first_person:
            speaker = None

        seg = {
            "type": "dialogue" if has_dialogue else "narration",
            "text": para,
            "character": speaker,
        }
        if first_person:
            seg["_first_person"] = True
        segments.append(seg)

    # Pass 3: contextual attribution for still-unattributed dialogue
    if character_names:
        _apply_contextual_attribution(segments, character_names, pov_character=pov_character)

    # Final pass: split mixed paragraphs into narration/dialogue spans
    segments = _expand_mixed_paragraphs(segments)

    # Strip internal flags before returning
    for seg in segments:
        seg.pop("_first_person", None)
        seg.pop("_narrator_locked", None)

    return segments


# ---------------------------------------------------------------------------
# Intra-paragraph span splitting
# ---------------------------------------------------------------------------

def _expand_mixed_paragraphs(segments):
    """Split paragraphs that interleave narration and dialogue.

    A paragraph like::

        “Yes, that’s me,” Elias said, his voice loud. He extended a hand. “Elias Thorne.”

    is attributed to Elias as a whole, but the narration beats
    (``Elias said, his voice loud. He extended a hand.``) should be read
    by the narrator.  This function splits such paragraphs at quote
    boundaries so each span gets the correct voice.

    Pure-dialogue paragraphs (no outside text) and pure-narration paragraphs
    are returned unchanged.
    """
    expanded = []
    for seg in segments:
        if seg["type"] != "dialogue":
            expanded.append(seg)
            continue

        # If there is no non-quoted text, the whole paragraph is spoken — keep as-is
        outside = _QUOTE_RE.sub('', seg["text"]).strip()
        if not outside:
            expanded.append(seg)
            continue

        # Split at quote boundaries
        spans = _split_paragraph_into_spans(seg["text"], seg["character"])
        expanded.extend(spans)

    return expanded


def _split_paragraph_into_spans(para, speaker):
    """Split *para* into alternating narration/dialogue sub-segments.

    Quoted spans → ``{type: “dialogue”, character: speaker}``.
    Non-quoted spans → ``{type: “narration”, character: None}``.
    Whitespace-only spans are dropped.
    """
    spans = []
    last_end = 0

    for m in _QUOTE_RE.finditer(para):
        before = para[last_end:m.start()].strip()
        if before:
            spans.append({"type": "narration", "text": before, "character": None})
        spans.append({"type": "dialogue", "text": m.group(), "character": speaker})
        last_end = m.end()

    after = para[last_end:].strip()
    if after:
        spans.append({"type": "narration", "text": after, "character": None})

    return spans if spans else [{"type": "dialogue", "text": para, "character": speaker}]


# ---------------------------------------------------------------------------
# Dialogue vs. scare-quote detection
# ---------------------------------------------------------------------------

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
        # 4+ words → almost certainly dialogue
        if len(inner.split()) >= 4:
            return True
        # Shorter quote starting with uppercase → likely dialogue
        if inner[0].isupper():
            return True
    return False


# ---------------------------------------------------------------------------
# Pass 1 — Verb-based attribution
# ---------------------------------------------------------------------------

def _find_speaker_by_verb(paragraph, character_names, pov_character=None):
    """Identify speaker via explicit attribution verbs.

    Patterns matched:
        "…", Name said       |  Name said, "…"  |  Name said … "…"

    If *pov_character* is given, first-person patterns (``I said``,
    ``I asked``, etc.) near a quote are attributed to that character.
    """
    verbs = _ATTRIBUTION_VERBS

    # First-person attribution: "I said/asked/etc." near a quote
    # With pov_character → returns the character name (best for alternation).
    # Without → returns _FIRST_PERSON sentinel (narrator-locked, still tracked).
    if re.search(
        rf'(?<!\w)I\s+(?:{verbs})\b.{{0,80}}[\u201c"]|[\u201d"].{{0,80}}(?<!\w)I\s+(?:{verbs})\b',
        paragraph,
        re.DOTALL,
    ):
        return pov_character if pov_character else _FIRST_PERSON

    sorted_names = sorted(character_names, key=len, reverse=True)

    for name in sorted_names:
        if _name_matches_attribution(paragraph, name, verbs):
            return name
        # Also try first name only (common in prose)
        parts = name.split()
        if len(parts) > 1:
            first = parts[0]
            if len(first) > 2 and _name_matches_attribution(paragraph, first, verbs):
                return name

    return None


# ---------------------------------------------------------------------------
# Pass 2 — Name near dialogue (no verb required)
# ---------------------------------------------------------------------------

def _find_speaker_by_proximity(paragraph, character_names):
    """Attribute dialogue when a character name appears in the same paragraph.

    Only matches if the name is within ~60 characters of a quotation mark
    so we don't false-match a name mentioned in narration far from the
    spoken line.
    """
    sorted_names = sorted(character_names, key=len, reverse=True)

    for name in sorted_names:
        if _name_near_dialogue(paragraph, name):
            return name
        parts = name.split()
        if len(parts) > 1:
            first = parts[0]
            if len(first) > 2 and _name_near_dialogue(paragraph, first):
                return name

    return None


def _name_near_dialogue(paragraph, name):
    """Return True if *name* appears near a quote boundary *outside* quotes.

    Avoids false positives when the name only appears *inside* dialogue
    (e.g. '"You Elias?"' — Elias is the addressee, not the speaker).
    """
    escaped = re.escape(name)

    # Strip quoted text so we only search the non-dialogue portion
    stripped = _QUOTE_RE.sub('', paragraph)
    if not re.search(rf'\b{escaped}\b', stripped, re.IGNORECASE):
        return False

    # Name within 60 chars before an opening quote
    if re.search(
        rf'\b{escaped}\b.{{0,60}}[\u201c"]',
        paragraph,
        re.IGNORECASE | re.DOTALL,
    ):
        return True

    # Name within 60 chars after a closing quote
    if re.search(
        rf'[\u201d"].{{0,60}}\b{escaped}\b',
        paragraph,
        re.IGNORECASE | re.DOTALL,
    ):
        return True

    return False


# ---------------------------------------------------------------------------
# Pass 3 helpers — non-roster speaker detection
# ---------------------------------------------------------------------------

def _build_roster_lower(character_names):
    """Return a set of lowercased names and first-name variants from the roster."""
    result = set()
    for name in character_names:
        result.add(name.lower())
        parts = name.lower().split()
        if parts:
            result.add(parts[0])
    return result


def _has_unnamed_speaker_attribution(paragraph, character_names):
    """True if paragraph has 'ProperName verb' attributed to a non-roster name near a quote.

    Detects patterns like ``Mrs. Henderson replied, "..."`` where
    ``Mrs. Henderson`` is not in *character_names*.
    """
    verbs = _ATTRIBUTION_VERBS
    cn_lower = _build_roster_lower(character_names)
    pat = re.compile(
        rf'(?<!\w)([A-Z][a-zA-Z\'.-]+(?:\s+[A-Z][a-zA-Z\'.-]+)?)\s+(?:{verbs})\b'
    )
    for m in pat.finditer(paragraph):
        found = m.group(1).lower()
        if found in _COMMON_NON_NAMES or found == 'i':
            continue
        if found in cn_lower:
            continue
        # Non-roster name + attribution verb — verify a quote exists nearby
        end = min(len(paragraph), m.end() + 100)
        if re.search(r'[\u201c\u201d""]', paragraph[max(0, m.start() - 10):end]):
            return True
    return False


def _has_non_roster_addressee(paragraph, character_names):
    """True if paragraph has 'verb ProperName' where ProperName is not in roster.

    Detects patterns like ``I asked Mrs. Henderson`` or ``told Captain
    Reeves`` — indicating the *next* unattributed dialogue line is likely
    that non-roster character responding.
    """
    verbs = _ATTRIBUTION_VERBS
    cn_lower = _build_roster_lower(character_names)
    pat = re.compile(
        rf'\b(?:{verbs})\s+([A-Z][a-zA-Z\'.-]+(?:\s+[A-Z][a-zA-Z\'.-]+)?)\b'
    )
    for m in pat.finditer(paragraph):
        found = m.group(1).lower()
        if found in _COMMON_NON_NAMES or found == 'i':
            continue
        if found in cn_lower:
            continue
        return True
    return False


# ---------------------------------------------------------------------------
# Pass 3 — Contextual: adjacent paragraphs + alternation
# ---------------------------------------------------------------------------

def _apply_contextual_attribution(segments, character_names, pov_character=None):
    """Resolve unattributed dialogue using surrounding context.

    Two strategies applied in order:

    A) **Conversation-aware alternation** (applied first — strongest
       structural signal).  Alternates between the two most recently
       identified speakers.  Narration paragraphs do NOT reset the
       speaker chain; only a hard scene break would.  Three passes
       (forward → backward → forward) propagate attribution from both
       ends and fill remaining gaps.

    B) **Adjacent-paragraph proximity** (fallback for anything
       alternation couldn't resolve).  If the paragraph immediately
       before *or* after the still-unattributed dialogue mentions a
       character (and isn't itself attributed to someone else), assign
       that character.  Names that only appear *inside the target's
       quoted text* are excluded (likely addressees, not speakers).

    Before alternation runs, a **narrator-lock pre-pass** identifies
    unattributed segments that clearly belong to non-roster speakers:

    - The paragraph itself has an explicit attribution verb tied to a
      non-roster proper name (e.g. ``Mrs. Henderson replied``).
    - The immediately preceding attributed paragraph addressed a
      non-roster character (e.g. ``I asked Mrs. Henderson`` → her
      response should be read by the narrator, not guessed via
      alternation).

    Locked segments are skipped by alternation so the narrator voice
    is used instead of a wrong character's voice.

    Modifies *segments* in place.
    """
    # --- Narrator-lock pre-pass ---
    for i, seg in enumerate(segments):
        if seg.get('type') != 'dialogue' or seg.get('character') is not None:
            continue
        # Direct: this paragraph explicitly attributes to a non-roster name
        if _has_unnamed_speaker_attribution(seg['text'], character_names):
            seg['_narrator_locked'] = True
            continue
        # Indirect: the previous attributed/first-person paragraph addressed a
        # non-roster person — their response is next and should fall to narrator
        if i > 0:
            prev = segments[i - 1]
            prev_has_speaker = prev.get('character') is not None or prev.get('_first_person')
            if prev_has_speaker and _has_non_roster_addressee(prev['text'], character_names):
                seg['_narrator_locked'] = True
    # --- Strategy A: conversation-aware alternation ---
    # Three passes to propagate from both ends and fill remaining gaps.
    _alternation_pass(segments, forward=True)
    _alternation_pass(segments, forward=False)
    _alternation_pass(segments, forward=True)

    # --- Strategy B: adjacent-paragraph proximity (fallback) ---
    sorted_names = sorted(character_names, key=len, reverse=True)

    def names_mentioned_in(text):
        """Return character names found in *text* (longest first)."""
        found = []
        for name in sorted_names:
            escaped = re.escape(name)
            if re.search(rf'\b{escaped}\b', text, re.IGNORECASE):
                found.append(name)
                continue
            parts = name.split()
            if len(parts) > 1:
                first = parts[0]
                if len(first) > 2 and re.search(rf'\b{re.escape(first)}\b', text, re.IGNORECASE):
                    found.append(name)
        return found

    def names_inside_quotes(text):
        """Return character names that appear inside quoted text."""
        quoted_blob = " ".join(_QUOTE_RE.findall(text))
        if not quoted_blob:
            return set()
        return set(names_mentioned_in(quoted_blob))

    for i, seg in enumerate(segments):
        if seg["type"] != "dialogue" or seg["character"] is not None:
            continue
        if seg.get("_first_person") or seg.get("_narrator_locked"):
            continue

        # Names appearing inside the dialogue quotes are likely
        # addressees ("You Elias?") — exclude them as speaker candidates.
        addressees = names_inside_quotes(seg["text"])

        candidates = []
        # Look at paragraph before (skip locked/first-person neighbours)
        if i > 0:
            prev = segments[i - 1]
            if (prev["character"] is None
                    and not prev.get("_first_person")
                    and not prev.get("_narrator_locked")):
                candidates.extend(names_mentioned_in(prev["text"]))
        # Look at paragraph after
        if i < len(segments) - 1:
            nxt = segments[i + 1]
            if (nxt["character"] is None
                    and not nxt.get("_first_person")
                    and not nxt.get("_narrator_locked")):
                candidates.extend(names_mentioned_in(nxt["text"]))

        # Filter out addressees
        candidates = [c for c in candidates if c not in addressees]

        if candidates:
            seg["character"] = candidates[0]


def _alternation_pass(segments, forward=True):
    """Run one alternation pass over dialogue segments.

    When *forward* is True, iterates first→last.  When False, last→first.
    Multiple passes (forward → backward → forward) ensure attribution
    propagates from both ends and fills remaining gaps.

    Narration paragraphs do **not** reset the speaker chain — novels
    routinely interleave narration between dialogue turns.  Only a
    scene break (the original ``---`` separator which is filtered out
    during paragraph splitting) would cause a natural reset, and those
    paragraphs are already excluded from *segments*.
    """
    indices = range(len(segments)) if forward else range(len(segments) - 1, -1, -1)
    recent = []  # most-recent speaker first, max 2

    for i in indices:
        seg = segments[i]

        # Skip narration — but do NOT clear recent speakers.
        if seg["type"] != "dialogue":
            continue
        if seg.get("_narrator_locked"):
            continue

        # First-person segments are narrator-voiced but still tracked in
        # the alternation chain so the NEXT line alternates correctly.
        if seg.get("_first_person"):
            _push_recent(recent, _FIRST_PERSON)
            continue

        if seg["character"] is not None:
            _push_recent(recent, seg["character"])
        else:
            if len(recent) >= 2:
                seg["character"] = recent[1]
                _push_recent(recent, seg["character"])


def _push_recent(recent, name):
    """Push *name* to front of *recent* (max 2), avoiding duplicates."""
    if recent and recent[0] == name:
        return
    if name in recent:
        recent.remove(name)
    recent.insert(0, name)
    if len(recent) > 2:
        recent.pop()


# ---------------------------------------------------------------------------
# Verb-pattern matching (used by Pass 1)
# ---------------------------------------------------------------------------


def _name_matches_attribution(paragraph, name, verbs):
    """Check if a name appears in a dialogue attribution pattern."""
    escaped = re.escape(name)

    # Pattern 1: "dialogue", Name verbed
    if re.search(
        rf'[\u201d"]\s*[,.!?]?\s*{escaped}\s+(?:{verbs})\b',
        paragraph,
        re.IGNORECASE,
    ):
        return True

    # Pattern 2: Name verbed, "dialogue"
    if re.search(
        rf'\b{escaped}\s+(?:{verbs})\s*[,.:]?\s*[\u201c"]',
        paragraph,
        re.IGNORECASE,
    ):
        return True

    # Pattern 3: Name verbed (intervening text) "dialogue"
    # Looser — allows a short gap between verb and quote
    if re.search(
        rf'\b{escaped}\s+(?:{verbs})\b.{{0,40}}[\u201c"]',
        paragraph,
        re.IGNORECASE,
    ):
        return True

    return False


# ---------------------------------------------------------------------------
# Model-based dialogue tagging
# ---------------------------------------------------------------------------

def tag_dialogue_with_model(scene_text, character_names, pov_character,
                             host, model, num_ctx=4096):
    """Use a lightweight LLM to attribute dialogue paragraphs to speakers.

    Sends the scene's paragraphs to the configured Ollama model and asks
    it to label each one as 'narrator' or a character name.  The result
    is converted to the same segment list format returned by
    segment_text_for_tts(), so callers can use either transparently.

    Falls back to script-based segment_text_for_tts() on any error.

    Args:
        scene_text: Raw scene text (paragraphs separated by blank lines).
        character_names: List of character name strings present in the scene.
        pov_character: Optional POV character name (first-person anchor).
        host: Ollama server URL.
        model: Model name (e.g. 'qwen2.5:1.5b').
        num_ctx: Context window size for the tagging model.

    Returns:
        List of segment dicts with 'type', 'text', and 'character' keys.
    """
    from .ollama_client import call_ollama_with_retry

    if not host or not model:
        return segment_text_for_tts(scene_text, character_names,
                                    pov_character=pov_character)

    paragraphs = [p.strip() for p in scene_text.strip().split("\n\n") if p.strip()]
    if not paragraphs:
        return []

    names_str = ", ".join(character_names) if character_names else "none listed"
    if pov_character:
        names_str += f" (POV/narrator voice: {pov_character})"

    para_block = "\n".join(f"{i + 1}: {p}" for i, p in enumerate(paragraphs))

    system = (
        "You are a dialogue attribution assistant for audiobook production. "
        "Given scene text split into numbered paragraphs and a list of character "
        "names, label who speaks in each paragraph.\n\n"
        "Rules:\n"
        "- Output ONLY lines in the format: N: SpeakerName\n"
        "- Use 'narrator' for paragraphs with no spoken dialogue (pure narration, "
        "  action, or description).\n"
        "- Use a character name from the provided list for paragraphs that contain "
        "  spoken dialogue.\n"
        "- For unattributed dialogue, infer the speaker from conversational context "
        "  and alternation.\n"
        "- Character names MUST come from the provided list -- do not invent names.\n"
        "- Do not add explanation, headers, or any other text.\n"
    )

    user = (
        f"Characters in this scene: {names_str}\n\n"
        f"Paragraphs:\n{para_block}\n\n"
        "Attribute each paragraph (N: SpeakerName):"
    )

    try:
        raw = call_ollama_with_retry(
            host, model, system, user,
            timeout=120, retries=1, temperature=0.1, num_ctx=num_ctx,
        )
    except Exception:
        return segment_text_for_tts(scene_text, character_names,
                                    pov_character=pov_character)

    if not raw:
        return segment_text_for_tts(scene_text, character_names,
                                    pov_character=pov_character)

    # Parse: build paragraph_number -> speaker mapping
    valid_names = {n.lower(): n for n in (character_names or [])}
    allocation = {}
    for line in raw.strip().splitlines():
        line = line.strip()
        if ":" not in line:
            continue
        idx_str, _, speaker_str = line.partition(":")
        idx_str = idx_str.strip()
        speaker_str = speaker_str.strip()
        try:
            idx = int(idx_str)
        except ValueError:
            continue
        speaker_lower = speaker_str.lower()
        if speaker_lower in ("narrator", "narration", ""):
            allocation[idx] = None
        elif speaker_lower in valid_names:
            allocation[idx] = valid_names[speaker_lower]
        # Unknown name falls through -- treated as narrator below

    # Guard: if parsing produced nothing useful, fall back
    if not allocation:
        return segment_text_for_tts(scene_text, character_names,
                                    pov_character=pov_character)

    # Build segments from allocation + original text
    segments = []
    for i, para in enumerate(paragraphs):
        para_num = i + 1
        speaker = allocation.get(para_num)  # None = narrator
        has_dlg = _has_spoken_dialogue(para)

        if has_dlg and speaker:
            # Split mixed paragraphs into narration beats + quoted spans
            sub_segs = _split_paragraph_into_spans(para, speaker)
            segments.extend(sub_segs)
        else:
            segments.append({
                "type": "dialogue" if (has_dlg and speaker) else "narration",
                "text": para,
                "character": speaker,
            })

    return segments if segments else segment_text_for_tts(
        scene_text, character_names, pov_character=pov_character
    )
