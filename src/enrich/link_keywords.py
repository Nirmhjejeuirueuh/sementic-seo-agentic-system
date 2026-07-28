"""
"The join": (:Keyword)-[:ABOUT]->(:__Entity__)

This is the relationship the whole project exists for. Without it there
are two disconnected islands -- a keyword list, and a catalogue graph.

Rewritten from scratch. The previous version had two defects:

  1. It matched with `k.normalized CONTAINS toLower(e.name)`, so the
     entity "Pet" matched the keyword "carpet cleaning". Substring
     matching on short entity names produces large numbers of false
     positives.
  2. It wrote `MERGE (k)-[r:ABOUT {method:..., similarity_score: score}]->(e)`.
     Because MERGE matches on the *whole* pattern including properties,
     and score is a float that shifts slightly between runs, every run
     created a brand-new duplicate relationship.

Both are fixed here: pass 1 matches on whole words only, and no pass
puts a score inside a MERGE pattern.

Two passes, in order of precision:

  Pass 1  exact / whole-phrase match, computed in Python where the
          matching rules are testable. High precision.
  Pass 2  vector similarity via nearest chunks. Catches keywords that
          share no words with the entity name at all. Lower precision,
          so it never overwrites a pass-1 match.

ABOUT is a derived relationship -- it is deleted and recomputed on every
run, so a rule change never leaves stale edges behind.

Run:  python -m src.enrich.link_keywords
"""

import argparse
import logging
import re
from typing import Any, Dict, List

from src.db import DatabaseManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s %(message)s")
logger = logging.getLogger(__name__)

# Aliases shorter than this are too generic to match safely on.
MIN_ALIAS_LEN = 3


def entity_aliases(name: str) -> List[str]:
    """
    Surface forms a keyword might plausibly use for this entity.

    The catalogue uses compound titles that no one types into Google, so
    the parts have to be matchable individually:

        "Memorial / Loss"        -> memorial / loss, memorial, loss
        "Events (general)"       -> events (general), events
        "Trophy / Award"         -> trophy / award, trophy, award
        "Profession / Occupational" -> ..., profession, occupational
    """
    raw = name.lower().strip()
    aliases = {raw}

    without_parens = re.sub(r"\([^)]*\)", "", raw).strip()
    if without_parens:
        aliases.add(without_parens)

    for part in re.split(r"[/,]", without_parens or raw):
        part = part.strip()
        if len(part) >= MIN_ALIAS_LEN:
            aliases.add(part)

    return sorted(a for a in aliases if len(a) >= MIN_ALIAS_LEN)


def alias_pattern(alias: str) -> re.Pattern:
    """
    Whole-word match, tolerating a simple plural.

    `\\b` is what stops "Pet" matching "carpet". The optional (s|es)
    lets the entity "Trophy / Award" match the keyword "corporate
    awards", which is the same concept written in the plural.
    """
    return re.compile(rf"\b{re.escape(alias)}(s|es)?\b")


def link_pass1_exact(db: DatabaseManager) -> int:
    """Whole-word / whole-phrase matching, computed in Python."""
    logger.info("Pass 1: whole-word matching keyword -> entity...")

    entities = db.execute_query(
        "MATCH (e:__Entity__) RETURN e.name AS name, e.type AS type, e.aliases AS aliases"
    )
    keywords = db.execute_query(
        "MATCH (k:Keyword) RETURN k.normalized AS normalized"
    )
    if not entities or not keywords:
        raise RuntimeError(
            f"Nothing to join: {len(entities)} entities, {len(keywords)} keywords. "
            f"Run the vault and keyword ingests first."
        )

    # Two sources of surface forms:
    #   - derived from the title      ("Memorial / Loss" -> memorial, loss)
    #   - hand-authored `aliases:`    (memorial -> sympathy, bereavement)
    # The second matters more than it looks. Nobody searches "sports
    # figurine"; they search "football figurine". Without aliases the
    # title is the only thing we can match on, and the join misses every
    # keyword that uses the customer's word instead of the catalogue's.
    compiled = []
    for e in entities:
        forms = set(entity_aliases(e["name"]))
        for extra in (e.get("aliases") or []):
            cleaned = str(extra).strip().lower()
            if len(cleaned) >= MIN_ALIAS_LEN:
                forms.add(cleaned)
        for alias in sorted(forms):
            compiled.append((e["name"], alias, alias_pattern(alias)))

    rows: List[Dict[str, Any]] = []
    seen = set()
    for kw in keywords:
        normalized = kw["normalized"]
        for entity_name, alias, pattern in compiled:
            if pattern.search(normalized):
                pair = (normalized, entity_name)
                if pair in seen:
                    continue
                seen.add(pair)
                rows.append({
                    "keyword": normalized,
                    "entity": entity_name,
                    "matched_on": alias,
                    "exact": normalized == entity_name.lower(),
                })

    if not rows:
        logger.warning("Pass 1 matched nothing.")
        return 0

    db.batch_write(
        """
        UNWIND $rows AS row
        MATCH (k:Keyword {normalized: row.keyword})
        MATCH (e:__Entity__ {name: row.entity})
        MERGE (k)-[r:ABOUT]->(e)
        SET r.method = CASE WHEN row.exact THEN 'exact' ELSE 'phrase' END,
            r.matched_on = row.matched_on
        """,
        rows,
    )
    logger.info("Pass 1 complete: %d ABOUT relationships.", len(rows))
    return len(rows)


