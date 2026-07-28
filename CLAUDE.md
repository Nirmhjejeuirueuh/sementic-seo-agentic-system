# CLAUDE.md

Guidance for any AI assistant (and any human) working in this repository.
Read this first.

---

## What this project is

A **Neo4j knowledge graph that drives semantic SEO** for
**[Getfiguro.com](https://getfiguro.com)**, a business that turns a
customer's photo into a custom 3D-printed figurine, plus a **LangGraph
agent** that writes web pages grounded in that graph.

The goal is organic growth: rank for the long tail of what gift-buyers
actually search, by connecting *what people search for* (keywords) to
*what the business actually knows* (its catalogue and written content),
and generating pages that provably cover each topic.

The domain source of truth is
[`getfiguro-seo-knowledge-base.md`](getfiguro-seo-knowledge-base.md) — a
hand-written SEO strategy doc mapping the live sitemap (37 products, 31
collections) plus a full gap-analysis and content plan across three
pillars: **Occasion** (wedding, birthday, christmas…), **Figurine Type**
(pet, baby, sports, anime…), and **Figurine Style** (realistic, bobblehead,
nendoroid, bronze…). A product belongs to all three pillars at once.

### The pipeline, end to end

```
 keyword CSV ─┐
              ├─► Neo4j graph ─► topic clusters ─► site structure ─► pages
 sitemap XML ─┤                  (GDS Louvain)                       (LangGraph)
 knowledge   ─┘
 base (.md / PDF)
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

`Keyword -[:ABOUT]-> Entity` is the whole point of the project. Without it,
you have two disconnected islands: a keyword list and a document graph.
It is built in two passes — precise string matching first, then vector
similarity via nearest chunks (which catches
`how much does a personalised book cost` → the `Pricing` entity).

---

## Stack (do not substitute without a reason)

| Layer | Choice |
|---|---|
| Database | Neo4j 5.26 LTS in Docker, Community + APOC + GDS |
| Graph algorithms | GDS plugin (bundled) |
| Extraction | `neo4j-graphrag` `SimpleKGPipeline` |
| Extraction LLM | `claude-sonnet-5` |
| Cheap classification | `claude-haiku-4-5-20251001` |
| Embeddings | `fastembed` / `BAAI/bge-small-en-v1.5`, 384-dim (swappable to OpenAI `text-embedding-3-small`, 1536-dim) |
| Orchestration | LangGraph 1.2.x |
| Sitemap parsing | `advertools.sitemap_to_df` |
| Driver | `neo4j` Python driver 5.x |

**Environment note:** this is a **Windows** machine. There is no `make`
and no Node. Use `run.ps1` (PowerShell) and the `.venv` Python 3.11
interpreter. Docker Desktop must be running for anything database-related.

---

## Where the database runs

There are now **two live copies** of this graph, kept in sync manually —
nothing pushes automatically between them.

| | Local (primary dev) | DigitalOcean (shared, remote) |
|---|---|---|
| Host | Docker Desktop, this machine | Droplet `137.184.229.189` |
| Bolt | `bolt://localhost:7687` | `bolt://137.184.229.189:7688` |
| Browser | `http://localhost:7474` | `http://137.184.229.189:7475` |
| Install | `neo4j:5.26-community` image | Neo4j 5.26.0 unpacked at `/opt/neo4j2` |
| Password | `password123` | strong, shared privately — see mentor thread |

**The droplet is shared with an unrelated project.** `/opt/neo4j`
(ports 7474/7687) and `/root/figuro-backlink-agent` on that same server
belong to a different, unrelated team repo
(`axcer-shared-projects/figuro-backlink-agent`) — **never stop, delete,
or reconfigure anything under `/opt/neo4j` (no `2` suffix) or that repo.**
Everything for this project on the droplet lives under `/opt/neo4j2`
only.

To push a local edit (e.g. an updated vault note) to the remote copy,
re-run the loader with the remote URI:
```bash
NEO4J_URI="bolt://137.184.229.189:7688" NEO4J_USERNAME="neo4j" NEO4J_PASSWORD="<pw>" \
  python -m src.ingest.vault --dir data/vault
```
Safe to re-run — everything is `MERGE`d. There is currently no automated
sync and no systemd auto-restart on the droplet: if it reboots, the
instance must be started again by hand
(`sudo -u neo4j /opt/neo4j2/bin/neo4j start`).

---

## Hard rules (each exists because breaking it causes a hard-to-find bug)

1. **Never write to Neo4j in a Python loop.** Batch rows and
   `UNWIND $rows AS row`. Use `DatabaseManager.batch_write`.
2. **Normalise keywords in exactly one function** — `normalize_keyword`
   in `src/config.py`. Every ingest path routes through it.
3. **Vector dimensions must match** between `.env` and the index
   definitions. A mismatch fails *silently* (zero rows, no error).
4. **Target Cypher 5 syntax** (Neo4j 5.26): `CALL { WITH x ... }`, not
   `CALL (x) { ... }`.
5. **Match `FROM_CHUNK` undirected.** Its direction has moved between
   `neo4j-graphrag` releases.
6. **Cluster on entity co-occurrence, not extracted relationships.**
7. **One bad document must not kill an extraction run.** Catch per-file.
8. **Every structured LLM call uses `.with_structured_output(Model)`.**
   No regex on model output, no JSON parsing from prose.
9. **No silent fallbacks. If something cannot work, raise.** A pipeline
   that fakes success is worse than one that crashes. This rule was added
   after the handover code faked embeddings (SHA-256 hash) and faked agent
   context (hardcoded samples) when inputs were missing.

---

## How to run

```powershell
.\run.ps1 up          # start Neo4j (Docker must be running)
.\.venv\Scripts\Activate.ps1
.\run.ps1 schema      # apply constraints + indexes
.\run.ps1 verify      # definition of done for setup
```

Neo4j Browser: http://localhost:7474 (neo4j / password123).
See `README.md` for full setup and `progress-tracker.md` for current state.

---

## Working agreement

- The original build brief is a message from the user's mentor. Its intent
  governs; follow it unless it conflicts with reality on this machine
  (e.g. the LangGraph version pins, which were simply wrong).
- Work in phases. Each phase ends with something verifiable, and stops for
  human review before the next. Do not run ahead.
- Prefer boring, verifiable code over clever code.
- When a design decision is genuinely ambiguous and the answer changes
  the work, ask. Otherwise make the call and state the assumption.

---

## Current state (2026-07-28)

- **Phase 0 (infrastructure): done and verified.**
- **Phase 1 (repair pipeline modules): in progress.** Five modules still
  carry defects from the AI Studio handover — see `CHANGELOG.md` "Known
  issues" and `progress-tracker.md`.
- **Phase 2 (domain schema): done.** `ALLOWED_NODE_LABELS` /
  `ALLOWED_RELATIONSHIPS` in `src/config.py` now reflect the figurine
  domain: `Product`, `FigurineStyle`, `FigurineType`, `Occasion`,
  `Format`, `Recipient`, `Accessory`.
- **Phase 3 (knowledge base in Obsidian): done.** 72 notes (37 products +
  35 taxonomy) fully transcribed from the source document and loaded.
  `accessories/` is deliberately still empty — no product in the source
  document pairs with a specific accessory, so there's nothing true to
  tag yet.
- **Phase 4 (remote deployment): done.** The same 72-note graph is now
  also live on a DigitalOcean droplet (`/opt/neo4j2`, ports 7475/7688) —
  see "Where the database runs" above. Verified identical to local:
  72 entities, 61 pages, 31 links, 72 chunks, 175 relationships on both.
  No auto-sync, no auto-restart-on-reboot yet.
- Do not rewrite `src/ingest/documents.py` (the prose/PDF extractor) yet —
  it stays reserved for the source document's §7-8 SEO rulebook, a
  distinctly different job from the deterministic vault loader.
- **Phase 5+ (keywords, "the join", clustering, the agent): blocked** —
  no real keyword data yet, and four handover modules still need repair
  (Phase 1).
