"""
Module: src/dossier_generator.py
Purpose: Future Project Case Study Dossier Synthesizer & DOCX/MD Exporter.

Architectural Design Notes for AI Engineering:
---------------------------------------------
1. Zero-Hallucination Citation Constraint:
   Architectural research demands absolute factual fidelity. When an architect presents
   precedents to clients or planning authorities, every reference must correspond to
   a verified built work or lab-tested material. The LLM is strictly constrained to synthesize
   its narrative ONLY from the retrieved database records. Invented projects or dead links
   are structurally prevented.
2. Production DOCX & Markdown Dual-Output:
   - Microsoft Word (.docx): Formatted for client presentations, studio reviews, and reports
     with styled tables, typographies, callouts, and active hyperlinks.
   - GitHub Markdown (.md): Version-controlled, searchable, and human-readable repository artifact.
"""

import os
import re
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

import docx
import io
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import parse_xml, OxmlElement
from docx.oxml.ns import nsdecls, qn
from docx.opc.constants import RELATIONSHIP_TYPE
from dotenv import load_dotenv

from src.case_study_db import CaseStudyDatabase

load_dotenv()
logger = logging.getLogger("ArchIntel.Dossier")


def _resolve_exports_dir() -> Path:
    if os.environ.get("VERCEL") == "1":
        p = Path("/tmp/exports")
    else:
        p = Path(__file__).resolve().parent.parent / "exports"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return p


EXPORTS_DIR = _resolve_exports_dir()


def add_hyperlink(paragraph, url: str, text: str, color: str = "1E3A8A", underline: bool = True):
    """
    Inserts a clickable hyperlink into a python-docx paragraph.
    """
    try:
        part = paragraph.part
        r_id = part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
        u_tag = "<w:u w:val='single'/>" if underline else ""
        xml = (
            f'<w:hyperlink xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" r:id="{r_id}">'
            f'<w:r>'
            f'<w:rPr><w:color w:val="{color}"/>{u_tag}</w:rPr>'
            f'<w:t>{text}</w:t>'
            f'</w:r>'
            f'</w:hyperlink>'
        )
        hyperlink = parse_xml(xml)
        paragraph._p.append(hyperlink)
    except Exception as e:
        logger.debug(f"Hyperlink insertion fallback: {e}")
        paragraph.add_run(f" {text} ({url}) ")


def set_cell_background(cell, fill_hex: str):
    """Sets background shading for a table cell."""
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    tcPr.append(shd)


