"""
Deterministic vault loader: reads Obsidian notes (frontmatter + prose)
from data/vault/ and writes them into Neo4j as typed entities, pages,
and chunks.

This is the "Route B" path from the project plan: catalogue and taxonomy
facts come from YAML frontmatter a human wrote by hand, not from an LLM
guessing at prose. Nothing here calls an LLM. If a fact isn't in the
frontmatter, it does not end up in the graph -- there is no fallback
that invents it (CLAUDE.md rule 9).

Two kinds of notes, distinguished by frontmatter `type`:
  - Product notes   (type: Product)
  - Taxonomy notes  (type: one of FigurineStyle, FigurineType, Occasion,
                      Format, Recipient, Accessory)

Run:  python -m src.ingest.vault --dir data/vault
"""

import argparse
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

from src.config import ALLOWED_NODE_LABELS, ALLOWED_RELATIONSHIPS
from src.db import DatabaseManager, embed_texts

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s %(message)s")
logger = logging.getLogger(__name__)

# Maps a Product frontmatter list field to the taxonomy entity type it
# points at, and the relationship used to connect them. Must stay in
# sync with VALID_TRIPLETS in src/config.py.
FIELD_TO_REL: Dict[str, Tuple[str, str]] = {
    "styles": ("FigurineStyle", "HAS_STYLE"),
    "types": ("FigurineType", "DEPICTS"),
    "occasions": ("Occasion", "FOR_OCCASION"),
    "formats": ("Format", "HAS_FORMAT"),
    "recipients": ("Recipient", "GIFT_FOR"),
    "accessories": ("Accessory", "PAIRS_WITH"),
}


def split_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """Split a note into (frontmatter dict, body prose)."""
    if not text.startswith("---"):
        raise ValueError("note has no YAML frontmatter (must start with '---')")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError("malformed frontmatter -- expected a closing '---'")
    _, fm_text, body = parts
    frontmatter = yaml.safe_load(fm_text) or {}
    return frontmatter, body.strip()


def load_vault(directory: str) -> List[Dict[str, Any]]:
    """
    Read every .md note under directory and parse it.

    One bad note must not stop the rest -- the same "catch per file, keep
    going" rule as document ingestion (CLAUDE.md rule 7).
    """
    # Files that live inside the vault but are not notes -- reference
    # material for the human, not data for the graph.
    NON_NOTE_FILES = {"readme.md", "products_todo.md"}

    notes = []
    skipped = 0
    for path in sorted(Path(directory).rglob("*.md")):
        if path.name.lower() in NON_NOTE_FILES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
            frontmatter, body = split_frontmatter(text)
            note_type = frontmatter.get("type")
            if note_type not in ALLOWED_NODE_LABELS:
                raise ValueError(
                    f"frontmatter 'type: {note_type}' is not in ALLOWED_NODE_LABELS "
                    f"({ALLOWED_NODE_LABELS})"
                )
            if not frontmatter.get("title"):
                raise ValueError("missing required 'title'")
            notes.append({"path": str(path), "frontmatter": frontmatter, "body": body})
        except Exception as e:
            logger.error("Skipping %s: %s", path, e)
            skipped += 1

    if skipped:
        logger.warning("%d note(s) skipped due to errors -- see above.", skipped)
    return notes


