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


def segment_text_for_tts(text, character_names):
    """Split text into paragraph-level segments with voice attribution.

    Each paragraph is classified as narration (narrator voice) or dialogue
    (a specific character's voice).  Attribution uses a multi-pass approach:

      Pass 1 — Verb attribution (strongest signal).
      Pass 2 — Name-near-dialogue fallback (same paragraph).
      Pass 3 — Contextual: adjacent-paragraph proximity + alternation.

    Args:
        text: The full scene text (may include scene headers, separators).
        character_names: List of character name strings to attempt matching.

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
                    # Read the full label + title, e.g. "Chapter 2: Dust and Echoes"
                    segments.append({"type": "narration", "text": clean, "character": None})
                elif kind == 'chapter':
                    # Bare "Chapter 3" — read it
                    segments.append({"type": "narration", "text": clean, "character": None})
                # else bare "Scene 1.1" with no title — skip silently
            elif clean:
                # Plain header with no scene/chapter prefix — emit as-is
                segments.append({"type": "narration", "text": clean, "character": None})
            continue

        has_dialogue = bool(_QUOTE_RE.search(para))
        speaker = None

        if has_dialogue and character_names:
            # Pass 1: verb-based attribution (highest confidence)
            speaker = _find_speaker_by_verb(para, character_names)

            # Pass 2: name-near-dialogue fallback
            if speaker is None:
                speaker = _find_speaker_by_proximity(para, character_names)

        segments.append({
            "type": "dialogue" if has_dialogue else "narration",
            "text": para,
            "character": speaker,
        })

    # Pass 3: contextual attribution for still-unattributed dialogue
    if character_names:
        _apply_contextual_attribution(segments, character_names)

    # Final pass: split mixed paragraphs into narration/dialogue spans
    segments = _expand_mixed_paragraphs(segments)

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
# Pass 1 — Verb-based attribution
# ---------------------------------------------------------------------------

def _find_speaker_by_verb(paragraph, character_names):
    """Identify speaker via explicit attribution verbs.

    Patterns matched:
        "…", Name said       |  Name said, "…"  |  Name said … "…"
    """
    verbs = _ATTRIBUTION_VERBS
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
# Pass 3 — Contextual: adjacent paragraphs + alternation
# ---------------------------------------------------------------------------

def _apply_contextual_attribution(segments, character_names):
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

    Modifies *segments* in place.
    """
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

        # Names appearing inside the dialogue quotes are likely
        # addressees ("You Elias?") — exclude them as speaker candidates.
        addressees = names_inside_quotes(seg["text"])

        candidates = []
        # Look at paragraph before
        if i > 0:
            prev = segments[i - 1]
            if prev["character"] is None:
                candidates.extend(names_mentioned_in(prev["text"]))
        # Look at paragraph after
        if i < len(segments) - 1:
            nxt = segments[i + 1]
            if nxt["character"] is None:
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
