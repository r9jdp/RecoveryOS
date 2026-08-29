"""Fail-safe Supabase/PostgreSQL connectivity check with sanitized output."""

from __future__ import annotations

import os

import psycopg


def main() -> None:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL is empty. Fill the Supabase section in .env first.")
    if "CHANGE_ME" in database_url or "PROJECT_REF" in database_url:
        raise SystemExit("DATABASE_URL still contains a placeholder value.")

    dsn = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(dsn, connect_timeout=10) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), current_user, current_setting('server_version')")
        database, user, version = cursor.fetchone()

    print("Supabase PostgreSQL connection successful.")
    print(f"Database: {database}")
    print(f"Role: {user}")
    print(f"PostgreSQL: {version}")


if __name__ == "__main__":
    main()
