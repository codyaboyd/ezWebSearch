from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from config import Settings
from search_service import SearchService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one ezWebSearch query through SearXNG, retrieve the "
            "requested number of pages, "
            "render JavaScript-heavy pages when necessary, and print/save JSON."
        )
    )

    parser.add_argument(
        "query",
        nargs="?",
        help='Search query, e.g. "best local LLMs"',
    )
    parser.add_argument(
        "-q",
        "--query",
        dest="query_flag",
        help="Search query; alternative to the positional query",
    )
    parser.add_argument(
        "-l",
        "--links",
        type=int,
        default=5,
        help="Number of successfully extracted pages required (default: 5)",
    )
    parser.add_argument(
        "-r",
        "--retries",
        type=int,
        default=2,
        help=(
            "Number of additional SearXNG result pages to try "
            "(default: 2)"
        ),
    )
    parser.add_argument(
        "--searxng-url",
        default=Settings.from_env().searxng_url,
        help=(
            "SearXNG base URL (default: http://127.0.0.1:6667; "
            "or use SEARXNG_URL)."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Optional path to write the JSON result",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Print compact JSON instead of pretty-printed JSON",
    )

    return parser


async def run(args: argparse.Namespace) -> int:
    query = args.query_flag or args.query

    if not query:
        print("error: a query is required", file=sys.stderr)
        return 2

    try:
        settings = Settings.from_env()
        if getattr(args, "searxng_url", None):
            settings.searxng_url = args.searxng_url

        async with SearchService(settings) as service:
            result = await service.search(
                query=query,
                links=args.links,
                retries=args.retries,
            )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.compact:
        rendered = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    else:
        rendered = json.dumps(result, ensure_ascii=False, indent=2)

    print(rendered)

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")

    return 0 if result.get("complete") else 3


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
