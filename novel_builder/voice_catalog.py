"""Voice metadata catalog for TTS backends (Kokoro, Piper, etc.).

Provides casting-oriented metadata for known TTS voices: age range, pitch,
pacing, texture (smooth vs. gravelly), emotional tone, and best-for
recommendations.  These fields help authors make educated voice casting
decisions and feed the AI voice casting consultant enough detail to
match characters to voices by personality, age, and speaking style.
"""

# ---------------------------------------------------------------------------
# Kokoro voice catalog
# ---------------------------------------------------------------------------
# Naming convention:  {lang}{gender}_{name}
#   lang:   a = American English, b = British English,  -- speak English natively
#           f = French, h = Hindi, i = Italian,          -- speak English with accent
#           p = Portuguese, e = Spanish,                  -- speak English with accent
#           j = Japanese, z = Chinese, k = Korean         -- speak NATIVE LANGUAGE only
#   gender: f = female, m = male
#
# Source: Kokoro v1.0 by Hexgrad (MIT license).
#
# Field guide:
#   gender   -- male | female
#   accent   -- language/regional accent
#   age      -- young adult (18-25) | adult (25-40) | mature (40-55) |
#               senior (55+) | child
#   pitch    -- high | medium-high | medium | medium-low | low
#   pacing   -- fast | medium-fast | medium | medium-slow | slow
#   texture  -- smooth | clear | warm | breathy | crisp | gravelly |
#               silky | rich | raspy | bright | husky | velvety
#   tone     -- comma-separated emotional/tonal qualities
#   best_for -- casting recommendations (character types, scene types)
#   desc     -- one-line casting summary for UI display
# ---------------------------------------------------------------------------

