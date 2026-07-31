"""
Phase 8 retrofit: patch the 32 already-generated output/*.md pages with
real internal links (SHOULD_LINK_TO, src/analyze/linking.py) and JSON-LD
structured data (src/analyze/structured_data.py), without re-running the
page-writing agent.

Only frontmatter is rewritten -- the draft body (everything after the
second `---`) is never touched. That's deliberate: this is a
links/schema patch, not a content regeneration, so it costs zero LLM
calls and is safe to re-run any number of times (SHOULD_LINK_TO/LINKS_TO
are MERGE'd, and rewriting the same frontmatter twice is a no-op).

Any *future* fresh page (python -m src.agents.page_graph) already gets
both of these automatically -- see plan_links_node and persist_node in
src/agents/page_graph.py. This script exists only to backfill the pages
generated before Phase 8 existed.

Run:  python -m scripts.apply_internal_links_and_schema
"""

import json
import re
from pathlib import Path

from src.agents.context import fetch_agent_context
from src.analyze.linking import propose_anchor_links
from src.analyze.structured_data import build_json_ld, extract_price
from src.db import DatabaseManager

OUTPUT_DIR = "output"
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n\n(.*)\Z", re.DOTALL)


def parse_page(path: Path):
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(
            f"{path}: does not match the expected "
            f"'---\\nJSON\\n---\\n\\nbody' format written by persist_node."
        )
    frontmatter = json.loads(match.group(1))
    body = match.group(2)
    return frontmatter, body


def process_file(path: Path, db: DatabaseManager) -> str:
    frontmatter, body = parse_page(path)
    cluster_id = frontmatter["cluster_id"]

    page_row = db.execute_query(
        "MATCH (p:Page)-[:COVERS]->(:Cluster {id: $cluster_id}) "
        "RETURN p.url AS url, p.page_type AS page_type",
        {"cluster_id": cluster_id},
    )
    if not page_row:
        return f"!! SKIPPED -- no Page covers cluster {cluster_id!r}"
    url = page_row[0]["url"]
    page_type = page_row[0]["page_type"]

    ctx = fetch_agent_context(cluster_id, db)
    links = propose_anchor_links(cluster_id, body, db)

    # Same rule as persist_node: a price only ever comes from a real
    # "$NNN" found in this cluster's own evidence text (CLAUDE.md rule 9).
    price = None
    if page_type == "product":
        evidence_text = "\n".join(p.get("passage", "") for p in ctx["evidence_passages"])
        price = extract_price(evidence_text)

    json_ld = build_json_ld(
        page_type=page_type,
        title=frontmatter.get("title") or frontmatter.get("slug"),
        meta_description=frontmatter.get("meta_description", ""),
        url=url,
        primary_keyword=frontmatter.get("primary_keyword", ""),
        entities=ctx["entities"][:8],
        price=price,
    )

    frontmatter["page_type"] = page_type
    frontmatter["internal_links"] = links
    frontmatter["json_ld"] = json_ld

    path.write_text(f"---\n{json.dumps(frontmatter, indent=2)}\n---\n\n{body}", encoding="utf-8")

    # Mirror the same LINKS_TO edges persist_node writes on a fresh
    # generation (page_graph.py:394-398) -- identical Cypher shape.
    db.execute_query(
        """
        MATCH (p:Page)-[:COVERS]->(:Cluster {id: $cluster_id})
        WITH p
        UNWIND $links AS link
        MERGE (p2:Page {slug: link.target_slug})
        MERGE (p)-[r:LINKS_TO]->(p2)
        SET r.anchor_text = link.anchor_text, r.createdAt = timestamp()
        """,
        {"cluster_id": cluster_id, "links": links},
    )

    summary = f"{len(links)} link(s), page_type={page_type}"
    if price:
        summary += f", price={price}"
    return summary


def main() -> None:
    db = DatabaseManager()
    try:
        files = sorted(Path(OUTPUT_DIR).glob("*.md"))
        if not files:
            print(f"No .md files found in {OUTPUT_DIR}/. Nothing to do.")
            return

        print("\n" + "=" * 72)
        print("PHASE 8 -- RETROFIT LINKS + STRUCTURED DATA")
        print("=" * 72)
        print(f"\n  {len(files)} page(s) found\n")

        total_links = 0
        for path in files:
            try:
                status = process_file(path, db)
                if status.startswith(tuple("0123456789")):
                    total_links += int(status.split(" ", 1)[0])
            except Exception as exc:
                status = f"!! ERROR: {exc}"
            print(f"  {path.name:<45} {status}")

        print(f"\n  {total_links} total internal link(s) proposed across {len(files)} page(s)\n")
    finally:
        db.close()


if __name__ == "__main__":
    main()
