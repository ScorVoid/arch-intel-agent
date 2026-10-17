"""
File: app.py
Purpose: Streamlit Interactive UI for ArchIntel-Agent.
Provides a daily intelligence feed browser and a semantic case study retrieval engine.
"""

import os
import sys
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import streamlit as st

# Ensure root dir in path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.case_study_db import CaseStudyDatabase
from src.ingestor import FeedIngestor
from src.ai_triage import AITriageEngine, NewsCategory
from src.digest_builder import DailyDigestBuilder

load_dotenv()

# Streamlit Page Config
st.set_page_config(
    page_title="ArchIntel-Agent | Architectural Intelligence",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling for Architectural Aesthetics
st.markdown("""
<style>
    .reportview-container {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    .metric-card {
        background: rgba(255, 255, 255, 0.04);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 10px;
        padding: 16px;
        margin-bottom: 12px;
    }
    .badge-arch {
        background-color: #1e3a8a;
        color: #93c5fd;
        padding: 3px 8px;
        border-radius: 6px;
        font-size: 0.8rem;
        font-weight: 600;
    }
    .badge-interior {
        background-color: #581c87;
        color: #d8b4fe;
        padding: 3px 8px;
        border-radius: 6px;
        font-size: 0.8rem;
        font-weight: 600;
    }
    .badge-material {
        background-color: #064e3b;
        color: #6ee7b7;
        padding: 3px 8px;
        border-radius: 6px;
        font-size: 0.8rem;
        font-weight: 600;
    }
    .material-pill {
        display: inline-block;
        background-color: rgba(255, 255, 255, 0.08);
        border: 1px solid rgba(255, 255, 255, 0.15);
        color: #e2e8f0;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 0.75rem;
        margin-right: 4px;
        margin-top: 4px;
    }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_db():
    return CaseStudyDatabase()


@st.cache_resource
def get_ingestor():
    return FeedIngestor()


db = get_db()
ingestor = get_ingestor()

# --- Sidebar ---
with st.sidebar:
    st.title("🏛️ ArchIntel-Agent")
    st.caption("Automated Architectural & Material Intelligence")

    st.markdown("---")
    st.subheader("System Status")
    
    total_indexed = db.get_total_count()
    st.metric(label="Case Studies Indexed", value=total_indexed)

    api_key = os.getenv("GEMINI_API_KEY")
    if api_key and api_key != "YOUR_GEMINI_API_KEY_HERE":
        st.success("🟢 Gemini API: Active")
        st.caption(f"Model: `{os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')}`")
    else:
        st.warning("🟡 Gemini API: Inactive (Using Offline Mode)")
        st.caption("Add key to `.env` for AI inference.")

    st.markdown("---")
    st.subheader("Whitelisted Publications")
    for src in ingestor.sources:
        status_icon = "✅" if src.get("enabled") else "⚪"
        st.markdown(f"{status_icon} **{src['name']}**  \n<small>{src.get('category_hint')}</small>", unsafe_allow_html=True)


# --- Main Tabs ---
tab_finder, tab_daily, tab_trigger = st.tabs([
    "🔍 Case Study Knowledge Engine",
    "📰 Daily Intelligence Briefs",
    "⚡ Ingest & Sync Pipeline"
])


# =====================================================================
# TAB 1: Future Project Case Study Finder
# =====================================================================
with tab_finder:
    st.header("Future Project Case Study Finder")
    st.markdown(
        "Search your verified precedent database using natural language design requirements, "
        "material specifications, climate conditions, or typology."
    )

    col1, col2 = st.columns([3, 1])
    with col1:
        query = st.text_input(
            "Design Requirements / Case Study Query:",
            value="Hospitality project in a humid coastal climate using sustainable timber and perforated brick",
            placeholder="e.g. Cultural center in a desert climate featuring rammed earth and passive solar shading"
        )
    with col2:
        top_k = st.slider("Results to Retrieve", min_value=1, max_value=15, value=5)

    col_filter1, col_filter2 = st.columns(2)
    with col_filter1:
        cat_filter = st.selectbox(
            "Filter by Category",
            ["ALL", "ARCHITECTURAL_NEWS", "INTERIOR_NEWS", "MATERIAL_LAUNCH_NEWS"]
        )
    with col_filter2:
        typology_input = st.text_input(
            "Filter by Typology (optional)",
            value="",
            placeholder="e.g. Hospitality, Residential, Cultural, Pavilions"
        )

    if st.button("Search Case Studies", type="primary", use_container_width=True):
        with st.spinner("Embedding query & searching semantic index..."):
            typ_filter = typology_input.strip() if typology_input.strip() else None
            results = db.search_case_studies(
                query=query,
                n_results=top_k,
                category=cat_filter,
                typology=typ_filter
            )

        if not results:
            st.info("No matching case studies found in the local database. Try running the Ingestion pipeline on Tab 3 to populate your knowledge base.")
        else:
            st.markdown(f"### Found {len(results)} Verified Precedents")
            for item in results:
                with st.container():
                    st.markdown("---")
                    col_header1, col_header2 = st.columns([4, 1])
                    with col_header1:
                        st.subheader(f"[{item['title']}]({item['url']})")
                    with col_header2:
                        st.markdown(f"**Match:** `{item['similarity_score'] * 100:.1f}%`")

                    # Badges
                    badge_class = "badge-arch"
                    if item['category'] == "INTERIOR_NEWS":
                        badge_class = "badge-interior"
                    elif item['category'] == "MATERIAL_LAUNCH_NEWS":
                        badge_class = "badge-material"

                    st.markdown(
                        f"<span class='{badge_class}'>{item['category']}</span> "
                        f"**Source:** {item['source_name']} | **Studio / Brand:** {item['architect_or_manufacturer']} | "
                        f"**Typology:** {item['project_typology']} | **Location:** {item['climate_or_location']}",
                        unsafe_allow_html=True
                    )

                    # Materials
                    materials = item.get("materials_used", "")
                    if materials:
                        pills = "".join(f"<span class='material-pill'>{m.strip()}</span>" for m in materials.split(",") if m.strip())
                        st.markdown(f"<div style='margin: 8px 0;'><strong>Materials:</strong> {pills}</div>", unsafe_allow_html=True)

                    # 3 Bullet Takeaways
                    st.markdown("**Executive Takeaways:**")
                    if item.get("bullet_1"):
                        st.markdown(f"- {item['bullet_1']}")
                    if item.get("bullet_2"):
                        st.markdown(f"- {item['bullet_2']}")
                    if item.get("bullet_3"):
                        st.markdown(f"- {item['bullet_3']}")


# =====================================================================
# TAB 2: Daily Intelligence Briefs
# =====================================================================
with tab_daily:
    st.header("Daily Architectural Intelligence Reports")
    
    reports_dir = ROOT_DIR / "reports"
    report_files = sorted(list(reports_dir.glob("*-daily-brief.md")), reverse=True) if reports_dir.exists() else []

    if not report_files:
        st.info("No daily briefs have been generated yet. Go to 'Ingest & Sync Pipeline' to run your first daily intelligence cycle.")
    else:
        selected_report = st.selectbox(
            "Select Daily Brief:",
            report_files,
            format_func=lambda p: p.name
        )

        if selected_report:
            with open(selected_report, "r", encoding="utf-8") as f:
                content = f.read()
            st.markdown(content)


# =====================================================================
# TAB 3: Ingest & Sync Pipeline
# =====================================================================
with tab_trigger:
    st.header("Trigger Pipeline Execution")
    st.markdown(
        "Run the automated ingestion pipeline directly from the dashboard. "
        "Fetches the latest articles from whitelisted feeds, executes AI triage, updates ChromaDB, and builds today's report."
    )

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        items_per_source = st.number_input("Max articles per feed", min_value=1, max_value=10, value=2)
    with col_btn2:
        skip_chroma = st.checkbox("Skip ChromaDB vector indexing", value=False)

    if st.button("🚀 Run Pipeline Now", type="primary"):
        with st.status("Executing Daily Pipeline...", expanded=True) as status:
            st.write("Fetching articles through Domain Guard...")
            articles = ingestor.ingest_all(max_items_per_source=items_per_source)
            st.write(f"Ingested {len(articles)} candidate articles from trusted sources.")

            st.write("Executing AI triage & structured extraction...")
            triage_engine = AITriageEngine()
            triaged_items = []
            for art in articles:
                analysis = triage_engine.triage_article(art)
                triaged_items.append({"article": art, "analysis": analysis})
            st.write(f"Triage complete for {len(triaged_items)} articles.")

            if not skip_chroma:
                st.write("Indexing into ChromaDB Case Study Knowledge Base...")
                for it in triaged_items:
                    db.index_article(it["article"], it["analysis"])
                st.write(f"Updated ChromaDB. Total items in DB: {db.get_total_count()}")

            st.write("Generating Daily Digest Markdown Brief...")
            builder = DailyDigestBuilder()
            report_path = builder.generate_digest(triaged_items)
            st.write(f"Saved: {report_path.name}")

            status.update(label="Pipeline execution completed successfully!", state="complete")
        st.success(f"Report ready in `{report_path.name}`! Check the 'Daily Intelligence Briefs' tab.")
