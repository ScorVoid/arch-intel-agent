"""
Module: src/case_study_db.py
Purpose: Persistent SQLite + Vector Embedding Case Study Retrieval Engine.

Architectural Design Notes for AI Engineering:
---------------------------------------------
1. Why Vector Embeddings for Architecture?
   Architects search using descriptive, conceptual language:
   "Hospitality project in a humid coastal climate using sustainable timber and perforated brick"
   Traditional keyword search fails when an article discusses "resorts", "tropical shores", "CLT mass timber",
   and "porous terracotta screens". Vector embeddings map both the user's prompt and the articles
   into an n-dimensional geometric space where conceptual similarity translates directly to vector proximity.
2. Production SQLite + Dense Vector Search:
   Using SQLite with NumPy vector similarity offers distinct enterprise advantages:
   - Zero compilation overhead: Standard library SQLite requires no external C++ toolchains on Windows.
   - Atomic persistence: All case study records and embeddings reside in `data/case_studies_db/case_studies.sqlite3`.
   - Hybrid Filtering: Combines hard SQL filters (`category`, `typology`) with dense semantic ranking.
3. Offline & Online Embedding Support:
   When `GEMINI_API_KEY` is provided, high-dimensional embeddings are generated via Google GenAI's
   `text-embedding-004`. In offline/test mode, an intelligent fallback vectorizer allows local testing.
"""

import os
import json
import sqlite3
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
import numpy as np
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("ArchIntel.CaseStudyDB")

DEFAULT_DB_DIR = Path(__file__).resolve().parent.parent / "data" / "case_studies_db"
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "case_studies.sqlite3"


def _resolve_db_path(custom_path: Optional[Path] = None) -> Path:
    if custom_path:
        return custom_path
    
    # If on Vercel serverless environment, copy packaged database to writable /tmp
    if os.environ.get("VERCEL") == "1":
        tmp_db = Path("/tmp/case_studies.sqlite3")
        if not tmp_db.exists() and DEFAULT_DB_PATH.exists():
            try:
                import shutil
                shutil.copyfile(str(DEFAULT_DB_PATH), str(tmp_db))
                logger.info("Copied packaged SQLite database to /tmp/case_studies.sqlite3 for Vercel")
            except Exception as e:
                logger.warning(f"Failed to copy DB to /tmp: {e}")
        return tmp_db
        
    return DEFAULT_DB_PATH


