# Changelog

All notable changes to this project, newest first.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com).
Dates are absolute (YYYY-MM-DD).

---

## [Phase 8 — Internal linking + structured data] — 2026-07-31

Branch: `feature/keyword-graph-and-agent`. The mentor's **task 4**, and
the last of the four. Phase 7 left two things explicitly deferred: real
`SHOULD_LINK_TO` links (`plan_links_node` had proposed 0 links on every
one of the 32 generated pages) and JSON-LD structured data (not started
at all). Both close out here.

### Added: real internal linking (new `src/analyze/linking.py`)
- **`run_pagerank()`** — the real `gds.pageRank`, over every entity
  relationship type (`HAS_STYLE`, `FOR_OCCASION`, ..., plus
  `CO_OCCURS_WITH` from Phase 6), written to `e.pageRank` and summed
  onto `Page.pageRank`. `clusters.py`'s own docstring had flagged this
  as deferred ("internal linking is Phase 8's job and will use
  `gds.pageRank` properly") — this is that.
- **`build_should_link_to()`** — `(:Page)-[:SHOULD_LINK_TO]->(:Page)`
  from real connecting relationships between *different* clusters'
  entities. This is the literal "shared entities" signal Phase 7's
  sibling list never was: a Pet product `HAS_STYLE` Realistic connects
  the Pet cluster's page to the Realistic cluster's page. Ranked by
  `(weight DESC, target.pageRank DESC)`, top 5 per page.
- **`propose_anchor_links()`** — reads a page's `SHOULD_LINK_TO`
  targets and only proposes a link when a real candidate phrase (the
  target's primary keyword, lead entity, or cluster name) appears
  verbatim in the draft. Same honesty rule Phase 7's `plan_links_node`
  always had (no invented anchor text, zero links is a valid answer);
  now backed by real relevance instead of an arbitrary priority sort.
  Shared by both the live agent and the retrofit script below, so the
  two logics can't drift apart.

### Fixed: `gds.graph.project` rejected two of the configured relationship types
`ALLOWED_RELATIONSHIPS` (`src/config.py`) includes `PAIRS_WITH` and
`RELATES_TO`, but neither has ever been written to the graph —
`accessories/` is deliberately empty (no product pairs with one yet)
and no ingest path writes `RELATES_TO`. GDS's native projection syntax
requires every relationship type to already exist in the store's token
index, unlike a plain Cypher `type(r) IN [...]` check, and failed
outright: `Invalid relationship projection, one or more relationship
types not found`. Fixed by intersecting the configured type list
against `CALL db.relationshipTypes()` before projecting, logging which
configured types were skipped rather than silently succeeding on a
different set than requested.

### Added: JSON-LD structured data (new `src/analyze/structured_data.py`)
- **`build_json_ld()`** — a `BreadcrumbList` on every page (derived
  from the URL's own path segments) plus one type-specific block keyed
  off `decide_page_type()`'s own output (`site_structure.py`):
  `Product` / `CollectionPage` / `BlogPosting` / `Article` / `WebPage`.
  `tool` pages deliberately get `WebPage`, not `WebApplication` — there
  is no real interactive tool behind them yet, and claiming one would
  be false markup.
- **`extract_price()`** — a plain regex (`\$\d[\d,]*`) over an entity's
  own evidence text; returns `None` if nothing matches. `offers` is
  included in a Product's JSON-LD only when a real price was found
  (CLAUDE.md rule 9 — no invented prices). Caught and fixed a regex
  edge case during review: the greedy character class captured a
  trailing sentence comma ("$210, sizes 10cm/...") as part of the
  price; `build_json_ld()`'s own `.replace(",", "")` already cleaned
  the persisted value, but `extract_price()` now strips it directly so
  the raw return value is correct everywhere it's used, including the
  retrofit script's own log output.

### Wired up
- `plan_links_node` and `persist_node` (`src/agents/page_graph.py`)
  now call `propose_anchor_links()` / `build_json_ld()` directly — any
  future fresh page generation gets real links and structured data
  automatically, no separate step required.
- Removed the `sibling_pages` field from `src/agents/context.py`,
  `src/agents/state.py`, and `load_context_node`. It was only ever
  consumed by the old verbatim-sibling-slug matcher this phase
  replaced, and nothing else in the pipeline read it — left in place it
  would have been exactly the kind of half-wired leftover CLAUDE.md
  says not to keep.

### Added: retrofit script (new `scripts/apply_internal_links_and_schema.py`)
Patches all 32 already-generated `output/*.md` pages with real links
and JSON-LD **without re-running the LLM** — only the frontmatter block
is rewritten; the draft body is never touched. Re-running the full
7-node agent per cluster just to pick up a links/schema patch would
have cost 32 more Gemini calls for zero content change, so this reuses
`fetch_agent_context()` (read-only, no LLM) plus the same
`propose_anchor_links()` / `build_json_ld()` the live agent now uses.
Confirmed idempotent: a second run produces byte-identical
`SHOULD_LINK_TO`/`LINKS_TO` edge counts (`MERGE` guarantees no
duplicates) and the same frontmatter.

### Verified
```
python -m src.analyze.linking
  -> PageRank: 83 entities scored over 20 iterations
  -> SHOULD_LINK_TO: 8 edges written (top 5 per page, min weight 1)

python -m scripts.apply_internal_links_and_schema
  -> 5 of 8 SHOULD_LINK_TO candidates survived the verbatim-anchor-text
     gate -- 5 real internal links across 5 of the 32 pages
  -> 32/32 pages carry JSON-LD (BreadcrumbList + type-specific block)
  -> 1/5 product pages (personalized-anniversary-couple-gift) has a
     real offers.price ("210", sourced from its own vault note's
     "$210"); the other 4 product pages correctly have no offers
     block at all -- confirms no price was invented
  -> re-run confirmed idempotent: same 5 LINKS_TO edges, no duplicates
```
A small link count is the expected result, not a shortfall — Phase 6's
own clustering already found this dataset's entities are mostly
genuinely independent topics (11 co-occurring pairs out of 82 entities);
cross-cluster connections are similarly sparse, so 5 honest links beats
a padded number produced by loosening the anchor-text gate.

### Known follow-up
- Link volume scales with how many taxonomy connections exist between
  entities. The same lever Phase 5 used to raise keyword-join coverage
  (adding `aliases:` to vault notes) applies here too: adding real
  `styles:`/`occasions:`/etc. tags to more product notes would surface
  more genuine `SHOULD_LINK_TO` candidates.
- `PAIRS_WITH` and `RELATES_TO` remain unused (0 instances) — expected
  per `data/vault/README.md` (`accessories/` deliberately empty), not a
  bug. `run_pagerank()` already tolerates this and will pick them up
  automatically once either is ever written.

---

## [Phase 7 — The page-writing agent] — 2026-07-30

Branch: `feature/keyword-graph-and-agent`. The mentor's **task 3**: a
LangGraph agent that drafts a full page per cluster, grounded in the
graph rather than general knowledge. Provider is **Gemini**
(`gemini-2.5-flash`), chosen by the user over Anthropic/OpenAI — an
explicit `AGENT_PROVIDER` setting in `src/config.py`, mirroring the
existing `EMBEDDING_PROVIDER` pattern rather than guessing from which
key happens to be present.

### Wired up
- `get_llm()` dispatches on `AGENT_PROVIDER` explicitly. The handover
  code tried Anthropic, then OpenAI, then Gemini with a dummy key,
  silently — removed.
- Fixed a real `.env` bug: `os.getenv("AGENT_MODEL", "").strip() or
  _AGENT_MODEL_DEFAULTS[provider]`. The two-arg `os.getenv` form is
  wrong here because `.env` sets `AGENT_MODEL=` (present but blank),
  which `os.getenv` does not treat as absent, so the intended
  per-provider default was silently never applied.

### Removed: 4 fake-fallback blocks (rule 9)
`write_brief_node`, `draft_node`, `critique_node`, `revise_node` each
had an `except` branch that invented generic content and reported
success when the real LLM call failed — the same shape of bug as Phase
0's fake embeddings. All four now raise instead.

### Fixed: 3 real bugs, found by reading actual output rather than
trusting exit codes
1. **Wrong primary keyword.** `write_brief_node` picked
   `keywords_list[0]` (alphabetically first) instead of the cluster's
   real head term — e.g. `angel memorial figurine` instead of
   `memorial figurine` for a 49-keyword cluster. Fixed by reusing
   `pick_head_term()` from `site_structure.py`.
2. **Document-ID leak.** Evidence was formatted as
   `f"Source [{doc}]: {passage}"`, and literal tags like
   `[vault_FigurineType]` were leaking into customer-facing prose.
   Fixed by numbering evidence plainly and adding an explicit
   no-citation-markers instruction to the prompt.
3. **Duplicate Page nodes.** `persist_node` `MERGE`d a new `Page` keyed
   on an LLM-invented slug instead of updating the real page Phase 6.2
   had already planned. Hit 4 of 6 real test clusters, and once
   corrupted a real page's `status` (`existing` → `draft`) when the
   invented slug happened to collide with the real one. Fixed to
   `MATCH (p:Page)-[:COVERS]->(cl:Cluster {id: $cluster_id})` and find
   the real page first; added a separate `draft_status` property so
   the agent's own tracking never touches the real `status` field.

### Added: minimum-evidence-length guard (`src/agents/context.py`)
Batch-testing surfaced a failure mode no earlier fix caught: a cluster
with real but too-thin evidence (a one-line Phase-3 planning stub, e.g.
"High-volume, evergreen. No page exists yet.") produced a fluent,
confident, completely made-up page — the agent fell back on its own
training data instead of the graph. `MIN_EVIDENCE_CHARS = 140`,
calibrated from 6 hand-checked real clusters, not guessed:
```
67  chars -- Birthday   -- FAILED (fully ungrounded page)
112 chars -- Boyfriend  -- FAILED (4 dead "not covered" sections)
167 chars -- Wedding             -- worked
360 chars -- Corporate + Trophy  -- worked
369 chars -- Custom Figurine from Photo -- worked
418 chars -- Cake Topper         -- worked
```
An earlier guess of 200 wrongly blocked the real, good 167-char Wedding
cluster — length alone doesn't cleanly separate these, but this
specific gap does.

### Fixed: Memorial/Loss cluster mixing pet and human bereavement
The `Memorial / Loss` entity's 49 keywords spanned both pet-loss and
human-bereavement searches; the first generated page was 100%
pet-focused, silently dropping the human-bereavement half. Three
escalating fixes, each measured before moving to the next:
1. `exclude_aliases: [loss]` on Memorial/Loss — reduced but didn't
   eliminate contamination (co-occurrence still merged via the shared
   word "memorial").
2. Split into two vault entities — new
   `data/vault/occasions/loved-ones.md` for human bereavement,
   reassigning the existing "Personalized 3D Tribute Figurine for
   Memorials" product (previously untagged, 0 keywords, invisible) to
   it.
3. New `exclude_keywords:` mechanism (entity-level, exact-string
   exclusion) in `link_keywords.py` + `vault.py` — removes 3 specific
   keywords that literally contain the word "memorial" (needed by 44
   other pet-cluster keywords, so it can't be excluded as an alias) but
   are conceptually human-bereavement, not pet.
Verified: two fully separate clusters, zero forced overlap (one
keyword, "pet remembrance gift", legitimately appears in both by
choice, below the merge threshold).

### Page generation: 32 of 32 clusters
- First pass generated and hand-reviewed 6 pages for grounding and
  cannibalisation before batch-running the rest.
- Batch run over the remaining 26: 14 passed the evidence guard
  immediately; 12 were blocked by thin Phase-3 planning-stub notes
  (Mother's Day, Father's Day, Anniversary, Valentine's Day,
  Graduation, Retirement, Birthday, the Anniversary couple product,
  Boyfriend, Girlfriend, Dad, Sports).
- Wrote real content into those 12 vault notes, sourced directly from
  the live getfiguro.com site (product descriptions, dedicated blog
  posts, one full customer story, verified reviews) rather than
  inventing plausible-sounding copy — every fact traceable to a
  specific live URL, cited in each note's `source_section`. Re-ingested
  and regenerated: all 12 passed cleanly, 0 failures.
- Result: **32/32 clusters have a real, grounded, generated page** in
  `output/*.md`.

### DigitalOcean remote sync
- New `scripts/sync_page_metadata.py` — copies generated-page metadata
  (`title`, `draft_status`, `coverage_score`) from local onto the
  matching remote `Page` nodes, matched by `url` rather than
  `cluster_id` (GDS Louvain's internal community numbering is not
  guaranteed to land on the same integers across two independent runs
  on the same data, even though the resulting clusters are the same).
- Full ingest chain (`vault` → `keywords` → `link_keywords` →
  `clusters` → `site_structure` → `route_orphans`) re-run against the
  remote to pick up the new vault content, then the metadata sync.
- Found and fixed one pre-existing discrepancy: a `/blog/wife` orphan
  page existed locally with zero incoming keyword references and no
  `Cluster` link — a leftover from before `recipients/wife.md`
  existed, when "wife" keywords had nowhere real to go. Deleted (not
  pushed) once confirmed genuinely dead.
- Verified byte-identical on both databases: 147 keywords, 83 entities,
  82 chunks, 32 clusters, 75 pages, 6 documents, 3 intents.

### Known follow-up
- Internal linking (`plan_links_node`) only does verbatim anchor-text
  matching against sibling page names — 0 links proposed on every
  generated page so far. Real relevance-based linking
  (`SHOULD_LINK_TO` from shared entities / PageRank) is Phase 8, not
  built yet.

---

## [Phase 6 — Site structure: clusters, page types, orphan routing] — 2026-07-29 to 2026-07-30

Branch: `feature/keyword-graph-and-agent`. Turns the Phase 5
keyword→entity join into an actual site plan: which pages should exist,
what kind of page each one is, and where the head-term keywords that
matched no single entity should go. Covers the mentor's **task 2**.

### 6.1 — Topic clusters from keyword co-occurrence (`src/analyze/clusters.py`, rewritten)
- Replaced the handover's invented PageRank formula and hardcoded
  modularity value with real GDS Louvain community detection over
  entity co-occurrence — two entities co-occur when the same keyword is
  `ABOUT` both (CLAUDE.md rule 6: cluster on co-occurrence, not
  extracted relationships).
- `MIN_COOCCURRENCE_WEIGHT = 2` (raised from an initial 1) to stop
  single-shared-keyword false merges.
- Generic/untagged Products (no outgoing taxonomy relationship)
  excluded from co-occurrence merging entirely — they're horizontal
  catalogue-wide concepts, not vertical topics.
- `_dominant_intent()` with an explicit `INTENT_PRECEDENCE` tie-break
  order.
- Result: 32 clusters.

### 6.2 — Page type & action per cluster (new `src/analyze/site_structure.py`)
- `pick_head_term()` — picks the keyword contained as a substring by
  the most *other* keywords in the cluster, not the shortest or the
  first one alphabetically.
- Applies the mentor's own IF/THEN rules literally. Fixed one rule from
  `informational OR question-term-present` to `informational` alone
  (his actual AND) — a single keyword containing "ideas" had wrongly
  flipped a mostly-transactional Wedding cluster into a blog page.

### 6.3 — Orphan keyword routing (new `src/analyze/route_orphans.py`)
- Routes keywords that matched no single entity in Phase 5 (mostly
  generic head terms like "custom figurine") to `homepage` (`/`) or
  `blog` (`/blog`) rather than leaving them unattached.
- Genuine catalogue gaps (missing entities — resin as a material, a
  "car" prop) are flagged, not silently routed anywhere; not invented,
  since they need a real source, not a guess.

### Verified
32 clusters, each assigned a page type and action per the mentor's
rules; orphan keywords routed or flagged as real gaps.

---

## [Phase 5 — Keywords, intent, and "the join"] — 2026-07-28

Branch: `feature/keyword-graph-and-agent`.

The mentor supplied a real (if illustrative) keyword list — 154 keywords
across 13 headings, plus a second memorial-specific set. That list was
the thing blocking every remaining phase, and this phase turns it into
the `(:Keyword)-[:ABOUT]->(:__Entity__)` relationship the project exists
for. Covers the mentor's task 1 ("a knowledge graph that maps topics,
entities, and search intent").

### Added
- **`data/keywords.csv`** — all 154 keywords, each carrying the heading
  it appeared under. Replaces the AI Studio placeholder rows, which were
  fake ("semantic seo guide", "neo4j gds community detection louvain").
  **No `search_volume` column**: the supplied list has no volume figures
  and a fabricated number is worse than an absent one (rule 9).
- **10 taxonomy notes** the keyword list requires but the catalogue
  lacked: `types/profession.md`, `types/superhero.md`, `types/cosplay.md`,
  `types/mascot.md`, `formats/trophy-award.md`, and five recipients
  (`girlfriend`, `husband`, `wife`, `dad`, `mum`). The existing four
  recipients covered almost none of the gift keywords.
- **`aliases:` frontmatter field**, supported by `src/ingest/vault.py`
  and used by the join. The title is what the business calls a thing;
  aliases are what customers type. Nobody searches "sports figurine" —
  they search "football figurine". Documented in `data/vault/README.md`.
- **`scripts/inspect_keywords.py`** — keyword-side counterpart to
  `inspect_vault.py`. Reports intent split, join coverage by method,
  which entities attract the most keywords, entities no keyword reaches,
  and the unlinked keywords grouped by source heading.

### Rewritten (not repaired)
Both modules were replaced wholesale rather than patched, following the
proven `vault.py` shape — build rows in Python, validate, embed in bulk,
batch write:

- **`src/ingest/keywords.py`** — the old file imported
  `generate_embedding` from `src.db`, a function deleted in Phase 0 with
  the SHA-256 fake-embedding fallback, so the module could not even be
  imported. It also embedded one row per loop iteration. The new version
  classifies intent by rule (no LLM, no API cost, identical on every
  re-run), using the author's own category headings as the primary
  signal and word patterns to override them where a keyword clearly
  contradicts its heading ("buy memorial figurine" is transactional
  wherever it was listed).
- **`src/enrich/link_keywords.py`** — the old file had two real defects.
  It matched with `CONTAINS`, so the entity "Pet" matched the keyword
  "carpet cleaning". And it wrote
  `MERGE (k)-[r:ABOUT {similarity_score: score}]->(e)`; because MERGE
  matches on the whole pattern including properties and `score` is a
  float that shifts between runs, every run created a fresh duplicate
  edge. The new pass 1 matches whole words only (`\b`), tolerating a
  simple plural so `award` catches `awards`. ABOUT is treated as derived
  and recomputed from scratch each run, so a rule change can never leave
  a stale edge behind.

### Fixed
- **A duplicate-edge bug introduced during this phase.** After changing
  the intent rules and re-running, `pet figurine` had *two* intents: the
  new `HAS_INTENT` edge was created but the old one survived — the same
  class of bug being fixed in `link_keywords.py`. The write now deletes
  any existing intent edge before attaching the current one.
  `inspect_keywords.py` asserts the invariant so a regression is visible.

### Measured: the vector pass is off by default
Pass 2 (keyword → nearest chunk → entity) is implemented but requires
`--vector`. On this dataset it is **~1 correct in 14**:

```
0.8936  custom portrait figurine   -> Bronze / Sculpture Finish   wrong
0.8785  custom gifts               -> Him                         wrong
0.8782  buy custom figurine        -> Bronze / Sculpture Finish   wrong
0.8759  custom gift                -> Coach                       wrong
0.8778  create figurine from photo -> Turn Your Photo Into a ...   right
```

The cause is structural, not a threshold to tune. Every note in the
vault is about custom figurines, so the embeddings sit in one tight
cluster — the entire score range across all keyword-chunk pairs is
0.756–0.894. Worse, the keywords pass 1 misses are precisely the generic
head terms ("custom figurine", "personalised gift"), which are genuinely
equidistant from every entity because they describe the whole catalogue.
Nearest-neighbour search still returns something, so it returns an
arbitrary something — and the wrong matches score *higher* than the
right one. Kept, with the measurements in the docstring, because it
becomes useful once the graph holds genuinely distinct topics (pricing,
shipping, materials) rather than 82 variations on one subject.

### Verified
```
python -m src.ingest.keywords
  -> 154 CSV rows -> 147 unique keywords (7 duplicate spellings collapsed)
  -> intent: transactional 127, commercial 12, informational 8
  -> every keyword has exactly one intent

python -m src.enrich.link_keywords
  -> pass 1 only: 130 ABOUT relationships, 112/147 keywords linked (76.2%)

  before aliases:  81/147  (55.1%),  96 relationships
  after  aliases: 112/147  (76.2%), 130 relationships
  all 34 alias-driven matches checked by hand, all correct
```

Biggest keyword magnets: `Memorial / Loss` 45, `Pet` 9, `Corporate` 7,
`Wedding` 7 — memorial dominates, which matches the mentor supplying an
entire second memorial-specific keyword set.

### Known follow-up
- The 35 still-unlinked keywords are almost all **generic head terms**
  ("custom figurine", "buy custom figurine", "figurine maker") that
  correctly belong to the homepage or a top-level collection rather than
  to any single entity. Phase 6 should route them to site-level pages
  rather than force an entity match.
- Genuine missing entities among the remainder: action figure, resin (a
  material), and props ("custom figurine with car"). Not invented here —
  they need a real source, not a guess.
- `CLAUDE.md` rule 4 is **backwards** and has been corrected in this
  commit: it mandated `CALL { WITH x ... }`, but Neo4j 5.26 deprecates
  that form and emits a warning on every such query. `CALL (x) { ... }`
  is the current syntax and was verified working on 5.26.

---

## [Phase 4 — Deployed to DigitalOcean] — 2026-07-28

The mentor provided root SSH access to an existing DigitalOcean droplet
(`137.184.229.189`) with a guide for installing Neo4j directly (no
Docker). The droplet turned out to be **shared with an unrelated
project** — an existing Neo4j at `/opt/neo4j` (ports 7474/7687) backing
`/root/figuro-backlink-agent`, a different team repo
(`axcer-shared-projects/figuro-backlink-agent`), plus a separate Figuro
Shopify-theme checkout and various other unrelated tools. Confirmed by
searching the whole disk for anything matching this project (the
knowledge-base file, `vault.py`, a `data/vault` folder) and finding
nothing — this project had never touched that server before.

Given the shared, unrelated existing database, ran a **second, isolated
Neo4j instance** side by side rather than reusing or replacing the first.

### Added
- **A second Neo4j 5.26.0 install at `/opt/neo4j2`** on the droplet,
  extracted from the tarball already present on the server. Configured
  on its own ports (HTTP 7475, Bolt 7688) so it cannot collide with the
  existing instance's defaults.
- **GDS 2.13.2 + APOC 5.26.0** installed into `/opt/neo4j2/plugins` —
  APOC copied from the existing instance's `labs/` folder, GDS
  downloaded fresh. The mentor's guide only covered plain Neo4j; GDS is
  required for this project's clustering step (`src/analyze/clusters.py`,
  once repaired) and was added on top.
- **Memory tuned for the shared 1.9 GB droplet**: heap capped at 512m,
  page cache at 128m (existing instance already uses ~500 MB; a 2 GB
  swapfile already present on the box gives headroom either way).
- **A strong, unique password**, set via `neo4j-admin dbms
  set-initial-password` before first start (replacing the "will change
  it myself" placeholder from the mentor's handoff).
- Firewall opened for the new ports only: `ufw allow 7475`,
  `ufw allow 7688`.

### Migrated
- Applied `cypher/001_schema.cypher` against the remote instance — same
  12 statements, same command, just `NEO4J_URI` pointed at
  `bolt://137.184.229.189:7688` instead of localhost.
- Ran `python -m src.ingest.vault` against the remote instance from this
  machine (no code changes — the loader doesn't care which Neo4j it
  talks to). Verified byte-identical to local:
  ```
  72 entities, 61 pages, 31 links, 72 chunks, 175 relationships
  -- identical on local (:7687) and remote (:7688)
  ```

### Verified untouched
- `/opt/neo4j` (existing instance) confirmed still running throughout —
  checked before, during, and after via `ps aux` and an HTTP request to
  port 7474 — and its process was never stopped, its config never
  edited, its data directory never touched.

### Known follow-up
- **No systemd service yet** — if the droplet reboots, `/opt/neo4j2`
  must be started by hand:
  `sudo -u neo4j /opt/neo4j2/bin/neo4j start`. The existing instance
  presumably has its own separate start mechanism, not investigated
  (out of scope — not this project's install).
- **No automated sync** between local vault edits and the remote copy.
  Re-run `python -m src.ingest.vault` with `NEO4J_URI` pointed at the
  remote after any local change that should propagate.
- **Root password for the whole droplet was shared in plaintext** over
  chat during handoff. Recommended the user rotate it; not something
  this project's tooling can do on their behalf.
- Both ports (7475 HTTP, 7688 Bolt) are open to the public internet, not
  restricted to a specific IP — matches how the existing instance's
  ports were already configured on this droplet. Acceptable for a
  password-protected dev database; would need tightening before treating
  it as anything more sensitive.

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
