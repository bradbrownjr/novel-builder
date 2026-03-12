# Tips for Best Results

Short, practical advice for getting better output from the generation engine.

## 1. Invest in `vibe`

This single field has the highest impact on output quality. It shapes *how the character feels to the reader* — more valuable than listing facts.

```yaml
# Weak
vibe: "A brave warrior"

# Strong
vibe: "Someone who charges into danger not from courage but from an inability to sit still and think."
```

## 2. Use `voice` for dialogue

If dialogue feels generic, add a `voice` field. It shapes how a character *speaks*, separate from who they are.

```yaml
voice: "Short fragments, avoids direct answers, speaks in metaphors."
```

## 3. Write `notes` for the AI

Scene notes are your direct channel to the generation model. Be specific about what you want the scene to *feel* like.

```yaml
notes: "Make this tense. Let the silence carry the scene. No one says what they mean."
```

## 4. Start small, add detail

Write a bare outline first. Generate. Read the output. Then add `personality`, `voice`, `evolution`, and `pacing` where the output needs sharpening. Don't front-load every field.

## 5. Use the dry run

Before a long generation run, `--dry-run` catches YAML errors and shows you exactly what each scene will include — characters, setting, prompt structure.

```bash
python -m novel_builder --dry-run
```

## 6. Tag `pacing` on pivotal scenes

The AI defaults to mid-pace. Tagging a scene changes the output noticeably.

```yaml
pacing: slow-burn    # Lingering, atmospheric, internal
pacing: action       # Fast, kinetic, short paragraphs
pacing: dialogue-heavy
pacing: introspective
```

## 7. Don't fight the length

Scenes take the space they need. A dialogue-heavy scene will be shorter than a world-building opener. That's correct. No word count targets are imposed by design.

## 8. Use `evolution` for character growth

Characters can change across the story. Add evolution notes that get injected after the first appearance.

```yaml
evolution:
  - after_chapter: 2
    note: "Now distrustful of authority after the betrayal."
  - after_chapter: 4
    note: "Starting to open up. Less guarded in dialogue."
```

## 9. Use `secret` sparingly

The `secret` field is only included when the scene's notes reference tension or subtext. Don't expect it in every scene — that's by design.

## 10. Heritage saves repetition

If multiple characters share traits (species, faction, profession), define them once in `heritage` and reference by ID. Character-level fields always override.

```yaml
heritage:
  starfleet:
    label: "Starfleet Officer"
    traits: [disciplined, formal speech, duty-bound]

characters:
  picard:
    heritage: [starfleet]
    # Picard-specific fields override starfleet defaults
```

---

## 11. Anti-patterns have built-in defaults

You don't need to add common problems like purple prose, emoji, or em-dashes to your `anti_patterns` list — they're suppressed by default in every prompt. Only add patterns specific to your project:

```yaml
anti_patterns:
  - "shiver down * spine"    # Your addition
  - "a wave of *"            # Your addition
  # No need to add "delve", emoji, em-dashes, etc. — already covered
```

If you do add a duplicate, it's automatically skipped to save tokens.

---

← [Back to README](../README.md)
