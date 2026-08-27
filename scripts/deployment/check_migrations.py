"""Reject Alembic upgrades that violate RecoveryOS expand/contract deployment safety."""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

DESTRUCTIVE_OPERATIONS = {
    "drop_column",
    "drop_constraint",
    "drop_index",
    "drop_table",
    "rename_table",
}
DESTRUCTIVE_SQL = re.compile(
    r"\b(?:DROP|TRUNCATE)\b|\bALTER\s+TABLE\b.*\b(?:DROP|RENAME|TYPE)\b",
    re.IGNORECASE | re.DOTALL,
)


def _upgrade_function(module: ast.Module) -> ast.FunctionDef | None:
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == "upgrade":
            return node
    return None


def _operation_name(call: ast.Call) -> str | None:
    function = call.func
    if (
        isinstance(function, ast.Attribute)
        and isinstance(function.value, ast.Name)
        and function.value.id == "op"
    ):
        return function.attr
    return None


def inspect_upgrade(path: Path) -> list[str]:
    try:
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        return [f"cannot parse migration: {exc}"]

    upgrade = _upgrade_function(module)
    if upgrade is None:
        return ["missing upgrade() function"]

    findings: list[str] = []
    for node in ast.walk(upgrade):
        if not isinstance(node, ast.Call):
            continue
        operation = _operation_name(node)
        if operation in DESTRUCTIVE_OPERATIONS:
            findings.append(f"line {node.lineno}: op.{operation} is not expand-compatible")
        elif operation == "alter_column":
            unsafe_keywords = {
                item.arg
                for item in node.keywords
                if item.arg in {"new_column_name", "nullable", "type_"}
                and not (
                    item.arg == "nullable"
                    and isinstance(item.value, ast.Constant)
                    and item.value.value is True
                )
            }
            if unsafe_keywords:
                names = ", ".join(sorted(unsafe_keywords))
                findings.append(
                    f"line {node.lineno}: op.alter_column changes {names}; "
                    "split into expand/contract releases"
                )
        elif operation == "execute":
            sql_node: ast.AST | None = node.args[0] if node.args else None
            if (
                isinstance(sql_node, ast.Call)
                and isinstance(sql_node.func, ast.Attribute)
                and sql_node.func.attr == "text"
                and sql_node.args
            ):
                sql_node = sql_node.args[0]
            if not isinstance(sql_node, ast.Constant):
                findings.append(
                    f"line {node.lineno}: dynamic op.execute cannot be safety-inspected"
                )
            else:
                sql = sql_node.value
                if isinstance(sql, str) and DESTRUCTIVE_SQL.search(sql):
                    findings.append(f"line {node.lineno}: op.execute contains destructive DDL")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "migration_dir",
        nargs="?",
        type=Path,
        default=Path("services/api/alembic/versions"),
    )
    arguments = parser.parse_args()
    migration_dir = arguments.migration_dir.resolve()
    if not migration_dir.is_dir():
        parser.error(f"migration directory does not exist: {migration_dir}")

    failures: list[str] = []
    migrations = sorted(migration_dir.glob("*.py"))
    if not migrations:
        failures.append("no migration files found")
    for migration in migrations:
        for finding in inspect_upgrade(migration):
            failures.append(f"{migration.name}: {finding}")

    if failures:
        print("Migration safety gate failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(f"Migration safety gate passed for {len(migrations)} migration(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
