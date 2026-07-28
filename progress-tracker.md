# Progress Tracker

Last updated: **2026-07-27**

A plain-language view of what is done, what is next, and what is blocking.
For the technical detail behind each change, see `CHANGELOG.md`.

**Domain note:** this project pivoted from an initial "storybook business"
assumption to its real target — **Getfiguro.com**, a custom 3D-printed
figurine business — once `getfiguro-seo-knowledge-base.md` was supplied.
Phase 0 (infrastructure) was unaffected; Phase 2 onward reflects the
figurine domain.

---

## At a glance

| Phase | What it delivers | State |
|---|---|---|
| 0 | Infrastructure that runs and is verified | ✅ **Done** |
| 1 | Repair the pipeline modules the handover faked | 🔧 In progress |
| 2 | A domain schema that fits Getfiguro | ✅ **Done** |
| 3 | The knowledge base, authored in Obsidian | ✅ **Done — full 37-product catalogue** |
| 4 | Ingest the vault into the graph | ✅ **Done &amp; verified** |
| 5 | Keywords + the join | ⬜ Not started |
| 6 | Topic clusters (Louvain) | ⬜ Not started |
| 7 | Site structure & sitemap.xml | ⬜ Not started |
| 8 | The page-writing agent | ⬜ Not started |

---

## ✅ Phase 0 — Infrastructure (DONE)

- [x] Python 3.11 virtual environment, dependencies installed
- [x] Neo4j 5.26 + APOC + GDS running in Docker
- [x] Schema applied: 7 constraints, 14 indexes (2 vector)
- [x] Local embeddings working (`fastembed`, free, no API key)
- [x] `run.ps1` replaces `make`; off-spec React UI removed

```
smoke_test.py         -> related 0.785 vs unrelated 0.401   PASS
verify_vector_index   -> pricing query -> pricing passage   PASS
```

---

## 🔧 Phase 1 — Repair the pipeline (IN PROGRESS)

Unchanged by the domain pivot — these are generic pipeline defects from
the handover, independent of storybooks vs. figurines.

- [x] Removed fake hash-based embeddings from `src/db.py`
- [x] Removed silent schema-error swallowing
- [ ] `src/ingest/documents.py` — use `neo4j-graphrag` instead of the
      hand-rolled extractor; stop writing inside a Python loop; delete the
      regex fallback. **Scope note:** this module is now reserved for the
      source document's §7-8 prose SEO rulebook only — the catalogue
      itself loads deterministically via `src/ingest/vault.py` instead
      (see Phase 3/4 below).
- [ ] `src/enrich/link_keywords.py` — fix the duplicate-edge `MERGE`;
      replace `CONTAINS` matching with something precise
- [ ] `src/analyze/clusters.py` — use real GDS PageRank, not a formula
- [ ] `src/agents/context.py` — remove hardcoded sample fallbacks
- [ ] `src/ingest/keywords.py` — batch the embeddings

---

## ✅ Phase 2 — Domain schema (DONE)

`src/config.py` now defines, derived directly from
`getfiguro-seo-knowledge-base.md`:

```
ALLOWED_NODE_LABELS:  Product, FigurineStyle, FigurineType, Occasion,
                       Format, Recipient, Accessory

ALLOWED_RELATIONSHIPS: HAS_STYLE, DEPICTS, FOR_OCCASION, HAS_FORMAT,
                        GIFT_FOR, PAIRS_WITH, RELATES_TO
```

`FigurineType` (what the figurine is OF, e.g. Pet) and `FigurineStyle`
(the art style it's rendered in, e.g. Realistic) are deliberately kept
separate — the source document itself distinguishes "Anime type" from
"Anime style" as two different pillar pages.

---

## ✅ Phase 3 — Knowledge base in Obsidian (DONE)

Catalogue and taxonomy facts are **hand-authored as YAML frontmatter**,
not LLM-extracted — the source document is mostly clean tables, and an
LLM would paraphrase your trademark cautions. See `data/vault/README.md`
for the full convention.

You authored the first 5 products yourself (including catching a real
bug — a stray blank line breaking frontmatter parsing) before handing
the remaining 32 to Claude to transcribe mechanically from a
fully-resolved worksheet (`data/vault/PRODUCTS_TODO.md`, kept for
reference/audit trail).

- [x] Vault scaffold: `products/`, `styles/`, `types/`, `occasions/`,
      `formats/`, `recipients/`, `accessories/`
- [x] All 15 Occasion, 8 FigurineType, 6 FigurineStyle notes
- [x] 4 Recipient notes (Him, Her, Boyfriend, Coach), 2 Format notes
      (Bust / Half-Body, Keychain) — added when scaling past the first 5
- [x] All 37 Product notes
- [ ] `accessories/` taxonomy folder intentionally still empty — no
      product in the source document states a figurine pairing with an
      accessory, so nothing to tag yet (see PRODUCTS_TODO.md note ③)
- [ ] 2 products (`dust-proof-acrylic-display-box.md`,
      `gift-box-packaging.md`) have a blank `url` — the source document's
      own table truncates these slugs. **Action for you:** confirm the
      real URLs against the live site and fill them in.

---

## ✅ Phase 4 — Vault ingestion (DONE & verified)

- [x] `src/ingest/vault.py` — deterministic loader, no LLM calls. Rejects
      (doesn't silently skip) any taxonomy tag that doesn't match an
      existing note title character-for-character.
- [x] Full catalogue loaded and verified:
      `72 entities, 61 pages (39 existing / 22 proposed), 31 links, 72 chunks`
- [x] All 9 products with no taxonomy links checked and confirmed
      correct (6 accessory SKUs + 3 rows the source document itself
      gives no pillar tag to)

---

## ⬜ Phases 5–8 — Not started

- **5. Keywords + the join** — ingest a real keyword export, build
  `Keyword→Entity` (needs your keyword data — you said none exists yet).
- **6. Clustering** — run Louvain, get named topic clusters.
- **7. Site structure & sitemap** — turn clusters + the three pillars into
  a URL plan. Largely already drafted in the source document's sections
  3-6 — this phase mostly formalises it.
- **8. Page agent** — the LangGraph write→critique→revise loop, run
  against one cluster and reviewed before any bulk generation.

---

## What to do manually right now

The catalogue is loaded. Two loose ends from the transcription, both
low-priority:

1. **Confirm 2 truncated URLs** against the live Getfiguro site and fill
   them into `products/dust-proof-acrylic-display-box.md` and
   `products/gift-box-packaging.md` (`url:` field is currently blank).
2. Optional: browse the graph and sanity-check a few products against
   what you know of the real catalogue.

```powershell
.\run.ps1 browser
```

Try in Neo4j Browser: `MATCH (p:__Entity__ {type:'Product'})-->(t) RETURN p,t`
to see every product and its tags at once.

The next real decision is **what to build next** — Phase 5 (keywords)
needs a keyword export you don't have yet, so likely candidates are
fixing the remaining Phase 1 pipeline defects, or jumping ahead to try
GDS Louvain clustering on this catalogue as-is to see what topic
clusters fall out of it.
