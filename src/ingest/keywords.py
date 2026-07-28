import csv
import argparse
import logging
from typing import List, Dict, Any
from src.config import normalize_keyword, SEARCH_INTENT_BUCKETS
from src.db import DatabaseManager, generate_embedding

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def classify_intent_rule_based(keyword: str, provided_intent: str = "") -> str:
    """Classify search intent into exactly one of the 4 buckets."""
    p_intent = provided_intent.lower().strip()
    if p_intent in SEARCH_INTENT_BUCKETS:
        return p_intent

    kw = keyword.lower()
    if any(term in kw for term in ["buy", "price", "pricing", "cost", "discount", "coupon", "order", "subscribe", "checkout"]):
        return "transactional"
    elif any(term in kw for term in ["best", "vs", "review", "comparison", "top", "software", "tool", "alternative", "platform"]):
        return "commercial"
    elif any(term in kw for term in ["login", "signin", "website", "contact", "official", "support", "portal", "download"]):
        return "navigational"
    else:
        return "informational"


def ingest_keywords(file_path: str, db: DatabaseManager):
    """
    Ingest CSV keyword export.
    Expected CSV columns: keyword, search_volume, intent, target_page (optional)
    Uses UNWIND batching to handle large files in seconds.
    """
    logger.info(f"Reading keyword CSV file: {file_path}")
    rows_to_insert = []

    try:
        with open(file_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                raw_kw = row.get("keyword", "") or row.get("Keyword", "")
                if not raw_kw:
                    continue

                normalized_kw = normalize_keyword(raw_kw)
                if not normalized_kw:
                    continue

                volume = int(row.get("search_volume") or row.get("volume") or row.get("Volume") or 0)
                raw_intent = row.get("intent") or row.get("Intent") or ""
                intent = classify_intent_rule_based(normalized_kw, raw_intent)
                target_page = row.get("target_page") or row.get("page") or row.get("Target Page") or ""

                embedding = generate_embedding(normalized_kw)

                rows_to_insert.append({
                    "raw_keyword": raw_kw,
                    "normalized": normalized_kw,
                    "search_volume": volume,
                    "intent": intent,
                    "target_page": target_page,
                    "embedding": embedding
                })

    except Exception as e:
        logger.error(f"Error reading CSV file {file_path}: {e}")
        return

    logger.info(f"Loaded {len(rows_to_insert)} keywords. Writing to Neo4j via UNWIND batching...")

    cypher_query = """
    UNWIND $rows AS row
    MERGE (k:Keyword {normalized: row.normalized})
    ON CREATE SET 
        k.name = row.raw_keyword,
        k.search_volume = row.search_volume,
        k.embedding = row.embedding,
        k.createdAt = timestamp()
    ON MATCH SET 
        k.search_volume = row.search_volume,
        k.embedding = row.embedding,
        k.updatedAt = timestamp()

    MERGE (i:Intent {name: row.intent})
    MERGE (k)-[:HAS_INTENT]->(i)

    WITH k, row
    WHERE row.target_page IS NOT NULL AND row.target_page <> ""
    MERGE (p:Page {url: row.target_page})
    MERGE (k)-[:TARGETS]->(p)
    """

    db.batch_write(cypher_query, rows_to_insert, batch_size=1000)
    logger.info("Keyword ingestion complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest Keyword CSV into Neo4j")
    parser.add_argument("--file", type=str, default="data/keywords.csv", help="Path to keywords CSV")
    args = parser.parse_args()

    db = DatabaseManager()
    ingest_keywords(args.file, db)
    db.close()
