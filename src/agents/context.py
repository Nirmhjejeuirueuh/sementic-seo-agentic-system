"""
Phase 7: pull everything the page-writing agent needs to know about one
cluster, straight from Neo4j.

Rewritten from scratch. The previous version had a hardcoded fallback on
every single query -- if a query came back empty, it silently substituted
sample data from an unrelated demo project ("SEO Optimization", "semantic
seo guide"), not even from the Getfiguro domain. The agent would then
write an entire page grounded in facts that don't exist and report
success. This is exactly the failure mode CLAUDE.md rule 9 exists to
ban, and it is the same shape of bug as the fake embeddings removed in
Phase 0.

The fix is not "better fallback data" -- it's no fallback data. Every
piece of context here is either real, or the function raises so the
problem is visible before an LLM call is ever made.

What legitimately CAN be empty vs what CANNOT, and why:

  entities / keywords / evidence_passages
      By construction these cannot be empty for a real cluster. Clusters
      are built (src/analyze/clusters.py) FROM keywords that are ABOUT
      entities in that cluster, and every entity has exactly one chunk
      (src/ingest/vault.py writes one per note). An empty result here
      means the cluster_id is wrong or the graph is in an inconsistent
      state -- a real bug, not a quiet edge case. Raise.

  sibling_pages
      Legitimately can be empty or short. Real relevance-based linking
      (SHOULD_LINK_TO, from shared entities/PageRank) is Phase 8's job,
      not built yet. An empty list here just means "no link candidates
      yet" -- log it, don't raise.

Run standalone for a smoke test: python -m src.agents.context <cluster_id>
"""

import logging
from typing import Any, Dict, List

from src.db import DatabaseManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s %(message)s")
logger = logging.getLogger(__name__)


