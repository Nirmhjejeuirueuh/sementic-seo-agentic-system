import os
import argparse
import logging
from typing import List, Dict, Any
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

from src.db import DatabaseManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def extract_slug(url: str) -> str:
    path = urlparse(url).path.strip("/")
    if not path:
        return "home"
    parts = path.split("/")
    return parts[-1] if parts else "home"


def parse_sitemap_file_or_url(sitemap_source: str) -> List[Dict[str, Any]]:
    """Parse XML sitemap using advertools if available, or xml.etree as fallback."""
    pages = []

    # Attempt advertools first
    try:
        import advertools as adv
        df = adv.sitemap_to_df(sitemap_source)
        if "loc" in df.columns:
            for _, row in df.iterrows():
                loc = str(row["loc"])
                if loc and loc != "nan":
                    pages.append({
                        "url": loc,
                        "slug": extract_slug(loc),
                        "lastmod": str(row.get("lastmod", "")),
                        "status": "existing"
                    })
            if pages:
                logger.info(f"Parsed {len(pages)} URLs using advertools.")
                return pages
    except Exception as e:
        logger.info(f"Advertools sitemap parsing fallback to XML parser: {e}")

    # XML parser fallback
    try:
        if os.path.exists(sitemap_source):
            tree = ET.parse(sitemap_source)
            root = tree.getroot()
        else:
            import requests
            resp = requests.get(sitemap_source, timeout=10)
            root = ET.fromstring(resp.content)

        # Handle sitemap XML namespace
        namespaces = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        urls = root.findall('.//ns:url', namespaces) or root.findall('.//url')

        for elem in urls:
            loc_elem = elem.find('ns:loc', namespaces) if elem.find('ns:loc', namespaces) is not None else elem.find('loc')
            lastmod_elem = elem.find('ns:lastmod', namespaces) if elem.find('ns:lastmod', namespaces) is not None else elem.find('lastmod')

            if loc_elem is not None and loc_elem.text:
                loc = loc_elem.text.strip()
                pages.append({
                    "url": loc,
                    "slug": extract_slug(loc),
                    "lastmod": lastmod_elem.text.strip() if lastmod_elem is not None and lastmod_elem.text else "",
                    "status": "existing"
                })
    except Exception as e:
        logger.error(f"Error parsing XML sitemap {sitemap_source}: {e}")

    return pages


def ingest_sitemap(sitemap_source: str, db: DatabaseManager):
    """Ingest sitemap.xml URLs as :Page nodes into Neo4j."""
    logger.info(f"Ingesting sitemap from: {sitemap_source}")
    pages = parse_sitemap_file_or_url(sitemap_source)

    if not pages:
        logger.warning("No URLs found in sitemap.")
        return

    logger.info(f"Writing {len(pages)} Page nodes to Neo4j via UNWIND batching...")

    cypher_query = """
    UNWIND $rows AS row
    MERGE (p:Page {url: row.url})
    ON CREATE SET 
        p.slug = row.slug,
        p.lastmod = row.lastmod,
        p.status = row.status,
        p.createdAt = timestamp()
    ON MATCH SET 
        p.slug = row.slug,
        p.lastmod = row.lastmod,
        p.updatedAt = timestamp()
    """

    db.batch_write(cypher_query, pages, batch_size=1000)
    logger.info("Sitemap ingestion complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest XML Sitemap into Neo4j")
    parser.add_argument("--url", type=str, default="data/sitemap.xml", help="Path or URL to sitemap.xml")
    args = parser.parse_args()

    db = DatabaseManager()
    ingest_sitemap(args.url, db)
    db.close()
