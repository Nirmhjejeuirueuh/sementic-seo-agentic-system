# The Getfiguro Knowledge Vault — authoring convention

This folder is an Obsidian vault. Every fact that ends up in the graph
from here comes from **YAML frontmatter you write by hand** — not from an
AI guessing at prose. If a fact isn't in the frontmatter, it does not
enter the graph. No fallback invents it. (See `CLAUDE.md` rule 9.)

Open this folder as a vault in Obsidian (`File → Open folder as vault`)
if you want the visual graph view and `[[wikilink]]` autocomplete. It
also works as plain text in any editor — Obsidian is optional tooling on
top of ordinary markdown files.

---

## Folder layout

```
products/     one note per sellable item        (type: Product)      37
styles/       the art style                      (type: FigurineStyle) 6
types/        what the figurine is OF             (type: FigurineType) 12
occasions/    the gifting / life event            (type: Occasion)    15
formats/      the physical form                   (type: Format)       3
recipients/   who it's a gift for                  (type: Recipient)    9
accessories/  add-ons                              (type: Accessory)    0
```

`accessories/` is deliberately still empty: no product in the source
document states that a figurine pairs with a specific accessory, so
there is nothing true to tag yet. The folder is scaffolded and waiting.

---

## Two kinds of note

### 1. Taxonomy notes (`styles/`, `types/`, `occasions/`, …)

One note per concept. Already fully written for styles/types/occasions —
you don't need to create these yourself. Shape:

```markdown
---
type: Occasion
title: Christmas / Holiday
collection_url: /collections/christmas-gifts
status: proposed
primary_keyword: custom christmas figurine
season: Oct–Dec
source_section: "3"
---

Seasonal spike Oct–Dec — the single biggest gifting window of the year.
```

- `type` — must be one of `FigurineStyle`, `FigurineType`, `Occasion`,
  `Format`, `Recipient`, `Accessory` (see `src/config.py`).
- `status` — `existing` if the URL is already live on the site,
  `proposed` if it's a gap identified in the source document. This is
  what makes content gaps visible directly in the graph.
- `source_section` — which part of `getfiguro-seo-knowledge-base.md`
  the fact came from. Keeps every claim traceable back to the source.
- `aliases` — optional. Other words a **customer** would type for this
  same thing.

#### On `aliases` — small field, large effect

The `title` is what the business calls something. `aliases` are what
people actually search for, and the two are often different words:

```yaml
title: Sports
aliases: [football, cricket, golfer, golf, basketball, soccer, athlete]
```

Nobody searches "sports figurine" — they search "football figurine".
Without the alias the keyword join simply misses, because the only thing
it can match on is the title. Adding aliases to 8 notes moved the join
from **55% to 76% coverage**, at no cost to precision.

Rules for adding one:
- It must be a genuine synonym or a specific instance of the concept
  (`nurse` for Profession — yes; `portrait` for Bust — no, a portrait
  figurine is not necessarily a bust).
- Do not add an alias to widen a match you merely *hope* is right. A
  wrong alias creates a wrong edge for every keyword containing it.
- Matching is whole-word and tolerates a simple plural, so `award`
  already catches `awards`. You don't need both.

### 2. Product notes (`products/`)

One note per sellable item.

```markdown
---
type: Product
title: Custom Wedding Cake Topper Figurines
url: /products/custom-wedding-cake-toppers
status: existing
styles: []
types: []
occasions: [Wedding]
formats: []
recipients: []
keywords: [custom wedding cake topper figurine]
source_section: "1.1 row 11"
---

Tagged Occasion: Wedding directly from the source document's Category
Signal column.
```

The `styles` / `types` / `occasions` lists connect this product to
taxonomy notes that must **already exist**. Names must match
**character-for-character** — `Nendoroid / Chibi`, not `nendoroid/chibi`
or `Nendoroid/Chibi`. This is exactly the normalisation problem
`normalize_keyword` in `src/config.py` solves for keywords — there is no
equivalent auto-fixer for these tags, so precision matters. The loader
will refuse to run (not silently skip) if a name doesn't match anything.

**Only tag what the source document actually states.** If the Category
Signal column for a product doesn't mention a style, leave `styles: []`
empty rather than guessing one. An empty field you fill in later is
fine; a guessed field that's wrong pollutes every downstream query.

---

## What happens when you run the loader

```bash
python -m src.ingest.vault
```

1. Every note becomes a `:__Entity__` node (`type` = Product /
   FigurineStyle / FigurineType / Occasion / …).
2. Every `url` / `collection_url` becomes a `:Page` node, carrying its
   `status`. This is how proposed-but-not-built pages show up in the
   graph as visible gaps.
3. Product → taxonomy tags become relationships: `HAS_STYLE`, `DEPICTS`,
   `FOR_OCCASION`, `HAS_FORMAT`, `GIFT_FOR`, `PAIRS_WITH`.
4. The body text below the `---` becomes a `:Chunk`, embedded and linked
   to the entity it belongs to — so this hand-authored content also
   participates in keyword vector-matching later (Phase 5), the same
   mechanism as prose documents.

Re-running the loader is safe — everything is `MERGE`d, not duplicated.
