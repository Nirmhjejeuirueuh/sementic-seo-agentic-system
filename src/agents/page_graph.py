import os
import json
import logging
from typing import Dict, Any, List, Literal

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import InMemorySaver
# NOTE ON CHECKPOINTER FOR PRODUCTION DEPLOYMENT:
# Swap InMemorySaver with SqliteSaver or PostgresSaver for persistence.
# InMemorySaver silently loses state when the process exits.
# Example:
# from langgraph.checkpoint.sqlite import SqliteSaver
# checkpointer = SqliteSaver.from_conn_string("checkpoints.db")

from src.config import AGENT_PROVIDER, AGENT_MODEL, require_agent_key
from src.db import DatabaseManager
from src.agents.context import fetch_agent_context
from src.agents.state import AgentState, PageBrief, PageCritique, PageLinkPlan
from src.analyze.site_structure import pick_head_term

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def get_llm():
    """
    Instantiate the LLM for AGENT_PROVIDER (set in .env).

    require_agent_key() raises immediately if that provider's key is
    missing, rather than silently trying a fake key -- see
    src/config.py for why that matters.
    """
    api_key = require_agent_key()

    if AGENT_PROVIDER == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=AGENT_MODEL, anthropic_api_key=api_key, temperature=0.1)
    elif AGENT_PROVIDER == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=AGENT_MODEL, api_key=api_key, temperature=0.1)
    else:  # "gemini" -- config.py already validated AGENT_PROVIDER is one of the three
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=AGENT_MODEL, google_api_key=api_key, temperature=0.1)


# -------------------------------------------------------------------
# NODE FUNCTIONS
# -------------------------------------------------------------------

def load_context_node(state: AgentState) -> Dict[str, Any]:
    """Node 1: Load all graph context for cluster from Neo4j."""
    logger.info(f"[Agent] Step 1: Loading graph context for cluster {state['cluster_id']}...")
    db = DatabaseManager()
    context = fetch_agent_context(state["cluster_id"], db)
    db.close()

    return {
        "cluster_name": context["cluster_name"],
        "entities": context["entities"],
        "keywords": context["keywords"],
        "dominant_intent": context["dominant_intent"],
        "evidence_passages": context["evidence_passages"],
        "sibling_pages": context["sibling_pages"],
        "revision_counter": 0,
        "revision_budget": state.get("revision_budget", 2)
    }


def write_brief_node(state: AgentState) -> Dict[str, Any]:
    """Node 2: Generate structured SEO Page Brief."""
    logger.info("[Agent] Step 2: Generating structured content brief...")
    
    entities = state["entities"]
    must_cover = entities[:min(len(entities), 8)]
    # keywords_list is never empty here -- fetch_agent_context() raises
    # rather than returning an empty keyword list (src/agents/context.py).
    keywords_list = [k["name"] for k in state["keywords"]]

    # The head term by containment (src/analyze/site_structure.py,
    # already proven in Phase 6.2), not keywords_list[0]. Bare list
    # order is whatever context.py's Cypher ORDER BY produced --
    # alphabetical, since there's no real popularity signal to sort by
    # (Phase 5 has no search-volume data). For this cluster that meant
    # "angel memorial figurine" became the primary keyword simply
    # because "angel" sorts first, not because it's what the cluster is
    # actually about. pick_head_term finds "memorial figurine" instead,
    # the phrase 15 of this cluster's 49 keywords actually contain.
    primary_kw = pick_head_term([k["normalized"] for k in state["keywords"]])
    secondary_kws = [k for k in keywords_list if k.lower() != primary_kw][:4]

    # No fallback brief on failure. The removed code wrote a generic
    # "Complete Guide to X" / "Core Concepts & Architecture" brief on any
    # LLM error -- boilerplate lifted from an unrelated demo project, not
    # grounded in this cluster at all. A failed brief must stop the
    # pipeline here, visibly, not produce a page built on invented
    # structure (CLAUDE.md rule 9; same fix already applied to
    # fetch_agent_context, plan_links_node).
    llm = get_llm()
    structured_llm = llm.with_structured_output(PageBrief)
    prompt = f"""
    Create a detailed SEO Page Brief for a web page in topic cluster '{state['cluster_name']}'.
    Target Dominant Intent: {state['dominant_intent']}
    Primary Keyword: {primary_kw}
    Secondary Keywords: {secondary_kws}
    Cluster Entities Available: {entities}

    Requirement: Choose 5-10 entity names verbatim from the entity list for 'must_cover'.
    """
    brief_obj = structured_llm.invoke(prompt)
    if brief_obj is None:
        raise RuntimeError(
            f"write_brief_node: structured_llm.invoke() returned None for "
            f"cluster {state['cluster_id']!r}. The LLM call succeeded but "
            f"produced no parseable PageBrief."
        )
    brief = brief_obj.model_dump()

    return {"brief": brief}


