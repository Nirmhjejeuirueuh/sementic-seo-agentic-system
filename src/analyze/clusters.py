"""
Phase 6.1 -- topic clusters: group the keyword demand into page-sized units.

A cluster is "one topic a page could be written about". It is built from
the join: every entity that attracts at least one keyword becomes a
cluster, except where two entities clearly belong on the same page, in
which case they share one.

Rewritten from scratch. The previous version had two defects:

  1. `run_pagerank_and_link_candidates` did not compute PageRank. It set
     `e.pageRank = keyword_degree * 1.5 + log10(total_volume + 1.0)`,
     an invented formula stored under a name that implies the real
     algorithm. Downstream code would trust the name. That function is
     removed here -- internal linking is Phase 8's job and will use
     `gds.pageRank` properly.
  2. Its GDS fallback returned `0.72 AS modularity`, a hardcoded
     constant. Modularity is the number that tells you whether the
     clustering is any good, so returning a plausible-looking literal
     made a completely failed run report a healthy score.

HOW ENTITIES ARE GROUPED, and why it is this and not something cleverer:

Two entities belong together when the same keyword is about both --
"pet memorial figurine" is about Pet and about Memorial / Loss, so those
two share a page. That is entity co-occurrence, per CLAUDE.md rule 6.

Measured on this dataset (2026-07-28, 82 entities, 112 linked keywords):

    entity pairs sharing >= 1 keyword      11
    keywords pointing at exactly 1 entity  95 of 112
    GDS Louvain communities                73 of 82 entities

So the co-occurrence graph is very sparse and Louvain is close to the
identity function -- most entities are genuinely independent topics.
It is still used rather than hand-rolled, because the merges it does
find are exactly the right ones:

    Memorial / Loss           + Pet                            (5 shared)
    Family / Group Custom Fig + Family                          (4 shared)
    Trophy / Award            + Corporate                       (2 shared)

Clusters are derived. They are dropped and rebuilt on every run.

Run:  python -m src.analyze.clusters
"""

import logging
from collections import defaultdict
from typing import Any, Dict, List

from src.db import DatabaseManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s %(message)s")
logger = logging.getLogger(__name__)

GRAPH_NAME = "entity_cooccurrence"

# How many keywords two entities must share before they are treated as
# one topic.
#
# This is 2, not 1, and the difference is large. At 1, a single keyword
# is enough to fuse two entities, and Louvain then chains through those
# weak links. Measured on this dataset:
#
#   "loss of husband gift"      is the ONLY keyword shared by Husband
#                               and Memorial / Loss
#   "loss of wife gift"         likewise for Wife
#   "realistic memorial figurine" likewise for Realistic
#
# At threshold 1 those three single links merged Husband, Wife and
# Realistic into the memorial cluster, dragging 10 unrelated keywords
# with them -- "gifts for husband", "gifts for wife", "realistic
# figurine", "pet figurine" -- and produced one incoherent 55-keyword
# cluster that no single page could serve.
#
# At 2, only genuinely overlapping topics merge.
MIN_COOCCURRENCE_WEIGHT = 2


def build_cooccurrence(db: DatabaseManager) -> int:
    """
    Materialise (:__Entity__)-[:CO_OCCURS_WITH]-(:__Entity__).

    Weight is the number of keywords that are about both entities.
    Pairs below MIN_COOCCURRENCE_WEIGHT are not written at all, so the
    clustering never sees them.

    Undirected: written once per pair via the elementId ordering, then
    always matched without a direction.
    """
    db.execute_query("MATCH ()-[r:CO_OCCURS_WITH]-() DELETE r")

    result = db.execute_query(
        """
        MATCH (e1:__Entity__)<-[:ABOUT]-(k:Keyword)-[:ABOUT]->(e2:__Entity__)
        WHERE elementId(e1) < elementId(e2)
        WITH e1, e2, count(k) AS shared
        WHERE shared >= $min_weight
        MERGE (e1)-[r:CO_OCCURS_WITH]-(e2)
        SET r.weight = shared
        RETURN count(r) AS edges
        """,
        {"min_weight": MIN_COOCCURRENCE_WEIGHT},
    )
    edges = result[0]["edges"] if result else 0
    logger.info(
        "Co-occurrence: %d entity pairs share >= %d keywords.",
        edges, MIN_COOCCURRENCE_WEIGHT,
    )
    return edges


def run_louvain(db: DatabaseManager) -> Dict[str, Any]:
    """
    Assign each entity a community id via GDS Louvain.

    Returns the real communityCount and modularity that GDS reports. If
    GDS is unavailable this raises -- it does not substitute a plausible
    number and carry on (CLAUDE.md rule 9).
    """
    try:
        db.execute_query(f"CALL gds.graph.drop('{GRAPH_NAME}', false)")
    except Exception:
        pass  # not projected yet -- expected on a first run

    db.execute_query(
        f"""
        CALL gds.graph.project(
            '{GRAPH_NAME}',
            '__Entity__',
            {{ CO_OCCURS_WITH: {{ orientation: 'UNDIRECTED', properties: 'weight' }} }}
        )
        """
    )

    stats = db.execute_query(
        f"""
        CALL gds.louvain.write('{GRAPH_NAME}', {{
            writeProperty: 'community',
            relationshipWeightProperty: 'weight'
        }})
        YIELD communityCount, modularity
        RETURN communityCount, modularity
        """
    )[0]

    db.execute_query(f"CALL gds.graph.drop('{GRAPH_NAME}', false)")

    logger.info(
        "Louvain: %d communities across all entities, modularity %.4f",
        stats["communityCount"], stats["modularity"],
    )
    return stats


