# Progress Tracker

Last updated: **2026-07-31** — **all 8 phases complete.**

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
| 1 | Repair the pipeline modules the handover faked | ✅ **Done** (1 module deliberately deferred) |
| 2 | A domain schema that fits Getfiguro | ✅ **Done** |
| 3 | The knowledge base, authored in Obsidian | ✅ **Done — full 37-product catalogue** |
| 4 | Ingest the vault into the graph | ✅ **Done &amp; verified** |
| 4b | Deploy a copy to DigitalOcean | ✅ **Done** |
| 5 | Keywords + intent + the join | ✅ **Done — 76.2% coverage** |
| 6 | Site structure from the graph | ✅ **Done — 32 clusters** |
| 7 | The page-writing agent | ✅ **Done — 32/32 pages generated** |
| 8 | Internal linking + structured data | ✅ **Done — 5 real links, JSON-LD on all 32 pages** |

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

## ✅ Phase 1 — Repair the pipeline (DONE, except one deliberate deferral)

Unchanged by the domain pivot — these are generic pipeline defects from
the handover, independent of storybooks vs. figurines.

Most of these were not fixed as a standalone "Phase 1" pass. They were
fixed as a *consequence* of Phases 5–8, because each phase had to touch
the broken module anyway, and repairing it in place was cheaper than
repairing it twice. This checklist was left stale for several phases;
it is now reconciled against the actual code.

- [x] Removed fake hash-based embeddings from `src/db.py`
- [x] Removed silent schema-error swallowing
- [x] `src/enrich/link_keywords.py` — duplicate-edge `MERGE` and
      `CONTAINS` false positives both gone. **Rewritten in Phase 5**;
      matching is now whole-word (`\b`) and `ABOUT` is recomputed from
      scratch each run so a rule change can't leave a stale edge.