def draft_node(state: AgentState) -> Dict[str, Any]:
    """
    Node 3: Generate Markdown Draft grounded in evidence passages.
    System instruction: ground every factual claim in supplied passages; if sources don't support a claim, omit it.
    """
    logger.info("[Agent] Step 3: Writing content draft grounded strictly in source passages...")

    brief = state["brief"] or {}

    # Numbered evidence blocks, not "Source [vault_FigurineType]: ...".
    # The old format echoed straight into the visible draft as literal
    # bracketed tags -- vault_FigurineType is a Neo4j Document.id
    # (src/ingest/vault.py: f"vault_{note_type}"), internal bookkeeping,
    # never meant to be customer-facing text. Numbering plus an explicit
    # instruction not to cite is the fix, not just relabeling the source.
    passages_text = "\n\n".join(
        f"Evidence {i}:\n{p.get('passage', '')}"
        for i, p in enumerate(state["evidence_passages"], start=1)
    )

    prompt = f"""
    You are an expert technical writer and SEO strategist.
    Write a complete Markdown document based on the brief below.

    BRIEF:
    H1: {brief.get('h1')}
    Primary Keyword: {brief.get('primary_keyword')}
    Intent: {brief.get('intent')}
    Must Cover Entities (Explain these thoroughly): {brief.get('must_cover')}
    Sections: {brief.get('h2_sections')}

    EVIDENCE (STRICT SOURCE GROUNDING):
    {passages_text}

    SYSTEM INSTRUCTIONS:
    - Ground every factual claim in the evidence above.
    - If the evidence does not support a claim, omit it or state what is verified by the source.
    - Never fill knowledge gaps from unverified external assumptions.
    - An entity counts as covered only if explained thoroughly, not if merely listed in a bullet.
    - Write natural prose. Do NOT include source labels, citation markers,
      document IDs, or brackets like "[Evidence 1]" anywhere in the output --
      the evidence is background for you, not text to quote its label.
    """

    # No fallback draft on failure -- see write_brief_node for why.
    llm = get_llm()
    res = llm.invoke(prompt)
    draft_content = res.content if hasattr(res, 'content') else str(res)

    return {"draft": draft_content}


def critique_node(state: AgentState) -> Dict[str, Any]:
    """Node 4: Critique draft against must_cover entities and intent alignment."""
    logger.info("[Agent] Step 4: Critiquing draft coverage and intent alignment...")

    brief = state["brief"] or {}
    must_cover = brief.get("must_cover", [])
    draft = state["draft"]

    # No fallback critique on failure. The removed code's "programmatic
    # critique" looked like a reasonable degraded mode -- it computed a
    # real coverage_score from the actual draft -- but it silently
    # replaced LLM judgment ("does the draft explain this entity
    # meaningfully?") with a plain substring check (does the entity's
    # name appear anywhere?), and nothing in the returned critique
    # distinguished which path produced it. should_revise() would trust
    # either score identically. A quality gate that can silently become
    # much easier to pass is worse than one that fails loudly.
    llm = get_llm()
    structured_llm = llm.with_structured_output(PageCritique)
    prompt = f"""
    Evaluate this article draft against the required entity list and intent.

    Must Cover Entities: {must_cover}
    Required Intent: {brief.get('intent')}

    Draft Content:
    {draft[:4000]}

    Rules:
    An entity counts as covered ONLY if the draft explains or uses it meaningfully in context, not if it merely appears in a bullet list.
    """
    critique_obj = structured_llm.invoke(prompt)
    if critique_obj is None:
        raise RuntimeError(
            f"critique_node: structured_llm.invoke() returned None for "
            f"cluster {state['cluster_id']!r}."
        )
    critique = critique_obj.model_dump()

    return {"critique": critique}


