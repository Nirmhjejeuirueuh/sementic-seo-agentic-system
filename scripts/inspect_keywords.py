"""
What the keyword layer actually looks like in the graph.

Not part of the pipeline -- a sanity check you can re-run any time, the
keyword-side counterpart to scripts/inspect_vault.py.

Run:  python -m scripts.inspect_keywords
"""

from collections import defaultdict

from src.db import DatabaseManager


def main():
    db = DatabaseManager()
    try:
        print("\n" + "=" * 64)
        print("KEYWORDS")
        print("=" * 64)

        total = db.execute_query("MATCH (k:Keyword) RETURN count(*) AS n")[0]["n"]
        print(f"  {total} keyword nodes")

        print("\n  by intent:")
        for r in db.execute_query(
            "MATCH (:Keyword)-[:HAS_INTENT]->(i:Intent) "
            "RETURN i.name AS intent, count(*) AS n ORDER BY n DESC"
        ):
            print(f"    {r['intent']:<16} {r['n']}")

        # A keyword with two intents means a stale HAS_INTENT edge survived
        # a re-classification. Should always be zero.
        bad = db.execute_query(
            "MATCH (k:Keyword) OPTIONAL MATCH (k)-[:HAS_INTENT]->(i:Intent) "
            "WITH k, count(i) AS n WHERE n <> 1 RETURN k.normalized AS kw, n"
        )
        if bad:
            print(f"\n  !! {len(bad)} keyword(s) do NOT have exactly one intent:")
            for b in bad[:10]:
                print(f"       {b['kw']} -> {b['n']} intents")
        else:
            print("\n  OK  every keyword has exactly one intent")

        print("\n" + "=" * 64)
        print("THE JOIN  (:Keyword)-[:ABOUT]->(:__Entity__)")
        print("=" * 64)

        linked = db.execute_query(
            "MATCH (k:Keyword) WHERE (k)-[:ABOUT]->(:__Entity__) RETURN count(*) AS n"
        )[0]["n"]
        pct = (linked / total * 100) if total else 0
        print(f"  {linked}/{total} keywords reach an entity  ({pct:.1f}%)")

        print("\n  by match method:")
        for r in db.execute_query(
            "MATCH (:Keyword)-[r:ABOUT]->(:__Entity__) "
            "RETURN r.method AS m, count(*) AS n ORDER BY n DESC"
        ):
            print(f"    {r['m']:<10} {r['n']}")

        print("\n  entities attracting the most keywords:")
        for r in db.execute_query(
            "MATCH (:Keyword)-[:ABOUT]->(e:__Entity__) "
            "RETURN e.name AS name, e.type AS type, count(*) AS n "
            "ORDER BY n DESC LIMIT 12"
        ):
            print(f"    {r['n']:>3}  {r['name']:<32} ({r['type']})")

        orphans = db.execute_query(
            "MATCH (e:__Entity__) WHERE NOT (:Keyword)-[:ABOUT]->(e) "
            "RETURN e.name AS name, e.type AS type ORDER BY e.type, e.name"
        )
        print(f"\n  entities with NO keyword pointing at them ({len(orphans)}):")
        by_type = defaultdict(list)
        for o in orphans:
            by_type[o["type"]].append(o["name"])
        for t, names in sorted(by_type.items()):
            print(f"    {t} ({len(names)}): {', '.join(names[:6])}"
                  + (" ..." if len(names) > 6 else ""))

        print("\n" + "=" * 64)
        print("UNLINKED KEYWORDS, GROUPED BY SOURCE CATEGORY")
        print("=" * 64)
        print("  (these are the content gaps -- the point of the exercise)\n")

        unlinked = db.execute_query(
            "MATCH (k:Keyword) WHERE NOT (k)-[:ABOUT]->(:__Entity__) "
            "RETURN k.normalized AS kw, k.categories AS cats ORDER BY kw"
        )
        grouped = defaultdict(list)
        for u in unlinked:
            grouped[(u["cats"] or ["Uncategorised"])[0]].append(u["kw"])
        for cat, kws in sorted(grouped.items(), key=lambda x: -len(x[1])):
            print(f"  {cat}  ({len(kws)})")
            for kw in kws:
                print(f"      {kw}")
            print()

    finally:
        db.close()


if __name__ == "__main__":
    main()
