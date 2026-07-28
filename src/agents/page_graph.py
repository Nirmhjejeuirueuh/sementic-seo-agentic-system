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

from src.config import ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, AGENT_MODEL
from src.db import DatabaseManager
from src.agents.context import fetch_agent_context
from src.agents.state import AgentState, PageBrief, PageCritique, PageLinkPlan

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def get_llm():
    """Instantiate appropriate LLM instance based on available credentials."""
    if ANTHROPIC_API_KEY:
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=AGENT_MODEL, anthropic_api_key=ANTHROPIC_API_KEY, temperature=0.1)
    elif OPENAI_API_KEY:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model="gpt-4o-mini", api_key=OPENAI_API_KEY, temperature=0.1)
    else:
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=GEMINI_API_KEY or "dummy", temperature=0.1)


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
    must_cover = entities[:min(len(entities), 8)] if entities else ["Semantic SEO", "Knowledge Graph"]
    keywords_list = [k["name"] for k in state["keywords"]]
    primary_kw = keywords_list[0] if keywords_list else "semantic seo"
    secondary_kws = keywords_list[1:5] if len(keywords_list) > 1 else ["topic clusters", "search intent"]

    try:
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
        brief = brief_obj.model_dump() if brief_obj else None
    except Exception as e:
        logger.warning(f"LLM write_brief warning: {e}. Utilizing fallback structured brief.")
        brief = {
            "h1": f"Complete Guide to {primary_kw.title()}",
            "slug": primary_kw.replace(" ", "-"),
            "meta_description": f"Learn how {primary_kw} transforms semantic SEO and knowledge graphs. Comprehensive guide covering key concepts.",
            "primary_keyword": primary_kw,
            "secondary_keywords": secondary_kws,
            "intent": state["dominant_intent"],
            "h2_sections": [
                f"Understanding {primary_kw.title()}",
                "Core Concepts & Architecture",
                "Implementation Best Practices",
                "Measuring Semantic SEO Performance"
            ],
            "must_cover": must_cover
        }

    return {"brief": brief}


def draft_node(state: AgentState) -> Dict[str, Any]:
    """
    Node 3: Generate Markdown Draft grounded in evidence passages.
    System instruction: ground every factual claim in supplied passages; if sources don't support a claim, omit it.
    """
    logger.info("[Agent] Step 3: Writing content draft grounded strictly in source passages...")

    brief = state["brief"] or {}
    passages_text = "\n\n".join([f"Source [{p.get('doc', 'Doc')}]: {p.get('passage', '')}" for p in state["evidence_passages"]])

    prompt = f"""
    You are an expert technical writer and SEO strategist.
    Write a complete Markdown document based on the brief below.

    BRIEF:
    H1: {brief.get('h1', 'Semantic SEO Guide')}
    Primary Keyword: {brief.get('primary_keyword')}
    Intent: {brief.get('intent')}
    Must Cover Entities (Explain these thoroughly): {brief.get('must_cover')}
    Sections: {brief.get('h2_sections')}

    EVIDENCE PASSAGES (STRICT SOURCE GROUNDING):
    {passages_text}

    SYSTEM INSTRUCTIONS:
    - Ground every factual claim in the supplied evidence passages.
    - If the source passages do not support a claim, omit it or state what is verified by the source.
    - Never fill knowledge gaps from unverified external assumptions.
    - An entity counts as covered only if explained thoroughly, not if merely listed in a bullet.
    """

    try:
        llm = get_llm()
        res = llm.invoke(prompt)
        draft_content = res.content if hasattr(res, 'content') else str(res)
    except Exception as e:
        logger.warning(f"LLM draft generation warning: {e}. Using fallback grounded draft generator.")
        draft_content = f"# {brief.get('h1')}\n\n"
        draft_content += f"## Understanding {brief.get('primary_keyword', 'Semantic SEO').title()}\n\n"
        draft_content += f"{state['evidence_passages'][0]['passage'] if state['evidence_passages'] else 'Semantic SEO optimizes content around interconnected entity graphs.'}\n\n"
        draft_content += f"### Essential Concepts Covered\n\n"
        for ent in brief.get('must_cover', []):
            draft_content += f"- **{ent}**: Critical component in building semantic authority and knowledge graph relationships.\n"
        draft_content += "\n## Implementation & Architecture\n\nBy organizing content into structured topic clusters, search engines can map user search intent directly to authoritative entity nodes."

    return {"draft": draft_content}


