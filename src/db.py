"""
Neo4j connection, batched writes, schema management, and embeddings.

Two things in here are worth understanding before you read further:

1. BATCHED WRITES. Never write to Neo4j inside a Python for-loop. Every
   loop iteration is a separate network round-trip and a separate
   transaction. Send a list of rows once and let Cypher's UNWIND fan it
   out server-side. A 5,000-row keyword file goes from ~4 minutes to
   ~2 seconds. This is the single biggest performance rule in the project.

2. NO FAKE FALLBACKS. The previous version of this file, when no API key
   was present, generated "embeddings" from a SHA-256 hash. Those are not
   embeddings -- similarity between them is random noise. Vector search
   still returned rows, just meaningless ones, with no error anywhere.
   That code is gone. If embeddings cannot be produced, we raise.
"""

import os
import sys
import logging
from typing import List, Dict, Any, Optional

from neo4j import GraphDatabase, Driver

from src.config import (
    NEO4J_URI,
    NEO4J_USERNAME,
    NEO4J_PASSWORD,
    EMBEDDING_PROVIDER,
    EMBEDDING_MODEL,
    EMBEDDING_DIM,
    OPENAI_API_KEY,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s %(message)s")
logger = logging.getLogger(__name__)


# =====================================================================
# DATABASE
# =====================================================================

class DatabaseManager:
    def __init__(
        self,
        uri: str = NEO4J_URI,
        user: str = NEO4J_USERNAME,
        password: str = NEO4J_PASSWORD,
    ):
        self.uri = uri
        self.user = user
        self.password = password
        self._driver: Optional[Driver] = None

    def get_driver(self) -> Driver:
        if self._driver is None:
            self._driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
            try:
                self._driver.verify_connectivity()
            except Exception as e:
                raise RuntimeError(
                    f"Cannot reach Neo4j at {self.uri}.\n"
                    f"  - Is Docker Desktop running?\n"
                    f"  - Is the container up?  docker compose ps\n"
                    f"  - Do NEO4J_USERNAME / NEO4J_PASSWORD in .env match "
                    f"NEO4J_AUTH in docker-compose.yml?\n"
                    f"Underlying error: {e}"
                ) from e
        return self._driver

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def execute_query(
        self, query: str, parameters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Run one Cypher statement and return every row as a dict."""
        driver = self.get_driver()
        with driver.session() as session:
            result = session.run(query, parameters or {})
            return [record.data() for record in result]

    def batch_write(
        self, cypher: str, rows: List[Dict[str, Any]], batch_size: int = 1_000
    ) -> int:
        """
        Write many rows with a single `UNWIND $rows AS row` statement.

        `cypher` must start with UNWIND $rows AS row. We chunk into
        batches so one enormous transaction cannot exhaust heap.
        """
        if not rows:
            logger.warning("batch_write called with zero rows -- nothing to do.")
            return 0

        driver = self.get_driver()
        total = 0
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            with driver.session() as session:
                session.execute_write(lambda tx: tx.run(cypher, {"rows": batch}).consume())
            total += len(batch)
            logger.info("  written %d/%d rows", total, len(rows))
        return total

    # -----------------------------------------------------------------
    # SCHEMA
    # -----------------------------------------------------------------

    def init_schema(self, schema_file: str = "cypher/001_schema.cypher") -> None:
        """
        Execute the schema file, substituting the embedding dimension.

        The dimension cannot be a Cypher parameter -- `CREATE VECTOR INDEX`
        needs it as a literal. So the file contains the placeholder
        __EMBEDDING_DIM__ and we substitute it here. That keeps .env as
        the single source of truth and makes a mismatch impossible.
        """
        if not os.path.exists(schema_file):
            raise FileNotFoundError(f"Schema file not found: {schema_file}")

        with open(schema_file, "r", encoding="utf-8") as f:
            content = f.read()

        content = content.replace("__EMBEDDING_DIM__", str(EMBEDDING_DIM))

        # Strip comment lines before splitting, so a ';' inside a comment
        # cannot break a statement in half.
        lines = [ln for ln in content.splitlines() if not ln.strip().startswith("//")]
        cleaned = "\n".join(lines)

        statements = [s.strip() for s in cleaned.split(";") if s.strip()]

        logger.info(
            "Applying %d schema statements (embedding dim = %d, provider = %s)",
            len(statements), EMBEDDING_DIM, EMBEDDING_PROVIDER,
        )

        driver = self.get_driver()
        failures = []
        with driver.session() as session:
            for stmt in statements:
                first_line = stmt.splitlines()[0][:70]
                try:
                    session.run(stmt)
                    logger.info("  OK   %s", first_line)
                except Exception as e:
                    # We collect and re-raise at the end rather than
                    # swallowing. The old code logged a warning and moved
                    # on, so a failed vector index looked like success.
                    logger.error("  FAIL %s\n       %s", first_line, e)
                    failures.append((first_line, str(e)))

        if failures:
            raise RuntimeError(
                f"{len(failures)} schema statement(s) failed. "
                f"The schema is NOT correctly applied. See errors above."
            )

        logger.info("Schema applied cleanly.")

    def verify(self) -> bool:
        """
        The definition of done for Phase 0.

        Prints constraints, indexes and the GDS version. Returns True only
        if everything the pipeline depends on is actually present.
        """
        ok = True

        print("\n" + "=" * 66)
        print("CONSTRAINTS")
        print("=" * 66)
        constraints = self.execute_query("SHOW CONSTRAINTS")
        for c in constraints:
            print(f"  {c.get('name'):<28} {c.get('labelsOrTypes')} {c.get('properties')}")
        print(f"  -> {len(constraints)} constraint(s)")
        if len(constraints) < 7:
            print("  !! expected 7 -- schema may not have been applied")
            ok = False

        print("\n" + "=" * 66)
        print("INDEXES")
        print("=" * 66)
        indexes = self.execute_query("SHOW INDEXES")
        vector_indexes = []
        for i in indexes:
            itype = i.get("type")
            print(f"  {i.get('name'):<28} {itype:<10} {i.get('labelsOrTypes')} {i.get('properties')}")
            if itype == "VECTOR":
                vector_indexes.append(i.get("name"))
        print(f"  -> {len(indexes)} index(es), {len(vector_indexes)} vector")
        if len(vector_indexes) < 2:
            print("  !! expected 2 vector indexes (chunk + keyword)")
            ok = False

        print("\n" + "=" * 66)
        print("GRAPH DATA SCIENCE")
        print("=" * 66)
        try:
            gds = self.execute_query("CALL gds.version()")
            print(f"  GDS version: {list(gds[0].values())[0]}")
        except Exception as e:
            print(f"  !! GDS unavailable: {e}")
            print("     The container may still be installing plugins on first boot.")
            print("     Wait a minute and retry, or check:  docker compose logs neo4j")
            ok = False

        print("\n" + "=" * 66)
        print("EMBEDDINGS")
        print("=" * 66)
        print(f"  provider:   {EMBEDDING_PROVIDER}")
        print(f"  model:      {EMBEDDING_MODEL}")
        print(f"  dimensions: {EMBEDDING_DIM}")

        print("\n" + ("PHASE 0 VERIFIED" if ok else "PHASE 0 INCOMPLETE") + "\n")
        return ok

    def node_counts(self) -> List[Dict[str, Any]]:
        """Node count per label -- the sanity check after every ingest."""
        return self.execute_query(
            """
            MATCH (n)
            UNWIND labels(n) AS label
            RETURN label, count(*) AS count
            ORDER BY count DESC
            """
        )


# =====================================================================
# EMBEDDINGS
# =====================================================================

_embedder = None


def _get_embedder():
    """Load the embedding model once and reuse it (loading is slow)."""
    global _embedder
    if _embedder is not None:
        return _embedder

    if EMBEDDING_PROVIDER == "fastembed":
        try:
            from fastembed import TextEmbedding
        except ImportError as e:
            raise RuntimeError(
                "fastembed is not installed. Run:  pip install -r requirements.txt"
            ) from e
        logger.info("Loading local embedding model %s ...", EMBEDDING_MODEL)
        logger.info("(first run downloads ~130MB, then it is cached)")
        _embedder = TextEmbedding(model_name=EMBEDDING_MODEL)

    elif EMBEDDING_PROVIDER == "openai":
        if not OPENAI_API_KEY:
            raise RuntimeError(
                "EMBEDDING_PROVIDER=openai but OPENAI_API_KEY is not set in .env"
            )
        try:
            import openai
        except ImportError as e:
            raise RuntimeError(
                "openai is not installed. Uncomment it in requirements.txt and "
                "run:  pip install -r requirements.txt"
            ) from e
        _embedder = openai.OpenAI(api_key=OPENAI_API_KEY)

    return _embedder


def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    Embed a LIST of texts in one go. Always prefer this over embed_text.

    The old code called the embedding API once per row inside a Python
    loop. For 5,000 keywords that is 5,000 sequential round-trips.
    Batching is the same rule as for Neo4j writes.
    """
    if not texts:
        return []

    embedder = _get_embedder()

    if EMBEDDING_PROVIDER == "fastembed":
        vectors = [list(map(float, v)) for v in embedder.embed(texts)]
    else:
        resp = embedder.embeddings.create(input=texts, model=EMBEDDING_MODEL)
        vectors = [d.embedding for d in resp.data]

    # Guard against the silent-failure mode: if the model's real output
    # width does not match what the vector indexes were built with, every
    # similarity query returns nothing and Neo4j reports no error.
    actual = len(vectors[0])
    if actual != EMBEDDING_DIM:
        raise RuntimeError(
            f"Embedding model {EMBEDDING_MODEL!r} returned {actual} dimensions "
            f"but EMBEDDING_DIM is {EMBEDDING_DIM}. Fix .env and re-run the "
            f"schema step so the vector indexes are rebuilt."
        )

    return vectors


def embed_text(text: str) -> List[float]:
    """Single-text convenience wrapper. Use embed_texts for bulk work."""
    return embed_texts([text])[0]


# =====================================================================
# CLI
# =====================================================================

if __name__ == "__main__":
    db = DatabaseManager()
    try:
        if "--init-schema" in sys.argv:
            db.init_schema()
        elif "--verify" in sys.argv:
            sys.exit(0 if db.verify() else 1)
        elif "--counts" in sys.argv:
            rows = db.node_counts()
            if not rows:
                print("Graph is empty.")
            for r in rows:
                print(f"  {r['label']:<20} {r['count']:>8}")
        else:
            print("usage: python -m src.db [--init-schema | --verify | --counts]")
    finally:
        db.close()
