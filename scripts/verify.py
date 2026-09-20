"""Fail-closed release gate. --local omits infrastructure checks, never releases."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"


def run(args, cwd=ROOT, env=None):
    print("CHECK:", " ".join(map(str, args)), flush=True)
    subprocess.run(args, cwd=cwd, check=True, env=env)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", action="store_true")
    args = parser.parse_args()
    if not args.local and not os.getenv("TEST_DATABASE_URL", "").startswith("postgresql+"):
        raise SystemExit(
            "RELEASE BLOCKED: set TEST_DATABASE_URL to an isolated PostgreSQL meraipo_test database. Use --local for a non-release developer check."
        )
    run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "apps/api",
            "apps/worker",
            "packages",
            "tests",
            "scripts/verify.py",
        ]
    )
    run(
        [
            sys.executable,
            "-m",
            "black",
            "--check",
            "--target-version",
            "py312",
            "apps/api",
            "apps/worker",
            "packages",
            "tests",
            "scripts/verify.py",
        ]
    )
    run([sys.executable, "-m", "mypy", "packages/shared"])
    if not args.local:
        run([sys.executable, "tests/infrastructure_check.py"])
        migration_env = {
            **os.environ,
            "DATABASE_URL": os.environ["TEST_DATABASE_URL"],
            "ENVIRONMENT": "test",
        }
        run([sys.executable, "-m", "alembic", "upgrade", "head"], env=migration_env)
        run([sys.executable, "-m", "alembic", "check"], env=migration_env)
    run([sys.executable, "-m", "pytest", "-q"])
    for command in [
        ["node", "node_modules/typescript/bin/tsc", "--noEmit"],
        ["node", "node_modules/eslint/bin/eslint.js", ".", "--max-warnings", "0"],
        ["node", "node_modules/prettier/bin/prettier.cjs", "--check", "."],
        ["node", "node_modules/vitest/vitest.mjs", "run"],
    ]:
        run(command, WEB)
    if not args.local:
        run(["docker", "compose", "config", "--quiet"])
    run(["node", "node_modules/@playwright/test/cli.js", "test"], WEB)
    run(["node", "node_modules/next/dist/bin/next", "build"], WEB)
    print(
        "LOCAL CHECKS PASSED; production infrastructure remains a separate release gate."
        if args.local
        else "RELEASE CHECKS PASSED. Promote only these source and image revisions after staging smoke tests."
    )
