# Progress Tracker

Last updated: **2026-07-30**

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
| 6 | Site structure from the graph | ✅ **Done — 32 clusters** |
| 7 | The page-writing agent | ✅ **Done — 32/32 pages generated** |
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

## ✅ Phase 6 — Site structure (DONE)

His **task 2**: turn the keyword→entity join into an actual site plan.

- [x] **6.1** — `src/analyze/clusters.py` rewritten to use real GDS
      Louvain community detection on entity co-occurrence (replacing the
      handover's invented PageRank formula). 32 clusters.
- [x] **6.2** — new `src/analyze/site_structure.py` assigns a page type
      and action to every cluster using the mentor's own IF/THEN rules,
      plus `pick_head_term()` to choose the real primary keyword per
      cluster (not just the alphabetically-first one).
- [x] **6.3** — new `src/analyze/route_orphans.py` routes head-term
      keywords that matched no single entity to the homepage or `/blog`,
      and flags genuine catalogue gaps (resin, a "car" prop) instead of
      silently routing them anywhere.

```
32 clusters, each with a page type + action
orphan keywords routed or flagged as real content gaps, not guessed
```

---

## ✅ Phase 7 — The page-writing agent (DONE — 32/32 pages generated)

His **task 3**: the LangGraph brief→draft→critique→revise loop, grounded
in the graph. Provider is **Gemini** (`gemini-2.5-flash`), the user's
explicit choice.

- [x] `src/agents/context.py` rewritten — no more hardcoded sample
      fallbacks; raises if a cluster's graph data is missing or
      (new) too thin to ground a real page in
      (`MIN_EVIDENCE_CHARS = 140`, calibrated from 6 hand-checked
      clusters).
- [x] `src/agents/page_graph.py` — 4 fake-fallback blocks removed
      (rule 9); wrong-primary-keyword, document-ID-leak, and
      duplicate-Page-node bugs found and fixed by reading real
      generated output, not just checking exit codes.
- [x] The `Memorial / Loss` cluster's pet/human-bereavement mixing
      fixed — split into two vault entities plus a new
      `exclude_keywords:` mechanism for the 3 keywords that bridged
      them.
- [x] All 32 clusters now have a real, generated page in `output/*.md`.
      12 of them needed real content written into their vault notes
      first (sourced from the live getfiguro.com site, not invented)
      before they cleared the evidence guard.
- [x] Local and DigitalOcean remote databases verified byte-identical
      after syncing: 147 keywords, 83 entities, 82 chunks, 32 clusters,
      75 pages.

```
32/32 clusters generated
6 real bugs found and fixed (fake fallbacks, wrong keyword, ID leak,
  duplicate pages, thin-evidence hallucination, mixed-audience cluster)
```

---

## ⬜ Phase 8 — Not started

**Internal linking + structured data**, his **task 4**:
- `SHOULD_LINK_TO` relationships from shared entities / real PageRank
  (today `plan_links_node` only does verbatim anchor-text matching
  against sibling page names, and has proposed 0 links on every page
  generated so far — this is the actual gap it needs to fill).
- JSON-LD structured data per page type.

---

## What to do manually right now

1. **Review Phase 6 and 7** on the `feature/keyword-graph-and-agent`
   branch, and read a few of the 32 generated pages in `output/*.md` —
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

See a generated page's cluster in Neo4j Browser:
```cypher
MATCH (p:Page {draft_status: 'draft'})-[:COVERS]->(cl:Cluster)
RETURN p, cl
```

The next decision is **Phase 8 scope** — real internal linking from
shared entities, and how much structured-data markup to generate per
page type.
