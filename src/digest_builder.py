"""
Module: src/digest_builder.py
Purpose: Generates structured, executive 3-part Markdown Daily Briefs.

Architectural Design Notes for AI Engineering:
---------------------------------------------
1. Clear Hierarchical Information Architecture:
   Designers and project architects scan digests quickly. Articles are strictly
   partitioned into the 3 operational categories:
     - Section 1: Architectural News (Civic, Residential, Masterplans, Structures)
     - Section 2: Interior News (Spatial, Hospitality, Retail, Lighting)
     - Section 3: Newly Launched Material News (Surfaces, Composites, Facades)
2. Traceable Attribution:
   Every item links directly to its verified publication URL and attributes the
   architect, studio, or manufacturer.
"""

import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from src.ai_triage import NewsCategory

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


class DailyDigestBuilder:
    """
    Assembles triaged architectural intelligence into production-grade Markdown briefs.
    """

    def __init__(self, reports_dir: Path = REPORTS_DIR):
        self.reports_dir = reports_dir
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def generate_digest(
        self,
        triaged_items: List[Dict[str, Any]],
        run_date: datetime = None
    ) -> Path:
        """
        Builds and saves the daily markdown brief.
        `triaged_items` is a list of tuples or dicts containing:
          - article: dict (title, url, source_name, publish_date)
          - analysis: ArticleTriageResult
        """
        date_obj = run_date or datetime.now()
        date_str = date_obj.strftime("%Y-%m-%d")
        file_path = self.reports_dir / f"{date_str}-daily-brief.md"

        # Separate items into the 3 core buckets
        arch_news = []
        interior_news = []
        material_news = []
        rejected_count = 0

        for item in triaged_items:
            analysis = item.get("analysis")
            if not getattr(analysis, "is_relevant", True):
                rejected_count += 1
                continue

            category = getattr(analysis, "category", "")
            cat_val = category.value if hasattr(category, "value") else str(category)

            if cat_val == NewsCategory.ARCHITECTURAL_NEWS.value:
                arch_news.append(item)
            elif cat_val == NewsCategory.INTERIOR_NEWS.value:
                interior_news.append(item)
            elif cat_val == NewsCategory.MATERIAL_LAUNCH_NEWS.value:
                material_news.append(item)
            else:
                arch_news.append(item)

        total_relevant = len(arch_news) + len(interior_news) + len(material_news)

        # Markdown Document Generation
        lines = [
            f"# ArchIntel-Agent Daily Intelligence Brief",
            f"**Date:** {date_obj.strftime('%B %d, %Y')} | **Pipeline Status:** Verified Verified Sources Only",
            f"",
            f"> Executive Architectural & Material Intelligence compiled from verified global publications.",
            f"",
            f"### Executive Pipeline Metrics",
            f"- **Verified Curated Items:** {total_relevant}",
            f"- **Architectural Innovations:** {len(arch_news)}",
            f"- **Spatial & Interior Design:** {len(interior_news)}",
            f"- **Newly Launched Materials:** {len(material_news)}",
            f"- **Off-Topic / Ads Filtered Out:** {rejected_count}",
            f"",
            f"---",
            f"",
            f"## 1. Architectural News",
            f"*Structures, civic & cultural developments, masterplans, and structural engineering feats.*",
            f""
        ]

        if not arch_news:
            lines.append("_No major verified architectural items captured in this cycle._\n")
        else:
            for item in arch_news:
                lines.extend(self._format_article_markdown(item))

        lines.extend([
            f"---",
            f"",
            f"## 2. Interior News",
            f"*Spatial design, hospitality, residential interiors, lighting design, and acoustic environments.*",
            f""
        ])

        if not interior_news:
            lines.append("_No major verified interior items captured in this cycle._\n")
        else:
            for item in interior_news:
                lines.extend(self._format_article_markdown(item))

        lines.extend([
            f"---",
            f"",
            f"## 3. Newly Launched Material News",
            f"*Engineered surfaces, bio-based composites, facade technologies, and sustainable material breakthroughs.*",
            f""
        ])

        if not material_news:
            lines.append("_No major verified material launches captured in this cycle._\n")
        else:
            for item in material_news:
                lines.extend(self._format_article_markdown(item))

        lines.extend([
            f"---",
            f"*Report auto-generated by [ArchIntel-Agent](https://github.com/ScorVoid/arch-intel-agent). All sources vetted via strict domain whitelist.*"
        ])

        markdown_content = "\n".join(lines)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)

        return file_path

    def _format_article_markdown(self, item: Dict[str, Any]) -> List[str]:
        """Formats an individual article entry into structured Markdown."""
        art = item.get("article", {})
        analysis = item.get("analysis")

        title = art.get("title", "Untitled Project")
        url = art.get("url", "#")
        source = art.get("source_name", "Publication")
        date_str = art.get("publish_date", "")

        architect = getattr(analysis, "architect_or_manufacturer", "Not specified")
        typology = getattr(analysis, "project_typology", "General")
        climate = getattr(analysis, "climate_or_location", "Global")
        materials = getattr(analysis, "materials_used", [])
        materials_badge = ", ".join(f"`{m}`" for m in materials) if materials else "`Specified on site`"

        bullets = getattr(analysis, "three_bullet_summary", [])

        lines = [
            f"### [{title}]({url})",
            f"**Source:** {source} | **Studio / Manufacturer:** {architect} | **Typology:** {typology}",
            f"**Location / Climate:** {climate}",
            f"**Materials Identified:** {materials_badge}",
            f"",
            f"**Key Takeaways:**"
        ]

        for b in bullets:
            lines.append(f"- {b}")

        lines.append("")  # Blank spacing
        return lines
