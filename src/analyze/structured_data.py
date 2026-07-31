"""
Phase 8 -- JSON-LD structured data, one block per page type.

Pure functions: no DB writes, no LLM calls. decide_page_type()
(src/analyze/site_structure.py:59-91) already picked the page type from
deterministic rules; this only maps that decision to schema.org markup,
the same "boring, verifiable" style.

Price is the one field here that could be invented -- CLAUDE.md rule 9
forbids that explicitly. extract_price() only returns a price found in
an entity's own real evidence text (a vault note transcribed from the
live site, e.g. data/vault/products/personalized-anniversary-couple-
gift.md: "$210"). Every other product simply has no price anywhere in
the graph, so build_json_ld() omits `offers` entirely rather than
guess -- a Product with no Offer is still valid schema.org, just not
eligible for price-based rich results, which is the honest state of
the data.
"""

import re
from typing import Any, Dict, List, Optional

SITE_ROOT = "https://getfiguro.com"

PRICE_PATTERN = re.compile(r"\$\d[\d,]*")


def extract_price(evidence_text: str) -> Optional[str]:
    """
    First real "$NNN" found in this entity's own evidence text, or None.

    Plain regex over our own source text (a vault note), not parsing of
    LLM output -- rule 8 governs structured LLM output, not this.
    """
    if not evidence_text:
        return None
    match = PRICE_PATTERN.search(evidence_text)
    # [\d,]* is greedy and can swallow a trailing sentence comma, e.g.
    # "$210, sizes 10cm/..." -> "$210,". Trim it back off; a real price
    # never ends in a separator.
    return match.group(0).rstrip(",") if match else None


def _breadcrumb(url: str, title: str) -> Dict[str, Any]:
    """BreadcrumbList from the URL's own path segments -- Home > ... > title."""
    segments = [s for s in url.strip("/").split("/") if s]
    items: List[Dict[str, Any]] = [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{SITE_ROOT}/"}
    ]
    path = ""
    for i, segment in enumerate(segments):
        path += f"/{segment}"
        is_last = i == len(segments) - 1
        name = title if is_last else segment.replace("-", " ").title()
        items.append({
            "@type": "ListItem",
            "position": i + 2,
            "name": name,
            "item": f"{SITE_ROOT}{path}",
        })
    return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": items}


def build_json_ld(
    page_type: str,
    title: str,
    meta_description: str,
    url: str,
    primary_keyword: str,
    entities: List[str],
    price: Optional[str] = None,
) -> Dict[str, Any]:
    """
    BreadcrumbList (every page) plus one page-type-specific block.

    page_type is whatever decide_page_type() produced: product |
    collection | blog | comparison | tool. Anything else defaults to
    WebPage, mirroring that function's own "log and default" fallback
    rather than raising -- an unrecognised page_type here is a real gap
    worth surfacing, not a hard stop.
    """
    full_url = f"{SITE_ROOT}{url}"
    breadcrumb = _breadcrumb(url, title)

    if page_type == "product":
        main: Dict[str, Any] = {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": title,
            "description": meta_description,
            "url": full_url,
        }
        if price is not None:
            main["offers"] = {
                "@type": "Offer",
                "price": price.lstrip("$").replace(",", ""),
                "priceCurrency": "USD",
                "url": full_url,
            }
    elif page_type == "collection":
        main = {
            "@context": "https://schema.org",
            "@type": "CollectionPage",
            "name": title,
            "description": meta_description,
            "url": full_url,
        }
    elif page_type == "blog":
        main = {
            "@context": "https://schema.org",
            "@type": "BlogPosting",
            "headline": title,
            "description": meta_description,
            "url": full_url,
            "keywords": primary_keyword,
        }
    elif page_type == "comparison":
        main = {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": title,
            "description": meta_description,
            "url": full_url,
        }
    elif page_type == "tool":
        # Deliberately WebPage, not WebApplication -- there is no real
        # interactive tool behind these pages yet; claiming one would
        # be false markup.
        main = {
            "@context": "https://schema.org",
            "@type": "WebPage",
            "name": title,
            "description": meta_description,
            "url": full_url,
        }
    else:
        main = {
            "@context": "https://schema.org",
            "@type": "WebPage",
            "name": title,
            "description": meta_description,
            "url": full_url,
        }

    if entities:
        main["about"] = [{"@type": "Thing", "name": e} for e in entities[:8]]

    return {"page": main, "breadcrumb": breadcrumb}
