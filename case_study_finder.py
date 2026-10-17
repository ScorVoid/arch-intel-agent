"""
File: case_study_finder.py
Purpose: CLI Case Study Retrieval Tool for Future Architectural Projects.

Usage:
  python case_study_finder.py "Hospitality project in a humid coastal climate using sustainable timber and perforated brick"
  python case_study_finder.py --category MATERIAL_LAUNCH_NEWS "bio-composite facade"
  python case_study_finder.py --interactive
"""

import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv

# Ensure root dir in path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.case_study_db import CaseStudyDatabase

load_dotenv()


def display_results(results):
    """Prints retrieved case studies in a readable terminal layout."""
    if not results:
        print("\n❌ No matching case studies found. Try broadening your query or indexing more feeds.")
        return

    print(f"\n🔍 Found {len(results)} verified case study precedent(s):\n")
    print("=" * 80)

    for i, res in enumerate(results, 1):
        print(f"[{i}] {res['title']}")
        print(f"    Category:     {res['category']}")
        print(f"    Source:       {res['source_name']} ({res['publish_date']})")
        print(f"    Lead Studio:  {res['architect_or_manufacturer']}")
        print(f"    Typology:     {res['project_typology']} | Location/Climate: {res['climate_or_location']}")
        print(f"    Materials:    {res['materials_used']}")
        print(f"    Relevance:    {res['similarity_score'] * 100:.1f}% Match")
        print(f"    Direct URL:   {res['url']}")
        print(f"    Key Takeaways:")
        if res.get("bullet_1"):
            print(f"      • {res['bullet_1']}")
        if res.get("bullet_2"):
            print(f"      • {res['bullet_2']}")
        if res.get("bullet_3"):
            print(f"      • {res['bullet_3']}")
        print("-" * 80)


def interactive_mode(db: CaseStudyDatabase):
    """Interactive CLI prompt loop for architectural queries."""
    print("\n" + "=" * 80)
    print("🏛️  ArchIntel-Agent: Interactive Case Study & Precedent Finder")
    print(f"Current Database Records: {db.get_total_count()}")
    print("Type your project design requirements or 'exit' to quit.")
    print("=" * 80)

    while True:
        try:
            query = input("\nArchitectural Query > ").strip()
            if not query or query.lower() in ("exit", "quit", "q"):
                print("Exiting case study finder.")
                break

            results = db.search_case_studies(query, n_results=5)
            display_results(results)
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break


def main():
    parser = argparse.ArgumentParser(
        description="Search curated architectural case studies and material launches."
    )
    parser.add_argument(
        "query",
        nargs="?",
        type=str,
        default="",
        help="Natural language project description (e.g. 'coastal timber pavilion with passive ventilation')"
    )
    parser.add_argument(
        "--category",
        choices=["ALL", "ARCHITECTURAL_NEWS", "INTERIOR_NEWS", "MATERIAL_LAUNCH_NEWS"],
        default="ALL",
        help="Filter by specific category"
    )
    parser.add_argument(
        "--typology",
        type=str,
        default="ALL",
        help="Filter by project typology (e.g. Hospitality, Residential)"
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of results to retrieve (default: 5)"
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Launch interactive terminal prompt"
    )

    args = parser.parse_args()
    db = CaseStudyDatabase()

    if args.interactive or not args.query:
        interactive_mode(db)
    else:
        results = db.search_case_studies(
            query=args.query,
            n_results=args.top_k,
            category=None if args.category == "ALL" else args.category,
            typology=None if args.typology == "ALL" else args.typology
        )
        display_results(results)


if __name__ == "__main__":
    main()