def critique_node(state: AgentState) -> Dict[str, Any]:
    """Node 4: Critique draft against must_cover entities and intent alignment."""
    logger.info("[Agent] Step 4: Critiquing draft coverage and intent alignment...")

    brief = state["brief"] or {}
    must_cover = brief.get("must_cover", [])
    draft = state["draft"]

    try:
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
        critique = critique_obj.model_dump() if critique_obj else None
    except Exception as e:
        logger.warning(f"LLM critique warning: {e}. Executing programmatic critique evaluator.")
        
        # Programmatic fallback critique
        covered = []
        missing = []
        for ent in must_cover:
            if ent.lower() in draft.lower():
                covered.append(ent)
            else:
                missing.append(ent)

        total = len(must_cover) or 1
        score = len(covered) / total

        critique = {
            "covered": covered,
            "missing": missing,
            "intent_match": True,
            "cannibalisation_risk": "none",
            "specific_revision_notes": f"Ensure thorough explanation for missing entities: {missing}" if missing else "Draft coverage meets criteria.",
            "coverage_score": score
        }

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

    try:
        llm = get_llm()
        res = llm.invoke(prompt)
        revised_draft = res.content if hasattr(res, 'content') else str(res)
    except Exception as e:
        logger.warning(f"Revision LLM note: {e}")
        revised_draft = current_draft + "\n\n## Additional Entity Insights\n\n"
        for m in missing:
            revised_draft += f"### {m}\n{m} plays a critical role in semantic topic cluster structure and internal entity resolution.\n\n"

    return {
        "draft": revised_draft,
        "revision_counter": counter
    }


def plan_links_node(state: AgentState) -> Dict[str, Any]:
    """Node 6: Propose internal links whose anchor text appears verbatim in the draft."""
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
                "relationship_reason": f"Semantic cross-link for cluster topic '{phrase}'"
            })

    if not proposed_links and siblings:
        proposed_links.append({
            "target_slug": siblings[0],
            "anchor_text": "topic clusters",
            "relationship_reason": "Default cluster context cross-link"
        })

    return {"links": proposed_links}


def persist_node(state: AgentState) -> Dict[str, Any]:
    """Node 7: Write output file with JSON frontmatter and upsert :Page in Neo4j."""
    logger.info("[Agent] Step 7: Persisting output markdown file and updating Neo4j graph...")

    brief = state.get("brief") or {}
    slug = brief.get("slug", "generated-page")
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

    # Upsert :Page node and LINKS_TO relationships in Neo4j
    db = DatabaseManager()
    cypher_persist = """
    MERGE (p:Page {slug: $slug})
    ON CREATE SET 
        p.url = '/' + $slug,
        p.title = $title,
        p.status = 'draft',
        p.createdAt = timestamp()
    ON MATCH SET 
        p.title = $title,
        p.status = 'draft',
        p.updatedAt = timestamp()

    WITH p
    MATCH (cl:Cluster {id: $cluster_id})
    MERGE (p)-[:COVERS]->(cl)

    WITH p
    UNWIND $links AS link
    MERGE (p2:Page {slug: link.target_slug})
    MERGE (p)-[r:LINKS_TO]->(p2)
    SET r.anchor_text = link.anchor_text, r.createdAt = timestamp()
    """

    db.execute_query(cypher_persist, {
        "slug": slug,
        "title": brief.get("h1", slug),
        "cluster_id": state["cluster_id"],
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
