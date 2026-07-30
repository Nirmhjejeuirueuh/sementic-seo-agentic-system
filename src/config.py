"""
Central configuration. Every tunable value in the project lives here.

Design rule for this file: it must FAIL LOUDLY. The previous version of
this codebase was full of silent fallbacks -- if a key was missing, it
would quietly substitute fake data and carry on. That makes a broken
pipeline indistinguishable from a working one. Prefer a crash with a
clear message.
"""

import os
import re
from typing import List, Tuple
from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------
# NEO4J CONNECTION
# ---------------------------------------------------------------------
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password123")


# ---------------------------------------------------------------------
# EMBEDDINGS
# ---------------------------------------------------------------------
# An embedding turns text into a list of numbers ("a vector") such that
# texts with similar meaning end up close together. That is what lets us
# match the keyword "how much does a personalised book cost" to a passage
# about pricing, even though they share no words.
#
# Two providers are supported:
#
#   fastembed  BAAI/bge-small-en-v1.5, runs locally via ONNX. Free, no
#              API key, no network after first download. 384 dimensions.
#   openai     text-embedding-3-small. Costs money, better quality,
#              1536 dimensions. This is what the original spec called for.
#
# To switch: change EMBEDDING_PROVIDER in .env, uncomment `openai` in
# requirements.txt, then RE-RUN THE SCHEMA STEP. The dimension count is
# baked into the Neo4j vector indexes, so they must be rebuilt.

EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "fastembed").strip().lower()

_EMBEDDING_DEFAULTS = {
    # provider: (model name, dimensions)
    "fastembed": ("BAAI/bge-small-en-v1.5", 384),
    "openai": ("text-embedding-3-small", 1536),
}

if EMBEDDING_PROVIDER not in _EMBEDDING_DEFAULTS:
    raise ValueError(
        f"EMBEDDING_PROVIDER must be one of {list(_EMBEDDING_DEFAULTS)}, "
        f"got {EMBEDDING_PROVIDER!r}. Check your .env file."
    )

_default_model, _default_dim = _EMBEDDING_DEFAULTS[EMBEDDING_PROVIDER]
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", _default_model)
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", str(_default_dim)))

# A dimension mismatch between .env and the vector index definition fails
# SILENTLY in Neo4j -- queries just return zero rows, with no error at all.
# It is a genuinely horrible bug to track down, so we refuse to start.
if EMBEDDING_MODEL == _default_model and EMBEDDING_DIM != _default_dim:
    raise ValueError(
        f"EMBEDDING_DIM={EMBEDDING_DIM} does not match model "
        f"{EMBEDDING_MODEL!r}, which produces {_default_dim} dimensions. "
        f"A mismatch makes every vector query silently return nothing. "
        f"Fix EMBEDDING_DIM in .env, then re-run the schema step."
    )


# ---------------------------------------------------------------------
# LLM MODELS
# ---------------------------------------------------------------------
# Extraction needs strong schema adherence -- that is the whole job, so
# it gets the capable model. Bulk classification gets the cheap fast one.
EXTRACTION_MODEL = os.getenv("EXTRACTION_MODEL", "claude-sonnet-5")
CLASSIFICATION_MODEL = os.getenv("CLASSIFICATION_MODEL", "claude-haiku-4-5-20251001")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# ---------------------------------------------------------------------
# THE PAGE-WRITING AGENT'S PROVIDER (Phase 7)
# ---------------------------------------------------------------------
# Explicit, not guessed. The old code picked a provider by checking which
# API key happened to be non-empty, in a fixed order (Anthropic, then
# OpenAI, then Gemini) -- and its Gemini branch fell back to the literal
# string "dummy" as an API key if GEMINI_API_KEY was unset, so a missing
# key produced a confusing API error instead of a clear one. Same failure
# family as the fake-embeddings bug removed in Phase 0 (CLAUDE.md rule 9):
# a missing input should raise here, not get silently substituted.
#
# AGENT_PROVIDER says which provider to use. require_agent_key() then
# fails immediately and clearly if that provider's key is missing.
AGENT_PROVIDER = os.getenv("AGENT_PROVIDER", "anthropic").strip().lower()

_AGENT_MODEL_DEFAULTS = {
    "anthropic": "claude-sonnet-5",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.5-flash",
}
_AGENT_KEYS = {
    "anthropic": ANTHROPIC_API_KEY,
    "openai": OPENAI_API_KEY,
    "gemini": GEMINI_API_KEY,
}

if AGENT_PROVIDER not in _AGENT_MODEL_DEFAULTS:
    raise ValueError(
        f"AGENT_PROVIDER must be one of {list(_AGENT_MODEL_DEFAULTS)}, "
        f"got {AGENT_PROVIDER!r}. Check your .env file."
    )

# `or` here, not the two-arg os.getenv() form: .env can set AGENT_MODEL=
# (present but blank) rather than omitting the line entirely, and
# os.getenv()'s default only kicks in when the variable is ABSENT, not
# when it's an empty string. Without this, a blank line in .env would
# silently produce AGENT_MODEL = "" instead of the intended default.
AGENT_MODEL = os.getenv("AGENT_MODEL", "").strip() or _AGENT_MODEL_DEFAULTS[AGENT_PROVIDER]