def link_pass2_vector(
    db: DatabaseManager, top_k: int = 1, threshold: float = 0.87
) -> int:
    """
    Vector similarity: keyword -> nearest chunk -> the entity it describes.

    OFF BY DEFAULT. Enable with --vector.

    Why it is off, measured on this dataset (2026-07-28, 147 keywords,
    82 entities, bge-small-en-v1.5):

        score range across all keyword-chunk pairs   0.756 - 0.894
        precision of the additions it makes          ~1 correct in 14

    Sample of what it produced at threshold 0.87, restricted to keywords
    pass 1 had already missed:

        0.8936  custom portrait figurine  -> Bronze / Sculpture Finish   wrong
        0.8785  custom gifts              -> Him                         wrong
        0.8782  buy custom figurine       -> Bronze / Sculpture Finish   wrong
        0.8759  custom gift               -> Coach                       wrong
        0.8778  create figurine from photo-> Turn Your Photo Into a ...   right

    The cause is structural, not a tuning problem. Every note in this
    vault is about custom figurines, so the embeddings sit in one tight
    cluster and the score band is compressed into a 0.14-wide window.
    Worse, the keywords pass 1 misses are precisely the generic head
    terms -- "custom figurine", "personalised gift", "buy custom
    figurine" -- which are genuinely equidistant from every entity
    because they describe the whole catalogue rather than any part of
    it. Nearest-neighbour search still has to return something, so it
    returns an arbitrary something.

    Turning the threshold up does not fix this: the wrong matches score
    *higher* than the right one in the sample above.

    Left in place because it becomes useful the moment the graph holds
    genuinely distinct topics (a pricing page, a shipping FAQ, a
    materials guide) rather than 82 variations on one subject.

    `ON CREATE` means a pass-1 match is never downgraded, and only
    keywords with no ABOUT edge at all are considered, so enabling this
    can never corrupt a pass-1 result.
    """
    logger.info(
        "Pass 2: vector similarity, unmatched keywords only (top_k=%d, threshold=%.2f)...",
        top_k, threshold,
    )

    result = db.execute_query(
        """
        MATCH (k:Keyword)
        WHERE k.embedding IS NOT NULL
          AND NOT (k)-[:ABOUT]->(:__Entity__)
        CALL (k) {
            CALL db.index.vector.queryNodes('chunk_embedding_idx', $top_k, k.embedding)
            YIELD node AS chunk, score
            WITH chunk, score
            WHERE score >= $threshold
            MATCH (chunk)-[:FROM_CHUNK]-(e:__Entity__)
            RETURN e AS entity, score AS s
        }
        MERGE (k)-[r:ABOUT]->(entity)
            ON CREATE SET r.method = 'vector', r.score = s
        RETURN count(*) AS touched
        """,
        {"top_k": top_k, "threshold": threshold},
    )
    touched = result[0]["touched"] if result else 0
    logger.info("Pass 2 complete: %d relationships added.", touched)
    return touched


def coverage_report(db: DatabaseManager) -> Dict[str, Any]:
    """How much of the keyword list actually reached the catalogue."""
    stats = db.execute_query(
        """
        MATCH (k:Keyword)
        WITH count(k) AS total
        MATCH (k2:Keyword)
        WHERE (k2)-[:ABOUT]->(:__Entity__)
        RETURN total, count(k2) AS linked
        """
    )[0]

    total, linked = stats["total"], stats["linked"]
    pct = (linked / total * 100) if total else 0.0

    print("\n" + "=" * 62)
    print("THE JOIN -- keyword to entity coverage")
    print("=" * 62)
    print(f"  {linked}/{total} keywords linked  ({pct:.1f}%)")

    print("\n  by method:")
    for r in db.execute_query(
        "MATCH (:Keyword)-[r:ABOUT]->(:__Entity__) "
        "RETURN r.method AS method, count(*) AS n ORDER BY n DESC"
    ):
        print(f"    {r['method']:<10} {r['n']}")

    unlinked = db.execute_query(
        """
        MATCH (k:Keyword)
        WHERE NOT (k)-[:ABOUT]->(:__Entity__)
        RETURN k.normalized AS keyword, k.categories AS categories
        ORDER BY keyword
        """
    )
    print(f"\n  UNLINKED ({len(unlinked)}) -- these are your content gaps:")
    for u in unlinked:
        cats = ", ".join(u["categories"] or [])
        print(f"    {u['keyword']:<42} [{cats}]")
    print()

    return {"total": total, "linked": linked, "percentage": pct, "unlinked": unlinked}


def execute_the_join(
    use_vector: bool = False, threshold: float = 0.87, top_k: int = 1
) -> Dict[str, Any]:
    db = DatabaseManager()
    try:
        # ABOUT is derived. Recompute it from scratch so a rule change
        # can never leave a stale edge behind.
        db.execute_query("MATCH (:Keyword)-[r:ABOUT]->(:__Entity__) DELETE r")
        logger.info("Cleared previous ABOUT relationships (they are recomputed).")

        link_pass1_exact(db)
        if use_vector:
            link_pass2_vector(db, top_k=top_k, threshold=threshold)
        else:
            logger.info("Pass 2 (vector) skipped -- pass --vector to enable. "
                        "See the docstring for why it is off by default.")
        return coverage_report(db)
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the Keyword -> Entity join")
    parser.add_argument("--vector", action="store_true",
                        help="also run the vector pass (low precision on this dataset)")
    parser.add_argument("--threshold", type=float, default=0.87,
                        help="minimum vector similarity for pass 2")
    parser.add_argument("--top-k", type=int, default=1,
                        help="how many nearest chunks to consider per keyword")
    args = parser.parse_args()
    execute_the_join(use_vector=args.vector, threshold=args.threshold, top_k=args.top_k)
