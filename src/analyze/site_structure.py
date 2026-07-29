"""
Phase 6.2 -- decide what kind of page each cluster should become.

Phase 6.1 grouped keyword demand into 30 clusters. This step answers,
for each one: what kind of page is this, does it already exist, and how
urgent is it?

The rules are the mentor's own, quoted from the brief:

    IF intent = transactional AND product entity exists  -> collection/product
    IF intent = informational AND question keywords exist -> blog
    IF keyword contains: vs / compare / alternative       -> comparison
    IF keyword contains: calculator / tool / generator    -> tool

They are implemented as written -- deterministic rules, no LLM. The
inputs (intent, entity type, keyword text) are all already in the graph
from Phases 5 and 6.1, so an LLM here would only add cost, latency and
non-determinism to a decision that is a lookup.

Two things this produces that the brief does not name explicitly, but
that fall out of the graph for free and are the actually useful part:

  ACTION   whether the page is already live, planned-but-not-built, or
           has no URL at all. A cluster with 49 keywords and no page is
           a very different task from one that just needs optimising.
  PRIORITY keyword count. It is the only demand signal available -- the
           supplied keyword list has no search volumes, and inventing
           them would be worse than not ranking at all (rule 9).

Writes (:Page)-[:COVERS]->(:Cluster). Pages that already exist are
matched by URL; clusters with no page get a `proposed` one with a
suggested slug.

Run:  python -m src.analyze.site_structure
"""

import logging
import re
from typing import Any, Dict, List

from src.db import DatabaseManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s %(message)s")
logger = logging.getLogger(__name__)


# Keyword text patterns, checked before intent. A single "vs" or
# "calculator" in the cluster changes what the page has to be,
# regardless of what the majority intent says.
COMPARISON_TERMS = (" vs ", "compare", "comparison", "alternative", "best", "top ")
TOOL_TERMS = ("calculator", "tool", "generator", "builder", "configurator")
QUESTION_TERMS = ("how ", "what ", "why ", "when ", "which ", "ideas", "guide")

# Entity types that describe a browsable group of products rather than a
# single item. These become collection pages.
COLLECTION_TYPES = {"Occasion", "FigurineType", "FigurineStyle", "Format", "Recipient"}


def decide_page_type(lead_type: str, dominant_intent: str, keywords: List[str]) -> str:
    """
    Apply the brief's rules, most specific first.

    Text patterns win over intent because they are stronger evidence:
    "best custom figurine" is a roundup no matter how it was classified.
    """
    blob = " " + " ".join(keywords) + " "

    if any(t in blob for t in TOOL_TERMS):
        return "tool"
    if any(t in blob for t in COMPARISON_TERMS):
        return "comparison"

    # Intent decides, not the presence of a single research-y word.
    #
    # This was originally `informational OR any question term`, and that
    # OR was wrong. The Wedding cluster is 5 transactional and 2
    # commercial with no informational keyword at all, but it contains
    # "wedding gift ideas" -- one word, "ideas", flipped a commercial
    # collection into a blog. The brief says "IF intent = informational
    # AND question keywords exist", so intent is the necessary condition.
    if dominant_intent == "informational":
        return "blog"
    if lead_type == "Product":
        return "product"
    if lead_type in COLLECTION_TYPES:
        return "collection"

    # Reached only if a new entity type is added to config.py without
    # being classified here. Say so rather than guessing.
    logger.warning("No page-type rule matched lead type %r -- defaulting to collection.", lead_type)
    return "collection"


def decide_action(url: str, status: str) -> str:
    """
    What actually has to be done about this page.

    'optimise' the page is live -- rewrite it against the cluster
    'build'    a URL is planned in the catalogue but not live yet
    'create'   no URL exists at all; the page and its slug are both new
    """
    if not url:
        return "create"
    return "optimise" if status == "existing" else "build"


def pick_head_term(keywords: List[str]) -> str:
    """
    The cluster's primary target keyword.

    Chooses the keyword that the most other keywords in the cluster
    contain -- the head term the long tail is built from. In the memorial
    cluster, "memorial figurine" appears inside 15 of the other 48
    keywords ("custom memorial figurine", "buy memorial figurine",
    "memorial figurine from photo"...), which is exactly the term the
    page should target.

    The obvious alternative, "pick the shortest", chose "grief gift" for
    that cluster -- a minor long-tail phrase contained in nothing else.
    Length is a proxy for breadth; containment measures it directly.

    Ties break toward the shorter phrase, which is the broader one.
    """
    if not keywords:
        return None
    return max(
        keywords,
        key=lambda k: (sum(1 for other in keywords if k in other and k != other), -len(k)),
    )


