"""
Module: src/ingestor.py
Purpose: Strict RSS/Atom Feed Ingestion with Canonical Domain Guarding.

Architectural Design Notes for AI Engineering:
---------------------------------------------
1. Zero-Trust Web Ingestion:
   LLM systems easily hallucinate or pick up junk if fed arbitrary web search
   results or SEO clickbait. By validating against a strict whitelist of
   authoritative architectural publications, we ensure high signal-to-noise ratio.
2. Graceful Network Resilience:
   Web scrapers frequently face rate limits, network timeouts, or malformed HTML.
   We use `httpx` with timeout limits and headers, plus fallback to RSS summaries
   if full-page body extraction fails.
"""

import sys
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse

try:
    import yaml
except ImportError:
    from ruamel.yaml import YAML
    _yaml_parser = YAML(typ='safe')
    class _YamlCompat:
        @staticmethod
        def safe_load(f):
            return _yaml_parser.load(f)
    yaml = _YamlCompat()

import feedparser
import httpx
from bs4 import BeautifulSoup

# Configure logging to clearly visualize pipeline activity
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("ArchIntel.Ingestor")

# Default path to trusted sources YAML configuration
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "trusted_sources.yaml"


class DomainGuard:
    """
    Enforces strict whitelisting of domains. Any URL outside the allowed domains
    is immediately rejected before fetching to protect pipeline integrity.
    """

    def __init__(self, allowed_domains: List[str]):
        # Normalize allowed domains to lowercase
        self.allowed_domains = {d.lower().strip() for d in allowed_domains}

    def is_allowed(self, url: str) -> bool:
        """
        Validates if the provided URL's domain or parent domain matches the whitelist.
        """
        if not url:
            return False
        try:
            parsed = urlparse(url)
            hostname = (parsed.netloc or "").lower().split(":")[0]  # strip port
            if not hostname:
                return False

            # Check direct match
            if hostname in self.allowed_domains:
                return True

            # Check parent domain (e.g., news.archdaily.com matches archdaily.com)
            parts = hostname.split(".")
            if len(parts) > 2:
                parent_domain = ".".join(parts[-2:])
                if parent_domain in self.allowed_domains:
                    return True

            return False
        except Exception as e:
            logger.warning(f"Domain validation error for URL '{url}': {e}")
            return False


