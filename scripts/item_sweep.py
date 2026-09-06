"""One blueprint per item: sweep every craftable thing in the game.

    uv run python scripts/item_sweep.py --list            # classification only
    uv run python scripts/item_sweep.py --round 1         # the full sweep
    uv run python scripts/item_sweep.py --round 2 --items gear,plane-filter

The question this answers is the blunt one: *can we build at least one of every
item?*  It walks the vendored FactorioLab DSP dataset, decides for each item
whether it is buildable at all, and for the buildable ones drives the real CLI
-- the same argv a user types -- and records what came back.

CLASSIFICATION
--------------
Only three item categories are things a factory makes: ``components``,
``buildings`` and ``buildings-alt``.  ``technologies`` and ``upgrades`` are
research rows whose "output" is a technology token that never rides a belt
(``build_corpus.py`` excludes them for the same reason), and ``effects`` are the
proliferator module entries, not items.  Those are OTHER, out of scope, and
named rather than silently dropped.

Inside the scope each item is:

* **BUILD** -- at least one craftable, non-mining recipe with a producer
  machine.  ``Dataset.craftable_recipes_producing`` already drops the dataset's
  default exclusions and the technology recipes, so this is exactly the set a
  solver may choose from.
* **RAW** -- produced only by a mining/pumping/collecting recipe (``iron-vein``,
  ``ocean``, ``crude-oil-seep``, ``ice-giant-gas-hydrate``...).  A miner is
  placed on a vein, not on a blueprint tile, so there is no factory block to
  emit.  Out of scope, with the recipe named.
* **OTHER** -- in scope by category but produced by nothing at all: the Dark Fog
  drops, ``log`` and ``plant-fuel`` (gathered from trees), and
  ``ray-receiver-pro`` (a display-only alternate form of the Ray Receiver).

THE RATE
--------
The URL carries a rate, and the rate decides how big the block is.  Too small
and every recipe rounds to one machine and nothing about multi-machine layout is
exercised; too large and the upstream tree explodes and every failure is "that
does not fit on a belt" rather than a bug.

So the rate is derived per item, from the target recipe itself:

1. Pick the recipe -- the first craftable non-mining producer, which is the one
   FactorioLab's own default selection lands on.
2. Pick its machine with ``rates.adjust.select_machine`` against the rank a bare
   URL actually carries, which is *no* rank: ``recipe.producers[0]``.  The
   dataset's ``maxMachineRank`` would be the wrong answer here -- it leads with
   the Dark Fog buildings, so every rate would be derived from a
   ``df-recomposing-assembler`` no build will ever place.
3. ``R`` = one machine's output of the target item, in items/min:
   ``out_qty / recipe.time * 60 * machine.speed``.
4. Choose the value on a round-number ladder nearest ``1.5 * R`` that still lies
   in ``[R, 6*R]``.  That is "one to six machines of the target recipe", biased
   to the small end so the block stays a block, and it is a number a human would
   type (60, not 57.6).

``target_machines = rate / R`` is recorded on every row, so the claim is checked
rather than asserted.

THE RUN
-------
``uv run flab2bp "<url>" --budget 30 -v -o <dir>/bp-<item>.txt`` with stdout and
stderr captured to ``build-<item>.log``.  No ``--allow-invalid``: a build whose
validator found errors must fail, because that is what a user sees.  The
produced blueprint is then handed to the viewer's independent TypeScript decoder
(``flab2bp.bench.crossvalidate``), so an encoder defect counts as a bug too.

What the log yields is the CLI's own report line (strategy, machines, tiles,
buildings), the complete per-check error histogram from the ``N VALIDATION
ERRORS: {...}`` line -- that dict is a ``Counter`` over *every* error, not a
sample -- and the first five error messages, which is all the CLI prints.  That
is a deliberate limit of "run it exactly as a user would"; the histogram is
what the grouping needs and the messages are the reproducer hint.

BOX DISCIPLINE
--------------
One build at a time, never in parallel, and before each build the sweep waits
for any ``trace_overhead.py`` timing gate to finish, because that gate measures
wall clock and a CP-SAT solve next to it corrupts the measurement.  ``uptime``
is recorded beside every timing: load on this box is disk I/O, so a slow build
is a fact about the hour, not about the item.

Resumable: rows already in the round's JSONL are skipped, so an interrupted
sweep restarts where it stopped.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from flab2bp.lab.data import load_vendored  # noqa: E402
from flab2bp.lab.schema import Dataset, Item, Recipe  # noqa: E402
from flab2bp.rates.adjust import select_machine  # noqa: E402

#: Categories that name a physical thing a factory produces.
ITEM_CATEGORIES = ("components", "buildings", "buildings-alt")

#: Round numbers a human would actually type into FactorioLab's rate box.
RATE_LADDER = (
    1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 24, 30, 40, 45, 60, 75, 90,
    120, 150, 180, 240, 300, 360, 450, 600, 720, 900, 1200,
)  # fmt: skip

URL_BASE = "https://factoriolab.github.io/dsp/list"

EVIDENCE = _ROOT / "docs" / "superpowers" / "evidence" / "2026-09-06-item-sweep"

_REPORT_RE = re.compile(
    r"^(?P<strategy>\S+) / (?P<label>.*?): (?P<machines>\d+) machines, "
    r"(?P<tiles>\d+) tiles, (?P<buildings>\d+) buildings$"
)
_ERRORS_RE = re.compile(r"^\s*(?P<n>\d+) VALIDATION ERRORS: (?P<counts>\{.*\})$")
_SKIPPED_RE = re.compile(r"^\s*\d+ check\(s\) could not run: (?P<checks>.*)$")

#: The timing gate to stand clear of, matched on the *interpreter* running the
#: script rather than on the bare filename.  Every agent watching for this gate
#: runs a shell whose own command line contains ``trace_overhead.py``, so the
#: loose pattern matches the watchers -- including other copies of this wait --
#: and the sweep would then block forever on processes that are themselves only
#: blocking on it.  Requiring ``python <path>/trace_overhead.py`` matches the
#: real run and not the vigil.
GATE_PATTERN = r"python[0-9.]* +[^ ]*trace_overhead\.py"


def make_url(item_id: str, rate: int) -> str:
    """A bare URL: ``o=<item>*<rate>``, which ``_parse_objectives`` reads as
    Items / Output at the default per-minute display rate."""
    return f"{URL_BASE}?o={item_id}*{rate}&v=11"


# ---------------------------------------------------------------------------
# Classification and rate
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Plan:
    item_id: str
    name: str
    category: str
    kind: str  # BUILD | RAW | OTHER
    reason: str
    recipe_id: str | None = None
    machine_id: str | None = None
    per_machine_per_min: float | None = None
    rate_per_min: int | None = None
    target_machines: float | None = None
    url: str | None = None


def _machine_rank(data: Dataset) -> tuple[str, ...]:
    """The rank a *bare* URL carries, which is none at all.

    ``lab/url.py`` leaves ``machine_rank_ids`` at ``None`` when the URL has no
    ``mmr`` field, and ``rates/solve.py`` hands that straight to
    ``select_machine``, which then falls through to ``recipe.producers[0]``.
    Using the dataset's ``maxMachineRank`` here instead would be a *different*
    machine -- that rank leads with the Dark Fog buildings, so every rate would
    be derived from a ``df-recomposing-assembler`` the build will never place.
    """
    return ()


def per_machine_rate(
    data: Dataset, recipe: Recipe, item_id: str, rank: tuple[str, ...]
) -> tuple[str, Fraction]:
    machine_id = select_machine(data, recipe, rank)
    machine_item = data.item(machine_id)
    speed = Fraction(1)
    if machine_item is not None and machine_item.machine is not None:
        speed = Fraction(machine_item.machine.speed or 1)
    qty = Fraction(recipe.outputs.get(item_id, 0))
    time_s = Fraction(recipe.time or 1)
    if qty <= 0 or time_s <= 0:
        return machine_id, Fraction(0)
    return machine_id, qty / time_s * 60 * speed


def choose_rate(per_min: Fraction) -> int:
    """Nearest ladder rung to ``1.5 * R`` inside ``[R, 6R]`` -- one to six
    machines, biased small."""
    if per_min <= 0:
        return 1
    low, high, aim = per_min, per_min * 6, per_min * Fraction(3, 2)
    inside = [v for v in RATE_LADDER if low <= v <= high]
    if inside:
        return min(inside, key=lambda v: abs(Fraction(v) - aim))
    # R above the top rung: no round number is small enough, so take the aim.
    return max(1, round(float(aim)))


def plan_for(data: Dataset, item: Item, rank: tuple[str, ...]) -> Plan:
    craftable = data.craftable_recipes_producing(item.id)
    producing = [r for r in craftable if not r.is_mining and r.producers]
    if not producing:
        if craftable:
            named = ", ".join(sorted(r.id for r in craftable))
            return Plan(
                item.id,
                item.name or item.id,
                item.category or "",
                "RAW",
                f"only extraction recipes produce it ({named}); a miner sits on a "
                f"vein, not on a blueprint tile",
            )
        return Plan(
            item.id,
            item.name or item.id,
            item.category or "",
            "OTHER",
            "no recipe in the dataset produces it (Dark Fog drop, gathered, or a "
            "display-only alternate form)",
        )
    recipe = producing[0]
    machine_id, per_min = per_machine_rate(data, recipe, item.id, rank)
    rate = choose_rate(per_min)
    return Plan(
        item.id,
        item.name or item.id,
        item.category or "",
        "BUILD",
        f"{len(producing)} craftable recipe(s); using {recipe.id}",
        recipe_id=recipe.id,
        machine_id=machine_id,
        per_machine_per_min=float(per_min),
        rate_per_min=rate,
        target_machines=float(Fraction(rate) / per_min) if per_min > 0 else None,
        url=make_url(item.id, rate),
    )


def plans(data: Dataset) -> list[Plan]:
    rank = _machine_rank(data)
    out = [plan_for(data, item, rank) for item in data.items if item.category in ITEM_CATEGORIES]
    out.sort(key=lambda p: p.item_id)
    return out


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


def uptime() -> str:
    try:
        return subprocess.run(  # noqa: S603
            ["uptime"], capture_output=True, text=True, check=False, timeout=10
        ).stdout.strip()
    except Exception as exc:  # pragma: no cover - diagnostics only
        return f"<uptime failed: {exc}>"


def wait_for_timing_gate(*, poll_s: float = 60.0, max_polls: int = 120) -> int:
    """Block while a ``trace_overhead.py`` timing gate is running.

    Returns the number of polls spent waiting.  Bounded, so a wedged gate
    delays the sweep rather than hanging it forever.
    """
    for waited in range(max_polls):
        proc = subprocess.run(  # noqa: S603
            ["pgrep", "-f", GATE_PATTERN],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return waited
        print(f"  waiting for trace_overhead.py ({waited + 1}/{max_polls})", flush=True)
        time.sleep(poll_s)
    return max_polls


def _parse_log(text: str) -> dict[str, object]:
    out: dict[str, object] = {
        "strategy": None,
        "spec_label": None,
        "machines": None,
        "tiles": None,
        "buildings": None,
        "error_counts": {},
        "error_samples": [],
        "skipped_checks": [],
        "refused_lines": [],
        "nolayout": None,
    }
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        m = _REPORT_RE.match(line)
        if m:
            out["strategy"] = m["strategy"]
            out["spec_label"] = m["label"]
            out["machines"] = int(m["machines"])
            out["tiles"] = int(m["tiles"])
            out["buildings"] = int(m["buildings"])
            continue
        m = _ERRORS_RE.match(line)
        if m:
            try:
                # A `Counter`-shaped repr: single-quoted keys, int values.
                out["error_counts"] = json.loads(m["counts"].replace("'", '"'))
            except ValueError:
                out["error_counts"] = {"<unparsed>": int(m["n"])}
            out["error_samples"] = [
                s.strip() for s in lines[idx + 1 : idx + 6] if s.startswith("    ")
            ]
            continue
        m = _SKIPPED_RE.match(line)
        if m:
            out["skipped_checks"] = [c.strip() for c in m["checks"].split(",")]
            continue
        if line.startswith("flab2bp: "):
            out["nolayout"] = line[len("flab2bp: ") :]
        if line.startswith("    ") and "produced no layout" in text:
            refused = out["refused_lines"]
            assert isinstance(refused, list)
            if len(refused) < 12:
                refused.append(line.strip())
    return out


def _crossvalidate(blueprint: str) -> dict[str, object]:
    from flab2bp.bench.crossvalidate import crossvalidate

    try:
        results = crossvalidate([blueprint])
    except Exception as exc:  # pragma: no cover - toolchain failure
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
    if not results:
        return {"available": False, "reason": "bun or the viewer checkout is missing"}
    check = results[0]
    return {
        "available": True,
        "ok": check.ok,
        "hash_valid": check.hash_valid,
        "buildings": check.buildings,
        "areas": check.areas,
        "error": check.error,
    }


def classify_outcome(exit_code: int, parsed: dict[str, object], cross: dict[str, object]) -> str:
    if exit_code == -9 or exit_code == 124:
        return "TIMEOUT"
    if exit_code == 3:
        return "REFUSED"
    if exit_code == 2:
        return "CLI_ERROR"
    if exit_code == 1:
        return "INVALID"
    if exit_code != 0:
        return "CRASH"
    if cross.get("available") and not cross.get("ok"):
        return "CROSS_INVALID"
    if cross.get("available") and cross.get("buildings") != parsed.get("buildings"):
        return "CROSS_MISMATCH"
    return "CLEAN"


def run_one(plan: Plan, out_dir: Path, *, budget: float, timeout_s: float) -> dict[str, object]:
    assert plan.url is not None
    bp_path = out_dir / f"bp-{plan.item_id}.txt"
    log_path = out_dir / f"build-{plan.item_id}.log"
    argv = ["uv", "run", "flab2bp", plan.url, "--budget", str(budget), "-v", "-o", str(bp_path)]
    before = uptime()
    started = time.monotonic()
    timed_out = False
    try:
        proc = subprocess.run(  # noqa: S603
            argv,
            cwd=_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_s,
        )
        combined = proc.stdout + proc.stderr
        exit_code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        # `text=True` makes these str, but the stubs keep the bytes arm.
        def _text(chunk: str | bytes | None) -> str:
            if chunk is None:
                return ""
            return chunk.decode("utf-8", "replace") if isinstance(chunk, bytes) else chunk

        combined = _text(exc.stdout) + _text(exc.stderr)
        exit_code = 124
        timed_out = True
    wall_s = time.monotonic() - started
    log_path.write_text(combined)

    parsed = _parse_log(combined)
    cross: dict[str, object] = {"available": False, "reason": "no blueprint emitted"}
    if exit_code == 0 and bp_path.exists():
        cross = _crossvalidate(bp_path.read_text().strip())

    row: dict[str, object] = {
        "item": plan.item_id,
        "name": plan.name,
        "category": plan.category,
        "kind": plan.kind,
        "recipe": plan.recipe_id,
        "machine": plan.machine_id,
        "per_machine_per_min": plan.per_machine_per_min,
        "rate_per_min": plan.rate_per_min,
        "target_machines": plan.target_machines,
        "url": plan.url,
        "cmd": " ".join(argv),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "wall_s": round(wall_s, 2),
        "uptime_before": before,
        "uptime_after": uptime(),
        "cross": cross,
        "stderr_tail": combined[-2000:],
        **parsed,
    }
    row["outcome"] = classify_outcome(exit_code, parsed, cross)
    return row


def _existing(path: Path) -> set[str]:
    if not path.exists():
        return set()
    done: set[str] = set()
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            done.add(json.loads(line)["item"])
        except ValueError, KeyError:
            continue
    return done


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="item_sweep", description=__doc__)
    ap.add_argument("--round", type=int, default=1, help="round number; names the JSONL")
    ap.add_argument("--budget", type=float, default=30.0)
    ap.add_argument("--timeout", type=float, default=900.0, help="wall seconds per build")
    ap.add_argument("--items", default=None, help="comma-separated subset")
    ap.add_argument("--limit", type=int, default=None, help="stop after N builds")
    ap.add_argument("--list", action="store_true", help="print the classification and exit")
    ap.add_argument("--evidence", type=Path, default=EVIDENCE)
    ap.add_argument("--no-wait", action="store_true", help="skip the timing-gate wait")
    ap.add_argument("--redo", action="store_true", help="re-run items already in the JSONL")
    args = ap.parse_args(argv)

    data = load_vendored()
    all_plans = plans(data)

    if args.list:
        for p in all_plans:
            extra = ""
            if p.kind == "BUILD":
                extra = (
                    f" recipe={p.recipe_id} machine={p.machine_id} "
                    f"R={p.per_machine_per_min:.3f}/min rate={p.rate_per_min}/min "
                    f"machines={p.target_machines:.2f}"
                )
            print(f"{p.kind:6} {p.item_id:36} {p.category:14}{extra}")
        counts: dict[str, int] = {}
        for p in all_plans:
            counts[p.kind] = counts.get(p.kind, 0) + 1
        tally = "  ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        print(f"\ntotal {len(all_plans)}  {tally}")
        return 0

    evidence = args.evidence
    out_dir = evidence / f"round-{args.round}"
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl = evidence / f"sweep-{args.round}.jsonl"

    wanted = [p for p in all_plans if p.kind == "BUILD"]
    if args.items:
        subset = {s.strip() for s in args.items.split(",") if s.strip()}
        by_id = {p.item_id: p for p in all_plans}
        missing = subset - by_id.keys()
        if missing:
            ap.error(f"unknown item(s): {sorted(missing)}")
        wanted = [by_id[i] for i in sorted(subset)]
        not_build = [p.item_id for p in wanted if p.kind != "BUILD"]
        if not_build:
            ap.error(f"not BUILD items: {not_build}")

    done = set() if args.redo else _existing(jsonl)
    todo = [p for p in wanted if p.item_id not in done]
    if args.limit is not None:
        todo = todo[: args.limit]

    print(f"round {args.round}: {len(todo)} to run, {len(done)} already recorded", flush=True)
    for n, plan in enumerate(todo, start=1):
        if not args.no_wait:
            wait_for_timing_gate()
        row = run_one(plan, out_dir, budget=args.budget, timeout_s=args.timeout)
        with jsonl.open("a") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        print(
            f"[{n}/{len(todo)}] {plan.item_id:36} {row['outcome']:14} "
            f"{row['wall_s']:7.1f}s  exit={row['exit_code']}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
