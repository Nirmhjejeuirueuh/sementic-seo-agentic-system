import os
import sys
import glob
import logging
import argparse
from typing import List, Dict, Any, Tuple

from src.config import (
    ALLOWED_NODE_LABELS,
    ALLOWED_RELATIONSHIPS,
    VALID_TRIPLETS,
    ANTHROPIC_API_KEY,
    OPENAI_API_KEY,
    GEMINI_API_KEY,
    EXTRACTION_MODEL
)
from src.db import DatabaseManager, generate_embedding

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def parse_pdf_text(pdf_path: str) -> str:
    """Extract full text from PDF file using pdfplumber or pypdf."""
    text = ""
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        if text.strip():
            return text
    except Exception as e:
        logger.warning(f"pdfplumber failed for {pdf_path}: {e}. Trying pypdf...")

    try:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        for page in reader.pages:
            t = page.extract_text()
            if t:
                text += t + "\n"
    except Exception as e:
        logger.error(f"pypdf failed for {pdf_path}: {e}")

    return text


def extract_entities_and_relations(text: str) -> List[Dict[str, Any]]:
    """
    Schema-grounded entity extraction constrained by ALLOWED_NODE_LABELS and ALLOWED_RELATIONSHIPS.
    Supports LLM extraction with fallback entity extractor.
    """
    # Attempt LLM extraction using LangChain / OpenAI / Gemini
    if ANTHROPIC_API_KEY or OPENAI_API_KEY or GEMINI_API_KEY:
        try:
            if ANTHROPIC_API_KEY:
                from langchain_anthropic import ChatAnthropic
                llm = ChatAnthropic(model=EXTRACTION_MODEL, anthropic_api_key=ANTHROPIC_API_KEY, temperature=0)
            elif OPENAI_API_KEY:
                from langchain_openai import ChatOpenAI
                llm = ChatOpenAI(model="gpt-4o-mini", api_key=OPENAI_API_KEY, temperature=0)
            else:
                from langchain_google_genai import ChatGoogleGenerativeAI
                llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=GEMINI_API_KEY, temperature=0)

            from pydantic import BaseModel, Field

            class ExtractedEntity(BaseModel):
                name: str = Field(description="Name of the entity")
                type: str = Field(description=f"Allowed label from {ALLOWED_NODE_LABELS}")

            class ExtractedRelation(BaseModel):
                source: str
                relationship: str = Field(description=f"Allowed relationship from {ALLOWED_RELATIONSHIPS}")
                target: str

            class GraphExtraction(BaseModel):
                entities: List[ExtractedEntity]
                relations: List[ExtractedRelation]

            structured_llm = llm.with_structured_output(GraphExtraction)
            prompt = f"""
            Extract entities and relationships from the text below.
            You MUST follow these schema constraints strictly:
            Allowed Entity Types: {ALLOWED_NODE_LABELS}
            Allowed Relationship Types: {ALLOWED_RELATIONSHIPS}

            Text:
            {text[:3000]}
            """
            result = structured_llm.invoke(prompt)
            if result:
                valid_entities = [e.model_dump() for e in result.entities if e.type in ALLOWED_NODE_LABELS]
                valid_relations = [r.model_dump() for r in result.relations if r.relationship in ALLOWED_RELATIONSHIPS]
                return {"entities": valid_entities, "relations": valid_relations}
        except Exception as e:
            logger.warning(f"LLM entity extraction failed: {e}. Utilizing fallback pattern extractor...")

    # Fallback pattern/rule extractor
    import re
    words = re.findall(r'\b[A-Z][a-zA-Z0-9\-\.]{2,}\b', text)
    unique_words = sorted(list(set(words)))[:15]
    
    fallback_entities = []
    labels_cycle = ALLOWED_NODE_LABELS
    for i, word in enumerate(unique_words):
        lbl = labels_cycle[i % len(labels_cycle)]
        fallback_entities.append({"name": word, "type": lbl})

    fallback_relations = []
    if len(fallback_entities) >= 2:
        for i in range(len(fallback_entities) - 1):
            fallback_relations.append({
                "source": fallback_entities[i]["name"],
                "relationship": "RELATES_TO",
                "target": fallback_entities[i+1]["name"]
            })

    return {"entities": fallback_entities, "relations": fallback_relations}


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 150) -> List[str]:
    """Split text into overlapping chunks."""
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += (chunk_size - overlap)
    return chunks


