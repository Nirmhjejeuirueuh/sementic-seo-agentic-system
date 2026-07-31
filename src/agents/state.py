from typing import TypedDict, List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field

# -------------------------------------------------------------------
# PYDANTIC STRUCTURED OUTPUT MODELS FOR AGENT NODES
# -------------------------------------------------------------------

class PageBrief(BaseModel):
    h1: str = Field(description="Main page H1 title optimized for primary keyword")
    slug: str = Field(description="Clean URL slug, e.g. 'semantic-seo-guide'")
    meta_description: str = Field(description="Search meta description between 140-160 characters")
    primary_keyword: str = Field(description="Primary target keyword")
    secondary_keywords: List[str] = Field(default_factory=list, description="Secondary supporting keywords")
    intent: str = Field(description="Search intent: informational, navigational, commercial, or transactional")
    h2_sections: List[str] = Field(default_factory=list, description="List of H2 section headers")
    must_cover: List[str] = Field(description="5-10 entity names taken verbatim from the cluster entity list")


class PageCritique(BaseModel):
    covered: List[str] = Field(default_factory=list, description="Entities fully explained in the draft")
    missing: List[str] = Field(default_factory=list, description="Entities from must_cover that are missing or superficial")
    intent_match: bool = Field(description="True if content satisfies dominant search intent")
    cannibalisation_risk: Literal['none', 'low', 'high'] = Field(description="Risk of keyword/topic cannibalization with existing pages")
    specific_revision_notes: str = Field(description="Actionable instructions for revision if coverage < 0.8 or intent unsatisfied")
    coverage_score: float = Field(description="Ratio of covered entities (0.0 to 1.0)")


class PageLinkPlan(BaseModel):
    target_slug: str = Field(description="Slug or URL of sibling page to link to")
    anchor_text: str = Field(description="Exact verbatim phrase from the draft to convert into a link")
    relationship_reason: str = Field(description="Semantic reason for internal link")


# -------------------------------------------------------------------
# LANGGRAPH STATE TYPEDDICT
# -------------------------------------------------------------------

class AgentState(TypedDict):
    cluster_id: str
    cluster_name: str
    entities: List[str]
    keywords: List[Dict[str, Any]]
    dominant_intent: str
    evidence_passages: List[Dict[str, Any]]
    brief: Optional[Dict[str, Any]]
    draft: str
    critique: Optional[Dict[str, Any]]
    links: List[Dict[str, Any]]
    revision_counter: int
    revision_budget: int
