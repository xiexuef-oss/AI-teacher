"""Run the repository's non-mutating merge gates without uploading their output."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Gate:
    name: str
    command: tuple[str, ...]
    directory: str


def plan(uv: str, npm: str, flutter: str, dart: str) -> list[Gate]:
    return [
        Gate("pytest", (uv, "run", "--locked", "pytest", "-q"), "."),
        Gate("ruff", (uv, "run", "--locked", "ruff", "check", "."), "."),
        Gate(
            "dart-generated",
            (uv, "run", "--locked", "python", "tools/gen_dart_contracts.py", "--check"),
            ".",
        ),
        Gate("flutter-test", (flutter, "test", "--no-pub"), "apps/flutter_student"),
        Gate("dart-analyze", (dart, "analyze"), "apps/flutter_student"),
        Gate("dart-test", (dart, "test"), "packages/contracts/dart"),
        Gate("admin-test", (npm, "test"), "apps/admin_web"),
        Gate("admin-typecheck", (npm, "run", "typecheck"), "apps/admin_web"),
        Gate("admin-api", (npm, "run", "check:api"), "apps/admin_web"),
    ]


def _stop(process: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait()


def run(gates: list[Gate], root: Path, output: Path, timeout: float) -> int:
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "running", "started_at": datetime.now(UTC).isoformat(), "gates": []}

    def save() -> None:
        temporary = output / "status.json.tmp"
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(output / "status.json")

    save()
    try:
        for gate in gates:
            started = time.monotonic()
            log_path = output / f"{gate.name}.log"
            item = {
                "name": gate.name,
                "command": list(gate.command),
                "directory": gate.directory,
                "log": log_path.name,
                "status": "running",
                "returncode": None,
            }
            report["gates"].append(item)
            save()
            with log_path.open("w", encoding="utf-8") as log:
                try:
                    # Resolve npm.cmd on Windows as well as ordinary PATH binaries.
                    executable = shutil.which(gate.command[0]) or gate.command[0]
                    process = subprocess.Popen(
                        [executable, *gate.command[1:]],
                        cwd=root / gate.directory,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        start_new_session=os.name != "nt",
                    )
                    try:
                        item["returncode"] = process.wait(timeout=timeout)
                        item["status"] = "passed" if process.returncode == 0 else "failed"
                    except subprocess.TimeoutExpired:
                        _stop(process)
                        item["status"] = "timeout"
                        log.write(f"\nGate exceeded {timeout} seconds.\n")
                    except KeyboardInterrupt:
                        _stop(process)
                        item["status"] = "interrupted"
                        raise
                except OSError as error:
                    item["status"] = "error"
                    log.write(f"Cannot execute gate: {error}\n")
                finally:
                    item["seconds"] = round(time.monotonic() - started, 3)
                    save()
            print(f"{gate.name}: {item['status']} (log: {log_path})", flush=True)
    except KeyboardInterrupt:
        report["status"] = "interrupted"
        save()
        return 130
    report["status"] = (
        "passed"
        if gates and all(item["status"] == "passed" for item in report["gates"])
        else "failed"
    )
    report["finished_at"] = datetime.now(UTC).isoformat()
    save()
    print(f"Report: {output / 'status.json'}", flush=True)
    return 0 if report["status"] == "passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="List gates without running them")
    parser.add_argument("--uv", default="uv")
    parser.add_argument("--npm", default="npm")
    parser.add_argument(
        "--flutter", default="C:/src/flutter/bin/flutter.bat" if os.name == "nt" else "flutter"
    )
    parser.add_argument(
        "--dart", default="C:/src/flutter/bin/dart.bat" if os.name == "nt" else "dart"
    )
    parser.add_argument("--timeout", type=float, default=1200, help="Seconds per gate")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    gates = plan(args.uv, args.npm, args.flutter, args.dart)
    if args.list:
        for gate in gates:
            print(f"{gate.name}: {gate.directory}: {list(gate.command)}")
        return 0
    output = args.output or ROOT / "var/quality-gates" / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    )
    try:
        return run(gates, ROOT, output.resolve(), args.timeout)
    except (OSError, ValueError) as error:
        parser.exit(2, f"Cannot prepare quality report: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