def should_revise(state: AgentState) -> Literal["revise", "plan_links"]:
    """Conditional Edge: Route to revise if coverage < 0.8, intent unsatisfied, or cannibalisation high."""
    critique = state.get("critique") or {}
    coverage = critique.get("coverage_score", 1.0)
    intent_match = critique.get("intent_match", True)
    risk = critique.get("cannibalisation_risk", "none")
    counter = state.get("revision_counter", 0)
    budget = state.get("revision_budget", 2)

    logger.info(f"[Agent Evaluation] Coverage: {coverage:.2f}, Intent Match: {intent_match}, Risk: {risk}, Revision: {counter}/{budget}")

    if counter < budget and (coverage < 0.8 or not intent_match or risk == "high"):
        logger.info("[Agent Routing] -> Routing to REVISE node.")
        return "revise"

    logger.info("[Agent Routing] -> Criteria met or budget reached. Routing to PLAN_LINKS node.")
    return "plan_links"


def revise_node(state: AgentState) -> Dict[str, Any]:
    """Node 5: Revise draft based on critique feedback."""
    counter = state.get("revision_counter", 0) + 1
    logger.info(f"[Agent] Step 5: Executing draft revision iteration {counter}...")

    critique = state.get("critique") or {}
    notes = critique.get("specific_revision_notes", "")
    missing = critique.get("missing", [])
    current_draft = state["draft"]

    prompt = f"""
    Revise the article draft to address missing entities and critique feedback.

    Missing Entities to Integrate & Explain: {missing}
    Revision Notes: {notes}

    Current Draft:
    {current_draft}
    """

    # No fallback revision on failure. The removed code appended
    # "{entity} plays a critical role in semantic topic cluster structure
    # and internal entity resolution" for every missing entity -- content
    # true of nothing in particular, appended to a REAL draft that would
    # otherwise have shipped as-is. That's worse than the unrevised draft:
    # it looks like the missing coverage was addressed when it wasn't.
    llm = get_llm()
    res = llm.invoke(prompt)
    revised_draft = res.content if hasattr(res, 'content') else str(res)

    return {
        "draft": revised_draft,
        "revision_counter": counter
    }


def plan_links_node(state: AgentState) -> Dict[str, Any]:
    """
    Node 6: Propose internal links whose anchor text appears verbatim in
    the draft.

    No invented fallback link when nothing matches. The removed code
    appended a link with anchor_text="topic clusters" pointing at
    whichever sibling happened to be first, whenever no real sibling
    name appeared in the draft -- which directly contradicted this
    function's own stated contract ("verbatim anchor text"), and put a
    link into the persisted page whose anchor text doesn't exist in the
    page. Zero proposed links is the correct, honest answer when nothing
    matches (CLAUDE.md rule 9) -- real relevance-based suggestions
    (matching by shared entity/topic instead of literal text) are
    Phase 8's job, not a place-holder here.
    """
    logger.info("[Agent] Step 6: Planning internal links with verbatim anchor text matching...")

    siblings = state.get("sibling_pages", [])
    draft = state["draft"]
    proposed_links = []

    for sib in siblings:
        phrase = sib.replace("-", " ")
        if phrase.lower() in draft.lower():
            proposed_links.append({
                "target_slug": sib,
                "anchor_text": phrase,
                "relationship_reason": f"Verbatim mention of sibling topic '{phrase}' in the draft"
            })

    if not proposed_links:
        logger.info(
            "[Agent] 0 internal links proposed -- no sibling page name appears "
            "verbatim in the draft. Expected; not an error."
        )

    return {"links": proposed_links}