class CaseStudyDatabase:
    """
    Manages persistent indexing and semantic retrieval of architectural precedents in SQLite.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = _resolve_db_path(db_path)
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        self._init_db()

        # Connect to Google GenAI for embeddings if API key is provided
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.embedding_model = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
        self.genai_client = None

        if self.api_key and self.api_key != "YOUR_GEMINI_API_KEY_HERE":
            try:
                from google import genai
                self.genai_client = genai.Client(api_key=self.api_key)
                logger.info(f"Initialized Google GenAI Embeddings client ({self.embedding_model})")
            except Exception as e:
                logger.warning(f"Could not connect to GenAI embeddings: {e}")

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Creates the case studies table and indexes if not already present."""
        try:
            with self._get_connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS case_studies (
                        id TEXT PRIMARY KEY,
                        url TEXT UNIQUE,
                        title TEXT NOT NULL,
                        source_name TEXT,
                        publish_date TEXT,
                        category TEXT,
                        architect_or_manufacturer TEXT,
                        project_typology TEXT,
                        climate_or_location TEXT,
                        materials_used TEXT,
                        bullet_1 TEXT,
                        bullet_2 TEXT,
                        bullet_3 TEXT,
                        document_text TEXT,
                        embedding TEXT,
                        is_bookmarked INTEGER DEFAULT 0
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_category ON case_studies(category)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_typology ON case_studies(project_typology)")
                
                # Safe column migration for existing tables
                try:
                    conn.execute("ALTER TABLE case_studies ADD COLUMN is_bookmarked INTEGER DEFAULT 0")
                except Exception:
                    pass  # Column already exists

                # Auto-seed from data/seed_case_studies.json if database is empty (e.g. freshly booted on Vercel)
                try:
                    count = conn.execute("SELECT COUNT(*) FROM case_studies").fetchone()[0]
                    if count == 0:
                        seed_path = Path(__file__).resolve().parent.parent / "data" / "seed_case_studies.json"
                        if seed_path.exists():
                            with open(seed_path, "r", encoding="utf-8") as f:
                                seed_data = json.load(f)
                            for row in seed_data:
                                conn.execute("""
                                    INSERT OR REPLACE INTO case_studies (
                                        id, url, title, source_name, publish_date, category,
                                        architect_or_manufacturer, project_typology, climate_or_location,
                                        materials_used, bullet_1, bullet_2, bullet_3, document_text, embedding, is_bookmarked
                                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                Beweisen
                                """.replace("Beweisen", ""), (
                                    row.get("id"), row.get("url"), row.get("title"), row.get("source_name"),
                                    row.get("publish_date"), row.get("category"), row.get("architect_or_manufacturer"),
                                    row.get("project_typology"), row.get("climate_or_location"), row.get("materials_used"),
                                    row.get("bullet_1"), row.get("bullet_2"), row.get("bullet_3"), row.get("document_text"),
                                    row.get("embedding"), row.get("is_bookmarked", 0)
                                ))
                            conn.commit()
                            logger.info(f"Auto-seeded {len(seed_data)} verified precedents from seed JSON")
                except Exception as seed_err:
                    logger.debug(f"Auto-seeding check skipped: {seed_err}")
                    
                conn.commit()
        except Exception as e:
            logger.warning(f"Could not initialize or migrate schema (might be read-only): {e}")

    def _get_embedding(self, text: str) -> List[float]:
        """
        Generates semantic embedding vector.
        Uses Google GenAI gemini-embedding-001 when available, or a deterministic vector fallback offline.
        """
        if self.genai_client:
            try:
                response = self.genai_client.models.embed_content(
                    model=self.embedding_model,
                    contents=text
                )
                embeddings = getattr(response, "embeddings", None)
                if embeddings and len(embeddings) > 0:
                    return list(embeddings[0].values)
                single_emb = getattr(response, "embedding", None)
                if single_emb and hasattr(single_emb, "values"):
                    return list(single_emb.values)
            except Exception as e:
                logger.warning(f"GenAI embedding error: {e}. Falling back to local vectorizer.")

        # Offline deterministic fallback vectorizer (dimension 128)
        # Allows full testing of cosine ranking without active API key
        return self._offline_vectorize(text)

    def _offline_vectorize(self, text: str, dim: int = 128) -> List[float]:
        """Generates a normalized deterministic feature vector based on text token hashing."""
        words = text.lower().split()
        vec = np.zeros(dim, dtype=np.float32)
        for w in words:
            h = hash(w) % dim
            vec[h] += 1.0
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()

    def index_article(self, article: Dict[str, Any], triage_result: Any) -> bool:
        """
        Indexes a verified article and its structured metadata into SQLite.
        """
        if not getattr(triage_result, "is_relevant", True):
            logger.info(f"Skipping indexing for irrelevant article: {article.get('title')}")
            return False

        url = article.get("url", "")
        if not url:
            return False

        doc_id = f"arch_{abs(hash(url))}"
        title = article.get("title", "Untitled")
        source_name = article.get("source_name", "Unknown")
        publish_date = article.get("publish_date", "")

        category = getattr(triage_result, "category", "ARCHITECTURAL_NEWS")
        category_str = category.value if hasattr(category, "value") else str(category)

        architect = getattr(triage_result, "architect_or_manufacturer", "Unknown") or "Unknown"
        typology = getattr(triage_result, "project_typology", "General") or "General"
        climate = getattr(triage_result, "climate_or_location", "Global") or "Global"
        materials = getattr(triage_result, "materials_used", []) or []
        materials_str = ", ".join(materials) if isinstance(materials, list) else str(materials)

        bullets = getattr(triage_result, "three_bullet_summary", [])
        bullet_1 = bullets[0] if len(bullets) > 0 else ""
        bullet_2 = bullets[1] if len(bullets) > 1 else ""
        bullet_3 = bullets[2] if len(bullets) > 2 else ""

        document_text = f"""
TITLE: {title}
SOURCE: {source_name}
CATEGORY: {category_str}
ARCHITECT/MANUFACTURER: {architect}
TYPOLOGY: {typology}
LOCATION/CLIMATE: {climate}
MATERIALS & FINISHES: {materials_str}
SUMMARY:
- {bullet_1}
- {bullet_2}
- {bullet_3}
CONTENT:
{article.get('raw_content', '')[:1200]}
""".strip()

        embedding = self._get_embedding(document_text)
        embedding_json = json.dumps(embedding)

        try:
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO case_studies (
                        id, url, title, source_name, publish_date, category,
                        architect_or_manufacturer, project_typology, climate_or_location,
                        materials_used, bullet_1, bullet_2, bullet_3, document_text, embedding
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    doc_id, url, title, source_name, publish_date, category_str,
                    architect, typology, climate, materials_str,
                    bullet_1, bullet_2, bullet_3, document_text, embedding_json
                ))
                conn.commit()
            logger.info(f"Indexed case study: '{title}' [{category_str}]")
            return True
        except Exception as e:
            logger.error(f"Failed to index case study into SQLite: {e}")
            return False

    def search_case_studies(
        self,
        query: str,
        n_results: int = 5,
        category: Optional[str] = None,
        typology: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieves top-matching case studies given a natural-language architectural project query.
        Combines SQL metadata filtering with cosine vector similarity ranking.
        """
        query_vec = np.array(self._get_embedding(query), dtype=np.float32)
        q_norm = np.linalg.norm(query_vec)
        if q_norm > 0:
            query_vec = query_vec / q_norm

        conditions = []
        params = []

        if category and category != "ALL":
            conditions.append("category = ?")
            params.append(category)

        if typology and typology != "ALL":
            conditions.append("project_typology LIKE ?")
            params.append(f"%{typology}%")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        sql = f"""
            SELECT id, url, title, source_name, publish_date, category,
                   architect_or_manufacturer, project_typology, climate_or_location,
                   materials_used, bullet_1, bullet_2, bullet_3, embedding, is_bookmarked
            FROM case_studies
            {where_clause}
        """

        with self._get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()

        if not rows:
            return []

        scored_results = []
        for row in rows:
            doc_data = dict(row)
            emb_str = doc_data.pop("embedding", "[]")
            try:
                emb_vec = np.array(json.loads(emb_str), dtype=np.float32)
                d_norm = np.linalg.norm(emb_vec)
                if d_norm > 0 and q_norm > 0 and len(query_vec) == len(emb_vec):
                    similarity = float(np.dot(query_vec, emb_vec) / (q_norm * d_norm))
                elif d_norm > 0 and len(emb_vec) == 128:
                    q_sub = np.array(self._offline_vectorize(query), dtype=np.float32)
                    qs_norm = np.linalg.norm(q_sub)
                    similarity = float(np.dot(q_sub, emb_vec) / (qs_norm * d_norm)) if qs_norm > 0 else 0.5
                else:
                    similarity = 0.5
            except Exception:
                similarity = 0.5

            doc_data["similarity_score"] = round(similarity, 3)
            scored_results.append(doc_data)

        # Sort descending by similarity score
        scored_results.sort(key=lambda x: x["similarity_score"], reverse=True)
        return scored_results[:n_results]

    def toggle_bookmark(self, doc_id: str) -> bool:
        """
        Toggles the bookmark status (1 or 0) for a case study.
        Matches by id or url. Returns the new bookmarked state.
        """
        with self._get_connection() as conn:
            row = conn.execute("SELECT is_bookmarked, id FROM case_studies WHERE id = ? OR url = ?", (doc_id, doc_id)).fetchone()
            if not row:
                return False
            current = row[0] or 0
            actual_id = row[1]
            new_val = 0 if current else 1
            conn.execute("UPDATE case_studies SET is_bookmarked = ? WHERE id = ?", (new_val, actual_id))
            conn.commit()
            return bool(new_val)

    def get_bookmarked(self) -> List[Dict[str, Any]]:
        """Returns all shortlisted/bookmarked case studies."""
        sql = """
            SELECT id, url, title, source_name, publish_date, category,
                   architect_or_manufacturer, project_typology, climate_or_location,
                   materials_used, bullet_1, bullet_2, bullet_3, is_bookmarked
            FROM case_studies
            WHERE is_bookmarked = 1
            ORDER BY rowid DESC
        """
        with self._get_connection() as conn:
            rows = conn.execute(sql).fetchall()
            return [dict(r) for r in rows]

    def get_total_count(self) -> int:
        """Returns total number of indexed case studies."""
        try:
            with self._get_connection() as conn:
                res = conn.execute("SELECT COUNT(*) FROM case_studies").fetchone()
                return res[0] if res else 0
        except Exception:
            return 0

    def get_all_recent(self, limit: int = 60, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieves recent indexed articles, optionally filtered by category.
        """
        params = []
        where_clause = ""
        if category and category != "ALL":
            where_clause = "WHERE category = ?"
            params.append(category)

        sql = f"""
            SELECT id, url, title, source_name, publish_date, category,
                   architect_or_manufacturer, project_typology, climate_or_location,
                   materials_used, bullet_1, bullet_2, bullet_3, is_bookmarked
            FROM case_studies
            {where_clause}
            ORDER BY rowid DESC
            LIMIT ?
        """
        params.append(limit)

        try:
            with self._get_connection() as conn:
                rows = conn.execute(sql, params).fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"Error fetching recent articles: {e}")
            return []

    def get_articles_by_ids(self, article_ids: List[str]) -> List[Dict[str, Any]]:
        """
        Retrieves case study records matching any of the provided IDs or URLs.
        Preserves the input ordering.
        """
        if not article_ids:
            return []

        clean_ids = [str(aid).strip() for aid in article_ids if str(aid).strip()]
        if not clean_ids:
            return []

        placeholders = ",".join("?" for _ in clean_ids)
        sql = f"""
            SELECT id, url, title, source_name, publish_date, category,
                   architect_or_manufacturer, project_typology, climate_or_location,
                   materials_used, bullet_1, bullet_2, bullet_3, is_bookmarked
            FROM case_studies
            WHERE id IN ({placeholders}) OR url IN ({placeholders})
        """
        try:
            with self._get_connection() as conn:
                rows = conn.execute(sql, clean_ids + clean_ids).fetchall()
                items = [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"Error fetching articles by IDs: {e}")
            return []

        # Order by input IDs
        id_map = {item["id"]: item for item in items}
        url_map = {item["url"]: item for item in items}
        ordered = []
        seen = set()
        for aid in clean_ids:
            match = id_map.get(aid) or url_map.get(aid)
            if match and match["id"] not in seen:
                ordered.append(match)
                seen.add(match["id"])
        return ordered

    def export_seed_json(self, output_path: Optional[Path] = None) -> int:
        """
        Exports all indexed case studies from SQLite into data/seed_case_studies.json.
        Enables seamless persistence on serverless platforms (Vercel) by bundling
        the latest scraped architectural precedents with the repository.
        """
        target = output_path or (Path(__file__).resolve().parent.parent / "data" / "seed_case_studies.json")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            sql = """
                SELECT id, url, title, source_name, publish_date, category,
                       architect_or_manufacturer, project_typology, climate_or_location,
                       materials_used, bullet_1, bullet_2, bullet_3, document_text,
                       embedding, is_bookmarked
                FROM case_studies
                ORDER BY rowid DESC
            """
            with self._get_connection() as conn:
                rows = conn.execute(sql).fetchall()
                data = []
                for r in rows:
                    item = dict(r)
                    doc_txt = item.get("document_text") or item.get("title", "")
                    compact_vec = self._offline_vectorize(doc_txt, dim=128)
                    item["embedding"] = json.dumps([round(float(x), 4) for x in compact_vec])
                    data.append(item)

            with open(target, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            logger.info(f"Exported {len(data)} precedents to seed JSON at {target}")
            return len(data)
        except Exception as e:
            logger.error(f"Failed to export seed JSON to {target}: {e}")
            return 0
