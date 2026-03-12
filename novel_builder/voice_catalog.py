"""Voice metadata catalog for TTS backends (Kokoro, Piper, etc.).

Provides human-readable descriptions, accent info, gender, and tonal
qualities for known TTS voices so the UI can display meaningful labels
and the AI consultant can recommend voices for characters.
"""

# ---------------------------------------------------------------------------
# Kokoro voice catalog
# ---------------------------------------------------------------------------
# Naming convention:  {lang}{gender}_{name}
#   lang:   a = American English, b = British English, j = Japanese,
#           z = Chinese, k = Korean, f = French, h = Hindi,
#           i = Italian, p = Portuguese, e = Spanish
#   gender: f = female, m = male
#
# Source: Kokoro v1.0 by Hexgrad (MIT license).
# Descriptions based on publicly documented voice characteristics.
# ---------------------------------------------------------------------------

KOKORO_VOICES = {
    # -- American Female --
    "af_heart": {
        "gender": "female",
        "accent": "American",
        "tone": "warm, expressive",
        "best_for": "narration, emotional scenes, protagonists",
        "desc": "Warm and expressive with natural emotional range",
    },
    "af_alloy": {
        "gender": "female",
        "accent": "American",
        "tone": "clear, neutral",
        "best_for": "narration, professional characters",
        "desc": "Clear and balanced with a professional quality",
    },
    "af_aoede": {
        "gender": "female",
        "accent": "American",
        "tone": "bright, youthful",
        "best_for": "young characters, upbeat scenes",
        "desc": "Bright and youthful with an energetic quality",
    },
    "af_bella": {
        "gender": "female",
        "accent": "American",
        "tone": "confident, polished",
        "best_for": "strong female leads, authority figures",
        "desc": "Confident and polished with assertive delivery",
    },
    "af_jessica": {
        "gender": "female",
        "accent": "American",
        "tone": "articulate, professional",
        "best_for": "business characters, narration",
        "desc": "Articulate and professional with precise diction",
    },
    "af_kore": {
        "gender": "female",
        "accent": "American",
        "tone": "mature, steady",
        "best_for": "mentors, older characters, calm narration",
        "desc": "Mature and steady with a grounded presence",
    },
    "af_nicole": {
        "gender": "female",
        "accent": "American",
        "tone": "soft, intimate",
        "best_for": "introspective scenes, romantic leads",
        "desc": "Soft and intimate with a gentle, close quality",
    },
    "af_nova": {
        "gender": "female",
        "accent": "American",
        "tone": "energetic, vibrant",
        "best_for": "action scenes, enthusiastic characters",
        "desc": "Energetic and vibrant with dynamic range",
    },
    "af_river": {
        "gender": "female",
        "accent": "American",
        "tone": "calm, flowing",
        "best_for": "meditative narration, serene characters",
        "desc": "Calm and flowing with a serene, unhurried pace",
    },
    "af_sarah": {
        "gender": "female",
        "accent": "American",
        "tone": "warm, conversational",
        "best_for": "dialogue-heavy scenes, relatable characters",
        "desc": "Warm and conversational with natural cadence",
    },
    "af_sky": {
        "gender": "female",
        "accent": "American",
        "tone": "light, airy",
        "best_for": "whimsical characters, children's narration",
        "desc": "Light and airy with a delicate, ethereal quality",
    },

    # -- American Male --
    "am_adam": {
        "gender": "male",
        "accent": "American",
        "tone": "deep, authoritative",
        "best_for": "leaders, villains, dramatic narration",
        "desc": "Deep and authoritative with commanding presence",
    },
    "am_echo": {
        "gender": "male",
        "accent": "American",
        "tone": "resonant, clear",
        "best_for": "narration, storytelling",
        "desc": "Resonant and clear with good projection",
    },
    "am_eric": {
        "gender": "male",
        "accent": "American",
        "tone": "friendly, natural",
        "best_for": "everyday characters, dialogue-heavy scenes",
        "desc": "Friendly and natural with approachable warmth",
    },
    "am_fenrir": {
        "gender": "male",
        "accent": "American",
        "tone": "bold, dramatic",
        "best_for": "warriors, antagonists, intense scenes",
        "desc": "Bold and dramatic with intense delivery",
    },
    "am_liam": {
        "gender": "male",
        "accent": "American",
        "tone": "warm, approachable",
        "best_for": "protagonists, romantic leads",
        "desc": "Warm and approachable with gentle strength",
    },
    "am_michael": {
        "gender": "male",
        "accent": "American",
        "tone": "professional, balanced",
        "best_for": "business characters, neutral narration",
        "desc": "Professional and balanced with measured delivery",
    },
    "am_onyx": {
        "gender": "male",
        "accent": "American",
        "tone": "rich, deep",
        "best_for": "mysterious characters, noir narration",
        "desc": "Rich and deep with a velvety, dark quality",
    },
    "am_puck": {
        "gender": "male",
        "accent": "American",
        "tone": "playful, mischievous",
        "best_for": "tricksters, comic relief, young characters",
        "desc": "Playful and mischievous with impish energy",
    },
    "am_santa": {
        "gender": "male",
        "accent": "American",
        "tone": "jolly, warm",
        "best_for": "grandfatherly characters, festive scenes",
        "desc": "Jolly and warm with a hearty, avuncular quality",
    },

    # -- British Female --
    "bf_alice": {
        "gender": "female",
        "accent": "British",
        "tone": "elegant, refined",
        "best_for": "aristocratic characters, period fiction",
        "desc": "Elegant and refined with crisp RP diction",
    },
    "bf_emma": {
        "gender": "female",
        "accent": "British",
        "tone": "warm, articulate",
        "best_for": "narration, educated characters",
        "desc": "Warm and articulate with a welcoming British tone",
    },
    "bf_isabella": {
        "gender": "female",
        "accent": "British",
        "tone": "sophisticated, measured",
        "best_for": "mystery, period drama, authority figures",
        "desc": "Sophisticated and measured with poised delivery",
    },
    "bf_lily": {
        "gender": "female",
        "accent": "British",
        "tone": "bright, cheerful",
        "best_for": "young characters, light-hearted scenes",
        "desc": "Bright and cheerful with an upbeat British lilt",
    },

    # -- British Male --
    "bm_daniel": {
        "gender": "male",
        "accent": "British",
        "tone": "warm, distinguished",
        "best_for": "gentleman characters, eloquent narration",
        "desc": "Warm and distinguished with a classic British charm",
    },
    "bm_fable": {
        "gender": "male",
        "accent": "British",
        "tone": "storytelling, narrative",
        "best_for": "narration, fairy tales, omniscient voice",
        "desc": "Storytelling voice with a natural narrative cadence",
    },
    "bm_george": {
        "gender": "male",
        "accent": "British",
        "tone": "deep, authoritative",
        "best_for": "commanders, judges, dramatic narration",
        "desc": "Deep and authoritative with gravitas",
    },
    "bm_lewis": {
        "gender": "male",
        "accent": "British",
        "tone": "clear, precise",
        "best_for": "intellectuals, scientists, precise dialogue",
        "desc": "Clear and precise with an intellectual quality",
    },

    # -- Japanese --
    "jf_alpha": {
        "gender": "female",
        "accent": "Japanese",
        "tone": "gentle, clear",
        "best_for": "Japanese-speaking characters",
        "desc": "Gentle and clear Japanese female voice",
    },
    "jf_gongitsune": {
        "gender": "female",
        "accent": "Japanese",
        "tone": "soft, expressive",
        "best_for": "Japanese narration, emotional scenes",
        "desc": "Soft and expressive Japanese female voice",
    },
    "jf_nezumi": {
        "gender": "female",
        "accent": "Japanese",
        "tone": "youthful, bright",
        "best_for": "young Japanese characters",
        "desc": "Youthful and bright Japanese female voice",
    },
    "jf_tebukuro": {
        "gender": "female",
        "accent": "Japanese",
        "tone": "warm, storytelling",
        "best_for": "Japanese narration",
        "desc": "Warm storytelling Japanese female voice",
    },
    "jm_kumo": {
        "gender": "male",
        "accent": "Japanese",
        "tone": "calm, measured",
        "best_for": "Japanese-speaking characters",
        "desc": "Calm and measured Japanese male voice",
    },

    # -- Chinese --
    "zf_xiaobei": {
        "gender": "female",
        "accent": "Chinese",
        "tone": "clear, bright",
        "best_for": "Chinese-speaking characters",
        "desc": "Clear and bright Chinese female voice",
    },
    "zf_xiaoni": {
        "gender": "female",
        "accent": "Chinese",
        "tone": "warm, friendly",
        "best_for": "Chinese narration",
        "desc": "Warm and friendly Chinese female voice",
    },
    "zf_xiaoxiao": {
        "gender": "female",
        "accent": "Chinese",
        "tone": "youthful, energetic",
        "best_for": "young Chinese characters",
        "desc": "Youthful and energetic Chinese female voice",
    },
    "zf_xiaoyi": {
        "gender": "female",
        "accent": "Chinese",
        "tone": "gentle, soft",
        "best_for": "gentle Chinese characters",
        "desc": "Gentle and soft Chinese female voice",
    },
    "zm_yunjian": {
        "gender": "male",
        "accent": "Chinese",
        "tone": "strong, clear",
        "best_for": "Chinese-speaking characters",
        "desc": "Strong and clear Chinese male voice",
    },
    "zm_yunxi": {
        "gender": "male",
        "accent": "Chinese",
        "tone": "warm, natural",
        "best_for": "Chinese narration",
        "desc": "Warm and natural Chinese male voice",
    },
    "zm_yunxia": {
        "gender": "male",
        "accent": "Chinese",
        "tone": "youthful, bright",
        "best_for": "young Chinese characters",
        "desc": "Youthful and bright Chinese male voice",
    },
    "zm_yunyang": {
        "gender": "male",
        "accent": "Chinese",
        "tone": "deep, authoritative",
        "best_for": "authority figures",
        "desc": "Deep and authoritative Chinese male voice",
    },

    # -- Korean --
    "kf_sarah": {
        "gender": "female",
        "accent": "Korean",
        "tone": "warm, conversational",
        "best_for": "Korean-speaking characters",
        "desc": "Warm conversational Korean female voice",
    },
    "kf_siwoo": {
        "gender": "female",
        "accent": "Korean",
        "tone": "bright, youthful",
        "best_for": "young Korean characters",
        "desc": "Bright and youthful Korean female voice",
    },
    "km_chul": {
        "gender": "male",
        "accent": "Korean",
        "tone": "strong, clear",
        "best_for": "Korean-speaking characters",
        "desc": "Strong and clear Korean male voice",
    },

    # -- French --
    "ff_siwis": {
        "gender": "female",
        "accent": "French",
        "tone": "elegant, flowing",
        "best_for": "French-speaking characters",
        "desc": "Elegant and flowing French female voice",
    },
    "fm_noel": {
        "gender": "male",
        "accent": "French",
        "tone": "warm, expressive",
        "best_for": "French-speaking characters",
        "desc": "Warm and expressive French male voice",
    },

    # -- Hindi --
    "hf_alpha": {
        "gender": "female",
        "accent": "Hindi",
        "tone": "clear, warm",
        "best_for": "Hindi-speaking characters",
        "desc": "Clear and warm Hindi female voice",
    },
    "hf_beta": {
        "gender": "female",
        "accent": "Hindi",
        "tone": "gentle, soft",
        "best_for": "Hindi narration",
        "desc": "Gentle and soft Hindi female voice",
    },
    "hm_omega": {
        "gender": "male",
        "accent": "Hindi",
        "tone": "deep, steady",
        "best_for": "Hindi-speaking characters",
        "desc": "Deep and steady Hindi male voice",
    },
    "hm_psi": {
        "gender": "male",
        "accent": "Hindi",
        "tone": "warm, natural",
        "best_for": "Hindi narration",
        "desc": "Warm and natural Hindi male voice",
    },

    # -- Italian --
    "if_sara": {
        "gender": "female",
        "accent": "Italian",
        "tone": "warm, melodic",
        "best_for": "Italian-speaking characters",
        "desc": "Warm and melodic Italian female voice",
    },
    "im_nicola": {
        "gender": "male",
        "accent": "Italian",
        "tone": "rich, expressive",
        "best_for": "Italian-speaking characters",
        "desc": "Rich and expressive Italian male voice",
    },

    # -- Portuguese (Brazilian) --
    "pf_dora": {
        "gender": "female",
        "accent": "Brazilian Portuguese",
        "tone": "warm, lively",
        "best_for": "Brazilian characters",
        "desc": "Warm and lively Brazilian Portuguese female voice",
    },
    "pm_alex": {
        "gender": "male",
        "accent": "Brazilian Portuguese",
        "tone": "friendly, natural",
        "best_for": "Brazilian characters",
        "desc": "Friendly and natural Brazilian Portuguese male voice",
    },
    "pm_santa": {
        "gender": "male",
        "accent": "Brazilian Portuguese",
        "tone": "warm, resonant",
        "best_for": "Brazilian narration",
        "desc": "Warm and resonant Brazilian Portuguese male voice",
    },

    # -- Spanish --
    "ef_dora": {
        "gender": "female",
        "accent": "Spanish",
        "tone": "warm, expressive",
        "best_for": "Spanish-speaking characters",
        "desc": "Warm and expressive Spanish female voice",
    },
    "em_alex": {
        "gender": "male",
        "accent": "Spanish",
        "tone": "clear, natural",
        "best_for": "Spanish-speaking characters",
        "desc": "Clear and natural Spanish male voice",
    },
    "em_santa": {
        "gender": "male",
        "accent": "Spanish",
        "tone": "warm, deep",
        "best_for": "Spanish narration",
        "desc": "Warm and deep Spanish male voice",
    },
}


