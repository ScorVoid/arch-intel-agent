"""
Module: api/index.py
Purpose: Vercel-Compatible FastAPI Serverless Application & Architectural Studio Web Portal.
"""

import os
import sys
import io
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, Request, HTTPException, Query, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# Ensure project root in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.case_study_db import CaseStudyDatabase
from src.dossier_generator import DossierGenerator
from src.ingestor import FeedIngestor
from src.ai_triage import AITriageEngine
from src.digest_builder import DailyDigestBuilder

load_dotenv()
logger = logging.getLogger("ArchIntel.API")

# Top-level ASGI Application for Vercel
app = FastAPI(
    title="ArchIntel Studio",
    description="Automated Architectural Intelligence & Case Study Retrieval Workstation",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def vercel_cli_rewrite_middleware(request: Request, call_next):
    """
    Normalizes request paths when Vercel CLI 64+ rewrites requests to /api/index.py.
    Strips the destination prefix so FastAPI routes match cleanly regardless of proxy rewrites.
    """
    path = request.scope.get("path", "")
    for prefix in ["/api/index.py", "/api/index"]:
        if path.startswith(prefix):
            remainder = path[len(prefix):]
            request.scope["path"] = remainder if remainder else "/"
            break
    response = await call_next(request)
    return response


# Global Lazy-loaded engines
_db: Optional[CaseStudyDatabase] = None
_dossier_gen: Optional[DossierGenerator] = None


def get_db() -> CaseStudyDatabase:
    global _db
    if _db is None:
        _db = CaseStudyDatabase()
    return _db


def get_dossier_gen() -> DossierGenerator:
    global _dossier_gen
    if _dossier_gen is None:
        _dossier_gen = DossierGenerator()
    return _dossier_gen


# Request Models
class SearchRequest(BaseModel):
    query: str
    category: Optional[str] = "ALL"
    typology: Optional[str] = None
    min_relevance: Optional[float] = 0.0
    limit: Optional[int] = 12


class DossierRequest(BaseModel):
    brief: Optional[str] = "Synthesis of Shortlisted Architectural Precedents"
    top_k: Optional[int] = 5
    article_ids: Optional[List[str]] = None


class BookmarkRequest(BaseModel):
    id: Optional[str] = None
    url: Optional[str] = None


# API Routes
@app.get("/api/health")
def health():
    db = get_db()
    return {
        "status": "healthy",
        "total_precedents": db.get_total_count(),
        "reasoning_model": os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
        "embedding_model": os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001"),
        "is_vercel": os.environ.get("VERCEL") == "1",
        "db_path": str(db.db_path)
    }


@app.get("/api/articles")
def get_articles(
    category: Optional[str] = Query(None, description="ARCHITECTURAL_NEWS, INTERIOR_NEWS, MATERIAL_LAUNCH_NEWS"),
    limit: int = Query(50, ge=1, le=100)
):
    db = get_db()
    items = db.get_all_recent(limit=limit, category=category)
    return {
        "count": len(items),
        "category": category or "ALL",
        "items": items
    }


@app.post("/api/search")
def search_precedents(req: SearchRequest):
    db = get_db()
    cat_param = req.category if req.category and req.category != "ALL" else None
    raw_results = db.search_case_studies(
        query=req.query,
        n_results=req.limit or 12,
        category=cat_param,
        typology=req.typology.strip() if req.typology and req.typology.strip() else None
    )

    filtered = [
        r for r in raw_results
        if (r["similarity_score"] * 100 >= (req.min_relevance or 0))
    ]

    return {
        "query": req.query,
        "count": len(filtered),
        "results": filtered
    }


@app.post("/api/dossier")
def generate_dossier_download(req: DossierRequest):
    """
    Synthesizes a structured Case Study Dossier and streams the .docx file directly to browser.
    Can be generated from a design brief OR from explicitly shortlisted article_ids.
    """
    brief = (req.brief or "").strip()
    if not req.article_ids and len(brief) < 5:
        raise HTTPException(status_code=400, detail="Project design brief or shortlisted article IDs required.")

    dossier_gen = get_dossier_gen()
    result = dossier_gen.generate_dossier(
        project_brief=brief or "Curated Architectural Precedent Review",
        top_k=req.top_k or 5,
        article_ids=req.article_ids
    )

    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "Failed to generate dossier."))

    docx_bytes = result.get("docx_bytes")
    if not docx_bytes and result.get("docx_path"):
        try:
            with open(result["docx_path"], "rb") as f:
                docx_bytes = f.read()
        except Exception:
            pass

    if not docx_bytes:
        raise HTTPException(status_code=500, detail="Could not retrieve generated Word document bytes.")

    filename = result.get("docx_filename", "Architectural-Dossier.docx")
    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Dossier-Filename": filename
        }
    )


@app.post("/api/dossier/preview")
def generate_dossier_preview(req: DossierRequest):
    """
    Synthesizes the dossier and returns the Markdown text & precedent metadata for in-browser preview.
    Supports either a design brief or shortlisted article_ids.
    """
    brief = (req.brief or "").strip()
    if not req.article_ids and len(brief) < 5:
        raise HTTPException(status_code=400, detail="Project design brief or shortlisted article IDs required.")

    dossier_gen = get_dossier_gen()
    result = dossier_gen.generate_dossier(
        project_brief=brief or "Curated Architectural Precedent Review",
        top_k=req.top_k or 5,
        article_ids=req.article_ids
    )

    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "Failed to synthesize dossier."))

    return {
        "success": True,
        "brief": result.get("project_brief", req.brief),
        "markdown": result.get("synthesis_markdown", ""),
        "filename": result.get("docx_filename", "dossier.docx"),
        "precedents": result.get("precedents", [])
    }


