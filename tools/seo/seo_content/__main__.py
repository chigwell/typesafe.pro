import argparse
import sys
from pathlib import Path

from .errors import ContentApiError, ReviewError


def main():
    parser = argparse.ArgumentParser(description="Verified TypeSafe use-case pages")
    commands = parser.add_subparsers(dest="command", required=True)
    review = commands.add_parser(
        "review", help="Interactively generate, preview, publish or skip new pages"
    )
    review.add_argument("--max-pages", type=int, default=5, help="Approvals per session (1–20)")
    review.add_argument("--resume", action="store_true", help="Review pending drafts first")
    review.add_argument(
        "--auto-select", action="store_true", help="Take every idea and the first demo concept"
    )
    review.add_argument(
        "--preview-base",
        default="https://typesafe.pro",
        help="Site that renders previews (e.g. http://localhost:8787 for `wrangler dev`)",
    )
    review.add_argument("--no-browser", action="store_true", help="Print preview URLs only")
    review.add_argument("--max-calls", type=int, default=400)
    review.add_argument("--max-minutes", type=float, default=60)
    review.add_argument("--session-id", default=None)
    review.add_argument(
        "--inspiration",
        choices=["hn", "words", "none"],
        default="hn",
        help="Idea seeds: newest Hacker News titles (default), random words, or none",
    )
    review.add_argument("--headlines", type=int, default=5, help="Seeds per idea round (1–10)")
    commands.add_parser("check", help="Validate every stored page against the schema")
    importer = commands.add_parser(
        "import-files", help="One-time import of the former file catalog into the API"
    )
    importer.add_argument(
        "--content-dir",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "content" / "use-cases",
    )
    importer.add_argument(
        "--taxonomy",
        choices=["llm", "heuristic"],
        default="llm",
        help="How categories and tags are assigned to imported pages",
    )
    args = parser.parse_args()
    try:
        if args.command == "check":
            from .maintenance import check

            return check()
        if args.command == "import-files":
            from .maintenance import import_files

            return import_files(args.content_dir, taxonomy=args.taxonomy)
        from .providers import Budget
        from .review import ReviewSession

        if not 1 <= args.max_pages <= 20:
            raise ReviewError("--max-pages must be between 1 and 20")
        session = ReviewSession(
            session_id=args.session_id,
            budget=Budget(max_calls=args.max_calls, max_seconds=args.max_minutes * 60),
            preview_base=args.preview_base,
            open_browser=not args.no_browser,
            auto_select=args.auto_select,
            max_pages=args.max_pages,
            inspiration=args.inspiration,
            headlines=min(max(args.headlines, 1), 10),
        )
        report = session.run(resume=args.resume)
        return 0 if report.approved_count or report.skipped_count else 2
    except ContentApiError as exc:
        print(f"Content API failure: {exc} {getattr(exc, 'detail', '') or ''}", file=sys.stderr)
        return 1
    except ReviewError as exc:
        print(f"Review cannot start: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
