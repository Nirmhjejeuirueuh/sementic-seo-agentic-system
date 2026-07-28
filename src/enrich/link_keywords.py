import logging
from typing import List, Dict, Any
from src.db import DatabaseManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def link_keywords_pass1_string_match(db: DatabaseManager) -> int:
    """
    Pass 1: String Matching (Precise, low recall)
    Match Keyword.normalized or Keyword.name directly against Entity.name (case-insensitive).
    """
    logger.info("Executing Pass 1: String matching Keyword -> Entity...")

    cypher_pass1 = """
    MATCH (k:Keyword)
    MATCH (e:__Entity__)
    WHERE toLower(k.normalized) = toLower(e.name)
       OR toLower(k.name) = toLower(e.name)
       OR k.normalized CONTAINS toLower(e.name)
       OR toLower(e.name) CONTAINS k.normalized
    MERGE (k)-[r:ABOUT {method: 'string_match'}]->(e)
    RETURN count(r) AS links_created
    """

    res = db.execute_query(cypher_pass1)
    created = res[0]["links_created"] if res else 0
    logger.info(f"Pass 1 complete. Created {created} ABOUT relationships via string matching.")
    return created


def link_keywords_pass2_vector_chunks(db: DatabaseManager, top_k_chunks: int = 3, similarity_threshold: float = 0.60) -> int:
    """
    Pass 2: Vector similarity via nearest Chunks (Catches semantic queries)
    "Go through chunks rather than embedding entity names directly; an entity name alone carries little signal, the passage around it carries a lot."
    1. Query nearest Chunk vectors for each Keyword using vector index chunk_embedding_idx.
    2. Follow Chunk -[:FROM_CHUNK]- Entity (undirected match).
    3. Create (:Keyword)-[:ABOUT {method: 'vector_chunk'}]->(:__Entity__)
    """
    logger.info("Executing Pass 2: Vector similarity via nearest Chunks Keyword -> Chunk -> Entity...")

    # Get keywords without ABOUT edge or all keywords for semantic enrichment
    cypher_pass2 = """
    MATCH (k:Keyword)
    WHERE k.embedding IS NOT NULL
    CALL db.index.vector.queryNodes('chunk_embedding_idx', $top_k, k.embedding) 
    YIELD node AS chunk, score
    WHERE score >= $threshold
    MATCH (chunk)-[:FROM_CHUNK]-(e:__Entity__)
    MERGE (k)-[r:ABOUT {method: 'vector_chunk', similarity_score: score}]->(e)
    RETURN count(DISTINCT r) AS links_created
    """

    try:
        res = db.execute_query(cypher_pass2, {"top_k": top_k_chunks, "threshold": similarity_threshold})
        created = res[0]["links_created"] if res else 0
        logger.info(f"Pass 2 complete. Created/Verified {created} ABOUT relationships via vector chunk nearest neighbors.")
        return created
    except Exception as e:
        logger.warning(f"Pass 2 vector query warning: {e}. Executing fallback semantic join...")
        
        # Fallback join query if vector index is building or mock mode
        fallback_cypher = """
        MATCH (k:Keyword)
        MATCH (c:Chunk)-[:FROM_CHUNK]-(e:__Entity__)
        WHERE k.embedding IS NOT NULL AND c.embedding IS NOT NULL
        WITH k, e, gds.similarity.cosine(k.embedding, c.embedding) AS score
        WHERE score >= $threshold
        MERGE (k)-[r:ABOUT {method: 'vector_cosine', score: score}]->(e)
        RETURN count(DISTINCT r) AS links_created
        """
        try:
            res = db.execute_query(fallback_cypher, {"threshold": similarity_threshold})
            created = res[0]["links_created"] if res else 0
            logger.info(f"Fallback Pass 2 complete. Created {created} ABOUT relationships.")
            return created
        except Exception as ex:
            logger.error(f"Fallback Pass 2 failed: {ex}")
            return 0


def verify_link_coverage(db: DatabaseManager) -> Dict[str, Any]:
    """Verify percentage of keywords connected via ABOUT edge to Entities."""
    cypher_coverage = """
    MATCH (k:Keyword)
    WITH count(k) AS total_keywords
    OPTIONAL MATCH (k2:Keyword)-[:ABOUT]->(:__Entity__)
    WITH total_keywords, count(DISTINCT k2) AS linked_keywords
    RETURN 
        total_keywords, 
        linked_keywords, 
        CASE WHEN total_keywords > 0 THEN (toFloat(linked_keywords) / total_keywords) * 100 ELSE 0 END AS percentage_linked
    """
    res = db.execute_query(cypher_coverage)
    if res:
        stats = res[0]
        logger.info(f"Join Verification: {stats['linked_keywords']}/{stats['total_keywords']} ({stats['percentage_linked']:.2f}%) keywords linked via ABOUT edge.")
        return stats
    return {"total_keywords": 0, "linked_keywords": 0, "percentage_linked": 0}


def execute_the_join():
    db = DatabaseManager()
    link_keywords_pass1_string_match(db)
    link_keywords_pass2_vector_chunks(db)
    stats = verify_link_coverage(db)
    db.close()
    return stats


if __name__ == "__main__":
    execute_the_join()
