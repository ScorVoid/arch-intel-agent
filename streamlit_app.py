"""
File: app.py
Purpose: Streamlit Studio Workstation for ArchIntel-Agent.
Features:
- Semantic Case Study & Material Precedent Research Engine
- 1-Click Client-Ready Word (.docx) & Markdown Dossier Synthesizer
- Saved Project Bookmarks & Precedent Shortlist (SQLite persistence)
- 3-Part Daily Architectural Intelligence Brief Explorer
- Pipeline Sync & Live Ingestion Trigger
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
from src.dossier_generator import DossierGenerator

load_dotenv()

# Streamlit Page Config
st.set_page_config(
    page_title="ArchIntel Studio | Architectural Design Workstation",
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
    .dossier-box {
        background: rgba(30, 58, 138, 0.15);
        border: 1px solid rgba(147, 197, 253, 0.3);
        border-radius: 10px;
        padding: 20px;
        margin-top: 24px;
        margin-bottom: 24px;
    }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_db():
    return CaseStudyDatabase()


@st.cache_resource
def get_ingestor():
    return FeedIngestor()


@st.cache_resource
def get_dossier_gen():
    return DossierGenerator()


db = get_db()
ingestor = get_ingestor()
dossier_gen = get_dossier_gen()

# --- Sidebar ---
with st.sidebar:
    st.title("🏛️ ArchIntel Studio")
    st.caption("Architectural & Material Design Research Workstation")

    st.markdown("---")
    st.subheader("Knowledge Base Status")
    
    total_indexed = db.get_total_count()
    bookmarked_count = len(db.get_bookmarked())
    
    col_sb1, col_sb2 = st.columns(2)
    with col_sb1:
        st.metric(label="Total Indexed", value=total_indexed)
    with col_sb2:
        st.metric(label="Shortlisted", value=bookmarked_count)

    api_key = os.getenv("GEMINI_API_KEY")
    if api_key and api_key != "YOUR_GEMINI_API_KEY_HERE":
        st.success("🟢 Gemini Inference: Active")
        st.caption(f"Reasoning: `{os.getenv('GEMINI_MODEL', 'gemini-3.8-flash')}`")
        st.caption(f"Vectors: `{os.getenv('GEMINI_EMBEDDING_MODEL', 'gemini-embedding-001')}`")
    else:
        st.warning("🟡 Gemini API: Inactive (Using Offline Mode)")

    st.markdown("---")
    st.subheader("Curated Publications")
    for src in ingestor.sources:
        status_icon = "✅" if src.get("enabled") else "⚪"
        st.markdown(f"{status_icon} **{src['name']}**  \n<small>{src.get('category_hint')}</small>", unsafe_allow_html=True)


# --- Main Studio Tabs ---
tab_finder, tab_bookmarks, tab_daily, tab_trigger = st.tabs([
    "🔍 Case Study Research Engine",
    f"⭐ Saved Shortlist ({bookmarked_count})",
    "📰 Daily Intelligence Briefs",
    "⚡ Ingest & Sync Pipeline"
])


# =====================================================================
# TAB 1: Future Project Case Study Finder & Dossier Synthesizer
# =====================================================================
with tab_finder:
    st.header("Future Project Case Study & Material Precedent Finder")
    st.markdown(
        "Search your verified precedent database using natural language design requirements, "
        "regional climate conditions, structural systems, or material palettes."
    )

    query = st.text_input(
        "Enter Project Design Brief / Requirements:",
        value="Luxury eco-resort in coastal Maharashtra using laterite stone, lime plaster, and passive cooling",
        placeholder="e.g. Cultural center in a desert climate featuring rammed earth and passive solar shading"
    )

    col_f1, col_f2, col_f3 = st.columns([2, 1.5, 1])
    with col_f1:
        categories_selected = st.multiselect(
            "Filter Categories",
            options=["ARCHITECTURAL_NEWS", "INTERIOR_NEWS", "MATERIAL_LAUNCH_NEWS"],
            default=["ARCHITECTURAL_NEWS", "INTERIOR_NEWS", "MATERIAL_LAUNCH_NEWS"]
        )
    with col_f2:
        typology_filter = st.text_input(
            "Typology Filter (optional)",
            value="",
            placeholder="e.g. Hospitality, Residential, Civic, Cultural"
        )
    with col_f3:
        min_relevance = st.slider("Min. Relevance %", min_value=0, max_value=90, value=30, step=5)

    col_btn_search, col_btn_dossier = st.columns([1, 1])
    with col_btn_search:
        search_clicked = st.button("🔍 Search Precedents", type="primary", use_container_width=True)

    # State management for search results
    if search_clicked or "last_search_results" not in st.session_state:
        with st.spinner("Querying vector index & calculating semantic proximity..."):
            cat_param = categories_selected[0] if len(categories_selected) == 1 else None
            raw_results = db.search_case_studies(
                query=query,
                n_results=12,
                category=cat_param,
                typology=typology_filter.strip() if typology_filter.strip() else None
            )
            # Filter by multi-select and min_relevance
            filtered_results = [
                r for r in raw_results
                if (r["category"] in categories_selected) and (r["similarity_score"] * 100 >= min_relevance)
            ]
            st.session_state["last_search_results"] = filtered_results
            st.session_state["last_search_query"] = query

    results = st.session_state.get("last_search_results", [])
    current_query = st.session_state.get("last_search_query", query)

    # --- Precedent Results View ---
    if not results:
        st.info("No precedents matched your query and filter criteria. Try adjusting the minimum relevance slider or search terms.")
    else:
        st.markdown(f"### Found {len(results)} Verified Architectural Precedents")

        # Dossier Synthesis Banner
        with st.container():
            st.markdown("""
            <div class='dossier-box'>
                <h4 style='margin-top:0; color:#93c5fd;'>📄 Client-Ready Case Study & Material Precedent Dossier</h4>
                <p style='color:#e2e8f0; font-size:0.9rem;'>
                    Synthesize an executive architectural report with comparative matrix, material palette recommendations, 
                    and strict citations exported directly into <b>Microsoft Word (.docx)</b> and Markdown.
                </p>
            </div>
            """, unsafe_allow_html=True)

            if st.button("⚡ Generate Word (.docx) Case Study Dossier", type="secondary", use_container_width=True):
                with st.spinner("Synthesizing comparative matrix and formatting Word document via Gemini..."):
                    dossier_res = dossier_gen.generate_dossier(
                        project_brief=current_query,
                        top_k=min(len(results), 6)
                    )
                    if dossier_res["success"]:
                        st.session_state["active_dossier"] = dossier_res
                        st.success(f"Dossier generated: `{dossier_res['docx_filename']}`")

        # Display download buttons if dossier is ready
        if "active_dossier" in st.session_state:
            active_d = st.session_state["active_dossier"]
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                with open(active_d["docx_path"], "rb") as f:
                    st.download_button(
                        label="📥 Download Word Document (.docx)",
                        data=f.read(),
                        file_name=active_d["docx_filename"],
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        use_container_width=True
                    )
            with col_d2:
                with open(active_d["md_path"], "r", encoding="utf-8") as f:
                    st.download_button(
                        label="📄 Download Markdown Report (.md)",
                        data=f.read(),
                        file_name=active_d["md_filename"],
                        mime="text/markdown",
                        use_container_width=True
                    )

            with st.expander("👁️ Preview Synthesized Dossier Text", expanded=False):
                st.markdown(active_d["synthesis_markdown"])

        st.markdown("---")

        # Render Individual Result Cards
        for idx, item in enumerate(results):
            with st.container():
                col_header1, col_header2 = st.columns([5, 1])
                with col_header1:
                    st.markdown(f"#### [{item['title']}]({item['url']})")
                with col_header2:
                    st.markdown(f"**Match:** `{item['similarity_score'] * 100:.1f}%`")
                    # Bookmark Star Button
                    is_saved = bool(item.get("is_bookmarked", 0))
                    btn_label = "★ Saved" if is_saved else "☆ Shortlist"
                    if st.button(btn_label, key=f"bm_{item['id']}_{idx}"):
                        new_state = db.toggle_bookmark(item['id'])
                        item["is_bookmarked"] = int(new_state)
                        st.rerun()

                # Badges
                badge_class = "badge-arch"
                if item['category'] == "INTERIOR_NEWS":
                    badge_class = "badge-interior"
                elif item['category'] == "MATERIAL_LAUNCH_NEWS":
                    badge_class = "badge-material"

                st.markdown(
                    f"<span class='{badge_class}'>{item['category']}</span> "
                    f"**Source:** {item['source_name']} | **Lead Studio / Brand:** {item['architect_or_manufacturer']} | "
                    f"**Typology:** {item['project_typology']} | **Location / Climate:** {item['climate_or_location']}",
                    unsafe_allow_html=True
                )

                # Materials
                materials = item.get("materials_used", "")
                if materials and materials != "N/A":
                    pills = "".join(f"<span class='material-pill'>{m.strip()}</span>" for m in materials.split(",") if m.strip())
                    st.markdown(f"<div style='margin: 8px 0;'><strong>Materials:</strong> {pills}</div>", unsafe_allow_html=True)

                # 3-Bullet Summary
                st.markdown("**Executive Takeaways:**")
                if item.get("bullet_1"):
                    st.markdown(f"- {item['bullet_1']}")
                if item.get("bullet_2"):
                    st.markdown(f"- {item['bullet_2']}")
                if item.get("bullet_3"):
                    st.markdown(f"- {item['bullet_3']}")

                st.markdown("---")


# =====================================================================
# TAB 2: Saved Shortlist & Bookmarks
# =====================================================================
with tab_bookmarks:
    st.header(f"⭐ Saved Project Shortlist ({bookmarked_count})")
    st.markdown("Your persistent library of bookmarked architectural precedents, interior spaces, and material launches.")

    saved_items = db.get_bookmarked()

    if not saved_items:
        st.info("No case studies bookmarked yet. Click '☆ Shortlist' on any precedent in the Research Engine to pin it here.")
    else:
        col_bm_actions1, col_bm_actions2 = st.columns([3, 1])
        with col_bm_actions1:
            st.markdown(f"**{len(saved_items)}** precedents ready for project specification.")
        with col_bm_actions2:
            if st.button("⚡ Export Shortlist to Word (.docx)", use_container_width=True):
                with st.spinner("Generating shortlist dossier..."):
                    dossier_res = dossier_gen.generate_dossier(
                        project_brief="Curated Project Precedent Shortlist",
                        top_k=len(saved_items)
                    )
                    st.session_state["shortlist_dossier"] = dossier_res
                    st.rerun()

        if "shortlist_dossier" in st.session_state:
            sld = st.session_state["shortlist_dossier"]
            with open(sld["docx_path"], "rb") as f:
                st.download_button(
                    label="📥 Download Shortlist Dossier (.docx)",
                    data=f.read(),
                    file_name=sld["docx_filename"],
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True
                )

        st.markdown("---")
        for s_idx, s_item in enumerate(saved_items):
            with st.container():
                col_s1, col_s2 = st.columns([5, 1])
                with col_s1:
                    st.markdown(f"#### [{s_item['title']}]({s_item['url']})")
                with col_s2:
                    if st.button("❌ Remove", key=f"del_bm_{s_item['id']}_{s_idx}"):
                        db.toggle_bookmark(s_item["id"])
                        st.rerun()

                st.markdown(
                    f"**Category:** `{s_item['category']}` | **Studio:** {s_item['architect_or_manufacturer']} | "
                    f"**Typology:** {s_item['project_typology']} | **Location:** {s_item['climate_or_location']}"
                )

                if s_item.get("materials_used"):
                    st.markdown(f"**Materials:** `{s_item['materials_used']}`")

                if s_item.get("bullet_1"):
                    st.markdown(f"- {s_item['bullet_1']}")
                st.markdown("---")


# =====================================================================
# TAB 3: Daily Intelligence Briefs
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
# TAB 4: Ingest & Sync Pipeline
# =====================================================================
with tab_trigger:
    st.header("Trigger Pipeline Execution")
    st.markdown(
        "Run the automated ingestion pipeline directly from the workstation. "
        "Fetches the latest articles from whitelisted feeds (including Indian & global publications), "
        "executes AI triage with `gemini-3.8-flash`, updates SQLite vector store, and builds today's report."
    )

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        items_per_source = st.number_input("Max articles per feed", min_value=1, max_value=10, value=3)
    with col_btn2:
        skip_chroma = st.checkbox("Skip vector indexing", value=False)

    if st.button("🚀 Run Live Pipeline Now", type="primary"):
        with st.status("Executing Daily Pipeline...", expanded=True) as status:
            st.write("Fetching articles through Domain Guard...")
            articles = ingestor.ingest_all(max_items_per_source=items_per_source)
            st.write(f"Ingested {len(articles)} candidate articles from trusted sources.")

            st.write("Executing AI triage & structured extraction with Gemini 3.8 Flash...")
            triage_engine = AITriageEngine()
            triaged_items = []
            for art in articles:
                analysis = triage_engine.triage_article(art)
                triaged_items.append({"article": art, "analysis": analysis})
            st.write(f"Triage complete for {len(triaged_items)} articles.")

            if not skip_chroma:
                st.write("Indexing into SQLite 3072-d Vector Knowledge Base...")
                for it in triaged_items:
                    db.index_article(it["article"], it["analysis"])
                st.write(f"Updated SQLite vector store. Total items in DB: {db.get_total_count()}")

            st.write("Generating Daily Digest Markdown Brief...")
            builder = DailyDigestBuilder()
            report_path = builder.generate_digest(triaged_items)
            st.write(f"Saved: {report_path.name}")

            status.update(label="Pipeline execution completed successfully!", state="complete")
        st.success(f"Report ready in `{report_path.name}`! Check the 'Daily Intelligence Briefs' tab.")
