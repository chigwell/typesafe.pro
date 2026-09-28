import argparse
import sys
from pathlib import Path

from .catalog import Catalog, CatalogError
from .providers import Budget
from .review import ReviewError, ReviewSession


def main():
    parser = argparse.ArgumentParser(description="Verified TypeSafe use-case pages")
    parser.add_argument(
        "--content-dir",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "content" / "use-cases",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate", help="Validate storage, examples, indexes and release offline")
    review = commands.add_parser(
        "review", help="Interactively generate, preview, approve or skip new pages"
    )
    review.add_argument("--max-pages", type=int, default=5, help="Approvals per session (1–20)")
    review.add_argument("--resume", action="store_true", help="Review pending drafts first")
    review.add_argument(
        "--auto-select", action="store_true", help="Take every idea and the first demo concept"
    )
    review.add_argument("--dev-url", default="http://localhost:3000")
    review.add_argument("--no-browser", action="store_true", help="Print preview URLs only")
    review.add_argument(
        "--no-dev-server", action="store_true", help="Never start `npm run dev:web`"
    )
    review.add_argument("--max-calls", type=int, default=400)
    review.add_argument("--max-minutes", type=float, default=60)
    review.add_argument("--session-id", default=None)
    args = parser.parse_args()
    try:
        if args.command == "validate":
            catalog = Catalog(args.content_dir)
            release = catalog.validate_release()
            print(f"Validated {len(catalog.pages)} records; {len(release.pages)} released pages.")
            return 0
        if not 1 <= args.max_pages <= 20:
            raise ReviewError("--max-pages must be between 1 and 20")
        session = ReviewSession(
            args.content_dir,
            session_id=args.session_id,
            budget=Budget(max_calls=args.max_calls, max_seconds=args.max_minutes * 60),
            dev_url=args.dev_url,
            start_dev_server=not args.no_dev_server,
            open_browser=not args.no_browser,
            auto_select=args.auto_select,
            max_pages=args.max_pages,
        )
        report = session.run(resume=args.resume)
        return 0 if report.approved_count or report.skipped_count else 2
    except CatalogError as exc:
        print(f"Content integrity failure: {exc}", file=sys.stderr)
        return 1
    except ReviewError as exc:
        print(f"Review cannot start: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
