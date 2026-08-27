"""Minimal dotenv reader used by deployment scripts without executing shell input."""

from __future__ import annotations

import argparse
from pathlib import Path


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ValueError(f"{path}:{line_number}: expected KEY=VALUE")
        key, raw_value = line.split("=", 1)
        key = key.strip()
        value = raw_value.strip()
        if not key.replace("_", "a").isalnum() or not key[0].isalpha():
            raise ValueError(f"{path}:{line_number}: invalid environment key")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key in values:
            raise ValueError(f"{path}:{line_number}: duplicate key {key}")
        values[key] = value
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("key")
    arguments = parser.parse_args()
    values = read_env_file(arguments.path)
    if arguments.key not in values:
        parser.error(f"missing key {arguments.key} in {arguments.path}")
    print(values[arguments.key])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
