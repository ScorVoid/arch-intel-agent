"""
File: main.py
Purpose: Master Pipeline Orchestrator for ArchIntel-Agent.

Workflow:
1. Ingest verified RSS feeds through the strict Domain Guard.
2. AI Triage & Structured Categorization using google-genai + Pydantic.
3. Index verified precedents into local ChromaDB Case Study Knowledge Base.
4. Generate the 3-part Daily Digest in reports/YYYY-MM-DD-daily-brief.md.
"""

import os
import sys
import argparse
import logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Ensure the root directory is on the python search path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.ingestor import FeedIngestor
from src.ai_triage import AITriageEngine
from src.case_study_db import CaseStudyDatabase
from src.digest_builder import DailyDigestBuilder

# Vercel ASGI Application Compatibility Export
try:
    from api.index import app
except Exception:
    app = None

# Configure clean logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("ArchIntel.Main")


def run_pipeline(max_per_source: int = 3, skip_indexing: bool = False):
    """
    Executes the complete daily architectural intelligence cycle.
    """
    load_dotenv()
    start_time = datetime.now()

    print("\n" + "=" * 70)
    print("🏛️  ArchIntel-Agent: Production Ingestion & Intelligence Pipeline")
    print(f"Timestamp: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # 1. Ingestion Phase
    logger.info("PHASE 1: Ingesting feeds via strict Domain Guard...")
    ingestor = FeedIngestor()
    raw_articles = ingestor.ingest_all(max_items_per_source=max_per_source)
    logger.info(f"Retrieved {len(raw_articles)} candidate articles from trusted feeds.")

    if not raw_articles:
        logger.warning("No articles were ingested. Please verify network connectivity and feed URLs.")
        return

    # 2. AI Triage & Structured Categorization Phase
    logger.info("PHASE 2: Performing AI Triage & Structured Categorization (Gemini Flash + Pydantic)...")
    triage_engine = AITriageEngine()
    triaged_items = []

    for idx, article in enumerate(raw_articles, 1):
        logger.info(f"Analyzing [{idx}/{len(raw_articles)}]: {article.get('title')[:60]}...")
        result = triage_engine.triage_article(article)
        triaged_items.append({"article": article, "analysis": result})

    # 3. Persistent Case Study Indexing Phase
    if not skip_indexing:
        logger.info("PHASE 3: Indexing verified precedents into SQLite Vector Database...")
        db = CaseStudyDatabase()
        indexed_count = 0
        for item in triaged_items:
            if db.index_article(item["article"], item["analysis"]):
                indexed_count += 1
        logger.info(f"Indexed {indexed_count} verified case studies into ChromaDB. Total in DB: {db.get_total_count()}")
    else:
        logger.info("PHASE 3: Skipping ChromaDB vector indexing (--skip-indexing set).")

    # 4. Daily Digest Generation Phase
    logger.info("PHASE 4: Building 3-part Daily Digest Markdown Brief...")
    builder = DailyDigestBuilder()
    report_path = builder.generate_digest(triaged_items, run_date=start_time)
    logger.info(f"Daily Digest generated successfully at: {report_path}")

    # Summary
    duration = (datetime.now() - start_time).total_seconds()
    print("\n" + "=" * 70)
    print("✨ Pipeline Complete!")
    print(f"📄 Report: {report_path}")
    print(f"⏱️  Duration: {duration:.2f} seconds")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the ArchIntel-Agent automated pipeline.")
    parser.add_argument(
        "--max-per-source",
        type=int,
        default=2,
        help="Maximum articles to fetch per trusted feed (default: 2)."
    )
    parser.add_argument(
        "--skip-indexing",
        action="store_true",
        help="Skip storing into ChromaDB vector database."
    )
    args = parser.parse_args()

    run_pipeline(max_per_source=args.max_per_source, skip_indexing=args.skip_indexing)
