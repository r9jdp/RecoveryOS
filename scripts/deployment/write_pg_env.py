"""Write libpq variables from protected DATABASE_URL without exposing it in process arguments."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from env_file import read_env_file


def libpq_values(database_url: str) -> dict[str, str]:
    normalized = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError("DATABASE_URL must use PostgreSQL")
    if not parsed.hostname or not parsed.username or parsed.password is None:
        raise ValueError("DATABASE_URL must include host, user, and password")
    database = unquote(parsed.path.lstrip("/"))
    if not database:
        raise ValueError("DATABASE_URL must include a database name")
    query = parse_qs(parsed.query)
    values = {
        "PGHOST": parsed.hostname,
        "PGPORT": str(parsed.port or 5432),
        "PGUSER": unquote(parsed.username),
        "PGPASSWORD": unquote(parsed.password),
        "PGDATABASE": database,
        "PGCONNECT_TIMEOUT": "10",
    }
    sslmode = query.get("sslmode", [""])[0]
    if sslmode:
        values["PGSSLMODE"] = sslmode
    return values


def write_env(path: Path, values: dict[str, str]) -> None:
    for key, value in values.items():
        if any(character in value for character in "\r\n\0"):
            raise ValueError(f"{key} contains an unsupported control character")
    path.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
    os.chmod(path, 0o600)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_env", type=Path)
    parser.add_argument("output_env", type=Path)
    arguments = parser.parse_args()
    database_url = read_env_file(arguments.source_env)["DATABASE_URL"]
    write_env(arguments.output_env, libpq_values(database_url))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
