"""Command line entry point.

    flab2bp 'https://factoriolab.github.io/dsp/flow?o=super-magnetic-ring*60&...'

Prints the blueprint string to stdout, so it pipes and redirects cleanly; all
diagnostics go to stderr.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import threading
import time
from collections import Counter, deque
from pathlib import Path
from typing import TextIO

from flab2bp import pipeline
from flab2bp.layout import markers
from flab2bp.layout.band_policy import BAND_SELECTIONS, BandPolicy
from flab2bp.layout.base import NoValidLayout
from flab2bp.layout.observe import (
    TRACE_SAMPLE_INTERVAL_S,
    SampledObserver,
    SearchEvent,
)
from flab2bp.rates import DEFAULT_CANDIDATE_POLICIES, CandidatePolicy
from flab2bp.rates.machine_choice import MachineRank
from flab2bp.web.trace import TRACE_DRAIN_INTERVAL_S, frame_json


class _CliTraceWriter:
    """Buffers frozen ``SearchEvent``s off the search thread; a daemon thread
    of its own turns them into JSONL.

    Mirrors ``TraceCollector`` (web/trace.py) for exactly the reason that
    class exists: ``frame_json``'s own docstring says it "runs on the
    parent's trace thread, never on a search thread" -- before this class,
    the CLI's sink called it, plus ``json.dumps`` and the file write,
    SYNCHRONOUSLY on the thread the search was trying to spend its core on
    (fix round, Important 1). ``offer`` is the O(1) sink ``SampledObserver``
    calls; projection and I/O happen only in ``_drain_once``, off that
    thread.

    Unlike ``TraceCollector``'s stage-1 deque, ``_pending`` is unbounded: this
    is one CLI process tracing one build, not a long-lived server bounding
    memory across many jobs, and "no frames are lost" is exactly the
    guarantee a debugging JSONL file promises.
    """

    def __init__(self, trace_file: TextIO, started_at: float) -> None:
        self._trace_file = trace_file
        self._started_at = started_at
        self._pending: deque[SearchEvent] = deque()
        self._lock = threading.Lock()
        self._seq = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def offer(self, event: SearchEvent) -> None:
        """The sink. One deque append -- O(1), never touches ``placement``."""
        with self._lock:
            self._pending.append(event)

    def start(self) -> None:
        thread = threading.Thread(target=self._run, name="flab2bp-cli-trace", daemon=True)
        # `start()` BEFORE the assignment -- the same ordering
        # `TraceCollector.start()` was fixed to use (Critical 1): a failed
        # `thread.start()` must leave `self._thread` `None` rather than
        # referencing a Thread that was constructed but never actually
        # started, so `stop()` below drains directly instead of joining one.
        thread.start()
        self._thread = thread

    def _drain_once(self) -> None:
        # Swap the deque object out under the lock rather than copying it
        # (Minor, re-review round): `list(self._pending)` was an O(n) copy
        # held under the same lock `offer()` needs for its O(1) append, so a
        # long backlog could make the search thread's "O(1)" sink block
        # behind it. Reassignment is O(1); the old deque is drained below,
        # outside the lock, and nothing else holds a reference to it.
        with self._lock:
            pending, self._pending = self._pending, deque()
        for event in pending:
            frame = frame_json(self._seq, round(event.monotonic_s - self._started_at, 3), event)
            self._seq += 1
            try:
                self._trace_file.write(json.dumps(frame))
                self._trace_file.write("\n")
            except OSError:
                # R3: a debugging artefact must never take a real build down
                # with it. Re-review round: this used to propagate straight
                # out of `_run`/`stop()` -- on the writer thread that is a
                # silent thread death (tolerable), but `stop()`'s own final
                # drain runs on the MAIN thread once the writer thread is
                # gone, so an `OSError` here (disk full, a broken pipe, an
                # NFS hiccup) used to reach `cli_main`'s `finally` and kill a
                # build that had already succeeded -- precisely what R3
                # forbids, and the same "raise inside a `finally` skips the
                # resource release" shape as Critical 1, reintroduced here.
                # Whatever wrote before this point is on disk; a trace file
                # with a silently truncated tail is the correct trade, same
                # as the tolerance `trace_file.close()` already gets in
                # `main()`.
                return

    def _run(self) -> None:
        while not self._stop.is_set():
            self._drain_once()
            self._stop.wait(TRACE_DRAIN_INTERVAL_S)
        # One last pass after the stop flag is observed: a burst offered
        # between the previous periodic drain and `stop()` being called must
        # still reach the file, not be lost (mirrors `TraceCollector._run`).
        self._drain_once()

    def stop(self) -> None:
        """Join the writer thread and do one final drain, so every frame
        offered before this call is on disk before the caller closes the
        file."""
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        # Only drain here if the daemon thread is gone -- the same race
        # `TraceCollector.stop()` guards against: a wedged thread could still
        # be mid-drain, and draining again concurrently from this thread
        # would race on `self._seq`.
        if thread is None or not thread.is_alive():
            self._drain_once()


def _report(build: pipeline.Build, *, verbose: bool = False, out: TextIO | None = None) -> None:
    """Everything except the blueprint itself goes to stderr by default.

    ``out`` defaults to ``None`` rather than ``sys.stderr`` directly: a default
    argument binds once, at function-definition time, and ``capsys`` swaps in
    a fresh ``sys.stderr`` object per test -- binding the real stream eagerly
    would keep pointing at whatever object existed at import time and silently
    stop being captured.
    """
    if out is None:
        out = sys.stderr
    frame = build.placement.frame
    if frame is None:
        raise ValueError("successful build placement has no area frame")
    print(
        f"{build.strategy} / {build.spec.label}: {build.spec.machine_count} machines, "
        f"{build.placement.area} tiles, {len(build.placement.buildings)} buildings",
        file=out,
    )
    print(f"primary_band: {frame.primary_band}", file=out)
    print(
        f"certified_bands: {', '.join(map(str, frame.certified_bands))}",
        file=out,
    )

    unmarked = markers.unmarked_external_inputs(build.placement, build.spec)
    marked = int(build.placement.stats.get("input_markers", 0))
    print(
        f"inputs to belt in: {', '.join(sorted(build.spec.external_inputs)) or 'none'}"
        f"  ({marked} marked with icons)",
        file=out,
    )
    if unmarked:
        # Say it rather than let someone discover it while staring at an
        # unlabelled belt in game.
        print(f"  WARNING: no icon placed for {sorted(unmarked)}", file=out)

    # A self-loop recipe's block is dead on paste until a player hand-fills its
    # loop lane once (design §9 R3, "prime once and warn" -- never a permanent
    # external input, since the loop is steady-state correct on its own).
    prime_heads = markers.self_loop_prime_heads(build.placement, build.spec)
    for seed in build.spec.self_loop_seeds:
        head_index = prime_heads.get(seed.item_id)
        if head_index is not None:
            tile = build.placement.buildings[head_index]
            where = f" at ({tile.x},{tile.y})"
        else:
            # Honest rather than a crash: the loop's own placement should
            # always be locatable, but a report is a bad place to raise.
            where = ""
        print(
            f"prime once (self-loop): {seed.item_id} {seed.seed_items} items"
            f" onto the marked belt{where}"
            f" -- {seed.recipe_id} consumes what it produces, so the block will"
            f" not start until the loop has items in it",
            file=out,
        )

    # Say whether the selection was pinned. "No findings" and "nothing was
    # checked" read identically in silence, and only one of them is reassuring.
    if build.flow_pinned:
        if build.flow_findings:
            print(
                f"  {len(build.flow_findings)} difference(s) from the pinned flow:",
                file=out,
            )
            for finding in build.flow_findings:
                print(f"    {finding}", file=out)
        else:
            print("  recipe selection pinned to the supplied flow (no differences)", file=out)
    else:
        print(
            "  recipe selection DERIVED, not pinned -- pass --flow or --fetch-flow "
            "to build FactorioLab's own selection",
            file=out,
        )

    rules = build.belt_rules
    if rules is not None:
        if rules.from_url:
            print(
                f"  belt altitude ceiling {float(rules.max_z)} (lab level "
                f"{rules.lab_level}), vertical belt construction "
                f"{'YES' if rules.vertical_construction else 'no'} -- read from "
                f"the URL's researched technologies",
                file=out,
            )
        else:
            print(
                f"  WARNING: this URL carried no technology set, so a "
                f"FULLY-RESEARCHED save is ASSUMED: belt ceiling "
                f"{float(rules.max_z)} (lab level {rules.lab_level}), vertical "
                f"belt construction "
                f"{'YES' if rules.vertical_construction else 'no'}. A URL "
                f"exported from FactorioLab normally does carry one; if yours "
                f"did, the belts here may climb higher than your save allows.",
                file=out,
            )

    tiers = build.spec.belt_tiers
    floor = tiers[0]
    # Always report the effective cargo stack.  Only a stacked URL needs the
    # source-field suffix; stack one is the ordinary, explicit default.
    stack_note = f"; stack {build.spec.belt_stack}"
    if build.spec.belt_stack > 1:
        stack_note += f" (URL ist={build.spec.belt_stack})"
    piler_count = int(build.placement.stats.get("pilers", 0))
    piler_note = f"; {piler_count} piler(s)"
    if len(tiers) == 1:
        print(
            f"  belts: {floor.item_id} ({float(floor.items_per_second)}/s); it is "
            f"the fastest belt this save can build, so a lane over that rate is "
            f"refused{stack_note}{piler_note}",
            file=out,
        )
    else:
        ceiling = tiers[-1]
        raised = int(build.placement.stats.get("belt_runs_upgraded", 0))
        used = ", ".join(build.placement.stats.get("belt_upgrade_tiers", [])) or "none"
        if raised == 0:
            upgrade_note = "no run needed more than the floor"
        else:
            upgrade_note = f"{raised} run(s) raised to {used}"
        print(
            f"  belts: {floor.item_id} ({float(floor.items_per_second)}/s) floor, "
            f"{ceiling.item_id} ({float(ceiling.items_per_second)}/s) ceiling; "
            f"{upgrade_note}{stack_note}{piler_note}",
            file=out,
        )

    for lane_finding in build.report.by_check("flow.external_entry_points"):
        print(
            f"  entry lanes: {lane_finding.detail['item']} "
            f"{lane_finding.detail['entry_lanes']} "
            f"(needs {lane_finding.detail['lanes_needed']} at "
            f"{lane_finding.detail['capacity']}/s)",
            file=out,
        )

    if build.refused:
        # A strategy that produced NO layout is invisible in `attempts`, so say
        # so. Silence here would read as "that combination was simply not the
        # best", which is a different and much more reassuring claim.
        print(f"  {len(build.refused)} strategy/candidate pair(s) produced no layout:", file=out)
        for r in build.refused[:5]:
            print(f"    {r}", file=out)
            for failure in r.projection_failures[:5]:
                print(
                    f"      band {failure.band} {failure.check} buildings "
                    f"{failure.buildings}: {failure.detail}",
                    file=out,
                )

    if build.report.skipped:
        print(
            f"  {len(build.report.skipped)} check(s) could not run: "
            f"{', '.join(sorted(build.report.skipped))}",
            file=out,
        )
    if build.report.errors:
        counts = Counter(f.check for f in build.report.errors)
        print(f"  {len(build.report.errors)} VALIDATION ERRORS: {dict(counts)}", file=out)
        for f in build.report.errors[:5]:
            print(f"    {f.check}: {f.message}", file=out)
        print(
            "  This blueprint will paste but may not run correctly.",
            file=out,
        )

    if verbose:
        print(f"\n{'candidate':<20}{'strategy':<10}{'area':>8}{'errors':>8}", file=out)
        for a in sorted(build.attempts, key=lambda a: (not a.ok, a.area)):
            print(
                f"{a.candidate:<20}{a.strategy:<10}{a.area:>8}{len(a.report.errors):>8}",
                file=out,
            )


def _band_selection(value: str) -> str:
    try:
        return BandPolicy.parse(value).selection
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def add_candidate_policy_argument(ap: argparse.ArgumentParser) -> None:
    """Add the shared named-policy selection surface to a CLI parser."""
    labels = ", ".join(policy.value for policy in DEFAULT_CANDIDATE_POLICIES)
    ap.add_argument(
        "--candidate-policy",
        action="append",
        default=None,
        metavar="POLICY[,POLICY...]",
        help=f"candidate policies to run; repeat or comma-delimit from: {labels} "
        "(default: all three)",
    )


def candidate_policies_from_args(
    ap: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> tuple[CandidatePolicy, ...]:
    """Validate repeated/comma-delimited labels and restore canonical order."""
    selections: list[str] | None = args.candidate_policy
    if selections is None:
        return DEFAULT_CANDIDATE_POLICIES

    selected: set[CandidatePolicy] = set()
    for selection in selections:
        for raw_label in selection.split(","):
            label = raw_label.strip()
            if not label:
                ap.error("candidate policy must not be empty")
            try:
                policy = CandidatePolicy(label)
            except ValueError:
                ap.error(f"unknown candidate policy: {label!r}")
            if policy in selected:
                ap.error(f"duplicate candidate policy: {policy.value}")
            selected.add(policy)
    return tuple(policy for policy in DEFAULT_CANDIDATE_POLICIES if policy in selected)


def build_parser() -> argparse.ArgumentParser:
    """Every flag this CLI accepts, in one place a test can parse without main.

    Extracted from :func:`main` so the argument surface can be asserted on
    directly: a default that silently changes -- ``--race`` becoming opt-OUT
    before the flip commit intends it, say -- is a behaviour change no
    end-to-end test of ``main`` distinguishes from the pipeline's own default.
    """
    ap = argparse.ArgumentParser(
        prog="flab2bp",
        description="Turn a FactorioLab URL for Dyson Sphere Program into a "
        "pasteable DSP blueprint.",
    )
    ap.add_argument("url", help="a factoriolab.github.io/dsp/... URL")
    ap.add_argument(
        "--strategy",
        choices=pipeline.STRATEGY_CHOICES,
        default="best",
        help="layout backend; best runs freeform and sequence-pair and keeps the "
        "smallest valid result (default). hierarchical decomposes the spec into "
        "blocks, solves them apart and composes them; it is explicit-only and "
        "never part of best, and it may overshoot --budget by its settlement "
        "phase, which composes, routes every cut lane and certifies after the "
        "last block",
    )
    ap.add_argument(
        "--band",
        type=_band_selection,
        choices=BAND_SELECTIONS,
        default="portable",
        help="latitude-band policy (default: portable, the smallest fitting "
        "band plus up to two wider bands)",
    )
    ap.add_argument(
        "--sequence-islands",
        type=int,
        metavar="N",
        help="whole-solve process islands for explicit sequence-pair (default: "
        "CPU affinity capped at 8; explicit range 1..16). Islands inside a "
        "RACED sequence-pair arm pay the spawn cost twice and start a fresh "
        "budget those seconds late, because the islands branch derives its own "
        "deadlines and takes no absolute one",
    )
    add_candidate_policy_argument(ap)
    ap.add_argument(
        "--machine-rank",
        choices=[rank.value for rank in MachineRank],
        default=MachineRank.EXACT.value,
        help=(
            "how to read the URL's machine rank: 'exact' always uses the "
            "ranked producer (FactorioLab's behaviour, the default); 'up-to' "
            "treats it as a speed ceiling and uses the slowest unlocked "
            "producer that needs the same number of machines"
        ),
    )
    ap.add_argument(
        "--flow",
        type=Path,
        help="FactorioLab CSV export (the list view's 'download as CSV'). Pins "
        "the recipe selection to the one FactorioLab solved instead of "
        "re-deriving it. Refuses on a file that cannot be this URL's flow; "
        "there is no fallback to re-deriving.",
    )
    ap.add_argument(
        "--fetch-flow",
        action="store_true",
        help="fetch the CSV export ourselves by driving a headless browser to the "
        "URL. FactorioLab solves in the page, so this runs it and waits for the "
        "solve to finish. Off by default: a build should not silently need a "
        "browser or the network.",
    )
    ap.add_argument(
        "--fetch-timeout",
        type=float,
        default=90.0,
        metavar="SECONDS",
        help="how long to wait for FactorioLab to finish solving (default 90)",
    )
    ap.add_argument(
        "--browser",
        help="path to the Chromium or Chrome executable --fetch-flow should drive "
        "(default: search the usual locations, or $FLAB2BP_BROWSER)",
    )
    ap.add_argument(
        "--no-proliferator",
        action="store_true",
        help="build only from candidates that spray nothing, so no Spray Coaters "
        "are emitted. Refuses rather than falling back if every candidate this "
        "URL produces is proliferated.",
    )
    ap.add_argument("--budget", type=float, default=15.0, help="solver seconds per layout")
    ap.add_argument(
        "--workers",
        type=int,
        default=None,
        help="aggregate solver workers (default: up to 16 available CPUs; "
        "divided across candidate and strategy races)",
    )
    ap.add_argument(
        "--race",
        action="store_true",
        help="run --strategy best as a concurrent race for ONE budget instead of "
        "two serial solves for one budget each",
    )
    ap.add_argument(
        "--no-share",
        dest="share",
        action="store_false",
        help="race without exchanging incumbents or no-goods",
    )
    ap.add_argument("-o", "--out", type=Path, help="write to a file instead of stdout")
    ap.add_argument(
        "--trace-jsonl",
        type=Path,
        metavar="PATH",
        help="write every search snapshot as one JSON object per line to PATH "
        "-- the same frames the web transport carries (design §4), the input "
        "scripts/trace_overhead.py uses, and the offline-analysis path when "
        "there is no browser. Off by default: no path, no observer, no cost.",
    )
    ap.add_argument("-n", "--name", default="", help="blueprint short description")
    ap.add_argument("-v", "--verbose", action="store_true", help="show every attempt")
    ap.add_argument(
        "--allow-invalid",
        action="store_true",
        help="emit even when validation fails (default: exit non-zero instead, since "
        "an invalid blueprint pastes cleanly and then does not run)",
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    candidate_policies = candidate_policies_from_args(ap, args)
    if args.sequence_islands is not None and args.strategy not in (
        "sequence-pair",
        "best",
    ):
        ap.error("--sequence-islands requires --strategy sequence-pair or best")
    if args.sequence_islands is not None and not 1 <= args.sequence_islands <= 16:
        ap.error("--sequence-islands must be from 1 to 16")
    if args.workers is not None and args.workers < 1:
        ap.error("--workers must be a positive integer")
    if args.trace_jsonl is not None and args.race:
        # Task 13 fix round 1: a raced arm runs in a spawned child with no
        # in-process observer to call, and this CLI has no `trace_queue` to
        # give it one -- so before this check existed, `--trace-jsonl
        # --race` silently produced a valid-looking, permanently empty
        # file. That reads as "the search produced nothing," which is a much
        # worse failure than a build refusing to start. Threading a queue and
        # a drain thread through here (mirroring `web/jobs.py`'s
        # `Builder._run`) would fix it properly; refusing the combination
        # outright is the smaller, safer fix that removes the silent-empty-
        # file failure mode today. Tracing a raced build is not unsupported
        # forever, just not wired through this flag yet.
        ap.error(
            "--trace-jsonl is not yet supported together with --race: a raced "
            "arm has no channel to report search events through, so the "
            "combination would silently write an empty trace file. Drop "
            "--race, or omit --trace-jsonl."
        )
    # Islands are ON by default for both `sequence-pair` and `best`, which is
    # every plain `flab2bp <url>` build: four islands measured 13.6 % smaller
    # layouts at the same budget (design doc L1).  The count is deliberately NOT
    # resolved here.  `None` means "you decide", and only `pipeline.build` can:
    # a raced build resolves islands per candidate, from the worker share that
    # candidate's batch actually gave it, and the batch width is not known until
    # the candidates are.  Resolving eagerly here would hand `build` a number
    # that looks like an EXPLICIT request -- which travels verbatim, by design --
    # and every raced candidate would then get the whole build's island count
    # instead of its own share's.  Measured: four islands per candidate on a
    # five-worker share, where two is what the share funds.
    sequence_islands = args.sequence_islands

    # --trace-jsonl opens its output file here, before any solve starts, so a
    # bad path (missing directory, no permission, full disk) fails fast at
    # argument time -- the same place `--sequence-islands` and `--workers`
    # already fail on a bad value -- rather than surfacing five minutes into a
    # real build. `ap.error` never returns (argparse types it `NoReturn`), so
    # `trace_file` is a real, open file for the rest of `main` whenever it is
    # not `None`.
    trace_file = None
    search_observer = None
    writer: _CliTraceWriter | None = None
    if args.trace_jsonl is not None:
        try:
            trace_file = args.trace_jsonl.open("w", encoding="utf-8")
        except OSError as exc:
            ap.error(f"--trace-jsonl {args.trace_jsonl}: {exc}")
        # `frame_json` is the ONE place, web or CLI, that projects a
        # SearchEvent into the wire shape (web/trace.py, design §4), and its
        # own docstring says it must never run on a search thread. `writer`
        # is the CLI's side of that: `.offer` (the sink below) is an O(1)
        # deque append on the search thread, and `frame_json` plus the actual
        # file write happen only on the writer's own daemon thread (fix
        # round, Important 1). `event.monotonic_s` is captured where the
        # event was constructed (observe.py's default factory), never at
        # whatever later moment the writer thread gets around to it -- the
        # same relationship `TraceCollector.drain_once` uses against its own
        # `started_at`, so a CLI trace and a web trace measure `t` the same
        # way relative to their own start.
        writer = _CliTraceWriter(trace_file, time.monotonic())
        writer.start()
        search_observer = SampledObserver(sink=writer.offer, min_interval_s=TRACE_SAMPLE_INTERVAL_S)

    try:
        try:
            build = pipeline.build(
                args.url,
                strategy=args.strategy,
                band=args.band,
                candidate_policies=candidate_policies,
                machine_rank=MachineRank(args.machine_rank),
                time_budget_s=args.budget,
                sequence_islands=sequence_islands,
                name=args.name,
                flow=args.flow,
                fetch_flow=args.fetch_flow,
                fetch_timeout_s=args.fetch_timeout,
                browser=args.browser,
                no_proliferator=args.no_proliferator,
                workers=args.workers,
                race=args.race,
                share=args.share,
                search_observer=search_observer,
            )
            _report(build, verbose=args.verbose)
        except NoValidLayout as exc:
            # Distinct exit code: "no layout exists" is a different outcome from
            # "the URL was bad", and per the user a spec that cannot be laid out in
            # the retry budget is our bug until shown otherwise.
            print(f"flab2bp: {exc}", file=sys.stderr)
            for failure in exc.projection_failures[:5]:
                print(
                    f"  band {failure.band} {failure.check} buildings "
                    f"{failure.buildings}: {failure.detail}",
                    file=sys.stderr,
                )
            for attempt_failure in exc.attempt_failures:
                if not attempt_failure.stats:
                    continue
                numbers = " ".join(
                    f"{key}={value:g}" if isinstance(value, int | float) else f"{key}={value}"
                    for key, value in sorted(attempt_failure.stats.items())
                )
                pair = "/".join(
                    part for part in (attempt_failure.strategy, attempt_failure.candidate) if part
                )
                print(f"  stats {pair}: {numbers}", file=sys.stderr)
            return 3
        except (ValueError, KeyError) as exc:
            print(f"flab2bp: {exc}", file=sys.stderr)
            return 2
    finally:
        # `writer.stop()` FIRST: it joins the writer's daemon thread and
        # performs its final drain, so every frame `offer`ed during the build
        # is actually on disk before the file below is closed -- the
        # buffering that makes the sink O(1) (fix round, Important 1) must
        # never cost a frame at shutdown.
        #
        # Nested in its own `finally` (re-review round): `_drain_once`'s own
        # `OSError` guard should already keep `stop()` from raising, but the
        # file release below must run even if it somehow still does -- the
        # same "raise inside a `finally` skips the resource release" shape
        # Critical 1 fixed in `jobs.py`, reintroduced here by this same wave.
        try:
            if writer is not None:
                writer.stop()
        finally:
            # Every exit path -- success, NoValidLayout, ValueError/KeyError,
            # or any other exception propagating out of `pipeline.build` --
            # closes the file, so a raised build still leaves a complete,
            # readable trace instead of one truncated by a buffered write
            # that never flushed. `close()` itself is guarded: an OS-level
            # flush failure here (disk filled during the build, permission
            # revoked, an NFS hiccup) would otherwise raise AFTER a build
            # that already succeeded, discarding a finished blueprint over a
            # debugging artefact -- exactly what R3 ("a view must never kill
            # a build") forbids. A trace file with a silently truncated tail
            # is the correct trade.
            if trace_file is not None:
                with contextlib.suppress(OSError):
                    trace_file.close()

    if build.report.errors and not args.allow_invalid:
        print(
            "flab2bp: refusing to emit an invalid blueprint; pass --allow-invalid to override",
            file=sys.stderr,
        )
        return 1

    if args.out:
        args.out.write_text(build.blueprint)
        print(f"written to {args.out}", file=sys.stderr)
    else:
        print(build.blueprint)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