- [x] `src/analyze/clusters.py` — the invented `pageRank` formula is
      gone. **Phase 6** replaced clustering with real GDS Louvain;
      **Phase 8** added the real `gds.pageRank` in
      `src/analyze/linking.py`, which is where it always belonged
      (clusters.py's own docstring said so).
- [x] `src/agents/context.py` — hardcoded sample fallbacks removed.
      **Rewritten in Phase 7**, plus a new minimum-evidence guard that
      catches the subtler version of the same failure.
- [x] `src/ingest/keywords.py` — embeddings batched into one
      `embed_texts()` call. **Rewritten in Phase 5** (the old module
      couldn't even be imported).
- [ ] `src/ingest/documents.py` — **deliberately deferred, not
      forgotten.** It would use `neo4j-graphrag` instead of the
      hand-rolled extractor, stop writing inside a Python loop, and drop
      the regex fallback. It is reserved for the source document's §7–8
      prose SEO rulebook, which nothing in Phases 2–8 needs: the
      catalogue loads deterministically via `src/ingest/vault.py`
      instead. `CLAUDE.md` explicitly says not to rewrite it yet.
      **Nothing built so far depends on it.**

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
- [x] 2 products (`dust-proof-acrylic-display-box.md`,
      `gift-box-packaging.md`) had a blank `url` — the source document's
      own table truncates these slugs. **Resolved 2026-07-31:** both full
      slugs read from the live site's own product sitemap
      (`getfiguro.com/sitemap.xml` → `sitemap_products_1.xml`), and each
      prefix matches the source document's truncated version
      character-for-character. Verified, not guessed. Vault re-ingested:
      Page count 75 → 77.

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

## ✅ Phase 8 — Internal linking + structured data (DONE)

His **task 4**. Two real gaps closed, both previously flagged as "Phase
8's job" in the Phase 7 code itself:

- [x] **8.1** — new `src/analyze/linking.py`: real `gds.pageRank` over
      entity relationships (the TODO `clusters.py`'s own docstring left
      open), aggregated onto `Page.pageRank`; `(:Page)-[:SHOULD_LINK_TO]->(:Page)`
      built from actual connecting relationships between different
      clusters' entities (`HAS_STYLE`, `FOR_OCCASION`, `CO_OCCURS_WITH`,
      ...) — the literal "shared entities" signal, not a priority sort.
      `propose_anchor_links()` then gates each candidate on its anchor
      phrase actually appearing verbatim in the draft, same honesty
      rule Phase 7's `plan_links_node` always had.
- [x] **8.2** — new `src/analyze/structured_data.py`: JSON-LD per page
      type (`Product` / `CollectionPage` / `BlogPosting` / `Article` /
      `WebPage`) plus a `BreadcrumbList` on every page. Price is only
      ever included when a real `$NNN` is found in that product's own
      vault text (1 of 5 product pages qualifies — the other 4
      correctly have no `offers` block, not an invented price).
- [x] `plan_links_node` and `persist_node`
      (`src/agents/page_graph.py`) rewired onto both — any future fresh
      generation gets real links + JSON-LD automatically.
- [x] Retired the now-dead `sibling_pages` field from
      `src/agents/context.py` / `state.py` — it was only ever consumed
      by the old verbatim-sibling-slug matcher this phase replaced.
- [x] New `scripts/apply_internal_links_and_schema.py` retrofitted all
      32 already-generated `output/*.md` pages with real links + JSON-LD
      **without re-running the LLM** (frontmatter-only patch, draft
      body untouched) — confirmed idempotent on a second run.

```
8 SHOULD_LINK_TO edges built; 5 survived the verbatim-anchor-text gate
  and are now real internal links across 5 of the 32 pages -- most
  clusters are genuinely independent topics (same sparsity clusters.py
  found: most entities don't share keywords with anything else), so a
  small, honest number of real links is the correct result, not a bug.
32/32 pages now carry JSON-LD structured data
1/5 product pages has a real price (personalized-anniversary-couple-
  gift: $210, sourced from its own vault note) -- the other 4 have no
  offers block at all, proving no price was invented.
```

---

## The pipeline is complete. What remains is not code.

Every phase of the brief is built, verified, and synced to both
databases. There is **no known pipeline work outstanding** — the one
unbuilt module (`src/ingest/documents.py`) is deliberately deferred and
nothing depends on it.

What is left needs a human, and splits into three kinds:

### 1. Judgment calls only you and the mentor can make

- **Read the 32 pages.** `coverage_score` measures entity coverage, not
  brand voice, tone, or factual accuracy. Nobody has read all 32
  end-to-end yet. Worth a specific check: the source document's
  trademark cautions (`data/vault/styles/pop-vinyl.md`,
  `types/celebrity-fan-art.md`). Verified mechanically already — the
  string "Funko" appears nowhere in `output/`, only inside the vault
  note that warns against it — but tone and phrasing still need eyes.
- **Merge to `main`.** Everything lives on
  `feature/keyword-graph-and-agent`, pushed to GitHub, never merged.
  That is a deliberate stopping point, not an oversight.
- **Tell the mentor about one simplification**: his diagram shows five
  AI agents; this implements one real LLM agent (page generation, his
  task 3) plus deterministic code for the rest. Keyword parsing, intent
  classification, and entity expansion are a CSV read, a rule table,
  and a Cypher query — making them LLM calls costs money, adds failure
  modes, and makes them untestable, for no gain.

### 2. Publishing — a genuinely separate project

Nothing in this repo touches getfiguro.com. `output/*.md` are drafts;
the `url` on each page is a *proposal* matching the live site's URL
patterns, not a URL that already exists.

The live site is **Shopify** (confirmed: `getfiguro.com/sitemap.xml`
returns Shopify's `sitemap_products_1.xml?from=…&to=…` structure).
That means each page has to be created in Shopify as a Collection,
Product, or Blog article, and the `json_ld` block injected into the
theme template. Shopify then regenerates `sitemap.xml` on its own —
a sitemap is a crawl hint, not a publishing step, and hand-writing one
would do nothing.

Automating that (Shopify Admin API → create pages from `output/*.md`)
is real work this repo has no code for. Scope it separately.

### 3. Optional: denser internal linking

5 real links across 32 pages is honest, not broken — most topics in
this catalogue genuinely don't connect (Phase 6 measured the same
sparsity: 11 co-occurring pairs out of 82 entities). If you want more,
the lever is **data, not code**: add real `styles:` / `occasions:` /
`aliases:` tags to more vault notes, then re-run
`python -m src.analyze.linking`. Every genuine new tag creates a new
candidate connection. Same lever that took keyword coverage 55% → 76%
in Phase 5.

```powershell
.\run.ps1 browser
```

See the internal-link graph in Neo4j Browser:
```cypher
MATCH (p1:Page)-[r:SHOULD_LINK_TO]->(p2:Page)
RETURN p1, r, p2
```
