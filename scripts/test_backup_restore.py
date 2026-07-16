"""Temporary-container backup/restore drill. Does not touch project volumes."""

from __future__ import annotations

import gzip
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path


def run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=True, text=True, capture_output=True, **kwargs)  # type: ignore[arg-type]


def main() -> int:
    if shutil.which("docker") is None:
        print("BACKUP_RESTORE_SMOKE_SKIPPED: docker not available")
        return 0

    image = "pgvector/pgvector:pg16"
    name = f"tg-order-radar-backup-drill-{uuid.uuid4().hex[:8]}"
    db_name = "drill_db"
    db_user = "drill"
    db_password = "drill-pass-not-for-prod"
    workdir = Path(tempfile.mkdtemp(prefix="tg-backup-drill-"))
    dump_path = workdir / "drill.sql.gz"

    try:
        run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "-e",
                f"POSTGRES_DB={db_name}",
                "-e",
                f"POSTGRES_USER={db_user}",
                "-e",
                f"POSTGRES_PASSWORD={db_password}",
                image,
            ]
        )
        for _ in range(40):
            probe = subprocess.run(
                ["docker", "exec", name, "pg_isready", "-U", db_user, "-d", db_name],
                check=False,
                capture_output=True,
                text=True,
            )
            if probe.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("temporary postgres did not become ready")

        run(
            [
                "docker",
                "exec",
                "-i",
                name,
                "psql",
                "-U",
                db_user,
                "-d",
                db_name,
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                "create table drill_orders(id serial primary key, title text);"
                " insert into drill_orders(title) values ('backup-restore-smoke');",
            ]
        )

        dump = run(
            [
                "docker",
                "exec",
                "-e",
                f"PGPASSWORD={db_password}",
                name,
                "pg_dump",
                "-U",
                db_user,
                "-d",
                db_name,
                "--format=plain",
                "--no-owner",
            ]
        )
        dump_path.write_bytes(gzip.compress(dump.stdout.encode("utf-8")))

        # DROP DATABASE cannot run inside a multi-statement transaction (-c batch).
        for sql in (
            (
                f"select pg_terminate_backend(pid) from pg_stat_activity "
                f"where datname='{db_name}' and pid <> pg_backend_pid();"
            ),
            f"drop database {db_name};",
            f"create database {db_name} owner {db_user};",
        ):
            run(
                [
                    "docker",
                    "exec",
                    "-e",
                    f"PGPASSWORD={db_password}",
                    name,
                    "psql",
                    "-U",
                    db_user,
                    "-d",
                    "postgres",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-c",
                    sql,
                ]
            )

        restore = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                "-e",
                f"PGPASSWORD={db_password}",
                name,
                "psql",
                "-U",
                db_user,
                "-d",
                db_name,
                "-v",
                "ON_ERROR_STOP=1",
            ],
            input=gzip.decompress(dump_path.read_bytes()).decode("utf-8"),
            check=True,
            text=True,
            capture_output=True,
        )
        del restore

        count = run(
            [
                "docker",
                "exec",
                "-e",
                f"PGPASSWORD={db_password}",
                name,
                "psql",
                "-U",
                db_user,
                "-d",
                db_name,
                "-Atc",
                "select count(*) from drill_orders where title='backup-restore-smoke';",
            ]
        ).stdout.strip()
        if count != "1":
            print(f"BACKUP_RESTORE_SMOKE_FAILED count={count}", file=sys.stderr)
            return 1
        print("BACKUP_RESTORE_SMOKE_OK")
        return 0
    finally:
        subprocess.run(["docker", "rm", "-f", name], check=False, capture_output=True)
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
