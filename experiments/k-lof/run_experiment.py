#!/usr/bin/env python3
"""Offline LOF premium-history experiment harness.

The production LOF sidecar remains Rust. This harness makes K-language trials
safe: Python produces the reference output first; an optional K executable can
then be compared against the same input/output contract.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

WINDOWS = (7, 14, 30)


@dataclass(frozen=True)
class PremiumPoint:
    code: str
    date: str
    premium_pct: float


def load_history(path: Path) -> list[PremiumPoint]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    points: list[PremiumPoint] = []
    for code, by_date in raw.items():
        if not isinstance(by_date, dict):
            continue
        for date, value in by_date.items():
            try:
                points.append(PremiumPoint(str(code), str(date), float(value)))
            except (TypeError, ValueError):
                continue
    return sorted(points, key=lambda p: (p.code, p.date))


def write_csv(points: list[PremiumPoint], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["code", "date", "premium_pct"])
        for point in points:
            writer.writerow([point.code, point.date, f"{point.premium_pct:.6f}"])


def window_stats(points: list[PremiumPoint], window: int) -> dict[str, Any]:
    recent = sorted(points, key=lambda p: p.date, reverse=True)[:window]
    values = [p.premium_pct for p in recent]
    if not values:
        return {"n": 0, "latest": None, "avg": None, "min": None, "max": None, "positive_days": 0}
    return {
        "n": len(values),
        "latest": round(values[0], 4),
        "avg": round(sum(values) / len(values), 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "positive_days": sum(1 for value in values if value > 0),
    }


def reference(points: list[PremiumPoint]) -> dict[str, Any]:
    grouped: dict[str, list[PremiumPoint]] = {}
    for point in points:
        grouped.setdefault(point.code, []).append(point)

    items = []
    for code in sorted(grouped):
        rows = grouped[code]
        item: dict[str, Any] = {"code": code, "last_date": max(p.date for p in rows)}
        for window in WINDOWS:
            item[f"w{window}"] = window_stats(rows, window)
        items.append(item)
    return {"generated_by": "python-reference", "windows": list(WINDOWS), "items": items}


def compare(reference_path: Path, candidate_path: Path) -> tuple[bool, str]:
    expected = json.loads(reference_path.read_text(encoding="utf-8"))
    actual = json.loads(candidate_path.read_text(encoding="utf-8"))
    expected["generated_by"] = "normalized"
    actual["generated_by"] = "normalized"
    if expected == actual:
        return True, "K output matches Python reference"
    return False, "K output differs from Python reference"


def run_k(k_bin: str, script: Path, input_csv: Path, output_json: Path) -> tuple[bool, str]:
    resolved = shutil.which(k_bin) or k_bin
    try:
        result = subprocess.run(
            [resolved, str(script), str(input_csv), str(output_json)],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except FileNotFoundError:
        return False, f"K interpreter not found: {k_bin}"
    except subprocess.TimeoutExpired:
        return False, "K run timed out"
    if result.returncode != 0:
        return False, (result.stderr or result.stdout or f"K exited {result.returncode}").strip()
    if not output_json.exists():
        return False, f"K run finished but did not create {output_json}"
    return True, "K run finished"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("/tmp/k-lof"))
    parser.add_argument("--k-bin", default="")
    args = parser.parse_args()

    points = load_history(args.history)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.out_dir / "premium_history.csv"
    ref_path = args.out_dir / "reference.json"
    k_path = args.out_dir / "k-output.json"

    write_csv(points, csv_path)
    ref_path.write_text(json.dumps(reference(points), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"points={len(points)} csv={csv_path} reference={ref_path}")
    if not args.k_bin:
        print("k=skipped reason=no --k-bin provided")
        return 0

    script = Path(__file__).with_name("premium_stats.k")
    ok, msg = run_k(args.k_bin, script, csv_path, k_path)
    print(f"k_run={ok} {msg}")
    if not ok:
        return 2
    ok, msg = compare(ref_path, k_path)
    print(f"compare={ok} {msg}")
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