def build_clusters(db: DatabaseManager) -> List[Dict[str, Any]]:
    """
    Turn communities into (:Cluster) nodes -- but only those that
    actually carry keyword demand.

    An entity nobody searches for cannot justify a page, so communities
    with zero keywords are skipped rather than becoming empty clusters
    that Phase 6.2 would then have to filter out again.
    """
    db.execute_query("MATCH (c:Cluster) DETACH DELETE c")

    rows = db.execute_query(
        """
        MATCH (k:Keyword)-[:ABOUT]->(e:__Entity__)
        MATCH (k)-[:HAS_INTENT]->(i:Intent)
        WHERE e.community IS NOT NULL
        RETURN e.community AS community,
               e.name AS entity, e.type AS entity_type,
               k.normalized AS keyword, i.name AS intent
        """
    )
    if not rows:
        raise RuntimeError(
            "No keyword->entity->community paths found. "
            "Run the vault, keyword and link steps first."
        )

    # Fold the flat rows into one record per community.
    grouped: Dict[Any, Dict[str, Any]] = defaultdict(
        lambda: {"entities": {}, "keywords": set(), "intents": defaultdict(int)}
    )
    for r in rows:
        g = grouped[r["community"]]
        g["entities"][r["entity"]] = r["entity_type"]
        g["keywords"].add(r["keyword"])
        g["intents"][r["intent"]] += 1

    cluster_rows = []
    for community, g in grouped.items():
        # Name the cluster after the entity carrying the most keywords,
        # so "Memorial / Loss + Pet" reads as Memorial rather than Pet.
        per_entity = defaultdict(int)
        for r in rows:
            if r["community"] == community:
                per_entity[r["entity"]] += 1
        lead = max(per_entity, key=per_entity.get)

        others = [e for e in g["entities"] if e != lead]
        name = lead if not others else f"{lead} + {' + '.join(sorted(others))}"

        cluster_rows.append({
            "id": f"cluster_{community}",
            "name": name,
            "lead_entity": lead,
            "entity_names": sorted(g["entities"]),
            "entity_types": sorted(set(g["entities"].values())),
            "keyword_count": len(g["keywords"]),
            "dominant_intent": max(g["intents"], key=g["intents"].get),
        })

    cluster_rows.sort(key=lambda c: -c["keyword_count"])

    db.batch_write(
        """
        UNWIND $rows AS row
        MERGE (c:Cluster {id: row.id})
        SET c.name = row.name,
            c.lead_entity = row.lead_entity,
            c.entity_types = row.entity_types,
            c.keyword_count = row.keyword_count,
            c.dominant_intent = row.dominant_intent,
            c.updatedAt = timestamp()
        WITH c, row
        UNWIND row.entity_names AS entity_name
        MATCH (e:__Entity__ {name: entity_name})
        MERGE (e)-[:IN_CLUSTER]->(c)
        """,
        cluster_rows,
    )
    logger.info("Built %d clusters carrying keyword demand.", len(cluster_rows))
    return cluster_rows


def report(db: DatabaseManager, clusters: List[Dict[str, Any]]) -> None:
    total_kw = db.execute_query("MATCH (k:Keyword) RETURN count(*) AS n")[0]["n"]
    covered = sum(c["keyword_count"] for c in clusters)

    print("\n" + "=" * 72)
    print("PHASE 6.1 -- TOPIC CLUSTERS")
    print("=" * 72)
    print(f"  {len(clusters)} clusters covering {covered} of {total_kw} keywords\n")
    print(f"  {'#':>3}  {'keywords':>8}  {'intent':<14} cluster")
    print(f"  {'-'*3}  {'-'*8}  {'-'*14} {'-'*40}")
    for i, c in enumerate(clusters, 1):
        print(f"  {i:>3}  {c['keyword_count']:>8}  {c['dominant_intent']:<14} {c['name']}")

    merged = [c for c in clusters if " + " in c["name"]]
    print(f"\n  {len(merged)} cluster(s) merge more than one entity:")
    for c in merged:
        print(f"    {c['name']}  ({c['keyword_count']} keywords)")
    print()


def analyze_clusters() -> List[Dict[str, Any]]:
    db = DatabaseManager()
    try:
        build_cooccurrence(db)
        run_louvain(db)
        clusters = build_clusters(db)
        report(db, clusters)
        return clusters
    finally:
        db.close()


if __name__ == "__main__":
    analyze_clusters()
