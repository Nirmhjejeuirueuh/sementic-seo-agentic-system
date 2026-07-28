# Semantic SEO Knowledge Graph

A Neo4j knowledge graph that drives semantic SEO for a personalised
storybook business, plus a LangGraph agent that writes pages grounded in
that graph rather than in the model's training data.

---

## What this actually does

Normal keyword SEO gives you a spreadsheet and no idea how the rows relate.
This project connects two things that are usually disconnected:

- **What people search for** — a keyword list
- **What you actually know** — your product catalogue and written content

It joins them in a graph, finds topic clusters automatically, and then
generates pages that provably cover each cluster.

```
 keyword CSV ─┐
              ├─► Neo4j ─► clusters ─► site structure ─► generated pages
 sitemap XML ─┤            (Louvain)                     (LangGraph agent)
 knowledge   ─┘
 base (.md)
```

### The graph model

```
(:Document)-[:FROM_DOCUMENT]-(:Chunk)-[:FROM_CHUNK]-(:__Entity__)
(:Keyword)-[:HAS_INTENT]->(:Intent)
(:Keyword)-[:TARGETS]->(:Page)
(:Keyword)-[:ABOUT]->(:__Entity__)          <-- the join that matters
(:__Entity__)-[:IN_CLUSTER]->(:Cluster)
(:Page)-[:COVERS]->(:Cluster)
(:Page)-[:SHOULD_LINK_TO]->(:Page)
(:Page)-[:LINKS_TO]->(:Page)
```

`Keyword -[:ABOUT]-> Entity` is the whole point. Without it you have two
disconnected islands: a keyword list and a document graph.

It is built in two passes:

1. **String matching** — precise, low recall. Catches `dinosaur books`
   matching the entity `Dinosaurs`.
2. **Vector similarity via nearest chunks** — catches
   `how much does a personalised book cost` → `Pricing`, which string
   matching never will.

Pass 2 goes *through chunks* rather than embedding entity names directly.
An entity name on its own carries little signal; the passage around it
carries a lot.

---

## Setup

### Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | **3.11** | Not 3.12+. `pandas`/`advertools`/`fastembed` lack wheels for the newest Python and pip will try to build from source. |
| Docker Desktop | any recent | Must be *running*, not just installed. |
| Anthropic API key | — | Only needed from Phase 4 onward. |

There is no `make` and no Node. `run.ps1` replaces the Makefile.

### First-time setup

```bash
py -3.11 -m venv .venv
```

```bash
.\.venv\Scripts\Activate.ps1
```

```bash
pip install -r requirements.txt
```

```bash
Copy-Item .env.example .env
```

Then edit `.env` and add your `ANTHROPIC_API_KEY`.

### Start the database

```bash
.\run.ps1 up
```

First boot downloads the APOC and GDS plugins and takes 1–2 minutes.
Later boots are fast.

```bash
.\run.ps1 schema
```

```bash
.\run.ps1 verify
```

`verify` is the definition of done for setup. It should show 7 constraints,
2 vector indexes, and a GDS version.

Neo4j Browser: <http://localhost:7474> — log in with `neo4j` / `password123`.

---

## Commands

| Command | What it does |
|---|---|
| `.\run.ps1 up` | Start Neo4j, wait until it answers |
| `.\run.ps1 down` | Stop Neo4j (data kept in volumes) |
| `.\run.ps1 schema` | Apply constraints and indexes |
| `.\run.ps1 verify` | Check constraints, indexes, GDS |
| `.\run.ps1 counts` | Node count per label |
| `.\run.ps1 logs` | Tail the Neo4j log |
| `.\run.ps1 browser` | Open Neo4j Browser |
| `.\run.ps1 nuke` | Delete all data, start clean |

```bash
python -m scripts.smoke_test
```

Proves the embedding model produces meaningful vectors, not just vectors
of the right length.

---

## Embeddings

Set by `EMBEDDING_PROVIDER` in `.env`.

| Provider | Model | Dims | Cost |
|---|---|---|---|
| `fastembed` *(default)* | `BAAI/bge-small-en-v1.5` | 384 | free, local, no key |
| `openai` | `text-embedding-3-small` | 1536 | ~$0.02 / M tokens |

To switch to OpenAI:

