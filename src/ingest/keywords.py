"""
	Turn the CSV into (Keyword) nodes + assign intent

Keyword loader: reads data/keywords.csv and writes (:Keyword) nodes,
each classified into exactly one (:Intent) bucket.

Rewritten from scratch. The previous version imported `generate_embedding`
from src.db -- a function that no longer exists (it was the SHA-256 fake
embedding removed in Phase 0), so the module could not even be imported.
It also embedded one row at a time inside a Python loop.

This version follows the same shape as src/ingest/vault.py:
build rows in Python -> validate -> embed once in bulk -> batch write.
No LLM calls. Nothing is invented: the source CSV carries a keyword and
the category heading it appeared under, and that is all we claim to know.

Note on search volume: the supplied keyword list has no volume figures,
so no volume is stored. A fabricated number would be worse than none
(CLAUDE.md rule 9) -- downstream ranking must not silently trust a
made-up field.

Run:  python -m src.ingest.keywords --file data/keywords.csv
"""

import argparse
import csv
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

from src.config import SEARCH_INTENT_BUCKETS, normalize_keyword
from src.db import DatabaseManager, embed_texts

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# INTENT CLASSIFICATION -- rules, not an LLM.
#
# The supplied keyword list is already grouped by the author's own sense
# of intent ("High-Intent (Sales)", "Commercial Intent", "SEO Blog"...).
# That grouping is better evidence than anything we could re-derive, so
# the category is the primary signal and word patterns only break ties
# within an ambiguous category.
#
# Deterministic, free, and identical on every re-run.
# ---------------------------------------------------------------------

# Every category in the supplied list, mapped to its intent.
#
# Most headings describe product discovery -- someone searching "pet
# figurine" or "corporate awards" wants to find and buy that product, so
# these are transactional. "commercial" is reserved for genuine
# comparison/research language ("best X", "X vs Y", "figurine maker"),
# which the word rules below catch regardless of category.
CATEGORY_INTENT: Dict[str, str] = {
    "Commercial Intent": "commercial",
    "SEO Blog": "informational",
    "Seed (Google Ads)": "transactional",
    "High-Intent (Sales)": "transactional",
    "Long-Tail": "transactional",
    "Gift": "transactional",
    "Corporate": "transactional",
    "Hobby & Profession": "transactional",
    "Memorial - Primary": "transactional",
    "Memorial - Photo-Based": "transactional",
    "Memorial - Human": "transactional",
    "Memorial - Pet": "transactional",
    "Memorial - Long-Tail": "transactional",
}

# Word patterns, checked in order. Only consulted when the category alone
# does not settle it.
TRANSACTIONAL_TERMS = (
    "buy", "order", "shop", "online", "price", "pricing", "cost",
    "cheap", "discount", "checkout", "create", "make",
)
COMMERCIAL_TERMS = (
    "best", "top", " vs ", "compare", "comparison", "alternative",
    "review", "maker", "company", "ideas",
)
NAVIGATIONAL_TERMS = ("login", "sign in", "contact", "official", "near me")


def classify_intent(normalized: str, category: str) -> str:
    """
    Return exactly one of SEARCH_INTENT_BUCKETS.

    Order matters: an explicit buying verb beats the category heading,
    because "buy memorial figurine" is transactional no matter which
    section of the document it was listed under.
    """
    padded = f" {normalized} "

    if any(t in padded for t in NAVIGATIONAL_TERMS):
        return "navigational"

    # An explicit purchase verb overrides the category heading:
    # "buy memorial figurine" is transactional wherever it was listed.
    if any(f" {t} " in padded for t in TRANSACTIONAL_TERMS):
        return "transactional"

    # Comparison / research language likewise overrides the heading.
    if any(t in padded for t in COMMERCIAL_TERMS):
        return "commercial"

    if category in CATEGORY_INTENT:
        return CATEGORY_INTENT[category]

    # Only reached by a category heading added to the CSV later without
    # being mapped above. Mid-funnel is the least wrong default.
    logger.warning("Unmapped category %r -- defaulting to commercial.", category)
    return "commercial"