def parse_document_text(file_path: str) -> str:
    """Extract full text from PDF, TXT, or MD file."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext in [".txt", ".md", ".markdown"]:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Error reading text file {file_path}: {e}")
            return ""

    return parse_pdf_text(file_path)


def process_single_document(file_path: str, db: DatabaseManager):
    """
    Process single document file.
    Constraint: One bad document must not kill an extraction run. Catch per-file and continue.
    """
    file_name = os.path.basename(file_path)
    doc_id = f"doc_{file_name}"
    logger.info(f"Processing document: {file_name}")

    try:
        raw_text = parse_document_text(file_path)
        if not raw_text.strip():
            logger.warning(f"Empty text extracted from {file_path}. Skipping.")
            return

        chunks = chunk_text(raw_text)
        logger.info(f"Extracted {len(chunks)} chunks from {file_name}.")

        # 1. Save Document Node
        db.execute_query("""
        MERGE (d:Document {id: $doc_id})
        SET d.filename = $filename, d.total_chunks = $total_chunks, d.updatedAt = timestamp()
        """, {"doc_id": doc_id, "filename": file_name, "total_chunks": len(chunks)})

        # 2. Save Chunks and Extract Entities per chunk
        for idx, chunk_content in enumerate(chunks):
            chunk_id = f"{doc_id}_chunk_{idx}"
            embedding = generate_embedding(chunk_content)

            # Extract entities from chunk
            extraction = extract_entities_and_relations(chunk_content)
            entities = extraction.get("entities", [])
            relations = extraction.get("relations", [])

            # Parse Obsidian Wikilinks [[Entity Name]] or [[Entity Name|Label]]
            import re
            obsidian_links = re.findall(r'\[\[([^\]\|]+)(?:\|[^\]]+)?\]\]', chunk_content)
            for link in set(obsidian_links):
                link_clean = link.strip()
                if link_clean and not any(e['name'].lower() == link_clean.lower() for e in entities):
                    entities.append({"name": link_clean, "type": "Concept"})

            # Write Chunk and Entities to Neo4j
            # Note on FROM_CHUNK direction: Match FROM_CHUNK undirected (-[:FROM_CHUNK]-)
            cypher_chunk_entity = """
            MATCH (d:Document {id: $doc_id})
            MERGE (c:Chunk {id: $chunk_id})
            ON CREATE SET c.text = $text, c.index = $index, c.embedding = $embedding
            MERGE (c)-[:FROM_DOCUMENT]->(d)

            WITH c
            UNWIND $entities AS ent
            MERGE (e:__Entity__ {name: ent.name})
            ON CREATE SET e.type = ent.type, e.createdAt = timestamp()
            MERGE (c)-[:FROM_CHUNK]->(e)
            """

            db.execute_query(cypher_chunk_entity, {
                "doc_id": doc_id,
                "chunk_id": chunk_id,
                "text": chunk_content,
                "index": idx,
                "embedding": embedding,
                "entities": entities
            })

            # Write relations between entities
            if relations:
                cypher_relations = """
                UNWIND $relations AS rel
                MATCH (e1:__Entity__ {name: rel.source})
                MATCH (e2:__Entity__ {name: rel.target})
                MERGE (e1)-[:RELATES_TO]->(e2)
                """
                db.execute_query(cypher_relations, {"relations": relations})

        logger.info(f"Successfully processed document {file_name}")

    except Exception as e:
        logger.error(f"Error processing document {file_path}: {e}. Continuing pipeline...")


def ingest_documents(directory: str, db: DatabaseManager):
    """Ingest all PDF, TXT, and MD files in directory."""
    if not os.path.exists(directory):
        logger.info(f"Directory {directory} does not exist. Creating...")
        os.makedirs(directory, exist_ok=True)

    supported_extensions = ["*.pdf", "*.txt", "*.md"]
    doc_files = []
    for ext in supported_extensions:
        doc_files.extend(glob.glob(os.path.join(directory, ext)))

    if not doc_files:
        sample_path = os.path.join(directory, "sample_semantic_seo_handbook.txt")
        logger.info(f"No documents found in {directory}. Generating sample document: {sample_path}")
        with open(sample_path, "w", encoding="utf-8") as f:
            f.write("""# Semantic SEO & Knowledge Graph Handbook
Semantic SEO is a modern content strategy that focuses on concepts, entities, and user search intent rather than individual target keywords.

## Core Concepts
- Topic Clusters: Groupings of closely related content around a central core pillar page.
- Knowledge Graph: A graph database structure mapping entities (Products, Services, Problems, Technologies) and their relationships.
- Search Intent: Categorized into Informational, Navigational, Commercial, and Transactional.
- Neo4j Graph Data Science: Graph analytics algorithms like Louvain community detection and PageRank to discover content gaps.
- Internal Linking: Strategic hyperlinks connecting related topic cluster pages to distribute page authority and guide crawlers.
""")
        doc_files = [sample_path]

    for file_path in doc_files:
        process_single_document(file_path, db)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest PDFs into Neo4j Document/Chunk/Entity Graph")
    parser.add_argument("--dir", type=str, default="data/documents/", help="Directory containing PDFs")
    args = parser.parse_args()

    db = DatabaseManager()
    ingest_documents(args.dir, db)
    db.close()
