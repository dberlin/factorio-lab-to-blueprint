"""Turn ``results-*.jsonl`` into the README's tables.

Two replicates per (cell, arm): the MEDIAN of two is the mean, so both values
are printed rather than a summary that hides a flake.  Every table is written
to ``analysis.txt``, which is authoritative; the README quotes it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ARMS = ("off", "A", "B", "AB")


def load(path: Path) -> dict[tuple[str, str], list[dict[str, Any]]]:
    out: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        out.setdefault((row["label"], row["arm"]), []).append(row)
    return out


def verdict(run: dict[str, Any]) -> str:
    text = run.get("verdict", "?")
    if text == "OK":
        return "OK"
    return text.replace("REFUSED: ", "")


def phase(run: dict[str, Any], name: str) -> float:
    return float(run.get("phases", {}).get(name, {}).get("s", 0.0))


def fmt(value: Any, width: int = 8) -> str:
    if value is None:
        return "-".rjust(width)
    if isinstance(value, float):
        return f"{value:{width}.2f}"
    return str(value).rjust(width)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kinds", default="large,corpus")
    ap.add_argument("--out", default=str(HERE / "analysis.txt"))
    args = ap.parse_args()

    lines: list[str] = []

    def emit(text: str = "") -> None:
        lines.append(text)
        print(text)

    for kind in args.kinds.split(","):
        path = HERE / f"results-{kind}.jsonl"
        if not path.exists():
            continue
        data = load(path)
        labels = sorted({label for label, _arm in data}, key=lambda s: (len(s), s))
        emit(f"===== {kind} =====")
        emit()
        emit(
            f'{"cell":34s} {"arm":4s} {"rep":3s} {"verdict":44s} '
            f'{"wall":>7s} {"area":>8s} {"belt":>7s} {"routeS":>7s} {"expans":>10s} '
            f'{"rounds":>6s} {"prepS":>7s} {"validS":>7s} {"finalS":>7s} {"load":>6s}'
        )
        for label in labels:
            for arm in ARMS:
                for row in sorted(data.get((label, arm), []), key=lambda r: r["rep"]):
                    run = row.get("run")
                    if run is None:
                        emit(f'{label:34s} {arm:4s} {row["rep"]:3d} CRASH rc={row["returncode"]}')
                        continue
                    stats = run.get("stats", {})
                    emit(
                        f'{label:34s} {arm:4s} {row["rep"]:3d} {verdict(run)[:44]:44s} '
                        f'{run["wall_s"]:7.2f} '
                        f'{fmt(None if run["area"] is None else int(run["area"]))} '
                        f'{fmt(None if "belt_tiles" not in stats else int(float(stats["belt_tiles"])), 7)} '  # noqa: E501
                        f'{run["route_all_s"]:7.2f} {run["expansions"]:10d} {run["rounds"]:6d} '
                        f"{phase(run, 'prepare'):7.2f} {phase(run, 'validate'):7.2f} "
                        f"{phase(run, 'finalize'):7.2f} "
                        f'{row["load_before"][0]:>6s}'
                    )
            emit()

        emit(f"----- {kind}: arm vs off (median of two reps) -----")
        emit(
            f'{"cell":34s} {"arm":4s} {"verdict":30s} {"wall":>7s} {"d wall%":>8s} '
            f'{"area":>8s} {"d area%":>8s} {"belt":>7s} {"d belt%":>8s} '
            f'{"routeS":>7s} {"d rt%":>8s} {"rounds":>6s} {"expans":>10s}'
        )

        def median(values: list[float]) -> float:
            values = sorted(values)
            n = len(values)
            return values[n // 2] if n % 2 else (values[n // 2 - 1] + values[n // 2]) / 2

        def pick(label: str, arm: str, key: str) -> float | None:
            runs = [r["run"] for r in data.get((label, arm), []) if r.get("run")]
            vals = [r[key] for r in runs if r.get(key) is not None]
            return median([float(v) for v in vals]) if vals else None

        def pick_stat(label: str, arm: str, key: str) -> float | None:
            runs = [r["run"] for r in data.get((label, arm), []) if r.get("run")]
            vals = [float(r["stats"][key]) for r in runs if key in r.get("stats", {})]
            return median(vals) if vals else None

        def delta(new: float | None, base: float | None) -> str:
            if new is None or base is None or base == 0:
                return "-".rjust(8)
            return f"{100.0 * (new - base) / base:+8.2f}"

        for label in labels:
            for arm in ARMS:
                runs = [r["run"] for r in data.get((label, arm), []) if r.get("run")]
                if not runs:
                    continue
                emit(
                    f"{label:34s} {arm:4s} {verdict(runs[0])[:30]:30s} "
                    f'{fmt(pick(label, arm, "wall_s"), 7)} '
                    f'{delta(pick(label, arm, "wall_s"), pick(label, "off", "wall_s"))} '
                    f'{fmt(pick(label, arm, "area"))} '
                    f'{delta(pick(label, arm, "area"), pick(label, "off", "area"))} '
                    f'{fmt(pick_stat(label, arm, "belt_tiles"), 7)} '
                    f'{delta(pick_stat(label, arm, "belt_tiles"), pick_stat(label, "off", "belt_tiles"))} '  # noqa: E501
                    f'{fmt(pick(label, arm, "route_all_s"), 7)} '
                    f'{delta(pick(label, arm, "route_all_s"), pick(label, "off", "route_all_s"))} '
                    f'{fmt(pick(label, arm, "rounds"), 6)} '
                    f'{fmt(pick(label, arm, "expansions"), 10)}'
                )
            emit()

    Path(args.out).write_text("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