def ingest_vault(directory: str, db: DatabaseManager) -> None:
    notes = load_vault(directory)
    if not notes:
        raise RuntimeError(f"No usable notes found under {directory}.")
    logger.info("Parsed %d notes.", len(notes))

    entity_rows: List[Dict[str, Any]] = []
    page_rows: List[Dict[str, Any]] = []
    link_rows: List[Dict[str, Any]] = []
    chunk_rows: List[Dict[str, Any]] = []

    for note in notes:
        fm = note["frontmatter"]
        note_type = fm["type"]
        name = fm["title"]

        entity_rows.append({
            "name": name,
            "type": note_type,
            "status": fm.get("status", "existing"),
            "url": fm.get("url") or fm.get("collection_url"),
            "primary_keyword": fm.get("primary_keyword"),
            "keywords": fm.get("keywords") or [],
            "season": fm.get("season"),
            "caution": fm.get("caution"),
            "source_section": fm.get("source_section"),
        })

        url = fm.get("url") or fm.get("collection_url")
        if url:
            page_rows.append({
                "url": url,
                "slug": url.strip("/").split("/")[-1],
                "status": fm.get("status", "existing"),
            })

        if note_type == "Product":
            for field, (target_type, rel) in FIELD_TO_REL.items():
                for target_name in (fm.get(field) or []):
                    link_rows.append({
                        "source": name,
                        "target": target_name,
                        "target_type": target_type,
                        "rel": rel,
                        "note_path": note["path"],
                    })

        if note["body"]:
            chunk_rows.append({
                "doc_id": f"vault_{note_type}",
                "chunk_id": f"vault_{Path(note['path']).stem}",
                "text": note["body"],
                "entity_name": name,
            })

    # ------------------------------------------------------------------
    # VALIDATE before writing anything. A MATCH on a name that doesn't
    # exist doesn't error in Cypher -- it just silently matches zero
    # rows, and the relationship never gets created. That is exactly the
    # kind of silent failure CLAUDE.md rule 9 forbids, so we catch it
    # here in Python where a mismatch DOES raise.
    # ------------------------------------------------------------------
    known_names = {row["name"] for row in entity_rows}
    unresolved = [
        row for row in link_rows if row["target"] not in known_names
    ]
    if unresolved:
        lines = "\n".join(
            f"  - {r['note_path']}: \"{r['target']}\" ({r['target_type']}) "
            f"-- no taxonomy note with this exact title exists"
            for r in unresolved
        )
        raise ValueError(
            f"{len(unresolved)} taxonomy reference(s) do not match any "
            f"existing note title. Names must match character-for-"
            f"character (see data/vault/README.md).\n{lines}"
        )

    for row in link_rows:
        if row["rel"] not in ALLOWED_RELATIONSHIPS:
            raise ValueError(f"{row['rel']} is not in ALLOWED_RELATIONSHIPS")

    # ------------------------------------------------------------------
    # WRITE -- everything batched via UNWIND, nothing in a Python loop.
    # ------------------------------------------------------------------
    logger.info("Writing %d entities...", len(entity_rows))
    db.batch_write(
        """
        UNWIND $rows AS row
        MERGE (e:__Entity__ {name: row.name})
        SET e.type = row.type,
            e.status = row.status,
            e.url = row.url,
            e.primary_keyword = row.primary_keyword,
            e.keywords = row.keywords,
            e.season = row.season,
            e.caution = row.caution,
            e.source_section = row.source_section,
            e.updatedAt = timestamp()
        """,
        entity_rows,
    )

    if page_rows:
        logger.info("Writing %d pages...", len(page_rows))
        db.batch_write(
            """
            UNWIND $rows AS row
            MERGE (p:Page {url: row.url})
            SET p.slug = row.slug, p.status = row.status, p.updatedAt = timestamp()
            """,
            page_rows,
        )

    if link_rows:
        logger.info("Writing %d taxonomy links...", len(link_rows))
        # Relationship TYPE cannot be a query parameter in Cypher, so we
        # group by relationship and issue one UNWIND per type -- still a
        # handful of batched statements, not one write per row.
        by_rel: Dict[str, List[Dict[str, Any]]] = {}
        for row in link_rows:
            by_rel.setdefault(row["rel"], []).append(row)

        for rel, rows in by_rel.items():
            db.batch_write(
                f"""
                UNWIND $rows AS row
                MATCH (a:__Entity__ {{name: row.source}})
                MATCH (b:__Entity__ {{name: row.target}})
                MERGE (a)-[:{rel}]->(b)
                """,
                rows,
            )

    if chunk_rows:
        logger.info("Embedding %d note passages...", len(chunk_rows))
        vectors = embed_texts([r["text"] for r in chunk_rows])
        for row, vec in zip(chunk_rows, vectors):
            row["embedding"] = vec

        logger.info("Writing chunks...")
        db.batch_write(
            """
            UNWIND $rows AS row
            MERGE (d:Document {id: row.doc_id})
            ON CREATE SET d.filename = row.doc_id, d.updatedAt = timestamp()
            MERGE (c:Chunk {id: row.chunk_id})
            SET c.text = row.text, c.embedding = row.embedding
            MERGE (c)-[:FROM_DOCUMENT]->(d)
            WITH c, row
            MATCH (e:__Entity__ {name: row.entity_name})
            MERGE (c)-[:FROM_CHUNK]->(e)
            """,
            chunk_rows,
        )

    logger.info(
        "Vault ingestion complete: %d entities, %d pages, %d links, %d chunks.",
        len(entity_rows), len(page_rows), len(link_rows), len(chunk_rows),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest the Obsidian vault into Neo4j")
    parser.add_argument("--dir", type=str, default="data/vault", help="Path to the vault")
    args = parser.parse_args()

    db = DatabaseManager()
    try:
        ingest_vault(args.dir, db)
    finally:
        db.close()