def slugify(name: str) -> str:
    """Suggested URL slug for a cluster that has no page yet."""
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-")


def build_site_structure(db: DatabaseManager) -> List[Dict[str, Any]]:
    clusters = db.execute_query(
        """
        MATCH (c:Cluster)
        MATCH (lead:__Entity__ {name: c.lead_entity})
        OPTIONAL MATCH (k:Keyword)-[:ABOUT]->(:__Entity__)-[:IN_CLUSTER]->(c)
        WITH c, lead, collect(DISTINCT k.normalized) AS keywords
        RETURN c.id AS cluster_id,
               c.name AS cluster_name,
               c.keyword_count AS keyword_count,
               c.dominant_intent AS dominant_intent,
               lead.type AS lead_type,
               lead.url AS url,
               lead.status AS status,
               keywords
        ORDER BY c.keyword_count DESC
        """
    )
    if not clusters:
        raise RuntimeError("No clusters found. Run python -m src.analyze.clusters first.")

    rows = []
    for c in clusters:
        page_type = decide_page_type(
            c["lead_type"], c["dominant_intent"], c["keywords"] or []
        )
        action = decide_action(c["url"], c["status"])

        # A cluster with no page needs a proposed URL. Collections and
        # blogs live under different prefixes on a normal storefront.
        url = c["url"]
        if not url:
            prefix = "/blog" if page_type == "blog" else "/collections"
            url = f"{prefix}/{slugify(c['cluster_name'])}"

        primary = pick_head_term(c["keywords"] or [])

        rows.append({
            "cluster_id": c["cluster_id"],
            "cluster_name": c["cluster_name"],
            "url": url,
            "slug": url.strip("/").split("/")[-1],
            "page_type": page_type,
            "action": action,
            "priority": c["keyword_count"],
            "dominant_intent": c["dominant_intent"],
            "primary_keyword": primary,
            "page_status": "existing" if action == "optimise" else "proposed",
        })

    db.batch_write(
        """
        UNWIND $rows AS row
        MERGE (p:Page {url: row.url})
        SET p.slug = row.slug,
            p.page_type = row.page_type,
            p.action = row.action,
            p.priority = row.priority,
            p.primary_keyword = row.primary_keyword,
            p.status = row.page_status,
            p.updatedAt = timestamp()
        WITH p, row
        MATCH (c:Cluster {id: row.cluster_id})
        MERGE (p)-[:COVERS]->(c)
        """,
        rows,
    )
    logger.info("Assigned a page type to %d clusters.", len(rows))
    return rows


def report(rows: List[Dict[str, Any]]) -> None:
    print("\n" + "=" * 78)
    print("PHASE 6.2 -- PROPOSED SITE STRUCTURE")
    print("=" * 78)

    by_type: Dict[str, int] = {}
    by_action: Dict[str, int] = {}
    for r in rows:
        by_type[r["page_type"]] = by_type.get(r["page_type"], 0) + 1
        by_action[r["action"]] = by_action.get(r["action"], 0) + 1

    print(f"\n  {len(rows)} pages planned")
    print("\n  by page type:")
    for t, n in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"    {t:<12} {n}")
    print("\n  by action:")
    for a, n in sorted(by_action.items(), key=lambda x: -x[1]):
        label = {"optimise": "page is live -- rewrite it",
                 "build": "URL planned, not built yet",
                 "create": "no URL at all -- new page"}[a]
        print(f"    {a:<10} {n:>3}   ({label})")

    print(f"\n  {'kw':>3}  {'type':<11} {'action':<9} {'primary keyword':<30} url")
    print(f"  {'-'*3}  {'-'*11} {'-'*9} {'-'*30} {'-'*30}")
    for r in rows:
        print(f"  {r['priority']:>3}  {r['page_type']:<11} {r['action']:<9} "
              f"{(r['primary_keyword'] or '-')[:30]:<30} {r['url']}")
    print()


def analyse_site_structure() -> List[Dict[str, Any]]:
    db = DatabaseManager()
    try:
        rows = build_site_structure(db)
        report(rows)
        return rows
    finally:
        db.close()


if __name__ == "__main__":
    analyse_site_structure()