class FeedIngestor:
    """
    Handles fetching and parsing of trusted RSS feeds, domain verification,
    and article full-text extraction.
    """

    def __init__(self, config_file: Optional[Path] = None):
        self.config_path = config_file or CONFIG_PATH
        self.config = self._load_config()
        self.domain_guard = DomainGuard(self.config.get("allowed_domains", []))
        self.sources = self.config.get("sources", [])
        
        # Standard desktop User-Agent to avoid generic bot blocking on RSS/HTML
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36 ArchIntelBot/1.0"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }

    def _load_config(self) -> Dict[str, Any]:
        """Loads and parses the YAML whitelist config."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")
        with open(self.config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def fetch_full_text(self, url: str, client: httpx.Client) -> str:
        """
        Fetches the article webpage and extracts clean readable text,
        stripping out navbars, sidebars, advertisements, and scripts.
        """
        # Guard: check domain before making an HTTP request
        if not self.domain_guard.is_allowed(url):
            logger.warning(f"SECURITY GUARD: URL rejected by domain whitelist: {url}")
            return ""

        try:
            response = client.get(url, headers=self.headers, timeout=12.0, follow_redirects=True)
            if response.status_code != 200:
                logger.debug(f"Failed to fetch {url} (HTTP {response.status_code})")
                return ""

            soup = BeautifulSoup(response.text, "html.parser")

            # Remove non-content elements
            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript", "svg"]):
                tag.decompose()

            # Prefer main article container if available
            article_tag = soup.find("article") or soup.find("main") or soup.find(id="content") or soup.body
            if not article_tag:
                return ""

            # Extract paragraphs
            paragraphs = [p.get_text(separator=" ", strip=True) for p in article_tag.find_all("p")]
            cleaned_text = "\n\n".join(p for p in paragraphs if len(p) > 25)

            # Limit text length to avoid token bloat (approx 4000 characters is plenty for architectural triage)
            return cleaned_text[:4000]

        except Exception as e:
            logger.debug(f"Could not extract full text for {url}: {e}")
            return ""

    def ingest_feed(self, source: Dict[str, Any], max_items: int = 5) -> List[Dict[str, Any]]:
        """
        Parses a single feed, filters entries against the domain guard,
        and extracts article payloads.
        """
        feed_url = source.get("feed_url")
        source_name = source.get("name")
        logger.info(f"Ingesting feed: {source_name} ({feed_url})")

        articles: List[Dict[str, Any]] = []

        try:
            # feedparser handles XML/RSS/Atom variants automatically
            parsed_feed = feedparser.parse(feed_url)
            if not parsed_feed.entries:
                logger.warning(f"No entries returned for {source_name}")
                return articles

            with httpx.Client(http2=False) as client:
                for entry in parsed_feed.entries[:max_items]:
                    link = entry.get("link", "").strip()
                    title = entry.get("title", "").strip()
                    published = entry.get("published", "") or entry.get("updated", "")

                    if not link or not title:
                        continue

                    # Strict Domain Whitelist check
                    if not self.domain_guard.is_allowed(link):
                        logger.warning(f"Skipping link from unauthorized domain: {link}")
                        continue

                    # Extract RSS description / summary
                    rss_summary = ""
                    if "summary" in entry:
                        rss_summary = BeautifulSoup(entry.summary, "html.parser").get_text(strip=True)

                    # Fetch full text
                    full_text = self.fetch_full_text(link, client)
                    content_to_use = full_text if full_text else rss_summary

                    articles.append({
                        "title": title,
                        "url": link,
                        "source_name": source_name,
                        "publish_date": published,
                        "raw_content": content_to_use,
                        "rss_summary": rss_summary,
                        "category_hint": source.get("category_hint", "GENERAL")
                    })

            logger.info(f"Successfully ingested {len(articles)} articles from {source_name}")
        except Exception as e:
            logger.error(f"Error reading feed {source_name}: {e}")

        return articles

    def ingest_all(self, max_items_per_source: int = 3) -> List[Dict[str, Any]]:
        """
        Iterates over all enabled trusted sources and extracts articles.
        """
        all_articles: List[Dict[str, Any]] = []
        for source in self.sources:
            if not source.get("enabled", True):
                continue
            items = self.ingest_feed(source, max_items=max_items_per_source)
            all_articles.extend(items)
        return all_articles


if __name__ == "__main__":
    # Dry-run test demonstration (No API key required!)
    print("\n" + "=" * 60)
    print("ArchIntel-Agent: Live Ingestor & Domain Guard Dry Run")
    print("=" * 60)

    ingestor = FeedIngestor()
    print(f"Loaded {len(ingestor.sources)} sources from configuration.")
    print("Whitelisted domains:", ", ".join(sorted(ingestor.domain_guard.allowed_domains)))

    # Test Domain Guard with an allowed and a blocked domain
    print("\n[Testing Domain Guard Security]")
    test_urls = [
        "https://www.archdaily.com/101234/timber-pavilion",
        "https://www.dezeen.com/2026/04/concrete-tower/",
        "https://random-spam-blog.xyz/scam-article",
        "https://fastfashionweekly.com/trends"
    ]
    for url in test_urls:
        allowed = ingestor.domain_guard.is_allowed(url)
        status = "ALLOWED" if allowed else "BLOCKED (REJECTED)"
        print(f"  {url} -> {status}")

    # Test live feed fetch on the first enabled source
    print("\n[Testing Live Feed Fetch from Primary Source]")
    first_source = ingestor.sources[0]
    sample_articles = ingestor.ingest_feed(first_source, max_items=2)

    print(f"\nFetched {len(sample_articles)} articles from {first_source['name']}:")
    for i, art in enumerate(sample_articles, 1):
        print(f"\n--- Article {i} ---")
        print(f"Title: {art['title']}")
        print(f"URL: {art['url']}")
        print(f"Date: {art['publish_date']}")
        print(f"Content Preview: {art['raw_content'][:180]}...")
