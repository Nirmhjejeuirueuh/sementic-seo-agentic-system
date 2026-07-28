"""
Phase 0 smoke test -- proves the embedding model produces MEANINGFUL
vectors, not just vectors of the right length.

The old code's hash-based "embeddings" would have passed a length check.
They would fail this one, because similarity between them is random.

Run:  python -m scripts.smoke_test
"""

import math
from src.db import embed_texts
from src.config import EMBEDDING_PROVIDER, EMBEDDING_MODEL, EMBEDDING_DIM


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb)


def main():
    print(f"provider = {EMBEDDING_PROVIDER}")
    print(f"model    = {EMBEDDING_MODEL}")
    print(f"expected = {EMBEDDING_DIM} dimensions\n")

    texts = [
        "personalised storybook for a 4 year old",
        "custom children's book featuring your kid's name",
        "industrial hydraulic pump maintenance schedule",
    ]
    vectors = embed_texts(texts)

    print(f"actual   = {len(vectors[0])} dimensions\n")

    related = cosine(vectors[0], vectors[1])
    unrelated = cosine(vectors[0], vectors[2])

    print(f"  storybook  vs  custom book   {related:>7.3f}   (want HIGH)")
    print(f"  storybook  vs  hydraulics    {unrelated:>7.3f}   (want LOW)")
    print()

    if related > unrelated + 0.10:
        print("PASS -- embeddings carry real semantic meaning.")
        print("        Two phrasings of the same idea score much closer")
        print("        than two unrelated topics. This is what makes the")
        print("        Keyword -> Chunk -> Entity join work.")
        return 0

    print("FAIL -- similarity scores are not separating related from")
    print("        unrelated text. Something is wrong with the model.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
