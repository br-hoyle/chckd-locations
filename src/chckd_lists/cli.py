"""Entry point: `chckd-lists <command>` (installed by poetry) or
`python -m chckd_lists.cli <command>`. Plain argparse — no click/typer
dependency for five subcommands.
"""

import argparse
import logging
from datetime import datetime, timezone

from chckd_lists.db.connection import connect
from chckd_lists.db.migrate import migrate
from chckd_lists.ids import make_id
from chckd_lists.logging_conf import setup_logging
from chckd_lists.pipeline.load_dimensions import load_all_dimensions
from chckd_lists.pipeline.registry_loader import load_all_list_entries
from chckd_lists.pipeline.run import run_list
from chckd_lists.seed.seed_from_context import seed

logger = logging.getLogger(__name__)


def cmd_migrate(_args: argparse.Namespace) -> None:
    migrate()


def cmd_seed(_args: argparse.Namespace) -> None:
    seed()
    con = connect()
    try:
        run_id = make_id("pipeline_run", f"seed:{datetime.now(timezone.utc).isoformat()}")
        con.execute(
            "INSERT INTO pipeline_runs (id, source_slug, started_at, finished_at, status) VALUES (?, ?, ?, ?, 'success')",
            [run_id, "seed", datetime.now(timezone.utc), datetime.now(timezone.utc)],
        )
        load_all_dimensions(con, run_id)
    finally:
        con.close()


def cmd_run(args: argparse.Namespace) -> None:
    con = connect()
    try:
        slugs = [args.slug] if args.slug else [e["slug"] for e in load_all_list_entries()]
        for slug in slugs:
            run_list(con, slug)
    finally:
        con.close()


def cmd_list(_args: argparse.Namespace) -> None:
    for entry in load_all_list_entries():
        print(f"{entry['slug']:40s} tier={entry.get('tier')} status={entry.get('status')} source={entry['source']['type']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chckd-lists")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate", help="Apply db/schema.sql to data/chckd.duckdb").set_defaults(func=cmd_migrate)

    sub.add_parser(
        "seed", help="Regenerate registry/ from chckd-context, then load dimension tables"
    ).set_defaults(func=cmd_seed)

    run_parser = sub.add_parser("run", help="Run one list's pipeline (or all, with --all)")
    run_parser.add_argument("slug", nargs="?", help="registry/lists/<slug>.yaml to run")
    run_parser.add_argument("--all", dest="all_", action="store_true", help="run every registered list")
    run_parser.set_defaults(func=cmd_run)

    sub.add_parser("list", help="List every registered list and its status").set_defaults(func=cmd_list)

    return parser


def main() -> None:
    setup_logging()
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "run" and not args.slug and not args.all_:
        parser.error("run requires a slug, or --all")
    args.func(args)


if __name__ == "__main__":
    main()