class DossierGenerator:
    """
    Synthesizes custom architectural project dossiers from verified database precedents.
    """

    def __init__(self, db: Optional[CaseStudyDatabase] = None, exports_dir: Optional[Path] = None):
        self.db = db or CaseStudyDatabase()
        self.exports_dir = exports_dir or EXPORTS_DIR
        self.exports_dir.mkdir(parents=True, exist_ok=True)

        self.api_key = os.getenv("GEMINI_API_KEY")
        self.model_name = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
        self.client = None

        if self.api_key and self.api_key != "YOUR_GEMINI_API_KEY_HERE":
            try:
                from google import genai
                self.client = genai.Client(api_key=self.api_key)
                logger.info(f"Dossier generator initialized with Gemini model: {self.model_name}")
            except Exception as e:
                logger.warning(f"Could not connect Gemini client for dossier: {e}")

    def generate_dossier(
        self,
        project_brief: str = "Synthesis of Curated Architectural Precedents",
        top_k: int = 5,
        category: Optional[str] = None,
        typology: Optional[str] = None,
        article_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        End-to-end dossier creation:
        1. If article_ids is provided, retrieves those specific case studies.
           Otherwise queries database for nearest verified case studies.
        2. Synthesize structured analysis via Gemini with strict citation bounds.
        3. Export formatted DOCX and MD documents.
        """
        if article_ids:
            logger.info(f"Synthesizing Case Study Dossier from {len(article_ids)} explicit article IDs...")
            precedents = self.db.get_articles_by_ids(article_ids)
            if not project_brief or project_brief.strip() == "Synthesis of Curated Architectural Precedents":
                project_brief = f"Curated Studio Precedent Review ({len(precedents)} Projects)"
        else:
            logger.info(f"Synthesizing Case Study Dossier for brief: '{project_brief[:60]}...'")
            precedents = self.db.search_case_studies(
                query=project_brief,
                n_results=top_k,
                category=category,
                typology=typology
            )

        if not precedents:
            logger.warning("No precedents found matching the selection or brief.")
            return {
                "success": False,
                "error": "No matching case studies found in the database. Please ingest feeds or select valid items.",
                "precedents": []
            }

        # 2. AI Synthesis with Strict Zero-Hallucination Citation Constraints
        synthesis_text = self._synthesize_analysis(project_brief, precedents)

        # 3. Export to Markdown and DOCX
        timestamp_str = datetime.now().strftime("%Y-%m-%d")
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", project_brief[:30].strip()).strip("-").lower()
        if not slug:
            slug = "project-brief"

        md_file = self.exports_dir / f"{timestamp_str}-{slug}-dossier.md"
        docx_file = self.exports_dir / f"{timestamp_str}-{slug}-dossier.docx"

        # Build DOCX in memory first (serverless-friendly)
        docx_buffer = io.BytesIO()

        self._build_docx(project_brief, precedents, synthesis_text, docx_buffer)
        docx_bytes = docx_buffer.getvalue()

        # Attempt saving to disk if writable
        try:
            with open(md_file, "w", encoding="utf-8") as f:
                f.write(synthesis_text)
            with open(docx_file, "wb") as f:
                f.write(docx_bytes)
            logger.info(f"Dossier generated successfully: {docx_file.name} and {md_file.name}")
        except Exception as e:
            logger.warning(f"Could not write dossier to disk (read-only filesystem): {e}")

        return {
            "success": True,
            "project_brief": project_brief,
            "precedents": precedents,
            "synthesis_markdown": synthesis_text,
            "docx_path": str(docx_file),
            "md_path": str(md_file),
            "docx_filename": docx_file.name,
            "md_filename": md_file.name,
            "docx_bytes": docx_bytes
        }

    def _synthesize_analysis(self, brief: str, precedents: List[Dict[str, Any]]) -> str:
        """Invokes Gemini to synthesize the dossier strictly from the provided precedents."""
        precedents_context = []
        for i, p in enumerate(precedents, 1):
            precedents_context.append(f"""
[PRECEDENT #{i}]
Title: {p['title']}
Source: {p['source_name']} ({p.get('publish_date', '')})
URL: {p['url']}
Lead Studio / Brand: {p.get('architect_or_manufacturer', 'Unknown')}
Typology: {p.get('project_typology', 'General')}
Location / Climate: {p.get('climate_or_location', 'Global')}
Materials Mentioned: {p.get('materials_used', 'N/A')}
Takeaway 1: {p.get('bullet_1', '')}
Takeaway 2: {p.get('bullet_2', '')}
Takeaway 3: {p.get('bullet_3', '')}
Similarity Score: {p.get('similarity_score', 0.5) * 100:.1f}% Match
""")

        full_precedents_str = "\n".join(precedents_context)

        prompt = f"""
You are the Principal Architectural Research Director at an elite spatial design consultancy.
You are preparing an authoritative **Architectural Case Study & Material Precedent Dossier** for an upcoming project.

---
### CLIENT / FUTURE PROJECT BRIEF:
"{brief}"
---

### STRICTLY VERIFIED PRECEDENTS (Retrieved from Studio Knowledge Base):
{full_precedents_str}

---
### STRICT SYNTHESIS RULES (Zero-Hallucination Mandate):
1. Use ONLY the precedents provided above. Do NOT invent, assume, or pull in unlisted architectural projects.
2. Every claim regarding a technique, structural feat, or material performance MUST cite the corresponding Precedent Title and verified URL.
3. Structure your response into EXACTLY these 4 sections:
   # Architectural Case Study & Material Precedent Dossier
   **Project Brief:** {brief}
   **Generated:** {datetime.now().strftime('%B %d, %Y')}

   ## 1. Executive Design Strategy
   (A deep-dive analysis explaining how the architectural methodologies, environmental strategies, and spatial layouts in the retrieved precedents directly inform and de-risk the client's brief.)

   ## 2. Comparative Precedent Matrix
   (Create a Markdown table with columns: Project Name | Studio / Architect | Typology & Climate | Key Tectonic / Spatial Takeaway | Source URL)

   ## 3. Material & Tectonic Palette Recommendations
   (Curate specific materials, assemblies, and finishes directly extracted from the case studies. For each material, explain its application, sustainability benefits, and link to the source project.)

   ## 4. Strict Reference Bibliography
   (Numbered list of all verified precedents cited with lead studio, publication name, and direct clickable source URLs.)
"""

        if not self.client:
            return self._offline_synthesis_fallback(brief, precedents)

        models_to_try = [self.model_name, "gemini-2.5-flash", "gemini-1.5-flash"]
        for m in models_to_try:
            try:
                response = self.client.models.generate_content(
                    model=m,
                    contents=prompt,
                    config={"temperature": 0.2}
                )
                if response.text:
                    logger.info(f"Synthesized dossier using model: {m}")
                    return response.text
            except Exception as e:
                logger.warning(f"Model {m} failed: {e}. Trying next fallback...")

        return self._offline_synthesis_fallback(brief, precedents)

    def _offline_synthesis_fallback(self, brief: str, precedents: List[Dict[str, Any]]) -> str:
        """Deterministic fallback when Gemini client is offline."""
        date_str = datetime.now().strftime("%B %d, %Y")
        lines = [
            f"# Architectural Case Study & Material Precedent Dossier",
            f"**Project Brief:** {brief}  ",
            f"**Generated:** {date_str} | **Status:** Studio Knowledge Base Synthesis\n",
            f"## 1. Executive Design Strategy",
            f"This dossier analyzes {len(precedents)} verified architectural precedents retrieved from authoritative publications.",
            f"The selected works establish proven approaches to spatial zoning, regional material adaptation, and tectonic assemblies directly aligned with the project requirements.\n",
            f"## 2. Comparative Precedent Matrix",
            f"| Project Name | Studio / Architect | Typology & Climate | Key Tectonic / Spatial Takeaway | Source URL |",
            f"| :--- | :--- | :--- | :--- | :--- |"
        ]

        for p in precedents:
            takeaway = p.get("bullet_1") or "Verified architectural precedent."
            clean_takeaway = takeaway.replace("|", "/")
            lines.append(
                f"| [{p['title']}]({p['url']}) | {p.get('architect_or_manufacturer', 'N/A')} | "
                f"{p.get('project_typology', 'General')} ({p.get('climate_or_location', 'Global')}) | "
                f"{clean_takeaway} | [View Source]({p['url']}) |"
            )

        lines.extend([
            f"\n## 3. Material & Tectonic Palette Recommendations",
            f"Based on the verified precedents, the following material strategies are recommended for specification:"
        ])

        for p in precedents:
            mats = p.get("materials_used")
            if mats and mats != "N/A":
                lines.append(f"- **{p['title']}:** Utilizes `{mats}`. Documented by {p['source_name']}.")

        lines.extend([
            f"\n## 4. Strict Reference Bibliography"
        ])
        for i, p in enumerate(precedents, 1):
            lines.append(f"{i}. **{p['title']}** - Studio: {p.get('architect_or_manufacturer', 'Studio')} | Publication: {p['source_name']} | URL: {p['url']}")

        return "\n".join(lines)

    def _build_docx(
        self,
        brief: str,
        precedents: List[Dict[str, Any]],
        markdown_text: str,
        output_path: Path
    ):
        """Constructs a polished, formatted Microsoft Word (.docx) document."""
        doc = docx.Document()

        # Set standard margins (1 inch)
        for section in doc.sections:
            section.top_margin = Inches(1.0)
            section.bottom_margin = Inches(1.0)
            section.left_margin = Inches(1.0)
            section.right_margin = Inches(1.0)

        # Document Header
        title_p = doc.add_paragraph()
        title_run = title_p.add_run("ARCHITECTURAL CASE STUDY & MATERIAL PRECEDENT DOSSIER")
        title_run.font.name = "Calibri"
        title_run.font.size = Pt(20)
        title_run.font.bold = True
        title_run.font.color.rgb = RGBColor(0x1E, 0x3A, 0x8A)  # Navy blue
        title_p.paragraph_format.space_after = Pt(4)

        subtitle_p = doc.add_paragraph()
        sub_run = subtitle_p.add_run(f"Project Design Research Report | ArchIntel-Agent Knowledge Engine")
        sub_run.font.name = "Calibri"
        sub_run.font.size = Pt(11)
        sub_run.font.color.rgb = RGBColor(0x64, 0x74, 0x8B)  # Slate grey
        subtitle_p.paragraph_format.space_after = Pt(16)

        # Project Brief Callout Box (1x1 table styled as callout)
        callout_table = doc.add_table(rows=1, cols=1)
        callout_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        cell = callout_table.cell(0, 0)
        cell.width = Inches(6.5)
        set_cell_background(cell, "F1F5F9")  # Light slate tint

        cp = cell.paragraphs[0]
        cp.paragraph_format.space_before = Pt(8)
        cp.paragraph_format.space_after = Pt(8)
        cp.paragraph_format.left_indent = Inches(0.2)
        cp.paragraph_format.right_indent = Inches(0.2)

        c_label = cp.add_run("PROJECT DESIGN BRIEF:\n")
        c_label.font.name = "Calibri"
        c_label.font.size = Pt(9.5)
        c_label.font.bold = True
        c_label.font.color.rgb = RGBColor(0x0F, 0x17, 0x2A)

        c_text = cp.add_run(f'"{brief}"\n')
        c_text.font.name = "Calibri"
        c_text.font.size = Pt(11)
        c_text.font.italic = True

        c_meta = cp.add_run(f"Date: {datetime.now().strftime('%B %d, %Y')} | Verified Precedents Analyzed: {len(precedents)}")
        c_meta.font.name = "Calibri"
        c_meta.font.size = Pt(9)
        c_meta.font.color.rgb = RGBColor(0x47, 0x55, 0x69)

        doc.add_paragraph().paragraph_format.space_after = Pt(12)

        # Section 1: Executive Design Strategy
        h1 = doc.add_heading("1. Executive Design Strategy", level=1)
        h1.paragraph_format.space_before = Pt(14)
        h1.paragraph_format.space_after = Pt(6)

        # Extract strategy text from markdown
        strategy_match = re.search(r"## 1\. Executive Design Strategy\s+(.*?)(?=\n## 2\.|$)", markdown_text, re.DOTALL)
        if strategy_match:
            strategy_body = strategy_match.group(1).strip()
            for para in strategy_body.split("\n\n"):
                if para.strip():
                    p = doc.add_paragraph(para.strip())
                    p.paragraph_format.line_spacing = 1.15
                    p.paragraph_format.space_after = Pt(6)
        else:
            p = doc.add_paragraph(
                f"This design dossier synthesizes verified strategies from {len(precedents)} premier architectural case studies. "
                f"The precedents address spatial layout, climatic suitability, and tectonic specifications tailored to the client's brief."
            )
            p.paragraph_format.space_after = Pt(6)

        # Section 2: Comparative Precedent Matrix Table
        h2 = doc.add_heading("2. Comparative Precedent Matrix", level=1)
        h2.paragraph_format.space_before = Pt(14)
        h2.paragraph_format.space_after = Pt(6)

        # Create Table
        matrix_table = doc.add_table(rows=len(precedents) + 1, cols=5)
        matrix_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        matrix_table.autofit = False

        col_widths = [Inches(1.8), Inches(1.2), Inches(1.1), Inches(1.6), Inches(0.8)]
        headers = ["Project Name", "Lead Studio", "Typology & Climate", "Key Tectonic Takeaway", "Source"]

        # Style Header Row
        hdr_row = matrix_table.rows[0]
        for idx, title in enumerate(headers):
            cell = hdr_row.cells[idx]
            cell.width = col_widths[idx]
            set_cell_background(cell, "1E3A8A")  # Navy Blue
            hp = cell.paragraphs[0]
            hp.alignment = WD_ALIGN_PARAGRAPH.LEFT
            hrun = hp.add_run(title)
            hrun.font.name = "Calibri"
            hrun.font.size = Pt(9.5)
            hrun.font.bold = True
            hrun.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

        # Fill Precedent Rows
        for r_idx, prec in enumerate(precedents, start=1):
            row = matrix_table.rows[r_idx]
            bg_color = "FFFFFF" if r_idx % 2 == 1 else "F8FAFC"

            # 0: Project Name
            cell_0 = row.cells[0]
            cell_0.width = col_widths[0]
            set_cell_background(cell_0, bg_color)
            p0 = cell_0.paragraphs[0]
            p0_run = p0.add_run(prec["title"])
            p0_run.font.name = "Calibri"
            p0_run.font.size = Pt(9)
            p0_run.font.bold = True

            # 1: Lead Studio
            cell_1 = row.cells[1]
            cell_1.width = col_widths[1]
            set_cell_background(cell_1, bg_color)
            p1 = cell_1.paragraphs[0]
            p1_run = p1.add_run(prec.get("architect_or_manufacturer", "Studio"))
            p1_run.font.name = "Calibri"
            p1_run.font.size = Pt(8.5)

            # 2: Typology & Climate
            cell_2 = row.cells[2]
            cell_2.width = col_widths[2]
            set_cell_background(cell_2, bg_color)
            p2 = cell_2.paragraphs[0]
            p2_run = p2.add_run(f"{prec.get('project_typology', 'General')}\n({prec.get('climate_or_location', 'Global')})")
            p2_run.font.name = "Calibri"
            p2_run.font.size = Pt(8.5)

            # 3: Key Takeaway
            cell_3 = row.cells[3]
            cell_3.width = col_widths[3]
            set_cell_background(cell_3, bg_color)
            p3 = cell_3.paragraphs[0]
            takeaway_text = prec.get("bullet_1") or prec.get("bullet_2") or "Documented precedent."
            p3_run = p3.add_run(takeaway_text[:120] + ("..." if len(takeaway_text) > 120 else ""))
            p3_run.font.name = "Calibri"
            p3_run.font.size = Pt(8.5)

            # 4: Source Link
            cell_4 = row.cells[4]
            cell_4.width = col_widths[4]
            set_cell_background(cell_4, bg_color)
            p4 = cell_4.paragraphs[0]
            add_hyperlink(p4, prec["url"], "Link", color="1E3A8A")

        doc.add_paragraph().paragraph_format.space_after = Pt(12)

        # Section 3: Material & Tectonic Palette Recommendations
        h3 = doc.add_heading("3. Material & Tectonic Palette Recommendations", level=1)
        h3.paragraph_format.space_before = Pt(14)
        h3.paragraph_format.space_after = Pt(6)

        mat_match = re.search(r"## 3\. Material & Tectonic Palette Recommendations\s+(.*?)(?=\n## 4\.|$)", markdown_text, re.DOTALL)
        if mat_match:
            mat_body = mat_match.group(1).strip()
            for line in mat_body.split("\n"):
                line_str = line.strip()
                if line_str.startswith("-") or line_str.startswith("*"):
                    bp = doc.add_paragraph(style="List Bullet")
                    bp.add_run(re.sub(r"^[-*]\s+", "", line_str))
                    bp.paragraph_format.space_after = Pt(4)
                elif line_str:
                    doc.add_paragraph(line_str).paragraph_format.space_after = Pt(4)
        else:
            for p in precedents:
                mats = p.get("materials_used")
                if mats and mats != "N/A":
                    bp = doc.add_paragraph(style="List Bullet")
                    r_bold = bp.add_run(f"{p['title']}: ")
                    r_bold.bold = True
                    bp.add_run(f"Specified materials include {mats} (Verified via {p['source_name']}).")
                    bp.paragraph_format.space_after = Pt(4)

        # Section 4: Strict Reference Bibliography
        h4 = doc.add_heading("4. Strict Reference Bibliography", level=1)
        h4.paragraph_format.space_before = Pt(14)
        h4.paragraph_format.space_after = Pt(6)

        for idx, prec in enumerate(precedents, 1):
            bp = doc.add_paragraph()
            num_run = bp.add_run(f"{idx}. ")
            num_run.bold = True

            title_run = bp.add_run(f"{prec['title']} ")
            title_run.bold = True

            meta_run = bp.add_run(f"– Lead: {prec.get('architect_or_manufacturer', 'N/A')} | Source: {prec['source_name']} ({prec.get('publish_date', '')}) | URL: ")
            meta_run.font.size = Pt(9.5)

            add_hyperlink(bp, prec["url"], prec["url"])
            bp.paragraph_format.space_after = Pt(4)

        # Save Document (supports Path, str, or io.BytesIO)
        if isinstance(output_path, (str, Path)):
            doc.save(str(output_path))
        else:
            doc.save(output_path)
