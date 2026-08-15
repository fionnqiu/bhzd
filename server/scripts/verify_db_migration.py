"""Verify the post-scenario-removal SQLite schema without changing the database.

The application owns migration execution; this script is intentionally read-only
so an operator can inspect a copied or stopped runtime database after migration.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE = REPO_ROOT / "var" / "bhzd.sqlite"

REMOVED_COLUMNS = {
    "conversations": "scenario_id",
    "agent_runs": "scenario_id",
    "learning_tasks": "scenario_id",
    "diagnostic_summaries": "scenario_id",
    "rag_documents": "scenario_ids_json",
    "mastery_events": "scenario_id",
}
MASTERY_COLUMNS = ["user_id", "cap_id", "score", "source", "updated_at"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the scenario-removal SQLite schema")
    parser.add_argument(
        "--database",
        default=os.environ.get("BHZD_DATABASE_PATH", str(DEFAULT_DATABASE)),
        help="SQLite path to inspect (default: BHZD_DATABASE_PATH or var/bhzd.sqlite)",
    )
    parser.add_argument(
        "--baseline",
        help=(
            "Optional pre-migration SQLite backup. Existing foreign-key errors "
            "present in both databases are reported as warnings, while new errors fail."
        ),
    )
    return parser.parse_args()


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _foreign_key_errors(database: str) -> set[tuple[str, int, str, int]]:
    """Read foreign-key violations without changing the inspected database."""
    conn = sqlite3.connect(database)
    try:
        return {tuple(row) for row in conn.execute("PRAGMA foreign_key_check")}
    finally:
        conn.close()


def verify(
    database: str, *, baseline: str | None = None
) -> tuple[list[str], list[str]]:
    path = Path(database)
    if not path.exists():
        return [f"database does not exist: {path}"], []

    errors: list[str] = []
    warnings: list[str] = []
    conn = sqlite3.connect(path)
    try:
        migration_names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
            )
        }
        if not migration_names:
            errors.append("schema_migrations table is missing")
        else:
            applied = {
                row[0]
                for row in conn.execute("SELECT name FROM schema_migrations")
            }
            if "016_remove_scenarios.sql" not in applied:
                errors.append("016_remove_scenarios.sql is not recorded as applied")

        for table, column in REMOVED_COLUMNS.items():
            columns = table_columns(conn, table)
            if column in columns:
                errors.append(f"{table}.{column} still exists")

        mastery_columns = table_columns(conn, "mastery")
        if mastery_columns != MASTERY_COLUMNS:
            errors.append(f"mastery columns differ: {mastery_columns!r}")

        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            errors.append(f"integrity_check returned {integrity!r}")
        foreign_key_errors = {tuple(row) for row in conn.execute("PRAGMA foreign_key_check")}
        if foreign_key_errors:
            if baseline:
                baseline_path = Path(baseline)
                if not baseline_path.exists():
                    errors.append(f"baseline database does not exist: {baseline_path}")
                else:
                    baseline_errors = _foreign_key_errors(str(baseline_path))
                    new_errors = foreign_key_errors - baseline_errors
                    unchanged_errors = foreign_key_errors & baseline_errors
                    if new_errors:
                        errors.append(
                            f"foreign_key_check found {len(new_errors)} new row(s): "
                            f"{sorted(new_errors)!r}"
                        )
                    if unchanged_errors:
                        warnings.append(
                            "foreign_key_check retained "
                            f"{len(unchanged_errors)} pre-existing row(s): "
                            f"{sorted(unchanged_errors)!r}"
                        )
            else:
                errors.append(f"foreign_key_check returned {len(foreign_key_errors)} row(s)")
    finally:
        conn.close()
    return errors, warnings


def main() -> int:
    args = parse_args()
    errors, warnings = verify(args.database, baseline=args.baseline)
    if errors:
        print("Scenario-removal migration verification failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    for warning in warnings:
        print(f"WARNING: {warning}")
    print(f"Scenario-removal migration verification passed: {args.database}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
