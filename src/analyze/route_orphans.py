"""
Phase 6.3 -- route keywords that belong to no single catalogue entity.

Phases 6.1-6.2 handled the 118 keywords that map to a specific product,
style, type, occasion, or format. The other 29 don't, and forcing them
into one of those clusters would be wrong -- "custom figurine" is not
more about "Pet" than it is about "Wedding". These are head terms: they
describe the whole business, not a slice of it, so they belong on
site-level pages (the homepage, a general blog hub) rather than on any
product/collection page.

Three groups, decided by rule, not guessed by an LLM -- the same
discipline as Phase 6.2:

  ROUNDUP    "best custom figurine", "unique gift ideas" -- research/
             comparison language. -> a blog page.
  SELLER     "custom figurine company", "buy custom figurine",
             "figurine maker" -- the person is looking for a business
             to buy from, not a specific product. -> the homepage,
             which is literally the answer to that search.
  GENERIC    "custom figurine", "custom statue", "personalised gift" --
             no material, occasion, or type specified at all. -> the
             homepage.

A fourth group is NOT routed to a page and is reported separately:
keywords that reveal a genuinely missing catalogue entity (a material or
a prop the vault has no note for). Silently sending "custom resin
figurine" to the homepage would hide that gap. CLAUDE.md rule 9 says not
to invent facts, so no Resin or Car entity is created here -- this only
flags that one should be considered, backed by real search demand.

Run:  python -m src.analyze.route_orphans
"""

import logging
from typing import Any, Dict, List

from src.db import DatabaseManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s %(message)s")
logger = logging.getLogger(__name__)

ROUNDUP_TERMS = ("best ", " ideas")
SELLER_TERMS = ("company", "shop", "maker", "online", "buy ", "order ", "create ")

# Terms that name something with no catalogue entity behind it. Checked
# before ROUNDUP/SELLER/GENERIC -- a missing material matters more than
# where the keyword would otherwise land.
GAP_TERMS = {
    "resin": "a FigurineStyle or material note for resin -- 3 keywords "
             "want it and the vault has none",
    "with car": "a prop/accessory concept (figurine posed with a car) -- "
                "no Accessory note covers this",
    "action figure": "the vault has no FigurineStyle for poseable/"
                      "action-figure-style pieces, distinct from static Realistic",
}

HOMEPAGE_URL = "/"
BLOG_HUB_URL = "/blog"


def classify_orphan(normalized: str) -> Dict[str, Any]:
    """Return {'route': 'homepage'|'blog'|None, 'gap': str|None}."""
    padded = f" {normalized} "

    for term, reason in GAP_TERMS.items():
        if term in padded:
            return {"route": None, "gap": reason, "gap_term": term}

    if any(t in padded for t in ROUNDUP_TERMS):
        return {"route": "blog", "gap": None, "gap_term": None}

    # SELLER and GENERIC both land on the homepage -- the distinction is
    # kept in `reason` for the report, not in the routing, because both
    # groups are answered by the same page today.
    if any(t in padded for t in SELLER_TERMS):
        return {"route": "homepage", "gap": None, "gap_term": None}

    return {"route": "homepage", "gap": None, "gap_term": None}


def route_orphans(db: DatabaseManager) -> Dict[str, Any]:
    orphans = db.execute_query(
        """
        MATCH (k:Keyword) WHERE NOT (k)-[:ABOUT]->(:__Entity__)
        MATCH (k)-[:HAS_INTENT]->(i:Intent)
        RETURN k.normalized AS kw, i.name AS intent
        """
    )
    if not orphans:
        logger.info("No orphan keywords -- every keyword reached an entity.")
        return {"routed": 0, "gaps": []}

    routed_rows: List[Dict[str, Any]] = []
    gap_rows: List[Dict[str, Any]] = []
    for o in orphans:
        result = classify_orphan(o["kw"])
        if result["gap"]:
            gap_rows.append({"keyword": o["kw"], "reason": result["gap"], "term": result["gap_term"]})
        else:
            routed_rows.append({
                "keyword": o["kw"],
                "url": HOMEPAGE_URL if result["route"] == "homepage" else BLOG_HUB_URL,
            })

    # Site-level pages. Homepage is assumed live (every real site has
    # one); the blog hub is proposed since none of the vault notes claim
    # one exists.
    db.execute_query(
        """
        MERGE (p:Page {url: $url})
        SET p.page_type = 'homepage', p.action = 'optimise', p.status = 'existing'
        """,
        {"url": HOMEPAGE_URL},
    )
    db.execute_query(
        """
        MERGE (p:Page {url: $url})
        SET p.page_type = 'blog', p.action = 'create', p.status = 'proposed'
        """,
        {"url": BLOG_HUB_URL},
    )

    if routed_rows:
        db.batch_write(
            """
            UNWIND $rows AS row
            MATCH (k:Keyword {normalized: row.keyword})
            MATCH (p:Page {url: row.url})
            MERGE (k)-[:TARGETS]->(p)
            """,
            routed_rows,
        )

    logger.info(
        "Routed %d orphan keywords to site-level pages; %d flagged as catalogue gaps.",
        len(routed_rows), len(gap_rows),
    )
    return {"routed": routed_rows, "gaps": gap_rows}


def report(result: Dict[str, Any]) -> None:
    routed = result["routed"]
    gaps = result["gaps"]

    print("\n" + "=" * 72)
    print("PHASE 6.3 -- ORPHAN KEYWORDS ROUTED TO SITE-LEVEL PAGES")
    print("=" * 72)

    by_url: Dict[str, List[str]] = {}
    for r in routed:
        by_url.setdefault(r["url"], []).append(r["keyword"])

    for url, kws in by_url.items():
        print(f"\n  {url}  ({len(kws)} keywords)")
        for k in sorted(kws):
            print(f"      {k}")

    print(f"\n  {len(gaps)} keyword(s) flagged as catalogue gaps -- NOT routed:")
    # Group by term explicitly rather than relying on list order -- two
    # keywords for the same gap are not guaranteed adjacent in `gaps`,
    # since it follows Neo4j's arbitrary query return order.
    by_term: Dict[str, Dict[str, Any]] = {}
    for g in gaps:
        by_term.setdefault(g["term"], {"reason": g["reason"], "keywords": []})
        by_term[g["term"]]["keywords"].append(g["keyword"])
    for term, info in by_term.items():
        print(f"\n    missing concept: {info['reason']}")
        for k in sorted(info["keywords"]):
            print(f"      {k}")
    print()


if __name__ == "__main__":
    db = DatabaseManager()
    try:
        result = route_orphans(db)
        report(result)
    finally:
        db.close()