def require_agent_key() -> str:
    """Call this before instantiating the page-writing agent's LLM."""
    key = _AGENT_KEYS[AGENT_PROVIDER]
    if not key:
        env_var = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY",
                    "gemini": "GEMINI_API_KEY"}[AGENT_PROVIDER]
        raise RuntimeError(
            f"AGENT_PROVIDER={AGENT_PROVIDER!r} but {env_var} is not set in .env. "
            f"Add it, or change AGENT_PROVIDER to a provider whose key you do have."
        )
    return key


# ---------------------------------------------------------------------
# EXTRACTION SCHEMA
# ---------------------------------------------------------------------
# PHASE 2 -- domain: Getfiguro.com, a custom 3D-figurine business (turn a
# photo into a physical 3D-printed figurine). Derived directly from
# getfiguro-seo-knowledge-base.md, section 1.1's "Category Signal" column
# and the three content pillars in sections 3-5 (Occasion / Figurine Type
# / Figurine Style).
#
# A product connects to all three pillars it belongs to at once -- e.g.
# "Custom 3D Pet Memorial Statue" is Type=Pet, Style=Realistic (once
# tagged), Occasion=Memorial/Loss, simultaneously. That is the whole
# point of the pillar structure in the source document.
#
# Why pin a fixed list at all: an unconstrained extractor invents hundreds
# of one-off labels and the graph becomes unqueryable.

ALLOWED_NODE_LABELS: List[str] = [
    "Product",         # a sellable item, e.g. "Custom Pet Figurine"
    "FigurineStyle",   # the art style: Realistic, Nendoroid/Chibi, Bobblehead, Bronze, Pop-Vinyl, Anime Style
    "FigurineType",    # what the figurine is OF: Pet, Baby, Sports, Anime, Family, Corporate, Model/Hobbyist, Celebrity/Fan Art
    "Occasion",        # the gifting/life event: Wedding, Birthday, Christmas, Memorial/Loss...
    "Format",          # the physical form: Bust, Full-body standing, Keychain, Urn, Cake Topper, Centerpiece
    "Recipient",       # who it's a gift for: Him, Her, Boyfriend, Parents, Coach, Corporate, Couple
    "Accessory",       # add-ons: display stand, acrylic box, wooden base, gift box
]

ALLOWED_RELATIONSHIPS: List[str] = [
    "HAS_STYLE",       # Product -> FigurineStyle
    "DEPICTS",         # Product -> FigurineType
    "FOR_OCCASION",    # Product -> Occasion
    "HAS_FORMAT",      # Product -> Format
    "GIFT_FOR",        # Product -> Recipient
    "PAIRS_WITH",      # Product -> Accessory
    "RELATES_TO",      # generic taxonomy-term <-> taxonomy-term co-occurrence
]

# Constraining valid (source, relationship, target) triples matters as much
# as constraining the labels. Without it an extractor draws edges like
# (Format)-[:GIFT_FOR]->(Accessory), which are syntactically fine and
# semantically meaningless. (This project loads the figurine catalogue
# deterministically from hand-authored frontmatter rather than LLM
# extraction -- see src/ingest/vault.py -- but VALID_TRIPLETS still
# governs any future prose extraction, e.g. the page-template rulebook
# in section 7-8 of the source document.)
VALID_TRIPLETS: List[Tuple[str, str, str]] = [
    ("Product", "HAS_STYLE", "FigurineStyle"),
    ("Product", "DEPICTS", "FigurineType"),
    ("Product", "FOR_OCCASION", "Occasion"),
    ("Product", "HAS_FORMAT", "Format"),
    ("Product", "GIFT_FOR", "Recipient"),
    ("Product", "PAIRS_WITH", "Accessory"),
    ("FigurineStyle", "RELATES_TO", "FigurineStyle"),
    ("FigurineType", "RELATES_TO", "FigurineType"),
    ("Occasion", "RELATES_TO", "Occasion"),
]


# ---------------------------------------------------------------------
# SEARCH INTENT TAXONOMY -- exactly four buckets, no more
# ---------------------------------------------------------------------
SEARCH_INTENT_BUCKETS = [
    "informational",   # "how long does a custom figurine take to make"
    "navigational",    # "getfiguro login"
    "commercial",      # "best custom figurine sites"
    "transactional",   # "order custom bobblehead"
]


# ---------------------------------------------------------------------
# KEYWORD NORMALISATION -- exactly one function, used by every path
# ---------------------------------------------------------------------
def normalize_keyword(keyword: str) -> str:
    """
    Lowercase, collapse whitespace, normalise smart quotes, strip.

    Every ingest path must route through this. If two paths normalise
    differently, "SEO Audit" and "seo audit" become two separate nodes
    and every count in the graph is quietly wrong.
    """
    if not keyword:
        return ""

    normalized = (
        keyword.replace("’", "'")   # right single quote
        .replace("‘", "'")          # left single quote
        .replace("“", '"')          # left double quote
        .replace("”", '"')          # right double quote
    )
    normalized = normalized.lower()
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized
