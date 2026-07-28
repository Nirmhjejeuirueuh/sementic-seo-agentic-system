"""
Quick look at what the vault loader put in the graph. Not part of the
pipeline -- just a sanity check you can re-run any time.

Run:  python -m scripts.inspect_vault
"""

from src.db import DatabaseManager


def main():
    db = DatabaseManager()
    try:
        print("\nEntities by type:")
        for r in db.execute_query(
            "MATCH (e:__Entity__) RETURN e.type AS type, count(*) AS n "
            "ORDER BY n DESC"
        ):
            print(f"  {r['type']:<16} {r['n']}")

        print("\nPages by status:")
        for r in db.execute_query(
            "MATCH (p:Page) RETURN p.status AS status, count(*) AS n "
            "ORDER BY n DESC"
        ):
            print(f"  {r['status']:<10} {r['n']}")

        print("\nProduct -> taxonomy links:")
        for r in db.execute_query(
            "MATCH (p:__Entity__ {type:'Product'})-[rel]->(t:__Entity__) "
            "RETURN p.name AS product, type(rel) AS rel, t.name AS target"
        ):
            print(f"  {r['product']}  -[{r['rel']}]->  {r['target']}")

        print("\nProducts with NO taxonomy links yet:")
        for r in db.execute_query(
            "MATCH (p:__Entity__ {type:'Product'}) "
            "WHERE NOT (p)-->(:__Entity__) "
            "RETURN p.name AS product"
        ):
            print(f"  {r['product']}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
