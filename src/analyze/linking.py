"""
Phase 8 -- real internal linking.

Phase 7's plan_links_node (src/agents/page_graph.py) has proposed 0
links on every one of the 32 generated pages. Not a bug in the matching
logic -- the candidates it was given (context.py's old sibling_pages
query) were just "other pages sorted by keyword-count priority",
topically unrelated pages whose slugs essentially never appear in
prose. This module supplies the thing that was actually missing: real
relevance between pages, computed from the graph, not a priority sort.

Two real signals, both already sitting in the graph and unused for
this purpose until now:

  1. Connecting relationships between different clusters' entities --
     HAS_STYLE / FOR_OCCASION / ... (src/ingest/vault.py) and
     CO_OCCURS_WITH (src/analyze/clusters.py). A Pet product HAS_STYLE
     Realistic connects the Pet cluster's page to the Realistic
     cluster's page -- that connection IS "shared entities" between
     two pages, and it already exists in the graph.
  2. Real gds.pageRank over those same entity relationships, used to
     break ties when a page has more candidate targets than its link
     budget. clusters.py's own docstring flagged this as deferred:
     "internal linking is Phase 8's job and will use gds.pageRank
     properly." This is that.

Run:  python -m src.analyze.linking
"""

import logging
from collections import defaultdict
from typing import Any, Dict, List

from src.config import ALLOWED_RELATIONSHIPS
from src.db import DatabaseManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s %(message)s")
logger = logging.getLogger(__name__)

GRAPH_NAME = "page_linking_entities"

# Every relationship type PageRank should flow across: the domain
# taxonomy edges (src/ingest/vault.py) plus CO_OCCURS_WITH
# (src/analyze/clusters.py). RELATES_TO is already inside
# ALLOWED_RELATIONSHIPS.
LINK_REL_TYPES = ALLOWED_RELATIONSHIPS + ["CO_OCCURS_WITH"]

# One real connecting relationship between two different clusters is
# enough to be a link *candidate*. This is deliberately much lower than
# clusters.py's MIN_COOCCURRENCE_WEIGHT=2 -- that threshold decides
# whether two topics are the same page; this only decides whether two
# already-separate pages are worth considering for a link, and weight +
# target pageRank do the actual ranking below.
MIN_LINK_WEIGHT = 1
DEFAULT_TOP_K = 5


def run_pagerank(db: DatabaseManager) -> Dict[str, Any]:
    """
    Real gds.pageRank.write over every entity relationship type, written
    to e.pageRank and then summed up onto p.pageRank per Page.

    Project/run/drop follows the exact pattern already used for Louvain
    in src/analyze/clusters.py:149-189 (drop-before wrapped in
    try/except since nothing is projected on a first run, drop-after
    unconditional).
    """
    try:
        db.execute_query(f"CALL gds.graph.drop('{GRAPH_NAME}', false)")
    except Exception:
        pass  # not projected yet -- expected on a first run

    # gds.graph.project's native syntax requires every relationship type
    # in the projection to already exist in the store's token index, or
    # it fails outright -- unlike a plain Cypher type(r) IN [...] check,
    # which just matches nothing for a type that was never used. Two of
    # LINK_REL_TYPES are exactly that: PAIRS_WITH (accessories/ is
    # deliberately empty -- data/vault/README.md) and RELATES_TO (no
    # ingest path writes it yet). Project only what's actually present.
    existing_types = {
        r["relationshipType"]
        for r in db.execute_query("CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType")
    }
    active_rel_types = [t for t in LINK_REL_TYPES if t in existing_types]
    unused = [t for t in LINK_REL_TYPES if t not in existing_types]
    if unused:
        logger.info("Skipping relationship type(s) with zero instances in the graph: %s", unused)

    rel_projection = ", ".join(
        f"{t}: {{ orientation: 'UNDIRECTED' }}" for t in active_rel_types
    )
    db.execute_query(
        f"""
        CALL gds.graph.project(
            '{GRAPH_NAME}',
            '__Entity__',
            {{ {rel_projection} }}
        )
        """
    )

    stats = db.execute_query(
        f"""
        CALL gds.pageRank.write('{GRAPH_NAME}', {{
            writeProperty: 'pageRank'
        }})
        YIELD nodePropertiesWritten, ranIterations
        RETURN nodePropertiesWritten, ranIterations
        """
    )[0]

    db.execute_query(f"CALL gds.graph.drop('{GRAPH_NAME}', false)")

    db.execute_query(
        """
        MATCH (p:Page)-[:COVERS]->(:Cluster)<-[:IN_CLUSTER]-(e:__Entity__)
        WITH p, sum(coalesce(e.pageRank, 0.0)) AS score
        SET p.pageRank = score
        """
    )

    logger.info(
        "PageRank: wrote %d entity scores over %d iterations; aggregated onto Page.pageRank.",
        stats["nodePropertiesWritten"], stats["ranIterations"],
    )
    return stats


