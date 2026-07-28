# Changelog

All notable changes to this project, newest first.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com).
Dates are absolute (YYYY-MM-DD).

---

## [Phase 3-4 — Full 37-product catalogue loaded] — 2026-07-27

Completed the vault begun earlier the same day. The user hand-authored
the first 5 products (catching a real bug independently — a stray blank
line before the frontmatter delimiter caused `custom-pet-figurine.md` to
be silently skipped by the loader's validation, diagnosed via the
loader's own error log). The remaining 32 products were then handed to
Claude to transcribe mechanically, using a worksheet
(`data/vault/PRODUCTS_TODO.md`) that had already resolved every tagging
judgment call.

### Added
- 6 more taxonomy notes: `formats/bust-half-body.md`,
  `formats/keychain.md`, `recipients/him.md`, `recipients/her.md`,
  `recipients/boyfriend.md`, `recipients/coach.md` — needed by products
  the first 5-product slice didn't touch.
- `data/vault/PRODUCTS_TODO.md` — a worksheet mapping all 32 remaining
  products to exact taxonomy tags, with the judgment calls resolved and
  explained (untaggable rows, two URLs truncated in the source document
  itself, why accessory/packaging SKUs stay untagged rather than being
  given a circular self-referential `PAIRS_WITH` link).
- 32 remaining product notes, completing the catalogue.

### Fixed
- `src/ingest/vault.py` — `load_vault()` now skips known non-note
  reference files (`README.md`, `PRODUCTS_TODO.md`) by name, rather than
  attempting to parse them as vault notes and logging a spurious error
  every run.

### Verified
```
python -m src.ingest.vault
  -> 72 entities, 61 pages (39 existing / 22 proposed), 31 links, 72 chunks

python -m scripts.inspect_vault
  Product 37, Occasion 15, FigurineType 8, FigurineStyle 6, Recipient 4, Format 2
  31 product -> taxonomy links, all checked against the source document
  9 products with no links -- all 9 individually confirmed correct:
    6 accessory/packaging SKUs (rows 27-30, 34-35) that ARE the accessory
      being sold rather than a figurine pairing with one
    3 rows the source document itself never assigns a pillar tag to
      (the flagship product, "Self/Mini-me", "Niche: Religious")
```

### Known follow-up
- `products/dust-proof-acrylic-display-box.md` and
  `products/gift-box-packaging.md` have a blank `url` — the source
  document's own table truncates both slugs (`...`). Needs the user to
  confirm the real URLs against the live site.
- `accessories/` taxonomy folder is still empty. No product in the
  source document states a figurine that pairs with a specific
  accessory, so there's nothing to tag yet.

---

## [Phase 2-4 — Domain pivot to Getfiguro + vault scaffold] — 2026-07-27

The project's actual domain turned out to be a custom 3D-printed figurine
business (Getfiguro.com), not the personalised-storybook assumption made
during Phase 0. `getfiguro-seo-knowledge-base.md` was supplied as the
domain source of truth: a hand-written SEO strategy document mapping the
live 37-product/31-collection sitemap plus a full content-gap analysis
across three pillars (Occasion, Figurine Type, Figurine Style). Phase 0
infrastructure is entirely unaffected by this pivot.

### Added
- **`src/ingest/vault.py`** — a new, deterministic loader for a
  hand-authored Obsidian vault. Reads YAML frontmatter (no LLM calls),
  writes `:__Entity__` nodes, `:Page` nodes, taxonomy relationships, and
  embeds note prose as `:Chunk`s. Validates every taxonomy reference
  against existing note titles *before* writing anything — a mismatch
  raises with a clear list, rather than Cypher's default behaviour of a
  `MATCH` on a nonexistent name silently matching zero rows.
- **`data/vault/`** — an Obsidian vault scaffold: `products/`, `styles/`,
  `types/`, `occasions/`, `formats/`, `recipients/`, `accessories/`, plus
  `data/vault/README.md` documenting the authoring convention.
- **29 taxonomy notes**, fully transcribed from the source document:
  15 Occasions, 8 FigurineTypes, 6 FigurineStyles — each carrying
  `status` (`existing`/`proposed`), `source_section`, and, where the
  source document specifies one, a `caution` field (trademark/publicity
  cautions for Pop-Vinyl style and Celebrity/Fan-Art type).
- **2 worked product-note examples** in `products/`, deliberately chosen
  to demonstrate two different disciplines: leaving every taxonomy field
  empty when the source document states no tag (`custom-3d-figurine-
  from-photo.md`), versus tagging only what's explicitly stated even when
  a plausible-looking extra tag is available (`custom-wedding-cake-
  toppers.md`).
- **`scripts/inspect_vault.py`** — reports entity/page counts and
  product→taxonomy links after a vault load.

### Changed
- **`src/config.py`** — `ALLOWED_NODE_LABELS` and
  `ALLOWED_RELATIONSHIPS` replaced with the figurine domain: `Product,
  FigurineStyle, FigurineType, Occasion, Format, Recipient, Accessory`
  and `HAS_STYLE, DEPICTS, FOR_OCCASION, HAS_FORMAT, GIFT_FOR,
  PAIRS_WITH, RELATES_TO`. `FigurineType` and `FigurineStyle` are kept as
  separate labels because the source document itself treats "Anime type"
  (the figurine is of an anime character) and "Anime style" (any subject
  rendered in anime art style) as two different pillar pages.
- **`CLAUDE.md`**, **`progress-tracker.md`** — updated to describe the
  Getfiguro domain and the current phase state.

### Verified
```
python -m src.ingest.vault
  -> 31 entities, 28 pages (22 proposed / 6 existing), 1 link, 31 chunks

python -m scripts.inspect_vault
  Entities by type:  Occasion 15, FigurineType 8, FigurineStyle 6, Product 2
  Pages by status:   proposed 22, existing 6
  Custom Wedding Cake Topper Figurines -[FOR_OCCASION]-> Wedding
  Products with no taxonomy links yet: Custom 3D Figurine from Photo
    (correct -- the source document gives this row no Category Signal
    tag, and the note deliberately leaves it untagged rather than guess)
```
Run against the live database as a verification step before handoff;
safe to re-run (everything is `MERGE`d).

### Known, deliberately deferred
- `formats/`, `recipients/`, `accessories/` taxonomy folders are
  scaffolded but empty. Several later products (rows 20-24, 26-30, 34-36)
  need them; out of scope for the first 5-product slice.
- `src/ingest/documents.py` (Phase 1's known issue) is now scoped
  specifically to the source document's §7-8 prose SEO rulebook, not the
  catalogue — the catalogue loads via `vault.py` instead.

---

## [Phase 0 — Infrastructure] — 2026-07-27

The project was handed over half-built from Google AI Studio. This phase
made it actually run on a Windows machine and stripped out code that faked
success. No pipeline logic was changed yet — that is Phase 1 onward.

### Removed
- **The entire React/TypeScript demo UI.** It was never in the project
  spec, its graph visualiser returned hardcoded fake data, and it shelled
  out to `python3`, which does not exist on Windows. Files deleted:
  `server.ts`, `package.json`, `tsconfig.json`, `vite.config.ts`,
  `index.html`, `metadata.json`, `src/App.tsx`, `src/main.tsx`,
  `src/index.css`, `src/types.ts`, `src/components/`, `assets/`.
  (Backed up to a scratchpad folder before deletion.)
- **`Makefile`.** `make` is a Unix tool and is not installed on Windows;
  it also relied on bash `until`/`sleep` loops. Replaced by `run.ps1`.

### Added
- **`run.ps1`** — PowerShell replacement for the Makefile. Commands:
  `up`, `down`, `schema`, `verify`, `counts`, `logs`, `browser`, `nuke`.
- **`scripts/smoke_test.py`** — proves the embedding model produces
  *meaningful* vectors (related text scores higher than unrelated), not
  just vectors of the right length.
- **`scripts/verify_vector_index.py`** — writes real chunks and queries
  them back, proving the vector index dimension matches the model. Guards
  against the silent zero-rows failure that `SHOW INDEXES` cannot catch.
- **Pluggable embedding provider** in `src/config.py` — `fastembed`
  (free, local, 384-dim, default) or `openai` (paid, 1536-dim). Switching
  is a `.env` change plus a schema rebuild.
- **`.venv`** — a Python 3.11 virtual environment (project now uses 3.11,
  not the machine's 3.14).
- **`.env`** — created from `.env.example`.

### Fixed
- **`requirements.txt`** — the old file pinned `langgraph`,
  `langgraph-prebuilt`, and `langgraph-checkpoint` all to `0.2.60`.
  `langgraph-prebuilt` never had a 0.2.x release, so the file would not
  install at all. Now pins only `langgraph>=1.2,<1.3` and lets pip resolve
  its siblings (which land on genuinely different minor versions:
  checkpoint 4.1.1, prebuilt 1.1.0). Added `fastembed` and `PyYAML`.
- **`docker-compose.yml`** — memory settings used Neo4j **4** names
  (`NEO4J_dbms_memory_*`), which Neo4j 5 silently ignores. Renamed to
  `NEO4J_server_memory_*`. Removed the obsolete `version:` key. Added
  `start_period` to the healthcheck so first-boot plugin downloads do not
  trip it.
- **`src/config.py`** — deleted nothing of value, added dimension
  validation at import time (a model/index dimension mismatch now refuses
  to start rather than failing silently later). Updated model IDs to
  `claude-sonnet-5` and `claude-haiku-4-5-20251001`. Added
  `require_anthropic_key()`.
- **`src/db.py`** — **removed the SHA-256 "fake embedding" fallback**
  entirely; if embeddings cannot be produced, it now raises. Embedding is
  now a batch operation (`embed_texts`) instead of one API call per row.
  Schema statement failures now raise instead of logging a warning and
  continuing (the old behaviour made a failed vector index look like
  success). Added `--counts` and a clearer connection-error message.
- **`cypher/001_schema.cypher`** — vector index dimension is now the
  placeholder `__EMBEDDING_DIM__`, substituted from `.env` at apply time,
  so `.env` is the single source of truth. Moved the `Keyword` uniqueness
  constraint from `name` to `normalized` (the ingest code keys on
  `normalized`, so the old constraint protected the wrong property).
- **`.gitignore`** — added Python, venv, output, and Obsidian-workspace
  ignores (the old one was Node-oriented).
- **`README.md`** — was AI Studio's "Run and deploy your AI Studio app"
  boilerplate about Node.js. Rewritten to document this project.

### Verified (definition of done for Phase 0)
```
7 constraints, 14 indexes (2 vector)
GDS 2.13.11
Neo4j 5.26-community, Python 3.11.7, langgraph 1.2.9
fastembed / BAAI/bge-small-en-v1.5 / 384 dims

scripts/smoke_test.py           related 0.785 vs unrelated 0.401   PASS
scripts/verify_vector_index.py  pricing query -> pricing passage   PASS
```

### Known issues carried into Phase 1
These pipeline modules still contain defects and have **not** been touched,
because the fixes depend on the Phase 2 domain schema decision:
- `src/ingest/documents.py` — hand-rolls extraction instead of using
  `neo4j-graphrag`; writes to Neo4j inside a Python loop; has a garbage
  regex fallback; discards typed relationships (writes everything as
  `RELATES_TO`); tags Obsidian wikilinks with a label not in the schema.
- `src/enrich/link_keywords.py` — `MERGE` includes the similarity score in
  the relationship pattern, creating duplicate edges; `CONTAINS` matching
  produces large numbers of false positives.
- `src/analyze/clusters.py` — `pageRank` is a hand-made formula, not
  PageRank.
- `src/agents/context.py` — returns hardcoded sample keywords/passages
  when the graph is empty.
- `src/ingest/keywords.py` — embeds one row at a time.
