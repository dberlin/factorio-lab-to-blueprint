"""Serial, resumable machine-rank gate recipes; run only after the review wave.

An existing chunk is evidence, never an invitation to rerun a failed cell. A
partial/corrupt chunk stops the recipe instead of silently choosing another run.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

URL_IDS = (
    "iron-ingot", "magnetic-coil", "graphene", "electromagnetic-matrix",
    "plastic", "processor", "energy-matrix", "super-magnetic-ring",
    "casimir-crystal", "information-matrix", "quantum-chip", "universe-matrix",
)
POLICIES = ("no-proliferator", "all-products", "output-products")
STRATEGIES = ("freeform", "sequence-pair")
BASE_SHA = "ad8a6f80"
AMM_URL = (
    "https://factoriolab.github.io/dsp/list?z=eJxNjrsKwkAQRf9miql2JCbVNANGTJdGiI1oSJFi"
    "WUnIQ4v9dska5HbnHAbmBrWcjxR0YnHOOWahoLckP.5wtpO9IdsCMgJf8ahFOYNcON.rA2oBvOIga9DK"
    "loJWabYJfjCUGSXd1nz4hzRz4.7ZqdHQrXon7wdtosVTrMm.Ri1pVpEvAnpFKg__&v=11"
)
HERE = Path(__file__).resolve().parent


def read_rows(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def pressure() -> float:
    lines = subprocess.check_output(["vmstat", "1", "6"], text=True).splitlines()
    return sum(float(line.split()[0]) for line in lines[-5:]) / 5


def record_candidate_identity(out: Path, identity: dict[str, str]) -> None:
    """Bind all candidate controls, rounds and reported cells to one checkout."""
    path = out / "candidate-provenance.json"
    if path.exists() and json.loads(path.read_text()) != identity:
        raise RuntimeError(f"refusing to mix candidate provenance in {path}")
    # Also refuse stale evidence made before the shared identity file existed.
    for mode in ("round", "controls", "reported"):
        for arm in ("exact", "up-to"):
            previous = out / f"{mode}-{arm}-provenance.json"
            if previous.exists():
                provenance = json.loads(previous.read_text())
                if any(provenance.get(key) != value for key, value in identity.items()):
                    raise RuntimeError(f"refusing stale candidate provenance in {previous}")
    if not path.exists():
        with path.open("x") as target:
            target.write(json.dumps(identity, indent=2) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("round", "controls", "reported"))
    parser.add_argument("arm", choices=("base", "exact", "up-to"))
    parser.add_argument("checkout", type=Path)
    parser.add_argument("--out", type=Path, default=HERE)
    args = parser.parse_args()
    root = args.checkout.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    for key in ("VIRTUAL_ENV", "FLAB2BP_COATER_NODE", "PYTHONPATH"):
        env.pop(key, None)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if args.arm == "base" and not commit.startswith(BASE_SHA):
        raise RuntimeError(f"baseline must remain {BASE_SHA}; found {commit}")
    imported = subprocess.check_output(
        ["uv", "run", "python", "-c", "import flab2bp; print(flab2bp.__file__)"],
        cwd=root, env=env, text=True,
    ).strip()
    if not Path(imported).resolve().is_relative_to(root):
        raise RuntimeError(f"wrong checkout imported: {imported}")
    if args.arm != "base":
        record_candidate_identity(
            out, {"commit": commit, "checkout": str(root), "imported": imported}
        )
    key = f"{args.mode}-{args.arm}"
    provenance_path = out / f"{key}-provenance.json"
    provenance = {"arm": args.arm, "mode": args.mode, "commit": commit, "checkout": str(root), "imported": imported}
    if provenance_path.exists() and json.loads(provenance_path.read_text()) != provenance:
        raise RuntimeError(f"refusing to mix provenance in {provenance_path}")
    provenance_path.write_text(json.dumps(provenance, indent=2) + "\n")
    chunks = out / key
    chunks.mkdir(exist_ok=True)
    if args.mode == "round":
        cells = [(url_id, "", "") for url_id in URL_IDS]
        aggregate = out / f"{args.arm}.jsonl"
    elif args.mode == "controls":
        cells = [(url_id, "no-proliferator", "freeform") for url_id in URL_IDS]
        aggregate = out / f"controls-{args.arm}.jsonl"
    else:
        if args.arm == "base":
            raise ValueError("reported comparison runs exact and up-to")
        cells = [("reported", policy, strategy) for strategy in STRATEGIES for policy in POLICIES]
        aggregate = out / f"reported-{args.arm}.jsonl"
    all_rows = []
    with (out / f"{key}-load.txt").open("a") as load:
        load.write(f"{datetime.now(UTC).isoformat()} before runnable_mean={pressure()}\n")
        load.flush()
        for url_id, policy, strategy in cells:
            slug = "-".join(value for value in (url_id, policy, strategy) if value)
            chunk = chunks / f"{slug}.jsonl"
            if not chunk.exists():
                log_path = chunks / f"{slug}.log"
                if log_path.exists():
                    raise RuntimeError(f"interrupted prior attempt retained at {log_path}; inspect, do not silently rerun")
                if args.mode == "round":
                    command = [
                        "uv", "run", "python", "scripts/audit.py", "--only", url_id,
                        "--budget", "30", "--jobs", "8", "--strategy", "both",
                        "--max-seconds", "3600", "--json", str(chunk),
                    ]
                else:
                    command = [
                        "uv", "run", "python", str(HERE / "probes/probe_cell.py"), url_id, policy,
                        "--strategy", strategy, "--budget", "30", "--workers",
                        "1" if args.mode == "controls" else "32", "--json", str(chunk),
                        "--bp", str(chunks / f"{slug}.blueprint.txt"),
                    ]
                    if args.mode == "reported":
                        command += ["--url", AMM_URL]
                if args.arm != "base":
                    command += ["--machine-rank", args.arm]
                with log_path.open("x") as log:
                    log.write(json.dumps({"command": command, "provenance": provenance}) + "\n")
                    log.flush()
                    result = subprocess.run(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
                    log.write(f"\nexit_code={result.returncode}\n")
                if result.returncode not in (0, 1) or not chunk.exists():
                    raise RuntimeError(f"incomplete gate chunk; retained log {log_path}")
            rows = read_rows(chunk)
            if args.mode == "round":
                expected = {(strategy, url_id, index) for strategy in STRATEGIES for index in range(3)}
                actual = {(row["strategy"], row["url_id"], row["spec_index"]) for row in rows}
                if actual != expected or len(rows) != 6:
                    raise RuntimeError(f"partial or duplicate chunk: {chunk}")
            elif len(rows) != 1 or (rows[0]["url_id"], rows[0]["policy"], rows[0]["strategy"]) != (url_id, policy, strategy):
                raise RuntimeError(f"invalid probe chunk: {chunk}")
            if any(row.get("commit") != commit for row in rows):
                raise RuntimeError(f"mixed commit provenance in {chunk}")
            if any(row.get("machine_rank", "base") != args.arm for row in rows):
                raise RuntimeError(f"mixed machine-rank arm in {chunk}")
            all_rows.extend(rows)
            pending = aggregate.with_suffix(".pending")
            pending.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in all_rows))
            pending.replace(aggregate)
            print(f"{key}: retained {len(all_rows)} cells", flush=True)
        load.write(f"{datetime.now(UTC).isoformat()} after runnable_mean={pressure()}\n")
    print(aggregate)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
