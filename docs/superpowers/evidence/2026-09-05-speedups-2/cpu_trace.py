"""How many cores does ONE build actually use over its budget?

Runs the profiling harness as a child and samples the child's /proc entry once
a second: thread count (nlwp) and the CPU-seconds it burned in that second
(utime+stime deltas over the whole process tree, so a CP-SAT worker thread and
a spawned island both count).  A mean near 1.0 means the build is serial on a
128-core box.

    uv run python cpu_trace.py universe-matrix --rate 60 --strategy freeform --out t.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
HARNESS = ROOT / "docs/superpowers/evidence/2026-09-05-scale-profile/prof_harness.py"
CLK = 100.0  # os.sysconf("SC_CLK_TCK") on Linux


def _tree(pid: int) -> list[int]:
    """PID and every descendant, via /proc/<pid>/task/*/children."""
    out, stack = [], [pid]
    while stack:
        cur = stack.pop()
        out.append(cur)
        try:
            for task in Path(f"/proc/{cur}/task").iterdir():
                kids = (task / "children").read_text().split()
                stack.extend(int(k) for k in kids)
        except (OSError, ValueError):
            continue
    return out


def _sample(pid: int) -> tuple[float, int, int]:
    """(cpu ticks, threads, live processes) over the process tree."""
    ticks, threads, live = 0.0, 0, 0
    for p in _tree(pid):
        try:
            fields = Path(f"/proc/{p}/stat").read_text().rsplit(") ", 1)[1].split()
        except (OSError, IndexError):
            continue
        # after the ") " split, index 0 is `state`, so utime is field 13-2=11.
        ticks += float(fields[11]) + float(fields[12])
        threads += int(fields[17])
        live += 1
    return ticks, threads, live


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--rate", default="60")
    ap.add_argument("--strategy", default="freeform")
    ap.add_argument("--budget", default="30")
    ap.add_argument("--policy", default=None)
    ap.add_argument("--url", default=None)
    ap.add_argument("--islands", default=None, help="passed through to the harness")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    cmd = ["uv", "run", "python", str(HARNESS), args.target, "--rate", args.rate,
           "--strategy", args.strategy, "--budget", args.budget,
           "--out", str(Path(args.out).with_suffix(".run"))]
    if args.policy:
        cmd += ["--policy", args.policy]
    if args.url:
        cmd += ["--url", args.url]
    if args.islands:
        cmd += ["--islands", args.islands]

    t0 = time.perf_counter()
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True)
    samples: list[dict[str, float]] = []
    # A process that exits takes its cumulative ticks out of the tree total, so
    # the LAST sample is not the run's CPU time.  Sum the per-second deltas and
    # floor each at zero instead; that is what the samples actually measured.
    prev_ticks, prev_t, cpu_s = 0.0, t0, 0.0
    while proc.poll() is None:
        time.sleep(1.0)
        now = time.perf_counter()
        ticks, threads, live = _sample(proc.pid)
        dt = now - prev_t
        step = max(0.0, ticks - prev_ticks) / CLK
        cpu_s += step
        samples.append({"t": round(now - t0, 2), "cores": round(step / dt, 2),
                        "threads": threads, "procs": live})
        prev_ticks, prev_t = ticks, now
    proc.wait()
    wall = time.perf_counter() - t0
    busy = [s["cores"] for s in samples if s["cores"] > 0.05]
    row = {
        "cmd": cmd[3:],
        "wall_s": round(wall, 2),
        "cpu_s": round(cpu_s, 2),
        "mean_cores_over_wall": round(cpu_s / wall, 2),
        "mean_cores_when_busy": round(sum(busy) / max(1, len(busy)), 2),
        "peak_cores": max((s["cores"] for s in samples), default=0.0),
        "peak_threads": max((s["threads"] for s in samples), default=0),
        "peak_procs": max((s["procs"] for s in samples), default=0),
        "samples": samples,
        "stdout": proc.stdout.read()[-400:] if proc.stdout else "",
    }
    Path(args.out).write_text(json.dumps(row, indent=1, sort_keys=True))
    print(json.dumps({k: row[k] for k in ("wall_s", "cpu_s", "mean_cores_over_wall",
                                          "mean_cores_when_busy", "peak_cores",
                                          "peak_threads", "peak_procs")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
