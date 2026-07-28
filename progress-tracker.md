# Progress Tracker

Last updated: **2026-07-28**

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
| 4b | Deploy a copy to DigitalOcean | ✅ **Done** |
| 5 | Keywords + intent + the join | ✅ **Done — 76.2% coverage** |
| 6 | Site structure from the graph | ⬜ Not started |
| 7 | The page-writing agent | ⬜ Not started |
| 8 | Internal linking + structured data | ⬜ Not started |

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

## ✅ Phase 5 — Keywords, intent, and the join (DONE)

Branch: `feature/keyword-graph-and-agent`. This is the mentor's **task 1**
("a knowledge graph that maps topics, entities, and search intent").

- [x] 154 supplied keywords → `data/keywords.csv` (147 unique after
      collapsing 7 duplicate spellings). Replaced the fake placeholder
      rows. No `search_volume` column — the list has no volumes, and an
      invented number is worse than none.
- [x] 10 new taxonomy notes the keyword list needed (Profession,
      Superhero, Cosplay, Mascot, Trophy/Award, + 5 recipients)
- [x] `src/ingest/keywords.py` **rewritten** (the old one couldn't even
      be imported). Intent by rule — no LLM, no API cost.
- [x] `src/enrich/link_keywords.py` **rewritten** — fixes the `CONTAINS`
      false positives ("Pet" matched "carpet") and the duplicate-edge
      `MERGE`
- [x] New `aliases:` frontmatter field — the single biggest win
- [x] `scripts/inspect_keywords.py` verification report

```
147 keywords, each with exactly one of 4 intents
   transactional 127 | commercial 12 | informational 8

the join:  112/147 keywords linked  (76.2%),  130 relationships
   before aliases:  81/147 (55.1%)
   after  aliases: 112/147 (76.2%)   <- all 34 alias matches hand-checked

biggest magnets: Memorial/Loss 45, Pet 9, Corporate 7, Wedding 7
```

**The vector pass is off by default** (`--vector` to enable). Measured
~1 correct in 14 on this dataset — every note is about custom figurines,
so all embeddings cluster tightly and the keywords pass 1 misses are
generic head terms equidistant from everything. Not a tuning problem:
the wrong matches score *higher* than the right ones. Full reasoning in
the module docstring and `CHANGELOG.md`.

---

## ⬜ Phases 6–8 — Not started

- **6. Site structure** — cluster keywords by the entity they're `ABOUT`,
  then decide page type per cluster using the mentor's own IF/THEN rules
  (transactional + product → collection page; "vs"/"compare" →
  comparison; question keywords → blog). His **task 2**.
- **7. Page agent** — the LangGraph brief→draft→critique→revise loop.
  His **task 3**. `src/agents/context.py` must be rewritten first (it
  returns hardcoded sample data), and `page_graph.py` currently imports
  `GEMINI_API_KEY`, which no longer exists.
- **8. Internal linking + structured data** — `SHOULD_LINK_TO` from
  shared entities, plus JSON-LD per page type. His **task 4**.

---

## What to do manually right now

1. **Review Phase 5** on the `feature/keyword-graph-and-agent` branch —
   nothing is merged to `main` or pushed yet.
2. **Confirm 2 truncated URLs** against the live Getfiguro site and fill
   them into `products/dust-proof-acrylic-display-box.md` and
   `products/gift-box-packaging.md` (still blank, low priority).
3. **Tell the mentor about one simplification**: his diagram shows five
   AI agents; the plan implements one real LLM agent (page generation,
   his task 3) plus deterministic code for the rest. Keyword parsing,
   intent classification, and entity expansion are a CSV read, a rule
   table, and a Cypher query — making them LLM calls costs money, adds
   failure modes, and makes them untestable, for no gain.

```powershell
.\run.ps1 browser
```

See the join in Neo4j Browser:
```cypher
MATCH (k:Keyword)-[:ABOUT]->(e:__Entity__ {name:'Memorial / Loss'})
RETURN k, e
```

The next decision is **Phase 6 scope** — whether to route the 35
unlinked head terms ("custom figurine", "buy custom figurine") to
site-level pages, which is what they actually want to be.
