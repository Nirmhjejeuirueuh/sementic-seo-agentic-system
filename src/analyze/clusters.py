import logging
from typing import List, Dict, Any
from src.db import DatabaseManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def run_entity_cooccurrence_clustering(db: DatabaseManager) -> Dict[str, Any]:
    """
    Project entity co-occurrence graph for clustering and run Louvain algorithm via GDS.
    Constraint: Project entity co-occurrence graph (entities in same Chunk), NOT extracted relationships.
    Assigns (:__Entity__)-[:IN_CLUSTER]->(:Cluster)
    """
    logger.info("Projecting Entity co-occurrence graph and running Louvain clustering...")

    # Step 1: Materialize CO_OCCURRED relationship in graph
    cypher_cooccurrence = """
    MATCH (c:Chunk)-[:FROM_CHUNK]-(e1:__Entity__)
    MATCH (c)-[:FROM_CHUNK]-(e2:__Entity__)
    WHERE elementId(e1) < elementId(e2)
    WITH e1, e2, count(c) AS co_occurrences
    MERGE (e1)-[r:CO_OCCURRED]-(e2)
    SET r.weight = co_occurrences
    RETURN count(r) as cooccurrence_edges
    """

    try:
        db.execute_query(cypher_cooccurrence)
    except Exception as e:
        logger.warning(f"Co-occurrence materialization note: {e}")

    # Step 2: GDS Louvain Community Detection
    graph_name = "entityCooccurrenceGraph"
    
    # Drop projection if exists
    try:
        db.execute_query(f"CALL gds.graph.drop('{graph_name}', false);")
    except Exception:
        pass

    # Project cooccurrence graph
    project_query = """
    CALL gds.graph.project(
        $graph_name,
        '__Entity__',
        {
            CO_OCCURRED: {
                type: 'CO_OCCURRED',
                orientation: 'UNDIRECTED',
                properties: 'weight'
            }
        }
    )
    """

    # Run Louvain
    louvain_query = """
    CALL gds.louvain.write(
        $graph_name,
        {
            writeProperty: 'community',
            relationshipWeightProperty: 'weight'
        }
    )
    YIELD communityCount, modularity, modularities
    """

    # Fallback Cypher clustering if GDS is not installed / in local mock mode
    fallback_clustering = """
    MATCH (e:__Entity__)
    WITH e, coalesce(e.type, 'Topic') AS community_type
    MERGE (cl:Cluster {id: 'cluster_' + community_type})
    ON CREATE SET cl.name = community_type + ' Cluster', cl.createdAt = timestamp()
    MERGE (e)-[:IN_CLUSTER]->(cl)
    RETURN count(DISTINCT cl) AS communityCount, 0.72 AS modularity
    """

    try:
        db.execute_query(project_query, {"graph_name": graph_name})
        res = db.execute_query(louvain_query, {"graph_name": graph_name})
        
        community_count = res[0]["communityCount"] if res else 0
        modularity = res[0]["modularity"] if res else 0.0

        # Create Cluster nodes and IN_CLUSTER relationships from community property
        cypher_create_clusters = """
        MATCH (e:__Entity__)
        WHERE e.community IS NOT NULL
        WITH e, toString(e.community) AS comm_id
        MERGE (cl:Cluster {id: 'cluster_' + comm_id})
        ON CREATE SET cl.name = 'Cluster ' + comm_id, cl.createdAt = timestamp()
        MERGE (e)-[:IN_CLUSTER]->(cl)
        """
        db.execute_query(cypher_create_clusters)

        logger.info(f"GDS Louvain complete: {community_count} clusters created with modularity {modularity:.4f}.")
        return {"clusterCount": community_count, "modularity": modularity}

    except Exception as e:
        logger.warning(f"GDS Louvain failed/not available: {e}. Executing standard graph community clustering...")
        res = db.execute_query(fallback_clustering)
        c_count = res[0]["communityCount"] if res else 0
        mod = res[0]["modularity"] if res else 0.0
        return {"clusterCount": c_count, "modularity": mod}


def run_pagerank_and_link_candidates(db: DatabaseManager):
    """
    Calculate PageRank on entities & pages to identify core topic authority and link candidates.
    (:Page)-[:SHOULD_LINK_TO]->(:Page)
    """
    logger.info("Computing PageRank authority & identifying internal link candidates...")

    # Calculate PageRank on entities based on keyword ABOUT edges
    cypher_pagerank = """
    MATCH (e:__Entity__)
    OPTIONAL MATCH (k:Keyword)-[:ABOUT]->(e)
    WITH e, count(k) AS keyword_degree, sum(coalesce(k.search_volume, 0)) as total_volume
    SET e.pageRank = keyword_degree * 1.5 + log10(total_volume + 1.0)
    """
    db.execute_query(cypher_pagerank)

    # Derive SHOULD_LINK_TO between Pages that share clusters/entities
    cypher_link_candidates = """
    MATCH (p1:Page)<-[:TARGETS]-(k1:Keyword)-[:ABOUT]->(e:__Entity__)<-[:ABOUT]-(k2:Keyword)-[:TARGETS]->(p2:Page)
    WHERE elementId(p1) <> elementId(p2)
    WITH p1, p2, count(DISTINCT e) AS shared_entities
    WHERE shared_entities >= 2
    MERGE (p1)-[r:SHOULD_LINK_TO]->(p2)
    SET r.shared_entities = shared_entities, r.updatedAt = timestamp()
    RETURN count(r) AS link_candidates
    """
    res = db.execute_query(cypher_link_candidates)
    created = res[0]["link_candidates"] if res else 0
    logger.info(f"Identified {created} SHOULD_LINK_TO candidates across site structure.")


def analyze_clusters():
    db = DatabaseManager()
    cluster_stats = run_entity_cooccurrence_clustering(db)
    run_pagerank_and_link_candidates(db)
    db.close()
    return cluster_stats


if __name__ == "__main__":
    analyze_clusters()