def persist_node(state: AgentState) -> Dict[str, Any]:
    """
    Node 7: Write output file with JSON frontmatter and update the
    Cluster's Page in Neo4j.

    Fills in the Page Phase 6.2 already planned -- it does not create a
    new one. The removed code did `MERGE (p:Page {slug: $slug})` where
    slug came from the LLM's brief, which almost never matches the real
    planned slug (site_structure.py derives it from the cluster name,
    e.g. "corporate-gifts"; the LLM invents its own from the H1 it
    wrote, e.g. "custom-trophies-awards"). Checked after generating 6
    real pages: 4 of 6 created a second, disconnected Page node instead
    of filling in the real one -- the site ended up with two different
    "pages" for the same cluster, one of them not even the URL that
    would go live.
    """
    logger.info("[Agent] Step 7: Persisting output markdown file and updating Neo4j graph...")

    db = DatabaseManager()

    # The real page Phase 6.2 planned for this cluster. Every cluster
    # gets one (src/analyze/site_structure.py), so this should always
    # find something -- if it doesn't, that's a pipeline gap worth
    # knowing about, not something to paper over with a guessed slug.
    existing = db.execute_query(
        "MATCH (p:Page)-[:COVERS]->(cl:Cluster {id: $cluster_id}) "
        "RETURN p.url AS url, p.slug AS slug",
        {"cluster_id": state["cluster_id"]},
    )
    if not existing:
        db.close()
        raise RuntimeError(
            f"No Page covers cluster {state['cluster_id']!r}. "
            f"Run src/analyze/site_structure.py before generating pages."
        )
    slug = existing[0]["slug"]

    brief = state.get("brief") or {}
    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)
    file_path = os.path.join(output_dir, f"{slug}.md")

    frontmatter = {
        "title": brief.get("h1"),
        "slug": slug,
        "meta_description": brief.get("meta_description"),
        "primary_keyword": brief.get("primary_keyword"),
        "intent": brief.get("intent"),
        "cluster_id": state["cluster_id"],
        "coverage_score": state.get("critique", {}).get("coverage_score", 1.0),
        "internal_links": state.get("links", [])
    }

    content_with_frontmatter = f"---\n{json.dumps(frontmatter, indent=2)}\n---\n\n{state['draft']}"

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content_with_frontmatter)

    cypher_persist = """
    MATCH (p:Page)-[:COVERS]->(cl:Cluster {id: $cluster_id})
    SET p.title = $title,
        p.draft_status = 'draft',
        p.coverage_score = $coverage_score,
        p.updatedAt = timestamp()

    WITH p
    UNWIND $links AS link
    MERGE (p2:Page {slug: link.target_slug})
    MERGE (p)-[r:LINKS_TO]->(p2)
    SET r.anchor_text = link.anchor_text, r.createdAt = timestamp()
    """

    db.execute_query(cypher_persist, {
        "cluster_id": state["cluster_id"],
        "title": brief.get("h1", slug),
        "coverage_score": state.get("critique", {}).get("coverage_score", 1.0),
        "links": state.get("links", [])
    })
    db.close()

    logger.info(f"Page persisted successfully to {file_path}")
    return {}


# -------------------------------------------------------------------
# BUILD LANGGRAPH WORKFLOW
# -------------------------------------------------------------------

def build_page_generation_graph():
    workflow = StateGraph(AgentState)

    # Add Nodes
    workflow.add_node("load_context", load_context_node)
    workflow.add_node("write_brief", write_brief_node)
    workflow.add_node("draft", draft_node)
    workflow.add_node("critique", critique_node)
    workflow.add_node("revise", revise_node)
    workflow.add_node("plan_links", plan_links_node)
    workflow.add_node("persist", persist_node)

    # Entry point
    workflow.set_entry_point("load_context")

    # Linear edges
    workflow.add_edge("load_context", "write_brief")
    workflow.add_edge("write_brief", "draft")
    workflow.add_edge("draft", "critique")

    # Conditional edge after critique
    workflow.add_conditional_edges(
        "critique",
        should_revise,
        {
            "revise": "revise",
            "plan_links": "plan_links"
        }
    )

    workflow.add_edge("revise", "critique")
    workflow.add_edge("plan_links", "persist")
    workflow.add_edge("persist", END)

    # InMemorySaver for local execution
    memory = InMemorySaver()
    app = workflow.compile(checkpointer=memory)
    return app


def generate_page_for_cluster(cluster_id: str):
    app = build_page_generation_graph()
    initial_state = {
        "cluster_id": cluster_id,
        "revision_budget": 2
    }
    config = {"configurable": {"thread_id": f"thread_{cluster_id}"}}
    result = app.invoke(initial_state, config=config)
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run LangGraph Page Generation Workflow")
    parser.add_argument("--cluster-id", type=str, default="cluster_Topic", help="Cluster ID to generate page for")
    args = parser.parse_args()

    res = generate_page_for_cluster(args.cluster_id)
    print("Page Generation Completed successfully!")
    print("Draft Slug:", res.get("brief", {}).get("slug"))
    print("Coverage Score:", res.get("critique", {}).get("coverage_score"))