def build_should_link_to(
    db: DatabaseManager, top_k: int = DEFAULT_TOP_K, min_weight: int = MIN_LINK_WEIGHT
) -> int:
    """
    (:Page)-[:SHOULD_LINK_TO]->(:Page) from real connecting relationships
    between different clusters' entities.

    Dropped and rebuilt on every run, like Cluster (clusters.py:201).
    """
    db.execute_query("MATCH ()-[r:SHOULD_LINK_TO]-() DELETE r")

    rows = db.execute_query(
        """
        MATCH (p1:Page)-[:COVERS]->(c1:Cluster)<-[:IN_CLUSTER]-(e1:__Entity__)
        MATCH (p2:Page)-[:COVERS]->(c2:Cluster)<-[:IN_CLUSTER]-(e2:__Entity__)
        WHERE c1 <> c2 AND p1 <> p2
        MATCH (e1)-[r]-(e2)
        WHERE type(r) IN $rel_types
        WITH p1, p2, count(DISTINCT r) AS weight,
             collect(DISTINCT type(r)) AS rel_types_used,
             collect(DISTINCT e2.name) AS via_entities,
             coalesce(p2.pageRank, 0.0) AS target_rank
        WHERE weight >= $min_weight
        RETURN p1.url AS from_url, p2.url AS to_url, weight, rel_types_used,
               via_entities, target_rank
        ORDER BY p1.url, weight DESC, target_rank DESC
        """,
        {"rel_types": LINK_REL_TYPES, "min_weight": min_weight},
    )

    by_source: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_source[r["from_url"]].append(r)

    link_rows = []
    for from_url, candidates in by_source.items():
        for r in candidates[:top_k]:
            reason = (
                f"connected via {', '.join(r['rel_types_used'])} "
                f"through {', '.join(r['via_entities'][:3])}"
            )
            link_rows.append({
                "from_url": from_url,
                "to_url": r["to_url"],
                "weight": r["weight"],
                "reason": reason,
            })

    db.batch_write(
        """
        UNWIND $rows AS row
        MATCH (p1:Page {url: row.from_url})
        MATCH (p2:Page {url: row.to_url})
        MERGE (p1)-[r:SHOULD_LINK_TO]->(p2)
        SET r.weight = row.weight, r.reason = row.reason, r.updatedAt = timestamp()
        """,
        link_rows,
    )
    logger.info(
        "SHOULD_LINK_TO: %d edges written (top %d per page, min weight %d).",
        len(link_rows), top_k, min_weight,
    )
    return len(link_rows)


def propose_anchor_links(
    cluster_id: str, draft_text: str, db: DatabaseManager, max_links: int = 5
) -> List[Dict[str, str]]:
    """
    Real relevance candidates (SHOULD_LINK_TO, built above) that also
    have real anchor text -- a phrase describing the target page that
    appears verbatim in this draft.

    Used by both the live agent (src/agents/page_graph.py:plan_links_node)
    and the retrofit script (scripts/apply_internal_links_and_schema.py)
    so the two never drift apart.

    No invented anchor text and no invented link when nothing matches:
    zero proposed links is the correct, honest answer, same principle
    plan_links_node has always followed -- now backed by real
    cross-cluster relevance instead of an arbitrary priority list.
    """
    rows = db.execute_query(
        """
        MATCH (p:Page)-[:COVERS]->(:Cluster {id: $cluster_id})
        MATCH (p)-[r:SHOULD_LINK_TO]->(target:Page)-[:COVERS]->(tc:Cluster)
        RETURN target.slug AS target_slug, target.primary_keyword AS primary_keyword,
               tc.name AS cluster_name, tc.lead_entity AS lead_entity,
               r.weight AS weight, r.reason AS reason
        ORDER BY r.weight DESC
        """,
        {"cluster_id": cluster_id},
    )

    draft_lower = draft_text.lower()
    proposed: List[Dict[str, str]] = []
    seen_targets = set()

    for row in rows:
        if len(proposed) >= max_links:
            break
        if row["target_slug"] in seen_targets:
            continue

        candidates = [row["primary_keyword"], row["lead_entity"]]
        candidates += [part.strip() for part in (row["cluster_name"] or "").split("+")]

        for phrase in candidates:
            if phrase and phrase.lower() in draft_lower:
                proposed.append({
                    "target_slug": row["target_slug"],
                    "anchor_text": phrase,
                    "relationship_reason": row["reason"],
                })
                seen_targets.add(row["target_slug"])
                break

    if not proposed:
        logger.info(
            "[linking] 0 internal links proposed for cluster %s -- no "
            "SHOULD_LINK_TO target's phrase appears verbatim in the draft.",
            cluster_id,
        )
    return proposed


def report(pagerank_stats: Dict[str, Any], edge_count: int, db: DatabaseManager) -> None:
    print("\n" + "=" * 72)
    print("PHASE 8 -- INTERNAL LINKING")
    print("=" * 72)
    print(f"\n  PageRank: {pagerank_stats['nodePropertiesWritten']} entities scored "
          f"over {pagerank_stats['ranIterations']} iterations")
    print(f"  SHOULD_LINK_TO: {edge_count} edges written\n")

    top = db.execute_query(
        """
        MATCH (p1:Page)-[r:SHOULD_LINK_TO]->(p2:Page)
        RETURN p1.url AS from_url, p2.url AS to_url, r.weight AS weight
        ORDER BY r.weight DESC
        LIMIT 10
        """
    )
    print(f"  {'weight':>6}  from -> to")
    print(f"  {'-'*6}  {'-'*60}")
    for r in top:
        print(f"  {r['weight']:>6}  {r['from_url']} -> {r['to_url']}")
    print()


def analyze_linking() -> int:
    db = DatabaseManager()
    try:
        stats = run_pagerank(db)
        edges = build_should_link_to(db)
        report(stats, edges, db)
        return edges
    finally:
        db.close()


if __name__ == "__main__":
    analyze_linking()
