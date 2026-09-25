import argparse
import sys
from pathlib import Path

from .catalog import Catalog, CatalogError
from .pipeline import generate


def main():
    parser = argparse.ArgumentParser(description="Generate independently verified TypeSafe pages")
    parser.add_argument(
        "--content-dir",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "content" / "use-cases",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate", help="Validate storage, examples, indexes and release offline")
    create = commands.add_parser("generate", help="Prepare up to five new pages for production")
    create.add_argument("--run-id", required=True)
    create.add_argument("--source-sha", required=True)
    create.add_argument("--baseline", type=Path, required=True)
    create.add_argument("--report", type=Path, required=True)
    create.add_argument(
        "--max-new-pages",
        type=int,
        default=5,
        help="Optional tighter allowance (0–5), primarily for controlled pilots",
    )
    args = parser.parse_args()
    try:
        if args.command == "validate":
            catalog = Catalog(args.content_dir)
            release = catalog.validate_release()
            print(f"Validated {len(catalog.pages)} records; {len(release.pages)} released pages.")
        else:
            report = generate(
                args.content_dir,
                run_id=args.run_id,
                source_sha=args.source_sha,
                baseline=args.baseline,
                report_path=args.report,
                max_new_pages=args.max_new_pages,
            )
            print(
                f"Content {report.status}: {report.reason}; "
                f"generated={report.generated_count}, calls={report.api_calls}."
            )
        return 0
    except CatalogError as exc:
        print(f"Content integrity failure: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
