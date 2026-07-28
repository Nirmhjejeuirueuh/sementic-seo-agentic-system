// =====================================================================
// Schema for Neo4j 5.26 LTS. Target Cypher 5 syntax.
//
// This file is applied by:  python -m src.db --init-schema
//
// __EMBEDDING_DIM__ is substituted by src/db.py from EMBEDDING_DIM in
// .env before execution. Vector index dimensions must be a literal in
// Cypher, so they cannot be passed as a query parameter -- and hardcoding
// them here would let .env and the index drift apart. A drift makes every
// vector query silently return zero rows with no error raised.
//
// Everything here is `IF NOT EXISTS`, so re-running is safe.
// =====================================================================


// ---------------------------------------------------------------------
// 1. UNIQUE CONSTRAINTS
//
// A uniqueness constraint also creates an index behind the scenes, so
// these give fast lookup as well as protecting against duplicates. They
// are what make MERGE both correct and fast.
// ---------------------------------------------------------------------

CREATE CONSTRAINT doc_id_unique IF NOT EXISTS
FOR (d:Document) REQUIRE d.id IS UNIQUE;

CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS
FOR (c:Chunk) REQUIRE c.id IS UNIQUE;

CREATE CONSTRAINT entity_name_unique IF NOT EXISTS
FOR (e:__Entity__) REQUIRE e.name IS UNIQUE;

// Keyword identity is the NORMALISED form, never the raw form. Otherwise
// "SEO Audit" and "seo audit" become two nodes and every volume figure
// downstream is wrong. See normalize_keyword() in src/config.py.
CREATE CONSTRAINT keyword_normalized_unique IF NOT EXISTS
FOR (k:Keyword) REQUIRE k.normalized IS UNIQUE;

CREATE CONSTRAINT page_url_unique IF NOT EXISTS
FOR (p:Page) REQUIRE p.url IS UNIQUE;

CREATE CONSTRAINT intent_name_unique IF NOT EXISTS
FOR (i:Intent) REQUIRE i.name IS UNIQUE;

CREATE CONSTRAINT cluster_id_unique IF NOT EXISTS
FOR (cl:Cluster) REQUIRE cl.id IS UNIQUE;


// ---------------------------------------------------------------------
// 2. LOOKUP INDEXES
// ---------------------------------------------------------------------

CREATE INDEX entity_type_idx IF NOT EXISTS
FOR (e:__Entity__) ON (e.type);

CREATE INDEX page_slug_idx IF NOT EXISTS
FOR (p:Page) ON (p.slug);

CREATE INDEX cluster_name_idx IF NOT EXISTS
FOR (cl:Cluster) ON (cl.name);


// ---------------------------------------------------------------------
// 3. VECTOR INDEXES
//
// Cosine similarity. Dimensions come from .env via substitution.
//
// Chunk.embedding  -- lets us find passages semantically near a keyword.
// Keyword.embedding -- lets us find keywords near each other.
//
// If you change EMBEDDING_PROVIDER or EMBEDDING_MODEL in .env, you MUST
// drop and recreate these, because IF NOT EXISTS will happily leave an
// index at the old dimension in place:
//   DROP INDEX chunk_embedding_idx;
//   DROP INDEX keyword_embedding_idx;
// then re-run --init-schema.
// ---------------------------------------------------------------------

CREATE VECTOR INDEX chunk_embedding_idx IF NOT EXISTS
FOR (c:Chunk) ON (c.embedding)
OPTIONS {
  indexConfig: {
    `vector.similarity_function`: 'cosine',
    `vector.dimensions`: __EMBEDDING_DIM__
  }
};

CREATE VECTOR INDEX keyword_embedding_idx IF NOT EXISTS
FOR (k:Keyword) ON (k.embedding)
OPTIONS {
  indexConfig: {
    `vector.similarity_function`: 'cosine',
    `vector.dimensions`: __EMBEDDING_DIM__
  }
};


// ---------------------------------------------------------------------
// NOTE ON THE FROM_CHUNK DIRECTION
//
// Always match FROM_CHUNK undirected:   (c:Chunk)-[:FROM_CHUNK]-(e)
// Its direction has moved between neo4j-graphrag releases, so a directed
// match silently returns nothing on the wrong version.
//
// To check which way it currently points, run this in Neo4j Browser:
//
//   MATCH (c:Chunk)-[r:FROM_CHUNK]-(e:__Entity__)
//   RETURN startNode(r) = c AS chunk_is_start, count(*)
//   LIMIT 5;
// ---------------------------------------------------------------------