KOKORO_VOICES = {
    # -- American Female --
    "af_heart": {
        "gender": "female",
        "accent": "American",
        "age": "adult",
        "pitch": "medium",
        "pacing": "medium",
        "texture": "warm",
        "tone": "warm, expressive, emotionally rich",
        "best_for": "narration, emotional scenes, protagonists, romantic leads",
        "desc": "Mid-range warm female; expressive with natural emotion; adult woman 25-40",
    },
    "af_alloy": {
        "gender": "female",
        "accent": "American",
        "age": "adult",
        "pitch": "medium",
        "pacing": "medium",
        "texture": "clear",
        "tone": "neutral, professional, steady",
        "best_for": "narration, professional characters, level-headed women",
        "desc": "Clear, balanced female; calm and professional; adult woman 25-40",
    },
    "af_aoede": {
        "gender": "female",
        "accent": "American",
        "age": "young adult",
        "pitch": "medium-high",
        "pacing": "medium-fast",
        "texture": "bright",
        "tone": "bright, youthful, energetic, perky",
        "best_for": "young women, college-age characters, upbeat scenes",
        "desc": "Bright higher-pitched female; energetic and youthful; young woman 18-25",
    },
    "af_bella": {
        "gender": "female",
        "accent": "American",
        "age": "adult",
        "pitch": "medium",
        "pacing": "medium",
        "texture": "crisp",
        "tone": "confident, polished, assertive, commanding",
        "best_for": "strong female leads, executives, authority figures, lawyers",
        "desc": "Polished confident female; assertive and direct; adult woman 30-45",
    },
    "af_jessica": {
        "gender": "female",
        "accent": "American",
        "age": "adult",
        "pitch": "medium",
        "pacing": "medium",
        "texture": "crisp",
        "tone": "articulate, professional, precise, composed",
        "best_for": "newscasters, doctors, businesswomen, sharp-witted characters",
        "desc": "Precise articulate female; composed and sharp; adult woman 28-40",
    },
    "af_kore": {
        "gender": "female",
        "accent": "American",
        "age": "mature",
        "pitch": "medium-low",
        "pacing": "medium-slow",
        "texture": "warm",
        "tone": "mature, grounded, steady, knowing",
        "best_for": "mentors, mothers, older women, calm authority, wise characters",
        "desc": "Lower-pitched mature female; grounded and steady; woman 40-55",
    },
    "af_nicole": {
        "gender": "female",
        "accent": "American",
        "age": "adult",
        "pitch": "medium",
        "pacing": "slow",
        "texture": "breathy",
        "tone": "soft, intimate, gentle, hushed",
        "best_for": "introspective scenes, romantic leads, pillow-talk, confessions",
        "desc": "Soft breathy female; intimate and gentle; slower pacing; woman 25-35",
    },
    "af_nova": {
        "gender": "female",
        "accent": "American",
        "age": "young adult",
        "pitch": "medium-high",
        "pacing": "fast",
        "texture": "bright",
        "tone": "energetic, vibrant, dynamic, spirited",
        "best_for": "action heroines, fast-paced dialogue, enthusiastic young characters",
        "desc": "Energetic higher-pitched female; fast and vibrant; young woman 20-30",
    },
    "af_river": {
        "gender": "female",
        "accent": "American",
        "age": "adult",
        "pitch": "medium-low",
        "pacing": "slow",
        "texture": "smooth",
        "tone": "calm, serene, flowing, unhurried, meditative",
        "best_for": "meditative narration, serene characters, dreamlike scenes, therapists",
        "desc": "Low calm female; smooth and unhurried; serene pacing; woman 30-45",
    },
    "af_sarah": {
        "gender": "female",
        "accent": "American",
        "age": "adult",
        "pitch": "medium",
        "pacing": "medium",
        "texture": "warm",
        "tone": "warm, conversational, natural, friendly, relatable",
        "best_for": "dialogue-heavy scenes, best friends, neighbors, everyday women",
        "desc": "Natural conversational female; friendly and relatable; woman 25-40",
    },
    "af_sky": {
        "gender": "female",
        "accent": "American",
        "age": "young adult",
        "pitch": "high",
        "pacing": "medium",
        "texture": "breathy",
        "tone": "light, airy, delicate, ethereal, dreamy",
        "best_for": "whimsical characters, fairies, young ingenues, children's narration",
        "desc": "High-pitched airy female; delicate and ethereal; young woman or teen",
    },

    # -- American Male --
    "am_adam": {
        "gender": "male",
        "accent": "American",
        "age": "mature",
        "pitch": "low",
        "pacing": "medium-slow",
        "texture": "gravelly",
        "tone": "deep, authoritative, commanding, stern",
        "best_for": "leaders, generals, villains, grizzled veterans, dramatic narration",
        "desc": "Deep gravelly male; commanding and stern; older man 45-60",
    },
    "am_echo": {
        "gender": "male",
        "accent": "American",
        "age": "adult",
        "pitch": "medium",
        "pacing": "medium",
        "texture": "clear",
        "tone": "resonant, clear, steady, reliable",
        "best_for": "narration, storytelling, reliable sidekicks, teachers",
        "desc": "Clear resonant male; steady and reliable; man 30-45",
    },
    "am_eric": {
        "gender": "male",
        "accent": "American",
        "age": "adult",
        "pitch": "medium",
        "pacing": "medium",
        "texture": "warm",
        "tone": "friendly, natural, approachable, easygoing",
        "best_for": "everyday guys, protagonists, dialogue-heavy scenes, neighbors",
        "desc": "Natural friendly male; approachable and easygoing; man 25-40",
    },
    "am_fenrir": {
        "gender": "male",
        "accent": "American",
        "age": "adult",
        "pitch": "medium-low",
        "pacing": "medium-fast",
        "texture": "raspy",
        "tone": "bold, intense, dramatic, aggressive, fierce",
        "best_for": "warriors, antagonists, action heroes, intense confrontations",
        "desc": "Raspy intense male; bold and aggressive; man 30-45; edgy delivery",
    },
    "am_liam": {
        "gender": "male",
        "accent": "American",
        "age": "young adult",
        "pitch": "medium",
        "pacing": "medium",
        "texture": "smooth",
        "tone": "warm, gentle, earnest, romantic, sincere",
        "best_for": "young protagonists, romantic leads, sensitive male characters",
        "desc": "Smooth warm male; gentle and sincere; young man 22-32",
    },
    "am_michael": {
        "gender": "male",
        "accent": "American",
        "age": "adult",
        "pitch": "medium",
        "pacing": "medium",
        "texture": "clear",
        "tone": "professional, balanced, measured, composed",
        "best_for": "businessmen, executives, detectives, neutral narration",
        "desc": "Balanced professional male; measured and composed; man 30-45",
    },
    "am_onyx": {
        "gender": "male",
        "accent": "American",
        "age": "mature",
        "pitch": "low",
        "pacing": "medium-slow",
        "texture": "velvety",
        "tone": "rich, deep, mysterious, dark, seductive",
        "best_for": "mysterious strangers, noir narration, seducers, shadowy figures",
        "desc": "Deep velvety male; dark and mysterious; slower pacing; man 35-50",
    },
    "am_puck": {
        "gender": "male",
        "accent": "American",
        "age": "young adult",
        "pitch": "medium-high",
        "pacing": "fast",
        "texture": "bright",
        "tone": "playful, mischievous, impish, cheeky, quick-witted",
        "best_for": "tricksters, comic relief, young rogues, teenage boys, sidekicks",
        "desc": "Higher-pitched quick male; playful and cheeky; young man or teen 16-25",
    },
    "am_santa": {
        "gender": "male",
        "accent": "American",
        "age": "senior",
        "pitch": "medium-low",
        "pacing": "medium-slow",
        "texture": "warm",
        "tone": "jolly, hearty, avuncular, gentle, grandfatherly",
        "best_for": "grandfathers, kindly elders, innkeepers, warm mentor figures",
        "desc": "Warm hearty male; jolly and grandfatherly; older man 55+; gentle pacing",
    },

    # -- British Female --
    "bf_alice": {
        "gender": "female",
        "accent": "British (RP)",
        "age": "adult",
        "pitch": "medium",
        "pacing": "medium",
        "texture": "crisp",
        "tone": "elegant, refined, poised, aristocratic",
        "best_for": "nobility, aristocratic women, period fiction heroines, governesses",
        "desc": "Crisp RP female; elegant and refined; well-bred woman 25-40",
    },
    "bf_emma": {
        "gender": "female",
        "accent": "British",
        "age": "adult",
        "pitch": "medium",
        "pacing": "medium",
        "texture": "warm",
        "tone": "warm, articulate, welcoming, intelligent",
        "best_for": "narration, educated women, librarians, teachers, bookish characters",
        "desc": "Warm articulate British female; welcoming and smart; woman 28-42",
    },
    "bf_isabella": {
        "gender": "female",
        "accent": "British",
        "age": "mature",
        "pitch": "medium-low",
        "pacing": "medium-slow",
        "texture": "smooth",
        "tone": "sophisticated, measured, poised, commanding, cool",
        "best_for": "matriarchs, mystery dames, headmistresses, period drama authority",
        "desc": "Lower-pitched British female; poised and commanding; woman 40-55",
    },
    "bf_lily": {
        "gender": "female",
        "accent": "British",
        "age": "young adult",
        "pitch": "medium-high",
        "pacing": "medium-fast",
        "texture": "bright",
        "tone": "bright, cheerful, perky, lively, upbeat",
        "best_for": "young British women, plucky heroines, light comedy, spirited girls",
        "desc": "Bright cheerful British female; lively and upbeat; young woman 18-28",
    },

    # -- British Male --
    "bm_daniel": {
        "gender": "male",
        "accent": "British",
        "age": "adult",
        "pitch": "medium",
        "pacing": "medium",
        "texture": "smooth",
        "tone": "warm, distinguished, charming, debonair",
        "best_for": "gentleman heroes, debonair leads, eloquent narration, spies",
        "desc": "Smooth British male; charming and distinguished; man 30-45",
    },
    "bm_fable": {
        "gender": "male",
        "accent": "British",
        "age": "mature",
        "pitch": "medium",
        "pacing": "medium-slow",
        "texture": "warm",
        "tone": "storytelling, narrative, patient, measured, reflective",
        "best_for": "omniscient narration, fairy tales, bedtime stories, wise observers",
        "desc": "Warm narrative British male; patient storytelling pace; man 40-55",
    },
    "bm_george": {
        "gender": "male",
        "accent": "British",
        "age": "mature",
        "pitch": "low",
        "pacing": "medium-slow",
        "texture": "rich",
        "tone": "deep, authoritative, commanding, imposing, grave",
        "best_for": "commanders, judges, kings, dramatic villains, gravitas narration",
        "desc": "Deep rich British male; imposing gravitas; older man 45-60",
    },
    "bm_lewis": {
        "gender": "male",
        "accent": "British",
        "age": "adult",
        "pitch": "medium",
        "pacing": "medium-fast",
        "texture": "crisp",
        "tone": "clear, precise, analytical, quick, intellectual",
        "best_for": "professors, scientists, detectives, quick-thinking intellectuals",
        "desc": "Crisp precise British male; analytical and quick; man 30-45",
    },

    # -- Japanese --
    "jf_alpha": {
        "gender": "female",
        "accent": "Japanese",
        "age": "adult",
        "pitch": "medium",
        "pacing": "medium",
        "texture": "clear",
        "tone": "gentle, clear, calm",
        "best_for": "Japanese-speaking female characters, composed women",
        "desc": "Clear gentle Japanese female; calm delivery; woman 25-40",
    },
    "jf_gongitsune": {
        "gender": "female",
        "accent": "Japanese",
        "age": "adult",
        "pitch": "medium",
        "pacing": "medium-slow",
        "texture": "smooth",
        "tone": "soft, expressive, emotional, wistful",
        "best_for": "emotional Japanese scenes, narration, melancholic characters",
        "desc": "Soft expressive Japanese female; emotional and wistful; woman 25-40",
    },
    "jf_nezumi": {
        "gender": "female",
        "accent": "Japanese",
        "age": "young adult",
        "pitch": "high",
        "pacing": "medium-fast",
        "texture": "bright",
        "tone": "youthful, bright, energetic, cute",
        "best_for": "young Japanese women, energetic girls, anime-style characters",
        "desc": "High-pitched bright Japanese female; youthful and energetic; girl 16-22",
    },
    "jf_tebukuro": {
        "gender": "female",
        "accent": "Japanese",
        "age": "mature",
        "pitch": "medium-low",
        "pacing": "medium-slow",
        "texture": "warm",
        "tone": "warm, storytelling, maternal, soothing",
        "best_for": "Japanese narration, motherly characters, bedtime stories",
        "desc": "Warm low Japanese female; maternal storytelling pace; woman 35-50",
    },
    "jm_kumo": {
        "gender": "male",
        "accent": "Japanese",
        "age": "adult",
        "pitch": "medium-low",
        "pacing": "medium-slow",
        "texture": "smooth",
        "tone": "calm, measured, composed, contemplative",
        "best_for": "stoic Japanese men, samurai, monks, contemplative characters",
        "desc": "Low calm Japanese male; measured and composed; man 30-50",
    },

    # -- Chinese --
    "zf_xiaobei": {
        "gender": "female",
        "accent": "Chinese (Mandarin)",
        "age": "young adult",
        "pitch": "medium-high",
        "pacing": "medium",
        "texture": "clear",
        "tone": "clear, bright, crisp",
        "best_for": "young Chinese women, news-style delivery",
        "desc": "Clear bright Chinese female; crisp diction; young woman 20-30",
    },
    "zf_xiaoni": {
        "gender": "female",
        "accent": "Chinese (Mandarin)",
        "age": "adult",
        "pitch": "medium",
        "pacing": "medium",
        "texture": "warm",
        "tone": "warm, friendly, approachable",
        "best_for": "Chinese narration, friendly female characters",
        "desc": "Warm friendly Chinese female; approachable; woman 25-38",
    },
    "zf_xiaoxiao": {
        "gender": "female",
        "accent": "Chinese (Mandarin)",
        "age": "young adult",
        "pitch": "high",
        "pacing": "medium-fast",
        "texture": "bright",
        "tone": "youthful, energetic, animated",
        "best_for": "young energetic Chinese women, lively scenes",
        "desc": "High-pitched energetic Chinese female; lively and animated; girl 18-25",
    },
    "zf_xiaoyi": {
        "gender": "female",
        "accent": "Chinese (Mandarin)",
        "age": "adult",
        "pitch": "medium",
        "pacing": "medium-slow",
        "texture": "smooth",
        "tone": "gentle, soft, soothing",
        "best_for": "gentle Chinese women, calming narration",
        "desc": "Soft soothing Chinese female; gentle pacing; woman 25-38",
    },
    "zm_yunjian": {
        "gender": "male",
        "accent": "Chinese (Mandarin)",
        "age": "adult",
        "pitch": "medium-low",
        "pacing": "medium",
        "texture": "clear",
        "tone": "strong, clear, direct, confident",
        "best_for": "confident Chinese men, military, leaders",
        "desc": "Strong clear Chinese male; direct and confident; man 28-42",
    },
    "zm_yunxi": {
        "gender": "male",
        "accent": "Chinese (Mandarin)",
        "age": "adult",
        "pitch": "medium",
        "pacing": "medium",
        "texture": "warm",
        "tone": "warm, natural, friendly, easygoing",
        "best_for": "Chinese narration, approachable male characters",
        "desc": "Warm natural Chinese male; friendly and easygoing; man 25-40",
    },
    "zm_yunxia": {
        "gender": "male",
        "accent": "Chinese (Mandarin)",
        "age": "young adult",
        "pitch": "medium-high",
        "pacing": "medium-fast",
        "texture": "bright",
        "tone": "youthful, bright, lively",
        "best_for": "young Chinese men, energetic male characters",
        "desc": "Bright youthful Chinese male; lively pacing; young man 18-28",
    },
    "zm_yunyang": {
        "gender": "male",
        "accent": "Chinese (Mandarin)",
        "age": "mature",
        "pitch": "low",
        "pacing": "medium-slow",
        "texture": "rich",
        "tone": "deep, authoritative, commanding",
        "best_for": "authority figures, elders, Chinese dramatic narration",
        "desc": "Deep rich Chinese male; authoritative and commanding; man 45-60",
    },

    # -- Korean --
    "kf_sarah": {
        "gender": "female",
        "accent": "Korean",
        "age": "adult",
        "pitch": "medium",
        "pacing": "medium",
        "texture": "warm",
        "tone": "warm, conversational, natural",
        "best_for": "Korean women, conversational dialogue",
        "desc": "Warm conversational Korean female; natural pacing; woman 25-38",
    },
    "kf_siwoo": {
        "gender": "female",
        "accent": "Korean",
        "age": "young adult",
        "pitch": "medium-high",
        "pacing": "medium-fast",
        "texture": "bright",
        "tone": "bright, youthful, cheerful",
        "best_for": "young Korean women, cheerful characters",
        "desc": "Bright youthful Korean female; cheerful and quick; girl 18-25",
    },
    "km_chul": {
        "gender": "male",
        "accent": "Korean",
        "age": "adult",
        "pitch": "medium-low",
        "pacing": "medium",
        "texture": "clear",
        "tone": "strong, clear, steady, reliable",
        "best_for": "Korean men, dependable male characters",
        "desc": "Clear strong Korean male; steady and reliable; man 28-42",
    },

    # -- French --
    "ff_siwis": {
        "gender": "female",
        "accent": "French",
        "age": "adult",
        "pitch": "medium",
        "pacing": "medium",
        "texture": "silky",
        "tone": "elegant, flowing, melodic, sophisticated",
        "best_for": "French women, sophisticated characters, romantic scenes",
        "desc": "Silky elegant French female; flowing and sophisticated; woman 25-40",
    },
    "fm_noel": {
        "gender": "male",
        "accent": "French",
        "age": "adult",
        "pitch": "medium",
        "pacing": "medium",
        "texture": "warm",
        "tone": "warm, expressive, charming, animated",
        "best_for": "French men, passionate characters, romantic leads",
        "desc": "Warm expressive French male; charming and animated; man 28-42",
    },

    # -- Hindi --
    "hf_alpha": {
        "gender": "female",
        "accent": "Hindi",
        "age": "adult",
        "pitch": "medium",
        "pacing": "medium",
        "texture": "clear",
        "tone": "clear, warm, composed",
        "best_for": "Hindi-speaking women, composed female characters",
        "desc": "Clear warm Hindi female; composed delivery; woman 25-38",
    },
    "hf_beta": {
        "gender": "female",
        "accent": "Hindi",
        "age": "adult",
        "pitch": "medium",
        "pacing": "medium-slow",
        "texture": "smooth",
        "tone": "gentle, soft, soothing, calming",
        "best_for": "Hindi narration, gentle women, maternal characters",
        "desc": "Soft soothing Hindi female; gentle pacing; woman 25-40",
    },
    "hm_omega": {
        "gender": "male",
        "accent": "Hindi",
        "age": "mature",
        "pitch": "low",
        "pacing": "medium-slow",
        "texture": "rich",
        "tone": "deep, steady, authoritative, weighty",
        "best_for": "Hindi authority figures, fathers, elders, serious men",
        "desc": "Deep rich Hindi male; steady and authoritative; man 40-55",
    },
    "hm_psi": {
        "gender": "male",
        "accent": "Hindi",
        "age": "adult",
        "pitch": "medium",
        "pacing": "medium",
        "texture": "warm",
        "tone": "warm, natural, friendly, approachable",
        "best_for": "Hindi narration, friendly male characters, protagonists",
        "desc": "Warm natural Hindi male; friendly and approachable; man 25-40",
    },

    # -- Italian --
    "if_sara": {
        "gender": "female",
        "accent": "Italian",
        "age": "adult",
        "pitch": "medium",
        "pacing": "medium",
        "texture": "warm",
        "tone": "warm, melodic, expressive, passionate",
        "best_for": "Italian women, passionate characters, emotional scenes",
        "desc": "Warm melodic Italian female; passionate and expressive; woman 25-40",
    },
    "im_nicola": {
        "gender": "male",
        "accent": "Italian",
        "age": "adult",
        "pitch": "medium",
        "pacing": "medium",
        "texture": "rich",
        "tone": "rich, expressive, animated, charismatic",
        "best_for": "Italian men, charismatic characters, dramatic dialogue",
        "desc": "Rich expressive Italian male; charismatic and animated; man 28-45",
    },

    # -- Portuguese (Brazilian) --
    "pf_dora": {
        "gender": "female",
        "accent": "Brazilian Portuguese",
        "age": "adult",
        "pitch": "medium",
        "pacing": "medium",
        "texture": "warm",
        "tone": "warm, lively, friendly, spirited",
        "best_for": "Brazilian women, lively characters, warm dialogue",
        "desc": "Warm lively Brazilian female; friendly and spirited; woman 25-38",
    },
    "pm_alex": {
        "gender": "male",
        "accent": "Brazilian Portuguese",
        "age": "young adult",
        "pitch": "medium",
        "pacing": "medium",
        "texture": "clear",
        "tone": "friendly, natural, casual, relaxed",
        "best_for": "young Brazilian men, casual characters, laid-back dialogue",
        "desc": "Clear friendly Brazilian male; relaxed and natural; young man 22-32",
    },
    "pm_santa": {
        "gender": "male",
        "accent": "Brazilian Portuguese",
        "age": "mature",
        "pitch": "medium-low",
        "pacing": "medium-slow",
        "texture": "rich",
        "tone": "warm, resonant, avuncular, steady",
        "best_for": "Brazilian narration, older men, warm authority figures",
        "desc": "Rich warm Brazilian male; resonant and steady; man 40-55",
    },

    # -- Spanish --
    "ef_dora": {
        "gender": "female",
        "accent": "Spanish",
        "age": "adult",
        "pitch": "medium",
        "pacing": "medium",
        "texture": "warm",
        "tone": "warm, expressive, passionate, heartfelt",
        "best_for": "Spanish women, emotional characters, passionate dialogue",
        "desc": "Warm expressive Spanish female; passionate delivery; woman 25-40",
    },
    "em_alex": {
        "gender": "male",
        "accent": "Spanish",
        "age": "young adult",
        "pitch": "medium",
        "pacing": "medium",
        "texture": "clear",
        "tone": "clear, natural, easygoing, direct",
        "best_for": "young Spanish men, straightforward characters",
        "desc": "Clear natural Spanish male; direct and easygoing; young man 22-32",
    },
    "em_santa": {
        "gender": "male",
        "accent": "Spanish",
        "age": "mature",
        "pitch": "low",
        "pacing": "medium-slow",
        "texture": "rich",
        "tone": "warm, deep, resonant, paternal",
        "best_for": "Spanish narration, elder men, fathers, warm authority",
        "desc": "Deep warm Spanish male; resonant and paternal; man 45-60",
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
    _FIELDS = ("desc", "gender", "accent", "age", "pitch", "pacing",
               "texture", "tone", "best_for")
    result = []
    for vid in voice_ids:
        info = KOKORO_VOICES.get(vid)
        if info:
            entry = {"id": vid}
            for f in _FIELDS:
                entry[f] = info.get(f, "")
            result.append(entry)
        else:
            result.append({
                "id": vid,
                "desc": _guess_desc(vid),
                "gender": _guess_gender(vid),
                "accent": _guess_accent(vid),
                "age": "",
                "pitch": "",
                "pacing": "",
                "texture": "",
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
            age = info.get("age", "")
            pitch = info.get("pitch", "")
            pacing = info.get("pacing", "")
            texture = info.get("texture", "")
            traits = ", ".join(t for t in [age, pitch + " pitch" if pitch else "",
                                           texture, pacing + " pace" if pacing else ""]
                               if t)
            lines.append(
                f"  {vid} [{traits}] -- {info['desc']}. "
                f"Best for: {info['best_for']}"
            )

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
