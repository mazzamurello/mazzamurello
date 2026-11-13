# ADR-0070: The design language and the sprite

- **Status:** Accepted
- **Date:** 2026-11-03
- **Deciders:** @tapionx
- **Related:** ADR-0058, ADR-0067, ADR-0068, ADR-0069, OBS-001, UX-003, UX-007, UX-011, UX-012, UX-013, UX-014, UX-015, UX-016, UX-017

## Context

The first web client (ADR-0067) worked, and looked like a skeleton: plain
boxes, placeholder characters as icons, no typography, and dark mode only in
part. The maintainer wants a client of professional quality, familiar to
people who already use a leading AI assistant, so that switching costs
nothing, without taking any other product's identity: no logos, colors,
typefaces or illustrations of another product.

The maintainer also wants the household to have a character: a small sprite
that greets people and shows what the assistant is doing. Sibillo is a
mazzamurello, by name: the mazzamurello of central Italian folklore is a
small house sprite known for knocking on walls. The maintainer chose the
look from a folklore illustration, which is someone else's work and must not
be copied.

A clickable prototype of the main screens was built and approved before this
record; it is kept as [`specs/design/web-prototype.html`](../design/web-prototype.html).

## Decision

1. **A familiar layout.** The conversation list on the side, which slides over
   the conversation on phones; one centered column for the conversation; the
   message box docked below it with the model picker (UX-015); actions on a
   message shown on hover, and always on touch screens; tool activity as
   compact rows that expand (UX-003); settings as pages with sections.
2. **Colors as tokens, in two themes.** Every color is a named token with a
   light and a dark value; the theme follows the device unless the user
   chooses one (UX-011). Neutrals are near-grey; the accent is the red of the
   sprite's hat. Colors for success and errors are separate from the accent.
3. **Open typefaces, bundled.** Hanken Grotesk for the interface and messages,
   Newsreader for quotes, JetBrains Mono for code: all under the SIL Open Font
   License, served by the app itself, so no font request reaches a third
   party (OBS-001) and the Content Security Policy needs no other origin.
4. **One icon set.** Lucide's icons (ISC license), imported one by one, in
   place of placeholder characters.
5. **The sprite is an original sibillo.** Small and lanky, with a big
   floppy red hat, pointy ears, straw-colored hair and eyes closed in a smile,
   in red stockings. It is drawn as SVG and animated with CSS: an animation
   runtime would add weight, and the policy blocks the WebAssembly some of
   them need (ADR-0067). It has one pose per moment:

   | Moment | Pose |
   |---|---|
   | The home screen | waves, beside a quote (UX-012) |
   | The model is working | thinks, with dots above its head |
   | Searching the web | searches with a lens |
   | Reading a page or a file | reads a book |
   | Writing a file | writes in a notebook |
   | Running a command | knocks with its mallet |
   | The answer streams | bobs gently |
   | The run has ended | stands still, waiting |
   | An error | holds up a sign, in the error notice (UX-014) |

   Clients choose the pose from the run's events: the tool being called
   decides it, and any other tool shows the thinking pose (UX-013). The
   sprite is decorative: hidden from assistive technologies, with the same
   information given as text, and still when the device asks for reduced
   motion (UX-007).
6. **Quotes from the public domain.** The greeting shows a quote chosen at
   random from a short list of famous lines whose authors died long ago, in
   translations that are in the public domain or written by the project,
   with author and work, kept in the client's translation files (I18N-001).
7. **The prototype is the reference.** The implementation follows its
   layout, tokens, sprite and wording. Its sample data, scripted answers and
   prototype controls are not part of the design.

## Consequences

- The app gains about 200 KB of fonts, subset to the scripts the translations
  use.
- Looks are not tested automatically; a reviewer checks them against the
  prototype (UX-017), while tests check behavior and accessibility.
- The sprite is drawn in code, so it can change pose by pose; an illustrator
  can redraw it later without changing how it is animated.
- New screens reuse the tokens and components, instead of designing anew.

## Alternatives considered

- **A ready-made component kit with its own look:** quick, and recognizably
  generic.
- **Animations made in an animation tool and played by a runtime:** richer,
  but a runtime to ship and, for some, WebAssembly that the policy forbids.
- **Fonts from a web font service:** every page load would tell a third party
  who opens the app.
- **A sprite traced from the illustration the maintainer liked:** that drawing
  belongs to its author.
