#!/usr/bin/env python3
"""Full passage test for TTS segmentation."""
import sys
from novel_builder.tts import segment_text_for_tts

FULL_TEXT = '''### Chapter 1: The Empire

The bell above the door, a brass monstrosity shaped like a grinning clown, shrieked as he pushed it open. It wasn't a gentle chime, but a piercing clang that vibrated in his teeth. Elias flinched, instinctively pressing a hand to his chest. The sound seemed to amplify the tremor already humming beneath his skin.

The air inside was thick, a humid blanket of cedar wood and something else—a sweetness he couldn't place, overlaid with the dry scent of aging paper. Dust motes danced in the shafts of light filtering through the grimy windows, illuminating rows upon rows of toys. Empire Toys and Hobbies. The name felt grander than the reality.

Three stories of crammed shelves, narrow aisles barely wider than his shoulders. The floorboards groaned under his weight, a chorus of complaints from decades past. He felt a sudden, almost irrational urge to apologize to the building itself.

He'd seen the place from the street countless times, always drawn to its faded charm. A defiant splash of color amidst the steel and glass of the city. Now, standing inside, he felt swallowed by it. It was a museum of forgotten childhoods, a mausoleum of plastic and cardboard.

"You Elias?"

The voice startled him. He turned to see a man emerge from behind a precarious tower of vintage board games. He was small, barely reaching Elias's shoulder, with a shock of white hair that defied gravity and spectacles perpetually sliding down his nose. He wore a faded, mustard-yellow cardigan buttoned haphazardly over a stained t-shirt.

"Yes, that's me," Elias said, his voice sounding unnaturally loud in the quiet space. He extended a hand. "Elias Thorne."

The man's grip was surprisingly firm. "Morty Silver. Welcome to the Empire. Don't mind the chaos." He gestured around the store with a dismissive wave. "It's… organized chaos, I prefer to think."

Elias scanned the room, taking in the sheer volume of… *stuff*. Action figures frozen in mid-battle, miniature trains circling a decaying landscape, dolls with vacant stares. Dead stock, most of it, he guessed. Things that hadn't been touched in years.

"It's… quite a collection," he managed, searching for something polite to say.

Morty chuckled, a dry, rustling sound. "Collection? It's a liability, mostly. But it's *my* liability. Been here since my father started the place. Sixty-two years ago." He peered at Elias over his glasses. "You look like a man who appreciates order."'''

CHARACTERS = ["Elias Thorne", "Morty Wick"]


def test_full_passage():
    segs = segment_text_for_tts(FULL_TEXT, CHARACTERS)
    print("=== Full passage (with header + mixed paragraphs) ===")
    for i, s in enumerate(segs):
        tag = f"[{s['character'] or 'NARRATOR'}]"
        preview = s['text'][:70].replace('\n', ' ')
        print(f"  {i:2d}. {s['type']:10s} {tag:20s} {preview}...")
    print()

    errors = 0

    # Header should be read by narrator
    assert segs[0]["type"] == "narration", "seg[0] should be narration (header)"
    assert segs[0]["character"] is None, "seg[0] character should be None"
    assert "Chapter 1" in segs[0]["text"] or "Empire" in segs[0]["text"]
    print("  OK   seg[0]: header read by narrator")

    # Find the segment containing "Yes, that's me,"
    yes_segs = [s for s in segs if "Yes, that" in s["text"]]
    for s in yes_segs:
        if s["type"] == "dialogue":
            assert s["character"] == "Elias Thorne", f"'Yes, that's me' should be Elias, got {s['character']}"
            print(f"  OK   'Yes, that\u2019s me,' → Elias")
        else:
            assert s["character"] is None, f"Narration beat should have no character, got {s['character']}"
            print(f"  OK   narration beat in Elias paragraph → narrator")

    # "He extended a hand." should be narration (not Elias voice)
    extended = [s for s in segs if "extended a hand" in s["text"]]
    for s in extended:
        assert s["type"] == "narration" and s["character"] is None, \
            f"'He extended a hand.' should be narrator, got type={s['type']} char={s['character']}"
        print("  OK   'He extended a hand.' → narrator")

    # "Morty Silver. Welcome..." quote should be Morty
    morty_welcome = [s for s in segs if "Welcome to the Empire" in s["text"]]
    for s in morty_welcome:
        assert s["type"] == "dialogue" and s["character"] == "Morty Wick", \
            f"'Morty Silver. Welcome...' should be Morty Wick, got {s['character']}"
        print("  OK   'Morty Silver. Welcome...' → Morty Wick")

    # "He gestured around the store" should be narration
    gestured = [s for s in segs if "gestured around" in s["text"]]
    for s in gestured:
        assert s["type"] == "narration" and s["character"] is None, \
            f"'He gestured...' should be narrator, got {s['character']}"
        print("  OK   'He gestured around the store' → narrator")

    # "It's… organized chaos" should be Morty
    chaos = [s for s in segs if "organized chaos" in s["text"]]
    for s in chaos:
        assert s["type"] == "dialogue" and s["character"] == "Morty Wick", \
            f"'organized chaos' should be Morty Wick, got {s['character']}"
        print("  OK   'It\u2019s\u2026 organized chaos' → Morty Wick")

    return errors


def test_rapid_back_and_forth():
    text2 = '''"I don't think that's a good idea," Claire said.

"Why not?"

"Because it's dangerous."

"I don't care."

"You should."

Marcus sighed. "Fine, let's at least bring supplies."

"Deal."'''
    segs = segment_text_for_tts(text2, ["Claire", "Marcus"])
    print("\n=== Rapid back-and-forth ===")
    for i, s in enumerate(segs):
        tag = f"[{s['character'] or 'NARRATOR'}]"
        preview = s['text'][:70].replace('\n', ' ')
        print(f"  {i:2d}. {s['type']:10s} {tag:20s} {preview}...")

    # "Marcus sighed." should split: narration then dialogue
    sighed = [s for s in segs if "sighed" in s["text"]]
    fine = [s for s in segs if "supplies" in s["text"]]
    errors = 0
    for s in sighed:
        if s["type"] != "narration":
            print(f"  FAIL 'Marcus sighed.' should be narration, got {s['type']}")
            errors += 1
        else:
            print("  OK   'Marcus sighed.' → narrator")
    for s in fine:
        if s["type"] != "dialogue" or s["character"] != "Marcus":
            print(f"  FAIL '\"Fine,...\"' should be Marcus dialogue, got {s['type']}/{s['character']}")
            errors += 1
        else:
            print("  OK   '\"Fine, let\u2019s...\"' → Marcus")
    return errors


if __name__ == "__main__":
    e1 = test_full_passage()
    e2 = test_rapid_back_and_forth()
    total = e1 + e2
    print(f"\n{'='*70}")
    if total == 0:
        print("ALL TESTS PASSED")
    else:
        print(f"FAILURES: {total}")
    print(f"{'='*70}")
    sys.exit(total)