def get_voice_info(voice_id):
    """Return metadata dict for a voice ID, or None if unknown."""
    return KOKORO_VOICES.get(voice_id)


def enrich_voice_list(voice_ids):
    """Enrich a list of voice ID strings with metadata.

    Returns a list of dicts with at minimum ``{"id": ..., "desc": ...}``.
    Unknown voices get a best-effort description parsed from the ID.
    """
    result = []
    for vid in voice_ids:
        info = KOKORO_VOICES.get(vid)
        if info:
            result.append({
                "id": vid,
                "desc": info["desc"],
                "gender": info["gender"],
                "accent": info["accent"],
                "tone": info["tone"],
                "best_for": info["best_for"],
            })
        else:
            result.append({
                "id": vid,
                "desc": _guess_desc(vid),
                "gender": _guess_gender(vid),
                "accent": _guess_accent(vid),
                "tone": "",
                "best_for": "",
            })
    return result


def get_catalog_summary():
    """Return a compact text summary of the voice catalog for LLM prompts."""
    lines = []
    grouped = {}
    for vid, info in KOKORO_VOICES.items():
        key = f"{info['accent']} {info['gender'].title()}"
        grouped.setdefault(key, []).append((vid, info))

    for group_key in sorted(grouped.keys()):
        lines.append(f"\n{group_key}:")
        for vid, info in grouped[group_key]:
            lines.append(f"  {vid} -- {info['desc']}. Best for: {info['best_for']}")

    return "KOKORO TTS VOICE CATALOG\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers for unknown voices
# ---------------------------------------------------------------------------

_ACCENT_PREFIXES = {
    "a": "American",
    "b": "British",
    "j": "Japanese",
    "z": "Chinese",
    "k": "Korean",
    "f": "French",
    "h": "Hindi",
    "i": "Italian",
    "p": "Portuguese",
    "e": "Spanish",
}


def _guess_accent(vid):
    """Guess accent from a Kokoro-style voice ID prefix."""
    if len(vid) >= 2 and vid[1] in ("f", "m") and vid[0] in _ACCENT_PREFIXES:
        return _ACCENT_PREFIXES[vid[0]]
    return ""


def _guess_gender(vid):
    """Guess gender from a Kokoro-style voice ID prefix."""
    if len(vid) >= 2 and vid[1] == "f":
        return "female"
    if len(vid) >= 2 and vid[1] == "m":
        return "male"
    return ""


def _guess_desc(vid):
    """Generate a best-effort description for an unknown voice ID."""
    accent = _guess_accent(vid)
    gender = _guess_gender(vid)
    name_part = vid.split("_", 1)[1] if "_" in vid else vid
    parts = []
    if accent:
        parts.append(accent)
    if gender:
        parts.append(gender)
    parts.append(f"voice ({name_part})")
    return " ".join(parts)
