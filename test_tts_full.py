#!/usr/bin/env python3
"""Full passage test for TTS segmentation."""
import sys
from novel_builder.tts import segment_text_for_tts

FULL_TEXT = r'''The bell above the door, a brass monstrosity shaped like a grinning clown, shrieked as he pushed it open. It wasn't a gentle chime, but a piercing clang that vibrated in his teeth. Elias flinched, instinctively pressing a hand to his chest. The sound seemed to amplify the tremor already humming beneath his skin.

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
    print("=== Full passage attribution (Morty Wick in YAML, Morty Silver in prose) ===")
    for i, s in enumerate(segs):
        tag = f"[{s['character'] or 'NARRATOR'}]"
        preview = s['text'][:80].replace('\n', ' ')
        print(f"  {i:2d}. {s['type']:10s} {tag:20s} {preview}...")

    expected = {
        4: ("dialogue", "Morty Wick"),
        6: ("dialogue", "Elias Thorne"),
        7: ("dialogue", "Morty Wick"),
        9: ("dialogue", "Elias Thorne"),
        10: ("dialogue", "Morty Wick"),
    }
    errors = 0
    print()
    for idx, (etype, echar) in expected.items():
        seg = segs[idx]
        ok = seg["type"] == etype and seg["character"] == echar
        label = "OK  " if ok else "FAIL"
        print(f"  {label} seg[{idx}]: expected ({etype}, {echar}) — got ({seg['type']}, {seg['character']})")
        if not ok:
            errors += 1
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

    expected = {
        0: ("dialogue", "Claire"),
        1: ("dialogue", "Marcus"),
        2: ("dialogue", "Claire"),
        3: ("dialogue", "Marcus"),
        4: ("dialogue", "Claire"),
        5: ("dialogue", "Marcus"),
        6: ("dialogue", "Claire"),
    }
    errors = 0
    print()
    for idx, (etype, echar) in expected.items():
        seg = segs[idx]
        ok = seg["type"] == etype and seg["character"] == echar
        label = "OK  " if ok else "FAIL"
        print(f"  {label} seg[{idx}]: expected ({etype}, {echar}) — got ({seg['type']}, {seg['character']})")
        if not ok:
            errors += 1
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