1. Set `EMBEDDING_PROVIDER=openai` and `EMBEDDING_DIM=1536` in `.env`
2. Uncomment `openai` in `requirements.txt`, then `pip install -r requirements.txt`
3. In Neo4j Browser: `DROP INDEX chunk_embedding_idx; DROP INDEX keyword_embedding_idx;`
4. `.\run.ps1 schema`
5. Re-run the ingest steps so embeddings are regenerated

Step 3 matters. The schema uses `IF NOT EXISTS`, so it will happily leave
an index at the old dimension in place — and a dimension mismatch makes
vector queries return **zero rows with no error**.

---

## Project rules

These are not style preferences. Each one exists because breaking it
causes a bug that is hard to find.

1. **Never write to Neo4j in a Python loop.** Batch rows and
   `UNWIND $rows AS row`. A 5,000-row file goes from ~4 minutes to
   ~2 seconds. Use `DatabaseManager.batch_write`.
2. **Normalise keywords in exactly one function** — `normalize_keyword`
   in `src/config.py`. Route every ingest path through it, or
   `SEO Audit` and `seo audit` become two nodes.
3. **Vector dimensions must match** between `.env` and the index
   definitions. A mismatch fails *silently*.
4. **Target Cypher 5 syntax** (Neo4j 5.26): `CALL { WITH x ... }` for
   scoped subqueries, not the newer `CALL (x) { ... }`.
5. **Match `FROM_CHUNK` undirected.** Its direction has moved between
   `neo4j-graphrag` releases.
6. **Cluster on entity co-occurrence, not extracted relationships.** Two
   entities discussed in the same chunk are related whether or not the
   extractor drew an edge, and that implicit signal clusters better.
7. **One bad document must not kill an extraction run.** Catch per-file
   and continue.
8. **Every LLM call needing structured data uses
   `.with_structured_output(Model)`.** No regex on model output, no JSON
   parsing from prose.
9. **No silent fallbacks.** If something cannot work, raise. A pipeline
   that fakes success is worse than one that crashes.

Rule 9 was added after the first version of this codebase generated
"embeddings" from a SHA-256 hash when no API key was present, and returned
hardcoded sample keywords when the graph was empty. Both looked like
success.

---

## Layout

```
cypher/001_schema.cypher     constraints, indexes, vector indexes
data/                        input: keywords.csv, sitemap.xml, vault/
scripts/                     one-off checks
src/config.py                settings + THE EXTRACTION SCHEMA
src/db.py                    driver, batched writes, embeddings
src/ingest/keywords.py       CSV -> Keyword, Intent, Page
src/ingest/sitemap.py        sitemap.xml -> Page
src/ingest/documents.py      docs -> Document, Chunk, Entity
src/enrich/link_keywords.py  Keyword -> Entity  (string + vector)
src/analyze/clusters.py      Louvain, node similarity, PageRank
src/agents/context.py        the queries that build the agent's context
src/agents/state.py          LangGraph state + Pydantic output models
src/agents/page_graph.py     the workflow
output/                      generated pages
```

---

## Status

| Phase | State |
|---|---|
| 0. Infrastructure | **done** — verified, see below |
| 1. Repair pipeline modules | in progress |
| 2. Domain schema | not started |
| 3. Knowledge base in Obsidian | not started |
| 4. Vault ingestion | not started |
| 5. Keywords + the join | not started |
| 6. Clustering | not started |
| 7. Site structure & sitemap | not started |
| 8. Page generation agent | not started |

### Phase 0 verified on 2026-07-27

```
7 constraints, 14 indexes (2 vector)
GDS 2.13.11
Neo4j 5.26-community, Python 3.11.7, langgraph 1.2.9
fastembed / BAAI/bge-small-en-v1.5 / 384 dims

scripts/smoke_test.py           related 0.785 vs unrelated 0.401   PASS
scripts/verify_vector_index.py  pricing query -> pricing passage   PASS
```

Two checks, not one. `smoke_test` proves the *model* produces meaningful
vectors. `verify_vector_index` proves the *index* dimension matches the
model, by writing real chunks and querying them back. `SHOW INDEXES` alone
proves neither — an index at the wrong dimension exists happily and
returns zero rows forever without ever raising.
