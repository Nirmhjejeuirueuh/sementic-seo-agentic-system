"""
Phase 8 counterpart to scripts/sync_page_metadata.py: pushes page_type,
real internal links (LINKS_TO), and JSON-LD structured data from the
local graph/output files onto the matching remote Page nodes.

Same reasoning as sync_page_metadata.py applies here, more so:
page_type and LINKS_TO both live in Neo4j and could in principle be
recomputed by re-running the full ingest chain + linking.py against
remote directly -- but LINKS_TO's endpoints and json_ld are matched by
url, never by cluster_id, because GDS Louvain's internal community
numbering is not guaranteed to land on the same integers across two
independent runs on the same data (see clusters.py / the CHANGELOG
Phase 7 remote-sync entry). url is the stable, human-meaningful
identifier shared by both databases.

json_ld does not live in Neo4j at all -- persist_node
(src/agents/page_graph.py) only ever wrote it into each output/*.md
file's frontmatter. It's read from there, matched to its own Page by
slug (also written into that frontmatter), and pushed to remote as a
JSON string (Neo4j properties cannot hold arbitrary nested maps).

Local connection: normal NEO4J_URI/NEO4J_USERNAME/NEO4J_PASSWORD from
.env. Remote connection: REMOTE_NEO4J_URI/REMOTE_NEO4J_USERNAME/
REMOTE_NEO4J_PASSWORD from the environment, deliberately not .env, so
the remote password never needs to live in a file.

Prerequisite: remote must already have the same Page/Cluster/SHOULD_LINK_TO
structure as local -- i.e. the full ingest chain (vault -> keywords ->
link_keywords -> clusters -> site_structure -> route_orphans) and
`python -m src.analyze.linking` must already have been run against
REMOTE_NEO4J_URI. This script only pushes the agent-authored /
retrofit-authored fields on top of that structure.

Run:  python -m scripts.sync_phase8_metadata
"""

import json
import os
import re
import sys
from pathlib import Path

from src.db import DatabaseManager

OUTPUT_DIR = "output"
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n\n", re.DOTALL)


def load_json_ld_by_slug() -> dict:
    """slug -> json_ld dict, read straight from output/*.md frontmatter."""
    by_slug = {}
    for path in Path(OUTPUT_DIR).glob("*.md"):
        match = FRONTMATTER_RE.match(path.read_text(encoding="utf-8"))
        if not match:
            continue
        frontmatter = json.loads(match.group(1))
        slug = frontmatter.get("slug")
        json_ld = frontmatter.get("json_ld")
        if slug and json_ld is not None:
            by_slug[slug] = json_ld
    return by_slug


def main() -> None:
    remote_uri = os.getenv("REMOTE_NEO4J_URI")
    remote_user = os.getenv("REMOTE_NEO4J_USERNAME")
    remote_password = os.getenv("REMOTE_NEO4J_PASSWORD")
    if not (remote_uri and remote_user and remote_password):
        raise RuntimeError(
            "Set REMOTE_NEO4J_URI, REMOTE_NEO4J_USERNAME, REMOTE_NEO4J_PASSWORD "
            "in the environment before running this script."
        )

    # load_dotenv() (src/config.py) never overrides an already-set shell
    # env var. If an earlier command in this same terminal session
    # exported NEO4J_URI to the remote address (e.g. to run
    # `python -m src.analyze.linking` against remote), DatabaseManager()'s
    # "local" default below would silently resolve to remote too, turning
    # every MATCH/MERGE in this script into a no-op remote-to-remote sync
    # -- observed in practice: LINKS_TO push silently found and moved 0
    # rows. Fail loudly instead of guessing.
    local_uri = os.getenv("NEO4J_URI")
    if local_uri and local_uri.strip() == remote_uri.strip():
        raise RuntimeError(
            f"NEO4J_URI is currently {local_uri!r} in this shell -- the same "
            f"host REMOTE_NEO4J_URI points to. 'local_db' below would "
            f"silently connect to remote too. Run "
            f"`Remove-Item Env:\\NEO4J_URI, Env:\\NEO4J_USERNAME, "
            f"Env:\\NEO4J_PASSWORD -ErrorAction SilentlyContinue` (or open a "
            f"fresh terminal, where NEO4J_URI is unset and .env's local "
            f"value applies) before re-running."
        )

    local_db = DatabaseManager()  # local, from .env
    remote_db = DatabaseManager(uri=remote_uri, user=remote_user, password=remote_password)

    try:
        pages = local_db.execute_query(
            """
            MATCH (p:Page {draft_status: 'draft'})
            RETURN p.url AS url, p.slug AS slug, p.page_type AS page_type
            ORDER BY p.url
            """
        )
        if not pages:
            print("No locally-generated pages found (p.draft_status = 'draft'). Nothing to sync.")
            return

        json_ld_by_slug = load_json_ld_by_slug()
        for p in pages:
            p["json_ld"] = json.dumps(json_ld_by_slug.get(p["slug"])) if p["slug"] in json_ld_by_slug else None

        links = local_db.execute_query(
            """
            MATCH (p1:Page)-[r:LINKS_TO]->(p2:Page)
            RETURN p1.url AS from_url, p2.url AS to_url, r.anchor_text AS anchor_text
            """
        )

        print(f"Found {len(pages)} page(s) and {len(links)} LINKS_TO edge(s) locally. Syncing to remote...")

        page_result = remote_db.execute_query(
            """
            UNWIND $rows AS row
            MATCH (p:Page {url: row.url})
            SET p.page_type = row.page_type,
                p.json_ld = row.json_ld,
                p.updatedAt = timestamp()
            RETURN p.url AS url
            """,
            {"rows": pages},
        )
        matched_urls = {r["url"] for r in page_result}

        for row in pages:
            status = "OK" if row["url"] in matched_urls else "!! NOT FOUND ON REMOTE"
            print(f"  {status:<24} {row['url']}")

        missing = len(pages) - len(matched_urls)
        if missing:
            print(
                f"\n{missing} page(s) had no matching url on remote -- remote "
                f"site_structure.py likely needs re-running first."
            )

        if links:
            link_result = remote_db.execute_query(
                """
                UNWIND $rows AS row
                MATCH (p1:Page {url: row.from_url})
                MATCH (p2:Page {url: row.to_url})
                MERGE (p1)-[r:LINKS_TO]->(p2)
                SET r.anchor_text = row.anchor_text, r.createdAt = timestamp()
                RETURN p1.url AS from_url
                """,
                {"rows": links},
            )
            print(f"\n{len(link_result)}/{len(links)} LINKS_TO edge(s) synced to remote.")
        else:
            print(
                "\n0 LINKS_TO edges found in the local database to sync. "
                "If you expected some, check that this script's 'local' "
                "connection is really local (NEO4J_URI unset or pointing "
                "at localhost) -- see the guard above."
            )

        print(f"\nDone: {len(matched_urls)}/{len(pages)} page(s) synced.")

    finally:
        local_db.close()
        remote_db.close()


if __name__ == "__main__":
    sys.exit(main() or 0)