@app.post("/api/bookmark")
def toggle_bookmark_endpoint(req: BookmarkRequest):
    """
    Shortlists or un-shortlists an architectural precedent by ID or URL.
    """
    db = get_db()
    identifier = req.id or req.url
    if not identifier:
        raise HTTPException(status_code=400, detail="Missing 'id' or 'url' in request.")
    new_state = db.toggle_bookmark(identifier)
    return {"success": True, "identifier": identifier, "is_bookmarked": new_state}


@app.get("/api/bookmarks")
def list_bookmarks():
    """Returns all shortlisted/bookmarked architectural case studies."""
    db = get_db()
    bookmarks = db.get_bookmarked()
    return {"count": len(bookmarks), "items": bookmarks}


@app.post("/api/ingest")
def trigger_ingest(
    max_items: int = Query(1, ge=1, le=5),
    max_sources: int = Query(3, ge=1, le=10)
):
    """
    Triggers fast, serverless-safe live ingestion and triage cycle.
    Constrained to top verified sources (max 3 sources, 1 item each by default)
    so execution finishes comfortably in under 15 seconds on Vercel serverless functions.
    """
    try:
        ingestor = FeedIngestor()
        enabled_sources = [s for s in ingestor.sources if s.get("enabled", True)][:max_sources]

        articles = []
        for src in enabled_sources:
            try:
                items = ingestor.ingest_feed(src, max_items=max_items)
                articles.extend(items)
            except Exception as e:
                logger.warning(f"Error reading feed {src.get('name')}: {e}")

        triage_engine = AITriageEngine()
        db = get_db()

        triaged_items = []
        indexed_count = 0
        for art in articles:
            try:
                analysis = triage_engine.triage_article(art)
                triaged_items.append({"article": art, "analysis": analysis})
                if getattr(analysis, "is_relevant", True):
                    if db.index_article(art, analysis):
                        indexed_count += 1
            except Exception as e:
                logger.warning(f"Error triaging/indexing {art.get('title')}: {e}")

        report_name = None
        try:
            builder = DailyDigestBuilder()
            report_path = builder.generate_digest(triaged_items)
            if report_path:
                report_name = report_path.name
        except Exception as e:
            logger.warning(f"Digest generation skipped: {e}")

        # Auto-export seed JSON for cloud persistence
        try:
            db.export_seed_json()
        except Exception as e:
            logger.warning(f"Seed JSON export skipped: {e}")

        return {
            "status": "success",
            "sources_polled": len(enabled_sources),
            "ingested_candidate_count": len(articles),
            "indexed_count": indexed_count,
            "total_now": db.get_total_count(),
            "report_name": report_name
        }
    except Exception as e:
        logger.error(f"Ingest trigger failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Front-End Architectural Portal
# Supports root /, /api, /api/index, and /api/index.py to eliminate Vercel CLI rewrite mismatch
@app.get("/", response_class=HTMLResponse)
@app.get("/api", response_class=HTMLResponse)
@app.get("/api/index", response_class=HTMLResponse)
@app.get("/api/index.py", response_class=HTMLResponse)
def index_html():
    db = get_db()
    total_count = db.get_total_count()
    return f"""<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ArchIntel Studio | Architectural & Material Research Workstation</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=Playfair+Display:ital,wght@0,600;0,700;1,400&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <script>
    tailwind.config = {{
      darkMode: 'class',
      theme: {{
        extend: {{
          fontFamily: {{
            sans: ['Outfit', 'sans-serif'],
            serif: ['Playfair Display', 'serif'],
            mono: ['JetBrains Mono', 'monospace'],
          }},
          colors: {{
            archDark: '#0B0F19',
            archSurface: '#111827',
            archCard: '#182234',
            archBorder: '#233044',
            archNavy: '#1E3A8A',
            archGold: '#D4AF37',
            archCyan: '#38BDF8',
            archEmerald: '#10B981',
          }}
        }}
      }}
    }}
  </script>
  <style>
    body {{
      background-color: #0B0F19;
      color: #E2E8F0;
      font-family: 'Outfit', sans-serif;
    }}
    .editorial-title {{
      font-family: 'Playfair Display', serif;
    }}
    .glass-nav {{
      background: rgba(17, 24, 39, 0.85);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    }}
    .glass-card {{
      background: rgba(24, 34, 52, 0.7);
      backdrop-filter: blur(8px);
      border: 1px solid rgba(255, 255, 255, 0.08);
      transition: all 0.25s ease;
    }}
    .glass-card:hover {{
      border-color: rgba(56, 189, 248, 0.35);
      transform: translateY(-2px);
      box-shadow: 0 12px 30px -10px rgba(0, 0, 0, 0.5);
    }}
  </style>
</head>
<body class="min-h-screen flex flex-col">

  <!-- Top Navigation Bar -->
  <header class="sticky top-0 z-50 glass-nav">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
      <div class="flex items-center space-x-3">
        <span class="text-2xl">🏛️</span>
        <div>
          <span class="editorial-title text-xl font-bold tracking-tight text-white">ArchIntel Studio</span>
          <span class="text-xs ml-2 px-2 py-0.5 rounded-full bg-blue-950/80 text-blue-400 border border-blue-800 font-mono">v3.0 Vercel</span>
        </div>
      </div>
      <div class="flex items-center space-x-4 text-sm">
        <div class="hidden md:flex items-center space-x-2 text-slate-400">
          <span class="inline-block w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
          <span>Gemini 3.8 Flash • 3072-d Vectors</span>
        </div>
        <span class="px-3 py-1 rounded-md bg-slate-800 border border-slate-700 text-xs font-mono text-cyan-400" id="db-counter">
          {total_count} Precedents
        </span>
        <button onclick="switchTab('tab-shortlist')" class="px-3 py-1 rounded-md bg-amber-950/60 border border-amber-700/60 text-xs font-mono text-amber-300 hover:bg-amber-900/60 transition flex items-center space-x-1">
          <span>⭐ Shortlist</span>
          <span id="header-shortlist-count" class="ml-1 px-1.5 py-0.2 rounded-full bg-amber-500/20 text-[10px]">0</span>
        </button>
        <button onclick="triggerIngest()" id="btn-ingest" class="px-3 py-1.5 rounded-md bg-gradient-to-r from-blue-700 to-indigo-700 hover:from-blue-600 hover:to-indigo-600 text-xs font-medium text-white transition flex items-center space-x-1 shadow-sm">
          <span>⚡ Sync Feeds</span>
        </button>
      </div>
    </div>
  </header>

  <!-- Hero Section -->
  <section class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-8 pb-4">
    <div class="border-b border-slate-800 pb-6 flex flex-col md:flex-row md:items-end justify-between gap-4">
      <div>
        <h1 class="editorial-title text-3xl sm:text-4xl font-bold text-white tracking-tight">
          Architectural Intelligence & Design Precedent Workstation
        </h1>
        <p class="text-slate-400 text-sm mt-2 max-w-2xl leading-relaxed">
          Zero-trust verified curation from global authorities (*ArchDaily, Dezeen, Architectural Record*) 
          and premier Indian publications (*Architectural Digest India, ThinkMatter, Design Pataki*).
        </p>
      </div>
      <div class="flex items-center space-x-2 text-xs">
        <span class="px-2.5 py-1 rounded bg-slate-800/80 text-slate-300 border border-slate-700">Strict DomainGuard</span>
        <span class="px-2.5 py-1 rounded bg-slate-800/80 text-slate-300 border border-slate-700">Client .docx Synthesis</span>
        <span class="px-2.5 py-1 rounded bg-slate-800/80 text-slate-300 border border-slate-700">Zero Hallucination</span>
      </div>
    </div>
  </section>

  <!-- Main Tabs Navigation -->
  <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 flex-1 w-full">
    <div class="flex border-b border-slate-800 space-x-6 mb-8 text-sm font-medium overflow-x-auto">
      <button onclick="switchTab('tab-finder')" id="nav-finder" class="tab-btn pb-3 border-b-2 border-cyan-400 text-cyan-400 flex items-center space-x-2 whitespace-nowrap">
        <span>🔍 Future Project Case Study Engine</span>
      </button>
      <button onclick="switchTab('tab-intelligence')" id="nav-intelligence" class="tab-btn pb-3 border-b-2 border-transparent text-slate-400 hover:text-white flex items-center space-x-2 whitespace-nowrap">
        <span>📰 3-Part Daily Intelligence</span>
      </button>
      <button onclick="switchTab('tab-shortlist')" id="nav-shortlist" class="tab-btn pb-3 border-b-2 border-transparent text-slate-400 hover:text-white flex items-center space-x-2 whitespace-nowrap">
        <span>⭐ Studio Shortlist Board</span>
        <span id="tab-shortlist-badge" class="px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 font-mono text-[11px] border border-amber-500/30">0</span>
      </button>
      <button onclick="switchTab('tab-dossier')" id="nav-dossier" class="tab-btn pb-3 border-b-2 border-transparent text-slate-400 hover:text-white flex items-center space-x-2 whitespace-nowrap">
        <span>📄 Client Word (.docx) Dossier Synthesizer</span>
      </button>
    </div>

    <!-- TAB 1: Future Project Case Study Engine -->
    <div id="tab-finder" class="tab-content">
      <div class="glass-card rounded-xl p-6 mb-8 border border-slate-800 shadow-xl">
        <h2 class="text-lg font-semibold text-white mb-2">Search Verified Architectural Precedents</h2>
        <p class="text-xs text-slate-400 mb-4">Input your natural language design brief, micro-climate constraints, or structural specifications:</p>
        
        <div class="space-y-4">
          <div class="relative">
            <input type="text" id="search-query" 
              class="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-3 text-sm text-white focus:outline-none focus:border-cyan-400 transition pr-28"
              value="Luxury eco-resort in coastal Maharashtra using laterite stone, lime plaster, and passive cooling"
              placeholder="e.g. Cultural center in a desert climate featuring rammed earth and passive solar shading">
            <button onclick="executeSearch()" id="btn-search" class="absolute right-2 top-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-md text-xs font-semibold text-white transition flex items-center space-x-1">
              <span>Search</span>
            </button>
          </div>

          <!-- Prompt Suggestions -->
          <div class="flex flex-wrap items-center gap-2 text-xs">
            <span class="text-slate-500">Suggested Briefs:</span>
            <button onclick="setQuery('Mass timber hybrid structural framework for an educational campus with high thermal mass')" class="text-slate-400 hover:text-cyan-400 underline decoration-slate-700">Mass Timber Educational Campus</button>
            <span class="text-slate-700">•</span>
            <button onclick="setQuery('Adaptive reuse of heritage brick industrial warehouse into multi-disciplinary art galleries')" class="text-slate-400 hover:text-cyan-400 underline decoration-slate-700">Adaptive Heritage Brick Gallery</button>
            <span class="text-slate-700">•</span>
            <button onclick="setQuery('Biophilic wellness retreat with porous screens, bamboo rafters, and passive ventilation')" class="text-slate-400 hover:text-cyan-400 underline decoration-slate-700">Biophilic Wellness Retreat</button>
          </div>

          <!-- Filters Row -->
          <div class="pt-2 grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
            <div>
              <label class="block text-slate-400 mb-1 font-medium">Filter Category</label>
              <select id="filter-category" class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-slate-200">
                <option value="ALL">All Categories</option>
                <option value="ARCHITECTURAL_NEWS">Architectural News</option>
                <option value="INTERIOR_NEWS">Interior News</option>
                <option value="MATERIAL_LAUNCH_NEWS">Material Launches</option>
              </select>
            </div>
            <div>
              <label class="block text-slate-400 mb-1 font-medium">Project Typology Filter</label>
              <input type="text" id="filter-typology" placeholder="e.g. Hospitality, Residential, Cultural" class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-slate-200">
            </div>
            <div>
              <label class="block text-slate-400 mb-1 font-medium">Min. Semantic Relevance (<span id="relevance-val">30%</span>)</label>
              <input type="range" id="filter-relevance" min="0" max="80" value="30" step="5" class="w-full accent-cyan-400 mt-1" oninput="document.getElementById('relevance-val').innerText = this.value + '%'">
            </div>
          </div>
        </div>
      </div>

      <!-- Quick Word Dossier Generation CTA for Current Search -->
      <div id="dossier-cta" class="hidden mb-6 p-4 rounded-xl bg-gradient-to-r from-blue-950/60 to-indigo-950/60 border border-blue-800/50 flex flex-col sm:flex-row items-center justify-between gap-4">
        <div>
          <h4 class="text-sm font-semibold text-blue-300">Client-Ready Case Study & Material Precedent Dossier (.docx)</h4>
          <p class="text-xs text-slate-400 mt-0.5">Synthesize executive design strategy, comparative matrix, and strict citations directly into Microsoft Word.</p>
        </div>
        <button onclick="downloadDossierFromSearch()" id="btn-download-search-dossier" class="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-md text-xs font-semibold text-white whitespace-nowrap shadow-md transition flex items-center space-x-1">
          <span>📥 Download Word (.docx) Dossier</span>
        </button>
      </div>

      <!-- Search Results Grid -->
      <div id="search-results-header" class="hidden mb-4 flex items-center justify-between">
        <h3 class="text-sm font-semibold text-slate-300 tracking-wider uppercase text-xs" id="results-count-label">Search Results</h3>
      </div>
      <div id="search-results" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        <!-- Rendered dynamically -->
      </div>
      <div id="search-empty" class="text-center py-16 text-slate-500 text-sm">
        Click "Search" above to query vector indexed precedents.
      </div>
    </div>

    <!-- TAB 2: 3-Part Daily Architectural Intelligence -->
    <div id="tab-intelligence" class="tab-content hidden">
      <div class="flex flex-wrap items-center justify-between gap-4 mb-6">
        <div>
          <h2 class="editorial-title text-2xl font-bold text-white">Daily Architectural Intelligence Feed</h2>
          <p class="text-xs text-slate-400 mt-1">Structured 3-part triage partitioned into Architecture, Interiors, and Materials.</p>
        </div>
        <div class="flex items-center space-x-2 text-xs">
          <button onclick="loadIntelligence('ALL')" class="intel-filter px-3 py-1 rounded bg-cyan-600 text-white font-medium" id="flt-all">All Items</button>
          <button onclick="loadIntelligence('ARCHITECTURAL_NEWS')" class="intel-filter px-3 py-1 rounded bg-slate-800 text-slate-300 hover:bg-slate-700" id="flt-arch">🏛️ Architectural</button>
          <button onclick="loadIntelligence('INTERIOR_NEWS')" class="intel-filter px-3 py-1 rounded bg-slate-800 text-slate-300 hover:bg-slate-700" id="flt-int">🛋️ Interiors</button>
          <button onclick="loadIntelligence('MATERIAL_LAUNCH_NEWS')" class="intel-filter px-3 py-1 rounded bg-slate-800 text-slate-300 hover:bg-slate-700" id="flt-mat">🧱 Materials</button>
        </div>
      </div>
      <div id="intelligence-grid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        <!-- Rendered dynamically -->
      </div>
    </div>

    <!-- TAB 3: Studio Shortlist Board -->
    <div id="tab-shortlist" class="tab-content hidden">
      <div class="glass-card rounded-xl p-6 mb-8 border border-slate-800 shadow-xl flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 class="editorial-title text-2xl font-bold text-white flex items-center space-x-2">
            <span>⭐ Curated Studio Shortlist Board</span>
          </h2>
          <p class="text-xs text-slate-400 mt-1 max-w-xl">
            Precedents pinned to this board are persisted in your browser (<code class="text-cyan-400">localStorage</code>) and synced to the database. 
            Synthesize an executive client document comparing these specific selected precedents in one click.
          </p>
        </div>
        <div class="flex flex-wrap items-center gap-3">
          <button onclick="downloadShortlistDossier()" id="btn-download-shortlist-dossier" class="px-4 py-2.5 bg-gradient-to-r from-amber-500 to-yellow-600 hover:from-amber-400 hover:to-yellow-500 text-slate-950 font-bold rounded-lg text-xs shadow-lg transition flex items-center space-x-1.5">
            <span>📥 Generate Word (.docx) Dossier from My Shortlist</span>
            <span id="shortlist-btn-count" class="px-1.5 py-0.5 rounded bg-black/20 text-[10px]">0 Selected</span>
          </button>
          <button onclick="previewShortlistDossier()" id="btn-preview-shortlist" class="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-medium transition">
            <span>👁️ Preview</span>
          </button>
          <button onclick="clearShortlist()" class="px-3 py-2 bg-slate-900 hover:bg-red-950/60 hover:text-red-400 text-slate-500 rounded-lg text-xs transition border border-slate-800">
            <span>Clear Board</span>
          </button>
        </div>
      </div>

      <!-- Shortlist Preview Container -->
      <div id="shortlist-preview-box" class="hidden mb-8 p-5 glass-card rounded-xl border border-slate-700">
        <div class="flex items-center justify-between mb-3">
          <h4 class="text-xs font-semibold uppercase tracking-wider text-amber-400">Synthesized Shortlist Dossier Preview</h4>
          <button onclick="document.getElementById('shortlist-preview-box').classList.add('hidden')" class="text-slate-500 hover:text-white text-xs">✕ Close</button>
        </div>
        <div id="shortlist-preview-markdown" class="p-4 rounded-lg bg-slate-900/90 border border-slate-800 text-xs text-slate-300 font-mono whitespace-pre-wrap max-h-96 overflow-y-auto leading-relaxed">
        </div>
      </div>

      <!-- Shortlist Grid -->
      <div id="shortlist-grid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        <!-- Rendered dynamically -->
      </div>
      <div id="shortlist-empty" class="text-center py-20 text-slate-500 text-sm">
        <div class="text-3xl mb-2">⭐</div>
        <p class="font-medium text-slate-400">No precedents shortlisted yet.</p>
        <p class="text-xs text-slate-600 mt-1">Browse the Case Study Engine or Daily Intelligence Feed and click "☆ Shortlist" on any project to pin it here.</p>
      </div>
    </div>

    <!-- TAB 4: Client Word (.docx) Dossier Synthesizer -->
    <div id="tab-dossier" class="tab-content hidden">
      <div class="glass-card rounded-xl p-6 border border-slate-800 max-w-3xl mx-auto shadow-2xl">
        <h2 class="editorial-title text-2xl font-bold text-white mb-2">Architectural Project Dossier Synthesizer</h2>
        <p class="text-xs text-slate-400 mb-6 leading-relaxed">
          Powered by <b>Gemini 3.8 Flash</b> with strict <b>Zero-Hallucination Citation Constraints</b>. 
          The agent queries the top matching verified case studies and produces a structured client-ready executive document formatted with headings, matrices, and verified links.
        </p>

        <div class="space-y-4">
          <div>
            <label class="block text-xs font-semibold text-slate-300 mb-1">Enter Future Project Brief:</label>
            <textarea id="dossier-brief-input" rows="4" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-3 text-sm text-white focus:outline-none focus:border-cyan-400 transition"
              placeholder="e.g. Luxury eco-resort in coastal Maharashtra using laterite stone, lime plaster, and passive cooling">Luxury eco-resort in coastal Maharashtra using laterite stone, lime plaster, and passive cooling</textarea>
          </div>

          <div class="flex items-center justify-between text-xs">
            <span class="text-slate-400">Precedent Sample Depth:</span>
            <select id="dossier-topk" class="bg-slate-900 border border-slate-700 rounded px-3 py-1.5 text-slate-200">
              <option value="3">Top 3 Most Relevant Precedents</option>
              <option value="5" selected>Top 5 Most Relevant Precedents</option>
              <option value="8">Top 8 Most Relevant Precedents</option>
            </select>
          </div>

          <div class="pt-4 flex flex-col sm:flex-row gap-3">
            <button onclick="downloadDirectDossier()" id="btn-generate-docx" class="flex-1 py-3 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white rounded-lg text-sm font-semibold transition flex items-center justify-center space-x-2 shadow-lg">
              <span>📥 Generate & Download Word (.docx) Dossier</span>
            </button>
            <button onclick="previewDossier()" id="btn-preview-dossier" class="px-5 py-3 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-sm font-medium transition">
              <span>👁️ On-Screen Preview</span>
            </button>
          </div>
        </div>

        <!-- Preview Container -->
        <div id="dossier-preview-box" class="hidden mt-8 pt-6 border-t border-slate-800">
          <div class="flex items-center justify-between mb-3">
            <h4 class="text-xs font-semibold uppercase tracking-wider text-cyan-400">Synthesized Dossier Preview</h4>
            <span class="text-xs text-slate-500" id="preview-filename"></span>
          </div>
          <div id="preview-markdown" class="p-4 rounded-lg bg-slate-900/90 border border-slate-800 text-xs text-slate-300 font-mono whitespace-pre-wrap max-h-96 overflow-y-auto leading-relaxed">
          </div>
        </div>
      </div>
    </div>
  </main>

  <!-- Footer -->
  <footer class="border-t border-slate-800/80 mt-12 py-6 text-center text-xs text-slate-500">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-2">
      <div>ArchIntel Studio • Architectural Design Intelligence & Research Workstation</div>
      <div class="font-mono text-slate-600">Zero-Trust Curation • SQLite Dense Vectors • Gemini 3.8 Flash</div>
    </div>
  </footer>

  <!-- JavaScript Client Logic -->
  <script>
    // Global registry of all fetched articles to support instantaneous shortlisting
    const articleRegistry = new Map();
    // Shortlisted items map: (id or url) -> article item
    const shortlistMap = new Map();

    function loadShortlistFromStorage() {{
      try {{
        const stored = localStorage.getItem('archintel_shortlist');
        if (stored) {{
          const list = JSON.parse(stored);
          list.forEach(item => {{
            if (item && (item.id || item.url)) {{
              const k = item.id || item.url;
              shortlistMap.set(k, item);
              articleRegistry.set(k, item);
            }}
          }});
        }}
      }} catch (e) {{
        console.warn('Could not read localStorage shortlist:', e);
      }}
      updateShortlistBadges();
    }}

    function saveShortlistToStorage() {{
      try {{
        const list = Array.from(shortlistMap.values());
        localStorage.setItem('archintel_shortlist', JSON.stringify(list));
      }} catch (e) {{
        console.warn('Could not save localStorage shortlist:', e);
      }}
      updateShortlistBadges();
    }}

    function updateShortlistBadges() {{
      const count = shortlistMap.size;
      const tabBadge = document.getElementById('tab-shortlist-badge');
      if (tabBadge) tabBadge.innerText = count;
      const headerBadge = document.getElementById('header-shortlist-count');
      if (headerBadge) headerBadge.innerText = count;
      const btnBadge = document.getElementById('shortlist-btn-count');
      if (btnBadge) btnBadge.innerText = `${{count}} Selected`;
    }}

    function switchTab(tabId) {{
      document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
      const targetContent = document.getElementById(tabId);
      if (targetContent) targetContent.classList.remove('hidden');

      document.querySelectorAll('.tab-btn').forEach(el => {{
        el.classList.remove('border-cyan-400', 'text-cyan-400');
        el.classList.add('border-transparent', 'text-slate-400');
      }});

      if (tabId === 'tab-finder') {{
        document.getElementById('nav-finder').classList.add('border-cyan-400', 'text-cyan-400');
      }} else if (tabId === 'tab-intelligence') {{
        document.getElementById('nav-intelligence').classList.add('border-cyan-400', 'text-cyan-400');
        loadIntelligence('ALL');
      }} else if (tabId === 'tab-shortlist') {{
        document.getElementById('nav-shortlist').classList.add('border-cyan-400', 'text-cyan-400');
        renderShortlistGrid();
      }} else if (tabId === 'tab-dossier') {{
        document.getElementById('nav-dossier').classList.add('border-cyan-400', 'text-cyan-400');
      }}
    }}

    function setQuery(text) {{
      document.getElementById('search-query').value = text;
      executeSearch();
    }}

    async function executeSearch() {{
      const query = document.getElementById('search-query').value.trim();
      if (!query) return;

      const category = document.getElementById('filter-category').value;
      const typology = document.getElementById('filter-typology').value;
      const minRel = parseFloat(document.getElementById('filter-relevance').value);

      const btn = document.getElementById('btn-search');
      btn.innerHTML = '<span>Searching...</span>';
      btn.disabled = true;

      try {{
        const res = await fetch('/api/search', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{
            query: query,
            category: category,
            typology: typology,
            min_relevance: minRel,
            limit: 12
          }})
        }});
        const data = await res.json();
        renderSearchResults(data.results || []);
        
        if (data.results && data.results.length > 0) {{
          document.getElementById('dossier-cta').classList.remove('hidden');
        }} else {{
          document.getElementById('dossier-cta').classList.add('hidden');
        }}
      }} catch (err) {{
        console.error('Search error:', err);
      }} finally {{
        btn.innerHTML = '<span>Search</span>';
        btn.disabled = false;
      }}
    }}

    function renderSearchResults(items) {{
      const container = document.getElementById('search-results');
      const empty = document.getElementById('search-empty');
      const header = document.getElementById('search-results-header');
      const countLabel = document.getElementById('results-count-label');

      container.innerHTML = '';
      if (!items || items.length === 0) {{
        empty.classList.remove('hidden');
        header.classList.add('hidden');
        empty.innerText = 'No matching precedents found for this query and relevance threshold.';
        return;
      }}

      empty.classList.add('hidden');
      header.classList.remove('hidden');
      countLabel.innerText = `Found ${{items.length}} Verified Architectural Precedents`;

      items.forEach(item => {{
        const card = createPrecedentCard(item, true);
        container.appendChild(card);
      }});
    }}

    function createPrecedentCard(item, showScore = false) {{
      const idKey = item.id || item.url;
      articleRegistry.set(idKey, item);

      const isStarred = shortlistMap.has(idKey) || !!item.is_bookmarked;
      if (isStarred && !shortlistMap.has(idKey)) {{
        shortlistMap.set(idKey, item);
      }}

      const div = document.createElement('div');
      div.className = 'glass-card rounded-xl p-5 flex flex-col justify-between';

      let catBadge = 'bg-blue-950 text-blue-300 border-blue-800';
      if (item.category === 'INTERIOR_NEWS') catBadge = 'bg-purple-950 text-purple-300 border-purple-800';
      if (item.category === 'MATERIAL_LAUNCH_NEWS') catBadge = 'bg-emerald-950 text-emerald-300 border-emerald-800';

      const matchHtml = showScore ? 
        `<span class="text-xs font-mono font-bold text-cyan-400 bg-cyan-950/80 px-2 py-0.5 rounded border border-cyan-800">${{(item.similarity_score * 100).toFixed(1)}}% Match</span>` : '';

      const materials = (item.materials_used && item.materials_used !== 'N/A') ?
        item.materials_used.split(',').slice(0, 3).map(m => `<span class="inline-block bg-slate-800 text-slate-300 text-[10px] px-2 py-0.5 rounded-full mr-1 mt-1 border border-slate-700">${{m.trim()}}</span>`).join('') : '';

      div.innerHTML = `
        <div>
          <div class="flex items-center justify-between gap-2 mb-2">
            <span class="text-[10px] uppercase font-mono font-semibold px-2 py-0.5 rounded border ${{catBadge}}">${{item.category.replace('_NEWS', '')}}</span>
            ${{matchHtml}}
          </div>
          <h3 class="font-bold text-white text-base leading-snug mb-2 hover:text-cyan-400 transition">
            <a href="${{item.url}}" target="_blank" rel="noopener noreferrer">${{item.title}}</a>
          </h3>
          <div class="text-xs text-slate-400 mb-3 space-y-0.5">
            <div><span class="text-slate-500">Source:</span> <span class="text-slate-300 font-medium">${{item.source_name}}</span> | <span class="text-slate-500">Studio:</span> <span class="text-slate-300">${{item.architect_or_manufacturer || 'Studio'}}</span></div>
            <div><span class="text-slate-500">Typology:</span> ${{item.project_typology || 'General'}} • <span class="text-slate-500">Climate:</span> ${{item.climate_or_location || 'Global'}}</div>
          </div>
          ${{materials ? `<div class="mb-3">${{materials}}</div>` : ''}}
          <div class="text-xs text-slate-300 space-y-1 mb-4 border-t border-slate-800/80 pt-2">
            ${{item.bullet_1 ? `<p class="line-clamp-2 text-slate-300">▪ ${{item.bullet_1}}</p>` : ''}}
          </div>
        </div>
        <div class="pt-3 border-t border-slate-800/60 flex items-center justify-between text-xs">
          <a href="${{item.url}}" target="_blank" rel="noopener noreferrer" class="text-cyan-400 hover:text-cyan-300 font-medium flex items-center space-x-1">
            <span>Verified Source</span>
            <span class="text-[10px]">↗</span>
          </a>
          <div class="flex items-center space-x-2">
            <button onclick="toggleBookmark('${{idKey}}', this)" class="btn-bookmark-star text-slate-400 hover:text-amber-400 transition flex items-center space-x-0.5 ${{isStarred ? 'text-amber-400 font-semibold' : ''}}" data-id="${{idKey}}">
              <span>${{isStarred ? '★ Shortlisted' : '☆ Shortlist'}}</span>
            </button>
            <span class="text-slate-600">•</span>
            <button onclick="synthesizeSingle('${{item.title.replace(/'/g, "\\'")}}')" class="text-slate-400 hover:text-white transition">Cite</button>
          </div>
        </div>
      `;
      return div;
    }}

    async function loadIntelligence(cat) {{
      const grid = document.getElementById('intelligence-grid');
      grid.innerHTML = '<div class="col-span-3 text-center py-12 text-slate-500">Loading intelligence feed...</div>';

      document.querySelectorAll('.intel-filter').forEach(b => {{
        b.classList.remove('bg-cyan-600', 'text-white');
        b.classList.add('bg-slate-800', 'text-slate-300');
      }});

      const btnMap = {{ 'ALL': 'flt-all', 'ARCHITECTURAL_NEWS': 'flt-arch', 'INTERIOR_NEWS': 'flt-int', 'MATERIAL_LAUNCH_NEWS': 'flt-mat' }};
      const activeBtn = document.getElementById(btnMap[cat]);
      if (activeBtn) {{
        activeBtn.classList.remove('bg-slate-800', 'text-slate-300');
        activeBtn.classList.add('bg-cyan-600', 'text-white');
      }}

      try {{
        const url = cat === 'ALL' ? '/api/articles?limit=48' : `/api/articles?category=${{cat}}&limit=48`;
        const res = await fetch(url);
        const data = await res.json();
        
        grid.innerHTML = '';
        if (!data.items || data.items.length === 0) {{
          grid.innerHTML = '<div class="col-span-3 text-center py-12 text-slate-500">No items in this category yet. Run "Sync Feeds" to ingest latest articles.</div>';
          return;
        }}

        data.items.forEach(item => {{
          grid.appendChild(createPrecedentCard(item, false));
        }});
      }} catch (err) {{
        grid.innerHTML = '<div class="col-span-3 text-center py-12 text-red-400">Failed to load feed.</div>';
      }}
    }}

    function synthesizeSingle(title) {{
      document.getElementById('dossier-brief-input').value = `Architectural analysis and precedent synthesis based on "${{title}}"`;
      switchTab('tab-dossier');
    }}

    function downloadDossierFromSearch() {{
      const query = document.getElementById('search-query').value.trim();
      document.getElementById('dossier-brief-input').value = query;
      downloadDirectDossier();
    }}

    async function downloadDirectDossier() {{
      const brief = document.getElementById('dossier-brief-input').value.trim();
      const topk = parseInt(document.getElementById('dossier-topk').value) || 5;
      if (!brief) return alert('Please enter a project brief.');

      const btn = document.getElementById('btn-generate-docx');
      const originalText = btn.innerHTML;
      btn.innerHTML = '<span>⚡ Synthesizing via Gemini & Compiling Word Doc...</span>';
      btn.disabled = true;

      try {{
        const res = await fetch('/api/dossier', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ brief: brief, top_k: topk }})
        }});

        if (!res.ok) throw new Error('Dossier generation failed');

        const blob = await res.blob();
        const headerFilename = res.headers.get('X-Dossier-Filename') || 'Architectural-Case-Study-Dossier.docx';

        const downloadUrl = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = downloadUrl;
        a.download = headerFilename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(downloadUrl);
      }} catch (err) {{
        alert('Could not generate dossier: ' + err.message);
      }} finally {{
        btn.innerHTML = originalText;
        btn.disabled = false;
      }}
    }}

    async function previewDossier() {{
      const brief = document.getElementById('dossier-brief-input').value.trim();
      const topk = parseInt(document.getElementById('dossier-topk').value) || 5;
      if (!brief) return alert('Please enter a project brief.');

      const btn = document.getElementById('btn-preview-dossier');
      btn.innerHTML = '<span>Synthesizing...</span>';
      btn.disabled = true;

      try {{
        const res = await fetch('/api/dossier/preview', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ brief: brief, top_k: topk }})
        }});
        const data = await res.json();
        if (data.success) {{
          document.getElementById('dossier-preview-box').classList.remove('hidden');
          document.getElementById('preview-filename').innerText = data.filename;
          document.getElementById('preview-markdown').innerText = data.markdown;
        }}
      }} catch (err) {{
        alert('Preview failed: ' + err.message);
      }} finally {{
        btn.innerHTML = '<span>👁️ On-Screen Preview</span>';
        btn.disabled = false;
      }}
    }}

    async function toggleBookmark(id, btn) {{
      const item = articleRegistry.get(id) || {{ id: id, url: id, title: 'Arch Precedent' }};
      const currentlyStarred = shortlistMap.has(id);

      if (currentlyStarred) {{
        shortlistMap.delete(id);
      }} else {{
        shortlistMap.set(id, item);
      }}
      saveShortlistToStorage();

      // Synchronize all buttons matching this ID across the entire DOM
      document.querySelectorAll(`[data-id="${{id}}"]`).forEach(b => {{
        if (!currentlyStarred) {{
          b.innerHTML = '<span>★ Shortlisted</span>';
          b.classList.add('text-amber-400', 'font-semibold');
        }} else {{
          b.innerHTML = '<span>☆ Shortlist</span>';
          b.classList.remove('text-amber-400', 'font-semibold');
        }}
      }});

      // If user is currently looking at the Shortlist tab, re-render immediately
      const activeShortlistTab = document.getElementById('tab-shortlist');
      if (activeShortlistTab && !activeShortlistTab.classList.contains('hidden')) {{
        renderShortlistGrid();
      }}

      // Background cloud sync
      try {{
        await fetch('/api/bookmark', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ id: id }})
        }});
      }} catch (err) {{
        console.debug('Bookmark cloud sync notice:', err);
      }}
    }}

    function renderShortlistGrid() {{
      const container = document.getElementById('shortlist-grid');
      const empty = document.getElementById('shortlist-empty');
      if (!container || !empty) return;

      container.innerHTML = '';
      const items = Array.from(shortlistMap.values());
      if (items.length === 0) {{
        empty.classList.remove('hidden');
        return;
      }}

      empty.classList.add('hidden');
      items.forEach(item => {{
        const card = createPrecedentCard(item, false);
        container.appendChild(card);
      }});
    }}

    function clearShortlist() {{
      if (shortlistMap.size === 0) return;
      if (!confirm('Clear all shortlisted precedents from this board?')) return;
      shortlistMap.clear();
      saveShortlistToStorage();
      renderShortlistGrid();
      document.querySelectorAll('.btn-bookmark-star').forEach(b => {{
        b.innerHTML = '<span>☆ Shortlist</span>';
        b.classList.remove('text-amber-400', 'font-semibold');
      }});
    }}

    async function downloadShortlistDossier() {{
      const ids = Array.from(shortlistMap.keys());
      if (ids.length === 0) {{
        alert('Your shortlist is empty! Star at least 1 architectural precedent first.');
        return;
      }}

      const btn = document.getElementById('btn-download-shortlist-dossier');
      const original = btn.innerHTML;
      btn.innerHTML = '<span>⚡ Synthesizing Shortlist Dossier...</span>';
      btn.disabled = true;

      try {{
        const res = await fetch('/api/dossier', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{
            article_ids: ids,
            brief: `Curated Studio Precedent Review (${{ids.length}} Shortlisted Projects)`
          }})
        }});

        if (!res.ok) throw new Error('Shortlist dossier generation failed');

        const blob = await res.blob();
        const headerFilename = res.headers.get('X-Dossier-Filename') || 'ArchIntel-Shortlist-Dossier.docx';
        const downloadUrl = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = downloadUrl;
        a.download = headerFilename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(downloadUrl);
      }} catch (err) {{
        alert('Could not generate shortlist dossier: ' + err.message);
      }} finally {{
        btn.innerHTML = original;
        btn.disabled = false;
      }}
    }}

    async function previewShortlistDossier() {{
      const ids = Array.from(shortlistMap.keys());
      if (ids.length === 0) {{
        alert('Your shortlist is empty! Star at least 1 architectural precedent first.');
        return;
      }}

      const btn = document.getElementById('btn-preview-shortlist');
      btn.innerHTML = '<span>Synthesizing...</span>';
      btn.disabled = true;

      try {{
        const res = await fetch('/api/dossier/preview', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{
            article_ids: ids,
            brief: `Curated Studio Precedent Review (${{ids.length}} Shortlisted Projects)`
          }})
        }});
        const data = await res.json();
        if (data.success) {{
          document.getElementById('shortlist-preview-box').classList.remove('hidden');
          document.getElementById('shortlist-preview-markdown').innerText = data.markdown;
        }}
      }} catch (err) {{
        alert('Preview failed: ' + err.message);
      }} finally {{
        btn.innerHTML = '<span>👁️ Preview</span>';
        btn.disabled = false;
      }}
    }}

    async function triggerIngest() {{
      const btn = document.getElementById('btn-ingest');
      btn.innerHTML = '<span>⏳ Ingesting (Fast Sync)...</span>';
      btn.disabled = true;

      try {{
        const res = await fetch('/api/ingest?max_items=1&max_sources=3', {{ method: 'POST' }});
        const data = await res.json();
        alert(`Fast Sync complete! Ingested ${{data.ingested_candidate_count}} articles, indexed ${{data.indexed_count}} into knowledge base. Total now: ${{data.total_now}}`);
        document.getElementById('db-counter').innerText = `${{data.total_now}} Precedents`;
      }} catch (err) {{
        alert('Ingestion error: ' + err.message);
      }} finally {{
        btn.innerHTML = '<span>⚡ Sync Feeds</span>';
        btn.disabled = false;
      }}
    }}

    // Auto-search and initialize shortlist on initial load
    window.addEventListener('DOMContentLoaded', async () => {{
      loadShortlistFromStorage();
      try {{
        const res = await fetch('/api/bookmarks');
        const data = await res.json();
        if (data.items && data.items.length > 0) {{
          data.items.forEach(it => {{
            const k = it.id || it.url;
            articleRegistry.set(k, it);
            shortlistMap.set(k, it);
          }});
          saveShortlistToStorage();
        }}
      }} catch (e) {{
        console.debug('Initial bookmark sync notice:', e);
      }}
      executeSearch();
    }});
  </script>
</body>
</html>
