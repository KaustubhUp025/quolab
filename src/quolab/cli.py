"""Tiny CLI: index / search a repo, or run the policy gate, from the terminal."""

from __future__ import annotations

import argparse
import sys

from quolab.engine import SearchEngine, format_results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quolab", description="OSS semantic code search")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_index = sub.add_parser("index", help="index a repo")
    p_index.add_argument("project_id")
    p_index.add_argument("--ref", default="HEAD")
    p_index.add_argument("--force", action="store_true")

    p_search = sub.add_parser("search", help="semantic search a repo")
    p_search.add_argument("project_id")
    p_search.add_argument("query")
    p_search.add_argument("--ref", default="HEAD")
    p_search.add_argument("-k", "--max-results", type=int, default=5)

    p_serve = sub.add_parser("serve", help="run the FastAPI service")

    args = parser.parse_args(argv)

    if args.cmd == "serve":
        from quolab.app import main as serve_main

        serve_main()
        return 0

    engine = SearchEngine()
    if args.cmd == "index":
        stats = engine.index(args.project_id, args.ref, force=args.force)
        print(f"indexed {stats.files} files → {stats.chunks} chunks")
        return 0
    if args.cmd == "search":
        results = engine.search(args.project_id, args.query, args.ref, args.max_results)
        print(format_results(args.query, results))
        return 0
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
