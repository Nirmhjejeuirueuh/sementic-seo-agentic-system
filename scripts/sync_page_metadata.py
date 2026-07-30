"""
One-off: copy generated-page metadata (title, draft_status, coverage_score)
from the local Neo4j graph onto the matching Page nodes on the remote
DigitalOcean instance.

Local and remote are two separate live databases (see CLAUDE.md, "Where
the database runs") -- nothing pushes automatically between them. The
full ingest chain (vault/keywords/link_keywords/clusters/site_structure/
route_orphans) rebuilds the remote graph structure from scratch when run
against the remote NEO4J_URI. It does NOT carry over what page_graph.py
wrote during agent generation, because that only ever runs against
whichever single database NEO4J_URI points to at the time. This script
is the second half of a sync: run the ingest chain against remote first,
then this.

Matched on p.url, not cluster_id -- cluster IDs come from GDS Louvain's
internal community numbering and are not guaranteed to land on the same
integers across two separate runs, even on identical input data. url is
the stable, human-meaningful identifier shared by both databases.

Local connection uses the normal NEO4J_URI/NEO4J_USERNAME/NEO4J_PASSWORD
from .env. Remote connection uses REMOTE_NEO4J_URI/REMOTE_NEO4J_USERNAME/
REMOTE_NEO4J_PASSWORD, which must be set in the environment before running
this script -- they are deliberately not read from .env so the remote
password never needs to live in a file.
"""

import os
import sys

from src.db import DatabaseManager


def main() -> None:
    remote_uri = os.getenv("REMOTE_NEO4J_URI")
    remote_user = os.getenv("REMOTE_NEO4J_USERNAME")
    remote_password = os.getenv("REMOTE_NEO4J_PASSWORD")
    if not (remote_uri and remote_user and remote_password):
        raise RuntimeError(
            "Set REMOTE_NEO4J_URI, REMOTE_NEO4J_USERNAME, REMOTE_NEO4J_PASSWORD "
            "in the environment before running this script."
        )

    local_db = DatabaseManager()  # local, from .env
    remote_db = DatabaseManager(uri=remote_uri, user=remote_user, password=remote_password)

    try:
        local_pages = local_db.execute_query(
            """
            MATCH (p:Page {draft_status: 'draft'})
            RETURN p.url AS url, p.title AS title, p.coverage_score AS coverage_score
            ORDER BY p.url
            """
        )
        if not local_pages:
            print("No locally-generated pages found (p.draft_status = 'draft'). Nothing to sync.")
            return

        print(f"Found {len(local_pages)} locally-generated page(s). Syncing to remote...")

        result = remote_db.execute_query(
            """
            UNWIND $rows AS row
            MATCH (p:Page {url: row.url})
            SET p.title = row.title,
                p.draft_status = 'draft',
                p.coverage_score = row.coverage_score,
                p.updatedAt = timestamp()
            RETURN p.url AS url
            """,
            {"rows": local_pages},
        )
        matched_urls = {r["url"] for r in result}

        for row in local_pages:
            status = "OK" if row["url"] in matched_urls else "!! NOT FOUND ON REMOTE"
            print(f"  {status:<24} {row['url']}")

        missing = len(local_pages) - len(matched_urls)
        if missing:
            print(
                f"\n{missing} page(s) had no matching url on remote -- remote "
                f"site_structure.py likely needs re-running first, or the url "
                f"changed locally after the remote was last synced."
            )
        else:
            print(f"\nAll {len(local_pages)} page(s) synced successfully.")

    finally:
        local_db.close()
        remote_db.close()


if __name__ == "__main__":
    sys.exit(main() or 0)