# ---------------------------------------------------------------------
# LOAD
# ---------------------------------------------------------------------

def load_keyword_csv(file_path: str) -> List[Dict[str, Any]]:
    """
    Read the CSV and collapse duplicate keywords.

    The same keyword legitimately appears under several headings (e.g.
    "personalised figurine" is both a High-Intent and a Seed keyword).
    Those are not errors: we keep every category it appeared under rather
    than letting the last row silently overwrite the first.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Keyword CSV not found: {file_path}")

    by_normalized: Dict[str, Dict[str, Any]] = {}
    categories: Dict[str, List[str]] = defaultdict(list)
    raw_row_count = 0
    skipped = 0

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if "keyword" not in (reader.fieldnames or []):
            raise ValueError(
                f"{file_path} has no 'keyword' column. Found: {reader.fieldnames}"
            )

        for row in reader:
            raw_row_count += 1
            raw = (row.get("keyword") or "").strip()
            normalized = normalize_keyword(raw)
            if not normalized:
                skipped += 1
                continue

            category = (row.get("category") or "").strip() or "Uncategorised"
            if category not in categories[normalized]:
                categories[normalized].append(category)

            # First spelling wins as the display name; later duplicates
            # only contribute their category.
            if normalized not in by_normalized:
                by_normalized[normalized] = {"name": raw, "normalized": normalized}

    rows = []
    for normalized, base in by_normalized.items():
        cats = categories[normalized]
        rows.append({
            **base,
            "categories": cats,
            "intent": classify_intent(normalized, cats[0]),
        })

    logger.info(
        "Read %d CSV rows -> %d unique keywords (%d duplicate spellings collapsed%s).",
        raw_row_count,
        len(rows),
        raw_row_count - len(rows) - skipped,
        f", {skipped} blank skipped" if skipped else "",
    )
    return rows


def ingest_keywords(file_path: str, db: DatabaseManager) -> None:
    rows = load_keyword_csv(file_path)
    if not rows:
        raise RuntimeError(f"No usable keywords found in {file_path}.")

    # Validate before writing: an intent outside the four buckets would
    # create junk Intent nodes that every downstream query then has to
    # defend against.
    bad = [r for r in rows if r["intent"] not in SEARCH_INTENT_BUCKETS]
    if bad:
        raise ValueError(
            f"{len(bad)} keyword(s) classified outside SEARCH_INTENT_BUCKETS "
            f"({SEARCH_INTENT_BUCKETS}): {[r['normalized'] for r in bad][:5]}"
        )

    logger.info("Embedding %d keywords...", len(rows))
    vectors = embed_texts([r["normalized"] for r in rows])
    for row, vec in zip(rows, vectors):
        row["embedding"] = vec

    logger.info("Writing %d keywords...", len(rows))
    db.batch_write(
        """
        UNWIND $rows AS row
        MERGE (k:Keyword {normalized: row.normalized})
        SET k.name = row.name,
            k.categories = row.categories,
            k.embedding = row.embedding,
            k.updatedAt = timestamp()

        // Drop any previous intent edge before attaching the current one.
        // Without this, re-running after a rule change leaves the old
        // edge in place and the keyword ends up with two intents -- the
        // graph then quietly disagrees with itself and every count that
        // groups by intent is inflated.
        WITH k, row
        OPTIONAL MATCH (k)-[stale:HAS_INTENT]->(:Intent)
        DELETE stale

        WITH k, row
        MERGE (i:Intent {name: row.intent})
        MERGE (k)-[:HAS_INTENT]->(i)
        """,
        rows,
    )

    breakdown: Dict[str, int] = defaultdict(int)
    for r in rows:
        breakdown[r["intent"]] += 1
    logger.info(
        "Keyword ingestion complete: %d keywords. Intent split: %s",
        len(rows),
        ", ".join(f"{k} {v}" for k, v in sorted(breakdown.items(), key=lambda x: -x[1])),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest the keyword CSV into Neo4j")
    parser.add_argument("--file", type=str, default="data/keywords.csv")
    args = parser.parse_args()

    db = DatabaseManager()
    try:
        ingest_keywords(args.file, db)
    finally:
        db.close()
