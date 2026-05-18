import argparse
import json
import sqlite3
import sys
from pathlib import Path

from fieldbook.db import init_ledger, resolve_init_path
from fieldbook.errors import ExitCode, FieldbookError, LedgerBusyError


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--ledger", help="Path to Fieldbook ledger")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")


def _cmd_init(args: argparse.Namespace) -> int:
    ledger_path = resolve_init_path(ledger=args.ledger)
    existed = ledger_path.exists()
    init_ledger(ledger_path)
    payload = {"ledger": str(ledger_path), "existed": existed}
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        state = "existing" if existed else "created"
        print(f"{state} Fieldbook ledger: {ledger_path}")
    return ExitCode.SUCCESS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fieldbook")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize a Fieldbook ledger")
    _add_common_options(init_parser)
    init_parser.set_defaults(func=_cmd_init)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FieldbookError as exc:
        print(f"fieldbook: {exc}", file=sys.stderr)
        return exc.exit_code
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            print(f"fieldbook: {exc}", file=sys.stderr)
            return LedgerBusyError(str(exc)).exit_code
        raise