def fetch_agent_context(cluster_id: str, db: DatabaseManager) -> Dict[str, Any]:
    """
    Returns:
        cluster_id, cluster_name  -- identity
        entities                  -- names, ranked by how many chunks mention them
        keywords                  -- {name, normalized, intent} for every keyword
                                      ABOUT an entity in this cluster
        dominant_intent           -- majority vote over those keywords
        evidence_passages         -- source text, ranked by how many
                                      cluster entities each passage covers
        sibling_pages             -- other real pages (may be empty)
    """
    logger.info("Loading Neo4j context for cluster: %s", cluster_id)

    cluster_row = db.execute_query(
        "MATCH (cl:Cluster {id: $cluster_id}) RETURN cl.name AS name",
        {"cluster_id": cluster_id},
    )
    if not cluster_row:
        raise ValueError(
            f"No Cluster with id={cluster_id!r}. Run "
            f"`python -m src.analyze.clusters` first, or check the id "
            f"against `MATCH (c:Cluster) RETURN c.id, c.name`."
        )
    cluster_name = cluster_row[0]["name"]

    # ------------------------------------------------------------------
    # Entities -- ranked by how many chunks (source passages) mention
    # them. This is a real, if simple, relevance signal available today.
    # A proper PageRank-based score is Phase 8's job (internal linking);
    # nothing here should pretend that exists yet.
    # ------------------------------------------------------------------
    entities_res = db.execute_query(
        """
        MATCH (cl:Cluster {id: $cluster_id})<-[:IN_CLUSTER]-(e:__Entity__)
        OPTIONAL MATCH (c:Chunk)-[:FROM_CHUNK]-(e)
        WITH e, count(DISTINCT c) AS mentions
        RETURN e.name AS name, e.type AS type, mentions
        ORDER BY mentions DESC, e.name
        """,
        {"cluster_id": cluster_id},
    )
    if not entities_res:
        raise RuntimeError(
            f"Cluster {cluster_id!r} ({cluster_name!r}) has no entities. "
            f"Clusters are built from entities that share keywords, so an "
            f"empty result here means the graph is inconsistent -- "
            f"re-run src/analyze/clusters.py."
        )
    entities = [e["name"] for e in entities_res]

    # ------------------------------------------------------------------
    # Keywords -- every keyword ABOUT an entity in this cluster.
    #
    # No search_volume: that property does not exist anywhere in this
    # graph (Phase 5 deliberately did not fabricate volumes the source
    # keyword list never provided). Ordering is alphabetical, not by a
    # popularity signal we don't have -- pretending otherwise would be
    # exactly the kind of invented precision rule 9 forbids.
    # ------------------------------------------------------------------
    keywords_res = db.execute_query(
        """
        MATCH (cl:Cluster {id: $cluster_id})<-[:IN_CLUSTER]-(e:__Entity__)<-[:ABOUT]-(k:Keyword)
        MATCH (k)-[:HAS_INTENT]->(i:Intent)
        RETURN DISTINCT k.name AS name, k.normalized AS normalized, i.name AS intent
        ORDER BY k.normalized
        """,
        {"cluster_id": cluster_id},
    )
    if not keywords_res:
        raise RuntimeError(
            f"Cluster {cluster_id!r} ({cluster_name!r}) has no keywords. "
            f"Every cluster is built FROM keyword demand, so this should "
            f"be impossible -- re-run src/analyze/clusters.py."
        )
    keywords = keywords_res

    dominant_intent = _majority_intent(keywords)

    # ------------------------------------------------------------------
    # Evidence passages -- the actual prose the draft must be grounded
    # in. Ranked by how many of THIS cluster's entities each chunk
    # mentions, so a passage covering several cluster entities at once
    # outranks one that only touches a single unrelated entity in
    # passing.
    # ------------------------------------------------------------------
    passages_res = db.execute_query(
        """
        MATCH (cl:Cluster {id: $cluster_id})<-[:IN_CLUSTER]-(e:__Entity__)
        MATCH (c:Chunk)-[:FROM_CHUNK]-(e)
        MATCH (c)-[:FROM_DOCUMENT]->(d:Document)
        WITH c, d, count(DISTINCT e) AS entity_coverage, collect(DISTINCT e.name) AS covered_entities
        RETURN c.id AS chunk_id, c.text AS passage, d.id AS doc,
               entity_coverage, covered_entities
        ORDER BY entity_coverage DESC
        """,
        {"cluster_id": cluster_id},
    )
    if not passages_res:
        raise RuntimeError(
            f"Cluster {cluster_id!r} ({cluster_name!r}) has entities but no "
            f"evidence passages. Every entity's vault note should have "
            f"produced exactly one Chunk (src/ingest/vault.py) -- this "
            f"means chunks are missing or FROM_CHUNK is broken."
        )
    evidence_passages = passages_res

    # ------------------------------------------------------------------
    # Sibling pages -- legitimately optional. Real relevance ranking
    # (shared entities, PageRank) is Phase 8. For now this surfaces
    # other real proposed/existing pages so the agent has *something* to
    # consider linking to, ranked by how much keyword demand they carry.
    # ------------------------------------------------------------------
    siblings_res = db.execute_query(
        """
        MATCH (p:Page)-[:COVERS]->(other:Cluster)
        WHERE other.id <> $cluster_id
        RETURN DISTINCT p.url AS url, p.slug AS slug, p.status AS status,
               p.priority AS priority
        ORDER BY p.priority DESC
        LIMIT 5
        """,
        {"cluster_id": cluster_id},
    )
    if not siblings_res:
        logger.info(
            "No sibling pages found for cluster %s -- expected until more "
            "clusters have pages, or once Phase 8 builds real relevance links.",
            cluster_id,
        )
    sibling_pages = [s["slug"] for s in siblings_res if s.get("slug")]

    return {
        "cluster_id": cluster_id,
        "cluster_name": cluster_name,
        "entities": entities,
        "keywords": keywords,
        "dominant_intent": dominant_intent,
        "evidence_passages": evidence_passages,
        "sibling_pages": sibling_pages,
    }


def _majority_intent(keywords: List[Dict[str, Any]]) -> str:
    """Simple majority vote -- every keyword counts equally (no volume data)."""
    counts: Dict[str, int] = {}
    for kw in keywords:
        counts[kw["intent"]] = counts.get(kw["intent"], 0) + 1
    return max(counts, key=counts.get)


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("usage: python -m src.agents.context <cluster_id>")
        sys.exit(1)

    db = DatabaseManager()
    try:
        ctx = fetch_agent_context(sys.argv[1], db)
        print(f"\ncluster: {ctx['cluster_name']}  ({ctx['cluster_id']})")
        print(f"dominant intent: {ctx['dominant_intent']}")
        print(f"entities ({len(ctx['entities'])}): {ctx['entities']}")
        print(f"keywords: {len(ctx['keywords'])}")
        print(f"evidence passages: {len(ctx['evidence_passages'])}")
        print(f"sibling pages: {ctx['sibling_pages']}")
    finally:
        db.close()
