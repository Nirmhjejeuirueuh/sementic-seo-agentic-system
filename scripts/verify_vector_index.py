"""
Proves the vector index round-trips end to end.

`SHOW INDEXES` only tells you an index EXISTS. It does not tell you the
dimension matches what your embedding model produces. When they disagree,
Neo4j raises no error -- vector queries just return zero rows forever.

So we write three real chunks, query the index, and assert the ranking is
semantically sensible. Then we clean up after ourselves.

Run:  python -m scripts.verify_vector_index
"""

from src.db import DatabaseManager, embed_texts
from src.config import EMBEDDING_DIM

PASSAGES = [
    ("__probe_1", "Our hardcover personalised books cost 24.99 with free UK delivery."),
    ("__probe_2", "The Dragon Adventure is a bedtime story for children aged three to six."),
    ("__probe_3", "Replace the hydraulic seal every two thousand operating hours."),
]

QUERY = "how much does a personalised book cost"


def main():
    db = DatabaseManager()
    try:
        vectors = embed_texts([text for _, text in PASSAGES])

        db.batch_write(
            """
            UNWIND $rows AS row
            MERGE (c:Chunk {id: row.id})
            SET c.text = row.text, c.embedding = row.embedding
            """,
            [
                {"id": cid, "text": text, "embedding": vec}
                for (cid, text), vec in zip(PASSAGES, vectors)
            ],
        )

        query_vector = embed_texts([QUERY])[0]
        results = db.execute_query(
            """
            CALL db.index.vector.queryNodes('chunk_embedding_idx', 3, $vec)
            YIELD node, score
            RETURN node.id AS id, node.text AS text, score
            ORDER BY score DESC
            """,
            {"vec": query_vector},
        )

        print(f"\nembedding dim : {EMBEDDING_DIM}")
        print(f'query         : "{QUERY}"\n')

        if not results:
            print("FAIL -- the index returned ZERO rows.")
            print("        This is the silent dimension-mismatch failure.")
            print("        Drop both vector indexes and re-run --init-schema.")
            return 1

        for r in results:
            print(f"  {r['score']:.3f}  {r['text'][:62]}")

        top = results[0]["id"]
        print()
        if top == "__probe_1":
            print("PASS -- the pricing passage ranked first for a pricing query.")
            print("        The index dimension matches the model, and semantic")
            print("        retrieval works. This is the mechanism behind")
            print("        Keyword -> Chunk -> Entity (pass 2 of the join).")
            return 0

        print(f"FAIL -- expected __probe_1 to rank first, got {top}.")
        return 1

    finally:
        db.execute_query(
            "MATCH (c:Chunk) WHERE c.id STARTS WITH '__probe_' DETACH DELETE c"
        )
        print("(probe chunks removed)")
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
