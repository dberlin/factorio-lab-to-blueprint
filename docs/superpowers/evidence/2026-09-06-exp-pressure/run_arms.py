"""Drive ``prof_harness.py`` over the four pressure arms.

One subprocess per (cell, arm, replicate), at most two at a time because
another experiment shares this box.  ``uptime`` is sampled beside every run and
kept in the row, so a slow wall can be read against the load that produced it
rather than assumed to be the arm.

Arms: ``off`` (neither switch), ``A`` (``FLAB2BP_PRESSURE_CORRIDORS``), ``B``
(``FLAB2BP_PRESSURE_ORDER``), ``AB`` (both).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
HARNESS = ROOT / "docs/superpowers/evidence/2026-09-05-scale-profile/prof_harness.py"
LARGE_URLS = ROOT / "docs/superpowers/evidence/2026-09-05-speedups-2/large-urls/urls.txt"

ARMS: dict[str, dict[str, str]] = {
    "off": {},
    "A": {"FLAB2BP_PRESSURE_CORRIDORS": "1"},
    "B": {"FLAB2BP_PRESSURE_ORDER": "1"},
    "AB": {"FLAB2BP_PRESSURE_CORRIDORS": "1", "FLAB2BP_PRESSURE_ORDER": "1"},
}


def large_urls() -> dict[str, str]:
    out = {}
    for line in LARGE_URLS.read_text().splitlines():
        if line.strip():
            label, url = line.split("\t", 1)
            out[label.strip()] = url.strip()
    return out


def corpus_urls() -> dict[str, str]:
    sys.path.insert(0, str(ROOT / "src"))
    from flab2bp.bench.corpus import URL_CORPUS

    return {entry.url_id: entry.url for entry in URL_CORPUS}


def cells(kind: str) -> list[dict[str, object]]:
    """The measurement grid.  ``kind`` picks the large set or the corpus set."""
    urls = large_urls()
    corpus = corpus_urls()
    if kind == "large":
        return [
            {"label": "um60", "target": "universe-matrix", "rate": 60, "policy": "no-proliferator", "budget": 30},  # noqa: E501
            {"label": "um120", "target": "universe-matrix", "rate": 120, "policy": "no-proliferator", "budget": 30},  # noqa: E501
            {"label": "gm200", "target": "gravity-matrix", "rate": 200, "policy": "no-proliferator", "budget": 30},  # noqa: E501
            {"label": "qc180", "target": "quantum-chip", "rate": 180, "policy": "no-proliferator", "budget": 30},  # noqa: E501
            {"label": "belt3-all", "target": "belt3", "url": urls["belt3"], "policy": "all-products", "budget": 60},  # noqa: E501
            {"label": "belt3-nopro", "target": "belt3", "url": urls["belt3"], "policy": "no-proliferator", "budget": 60},  # noqa: E501
            {"label": "mall", "target": "mall", "url": urls["mall"], "policy": "all-products", "budget": 60},  # noqa: E501
            {"label": "zurl2", "target": "zurl2", "url": urls["zurl2"], "policy": "all-products", "budget": 60},  # noqa: E501
        ]
    #: The eight corpus cells with the highest ``max_lane_pressure`` in
    #: ``2026-09-06-exp-features/features.jsonl``: universe-matrix and
    #: quantum-chip at all three policies, information-matrix at the two that
    #: tie at 8.
    grid = [
        ("universe-matrix", "all-products"),
        ("universe-matrix", "output-products"),
        ("universe-matrix", "no-proliferator"),
        ("quantum-chip", "all-products"),
        ("quantum-chip", "output-products"),
        ("quantum-chip", "no-proliferator"),
        ("information-matrix", "all-products"),
        ("information-matrix", "output-products"),
    ]
    return [
        {
            "label": f"{url_id}/{policy}",
            "target": url_id,
            "url": corpus[url_id],
            "policy": policy,
            "budget": 30,
        }
        for url_id, policy in grid
    ]


def run(cell: dict[str, object], arm: str, rep: int, outdir: Path) -> dict[str, object]:
    slug = str(cell["label"]).replace("/", "_")
    out = outdir / f"{slug}-{arm}-r{rep}"
    cmd = [
        "uv",
        "run",
        "python",
        str(HARNESS),
        str(cell["target"]),
        "--strategy",
        "freeform",
        "--policy",
        str(cell["policy"]),
        "--budget",
        str(cell["budget"]),
        "--out",
        str(out),
    ]
    if "url" in cell:
        cmd += ["--url", str(cell["url"])]
    if "rate" in cell:
        cmd += ["--rate", str(cell["rate"])]
    #: Cleared first, then set: an arm is defined by what it turns ON, and an
    #: inherited switch would make "off" quietly mean something else.
    env = {k: v for k, v in os.environ.items() if not k.startswith("FLAB2BP_PRESSURE_")}
    env |= ARMS[arm]
    load_before = Path("/proc/loadavg").read_text().split()[:3]
    proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    load_after = Path("/proc/loadavg").read_text().split()[:3]
    row: dict[str, object] = {
        "label": cell["label"],
        "arm": arm,
        "rep": rep,
        "returncode": proc.returncode,
        "load_before": load_before,
        "load_after": load_after,
    }
    payload = out.with_suffix(".json")
    if payload.exists():
        row["run"] = json.loads(payload.read_text())
    else:
        row["stderr_tail"] = proc.stderr[-2000:]
    (out.with_suffix(".log")).write_text(proc.stdout + "\n--- stderr ---\n" + proc.stderr)
    print(
        f'{cell["label"]:34s} {arm:3s} r{rep} rc={proc.returncode} '
        f'{"" if "run" not in row else row["run"]["verdict"][:44]}',
        flush=True,
    )
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=("large", "corpus"), default="large")
    ap.add_argument("--arms", default="off,A,B,AB")
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--jobs", type=int, default=2)
    args = ap.parse_args()

    outdir = Path(args.outdir or (HERE / f"runs-{args.kind}"))
    outdir.mkdir(parents=True, exist_ok=True)
    arms = args.arms.split(",")
    jobs = [
        (cell, arm, rep)
        for cell in cells(args.kind)
        for arm in arms
        for rep in range(1, args.reps + 1)
    ]
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        rows = list(pool.map(lambda job: run(job[0], job[1], job[2], outdir), jobs))
    (HERE / f"results-{args.kind}.jsonl").write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
