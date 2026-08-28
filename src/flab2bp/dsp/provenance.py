"""The mechanisms that read :mod:`flab2bp.dsp.registry` and answer, with numbers.

Three questions, one per mechanism in Phase R of
``docs/RULE_CONSOLIDATION_PLAN.md``:

R1 -- :func:`literal_violations`
    Does a declared game constant's *value* appear as a bare literal outside
    ``dsp``?  That is the check that would have caught ``24.0`` living in two
    files.  It hunts only for values the registry declares worth hunting for,
    so ``freeform.LEVELS = 3`` can never trip it.

R2 -- :func:`consultation`
    Is every declared rule *named by at least one check*, and by at least one
    strategy?  A rule with no readers is an unported rule wearing a ported
    rule's clothes.  This is the function that prints the percentage.

The tech-level clause -- :func:`flattened`
    Is any rule declared to vary over an input, yet stored as a scalar with
    nothing resolving the variation?  Such a rule is right by coincidence at one
    tech level and silently wrong at the others.

How "consulted" is decided
--------------------------

By a reference graph over the package's own source, not by grep.  Nodes are
module-level definitions (``flab2bp.layout.validate._footprint``,
``flab2bp.dsp.rules.SLOT_REACH``); an edge means the first names the second.
The graph is *transitive*, which is the whole point: ``ADDON_NEIGHBOUR_RADIAL_GAP``
appears nowhere in ``layout/`` and is nonetheless consulted, because
``game.addon_corner`` calls ``rules.addon_ride_is_straight`` which reads it.  A
grep says zero readers; the truth is one check and one strategy.

Two deliberate asymmetries:

* **Check reachability starts at the registered checks**, taken from
  ``validate.CHECKS`` at import time -- not at the module.  A helper nobody
  calls therefore cannot launder a rule into looking consulted.
* **Strategy reachability refuses to pass through ``validate``.**  Several
  strategies call ``certify()`` before they commit a placement.  Letting that
  edge stand would mark every rule any check reads as "consulted by the search",
  which is exactly the false reassurance this mechanism exists to prevent.  A
  strategy consults a rule when its own code reaches it.

What this cannot see
--------------------

Static reachability proves a rule is *named*.  It cannot prove the value is
*used* -- a module may read a constant into a variable and ignore it.  That is
R4's job (``tests/rules/test_rule_mutation.py``), and it is why R4 exists.
"""

from __future__ import annotations

import ast
import functools
import importlib
import math
import types
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from flab2bp.dsp import registry
from flab2bp.dsp.registry import Entry, Kind

__all__ = [
    "Consultation",
    "Graph",
    "LiteralViolation",
    "build_graph",
    "consultation",
    "flattened",
    "hardcoding_readers",
    "linted_values",
    "literal_violations",
    "module_level_names",
    "scan_source",
    "stale_lint_exceptions",
    "summary",
    "unexplained_literals",
]

PACKAGE = "flab2bp"

#: Modules whose code is the *search*.  Everything R4 calls a "strategy test"
#: exercises one of these.
STRATEGY_MODULES: tuple[str, ...] = (
    "flab2bp.layout.freeform",
    "flab2bp.layout.sequence_solver",
    "flab2bp.layout.sequence_pair",
    "flab2bp.layout.compact_seed",
    "flab2bp.layout.slots",
    "flab2bp.layout.junction",
    "flab2bp.layout.base",
    "flab2bp.layout.geometry",
    "flab2bp.layout.markers",
)

VALIDATE_MODULE = "flab2bp.layout.validate"

#: Where R1 hunts.  ``dsp`` itself is excluded by construction: that is where
#: the constants are supposed to live.
LINT_PACKAGES: tuple[str, ...] = (
    "flab2bp.layout",
    "flab2bp.bench",
    "flab2bp.rates",
)


def _package_root() -> Path:
    module = importlib.import_module(PACKAGE)
    paths = list(getattr(module, "__path__", []))
    if not paths:  # pragma: no cover - a namespace package would be a build bug
        raise RuntimeError("flab2bp has no __path__")
    return Path(paths[0])


def _source_files() -> dict[str, Path]:
    """Every module in the package, keyed by dotted name."""
    root = _package_root()
    out: dict[str, Path] = {}
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts.pop()
        out[".".join([PACKAGE, *parts])] = path
    return out


# --- the reference graph ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class Graph:
    """Nodes are dotted definition names; edges are "names".

    ``edges`` maps a node to everything it references.  ``owner`` maps a node to
    the module it is defined in, so a closure can be reported per module.
    """

    edges: Mapping[str, frozenset[str]]
    owner: Mapping[str, str]
    #: Node -> ``"const" | "func" | "class" | "method" | "module" | "default"``.
    #: ``const`` and ``default`` are the two that run at IMPORT time, which is
    #: what :func:`frozen_captures` needs to know.
    kind: Mapping[str, str] = types.MappingProxyType({})
    #: Node -> the subset of its references that appear in CALL position.
    #:
    #: Only recorded for import-time nodes, and the distinction is the whole
    #: reason :func:`frozen_captures` gives a usable answer.
    #: ``pipeline.PRODUCTION_STRATEGIES`` names backends at import; it does not
    #: run them, so it freezes nothing.
    #: ``junction._KEEPOUT = tuple(sorted(_keepout()))`` calls, so everything
    #: ``_keepout`` reaches really is resolved once and kept.
    calls: Mapping[str, frozenset[str]] = types.MappingProxyType({})

    def closure(self, roots: Iterable[str], *, block: Iterable[str] = ()) -> frozenset[str]:
        """Everything reachable from ``roots``, never entering a blocked module."""
        blocked = tuple(block)
        seen: set[str] = set()
        stack = [r for r in roots if r in self.edges]
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            for nxt in self.edges.get(node, frozenset()):
                if nxt in seen:
                    continue
                if any(self.owner.get(nxt, "") == b for b in blocked):
                    continue
                stack.append(nxt)
        return frozenset(seen)

    def nodes_in(self, module: str) -> frozenset[str]:
        return frozenset(n for n, m in self.owner.items() if m == module)


def _import_map(module: str, tree: ast.Module, modules: frozenset[str]) -> dict[str, str]:
    """Local name -> dotted target, for imports that land inside the package."""
    package_parts = module.split(".")
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(PACKAGE):
                    out[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package_parts[: len(package_parts) - node.level + 1]
                prefix = ".".join([*base, node.module] if node.module else base)
            elif node.module and node.module.startswith(PACKAGE):
                prefix = node.module
            else:
                continue
            for alias in node.names:
                out[alias.asname or alias.name] = f"{prefix}.{alias.name}"
    return out


def _refs(
    node: ast.AST,
    *,
    module: str,
    imports: Mapping[str, str],
    local: frozenset[str],
    modules: frozenset[str],
) -> set[str]:
    found: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name):
            base = imports.get(sub.value.id)
            if base is not None and base in modules:
                found.add(f"{base}.{sub.attr}")
                continue
        if isinstance(sub, ast.Name):
            target = imports.get(sub.id)
            if target is not None and target not in modules:
                found.add(target)
            elif sub.id in local:
                found.add(f"{module}.{sub.id}")
    return found


def _call_refs(
    node: ast.AST,
    *,
    module: str,
    imports: Mapping[str, str],
    local: frozenset[str],
    modules: frozenset[str],
) -> set[str]:
    """References in CALL position -- the ones an import-time expression runs."""
    kw = {"module": module, "imports": imports, "local": local, "modules": modules}
    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            out |= _refs(sub.func, **kw)  # type: ignore[arg-type]
    return out


def _default_refs(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    module: str,
    imports: Mapping[str, str],
    local: frozenset[str],
    modules: frozenset[str],
) -> set[str]:
    """Rules captured in a signature's DEFAULT values.

    ``def addon_axis_aligned(..., *, limit_deg: float = ADDON_AXIS_DEG)`` reads
    the constant once, when the ``def`` executes.  Rebinding the constant
    afterwards cannot move it, which is why R4 sees such a rule as inert even
    though it is plainly consulted.
    """
    out: set[str] = set()
    kw = {"module": module, "imports": imports, "local": local, "modules": modules}
    for default in (*fn.args.defaults, *(d for d in fn.args.kw_defaults if d is not None)):
        out |= _refs(default, **kw)  # type: ignore[arg-type]
    return out


def _default_call_refs(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    module: str,
    imports: Mapping[str, str],
    local: frozenset[str],
    modules: frozenset[str],
) -> set[str]:
    out: set[str] = set()
    kw = {"module": module, "imports": imports, "local": local, "modules": modules}
    for default in (*fn.args.defaults, *(d for d in fn.args.kw_defaults if d is not None)):
        out |= _call_refs(default, **kw)  # type: ignore[arg-type]
    return out


@functools.lru_cache(maxsize=1)
def build_graph() -> Graph:
    """Parse the whole package once and index what names what.

    Cached because four mechanisms want the same graph and parsing 108 modules
    for each of them is a second apiece out of a suite with 17 to spare.
    """
    files = _source_files()
    modules = frozenset(files)
    edges: dict[str, set[str]] = {}
    owner: dict[str, str] = {}
    kind: dict[str, str] = {}
    calls: dict[str, set[str]] = {}

    parsed: dict[str, ast.Module] = {
        name: ast.parse(path.read_text(encoding="utf-8")) for name, path in files.items()
    }
    locals_by_module: dict[str, frozenset[str]] = {
        name: frozenset(module_level_names(tree)) for name, tree in parsed.items()
    }

    for module, tree in parsed.items():
        imports = _import_map(module, tree, modules)
        local = locals_by_module[module]

        def add(
            node_name: str,
            refs: set[str],
            node_kind: str,
            *,
            owning: str = module,
            called: set[str] | None = None,
        ) -> None:
            edges.setdefault(node_name, set()).update(refs)
            owner[node_name] = owning
            kind[node_name] = node_kind
            if called:
                calls.setdefault(node_name, set()).update(called)

        loose: set[str] = set()
        for stmt in tree.body:
            kw = {"module": module, "imports": imports, "local": local, "modules": modules}
            if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
                node = f"{module}.{stmt.name}"
                add(node, _refs(stmt, **kw), "func")  # type: ignore[arg-type]
                defaults = _default_refs(stmt, **kw)  # type: ignore[arg-type]
                if defaults:
                    add(
                        f"{node}.<defaults>",
                        defaults,
                        "default",
                        called=_default_call_refs(stmt, **kw),  # type: ignore[arg-type]
                    )
            elif isinstance(stmt, ast.ClassDef):
                cls = f"{module}.{stmt.name}"
                body_refs: set[str] = set()
                for inner in stmt.body:
                    if isinstance(inner, ast.FunctionDef | ast.AsyncFunctionDef):
                        method = f"{cls}.{inner.name}"
                        add(method, _refs(inner, **kw), "method")  # type: ignore[arg-type]
                        body_refs.add(method)
                        defaults = _default_refs(inner, **kw)  # type: ignore[arg-type]
                        if defaults:
                            add(
                                f"{method}.<defaults>",
                                defaults,
                                "default",
                                called=_default_call_refs(inner, **kw),  # type: ignore[arg-type]
                            )
                    else:
                        body_refs |= _refs(inner, **kw)  # type: ignore[arg-type]
                for deco in stmt.decorator_list:
                    body_refs |= _refs(deco, **kw)  # type: ignore[arg-type]
                add(cls, body_refs, "class")
            elif isinstance(stmt, ast.Assign | ast.AnnAssign):
                targets = (
                    [t for t in stmt.targets if isinstance(t, ast.Name)]
                    if isinstance(stmt, ast.Assign)
                    else ([stmt.target] if isinstance(stmt.target, ast.Name) else [])
                )
                value_refs = _refs(stmt.value, **kw) if stmt.value is not None else set()  # type: ignore[arg-type]
                called = (
                    _call_refs(stmt.value, **kw) if stmt.value is not None else set()  # type: ignore[arg-type]
                )
                if targets:
                    for t in targets:
                        add(f"{module}.{t.id}", set(value_refs), "const", called=set(called))
                else:
                    loose |= value_refs
            else:
                loose |= _refs(stmt, **kw)  # type: ignore[arg-type]
        add(module, loose, "module")

    return Graph(
        edges={k: frozenset(v) for k, v in edges.items()},
        owner=dict(owner),
        kind=dict(kind),
        calls={k: frozenset(v) for k, v in calls.items()},
    )


def module_level_names(tree: ast.Module) -> Iterator[str]:
    """Every name a module binds at top level, imports included."""
    for stmt in tree.body:
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            yield stmt.name
        elif isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                if isinstance(t, ast.Name):
                    yield t.id
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            yield stmt.target.id
        elif isinstance(stmt, ast.Import | ast.ImportFrom):
            for alias in stmt.names:
                yield alias.asname or alias.name.split(".")[0]


# --- R2: who consults what -------------------------------------------------


@dataclass(frozen=True, slots=True)
class Consultation:
    entry: Entry
    #: Check ids whose transitive closure names this entry.
    checks: tuple[str, ...]
    #: Strategy modules whose own closure names it, ``validate`` excluded.
    strategies: tuple[str, ...]

    @property
    def consulted(self) -> bool:
        return bool(self.checks) or bool(self.strategies)

    @property
    def both(self) -> bool:
        return bool(self.checks) and bool(self.strategies)


def _check_roots() -> dict[str, str]:
    """Registered check id -> its function's graph node."""
    validate = importlib.import_module(VALIDATE_MODULE)
    out: dict[str, str] = {}
    for cid, fn in validate.CHECKS.items():
        out[cid] = f"{VALIDATE_MODULE}.{fn.__qualname__}"
    return out


def consultation(graph: Graph | None = None) -> tuple[Consultation, ...]:
    """One row per declared RULE, with who reaches it."""
    g = graph if graph is not None else build_graph()
    per_check = {cid: g.closure([root]) for cid, root in _check_roots().items()}
    per_strategy = {
        m: g.closure(g.nodes_in(m), block=(VALIDATE_MODULE,)) for m in STRATEGY_MODULES
    }
    rows: list[Consultation] = []
    for entry in registry.rules():
        node = entry.dotted
        rows.append(
            Consultation(
                entry=entry,
                checks=tuple(sorted(c for c, reach in per_check.items() if node in reach)),
                strategies=tuple(sorted(m for m, reach in per_strategy.items() if node in reach)),
            )
        )
    return tuple(rows)


def summary(rows: Iterable[Consultation]) -> dict[str, int]:
    rows = tuple(rows)
    return {
        "declared": len(rows),
        "by_a_check": sum(1 for r in rows if r.checks),
        "by_a_strategy": sum(1 for r in rows if r.strategies),
        "by_both": sum(1 for r in rows if r.both),
        "by_nothing": sum(1 for r in rows if not r.consulted),
    }


# --- the tech-level clause -------------------------------------------------


def _is_lookup(value: object) -> bool:
    return callable(value) or isinstance(value, Mapping)


def flattened() -> tuple[Entry, ...]:
    """Rules declared to vary, stored as a scalar, with nothing resolving them.

    Right by coincidence at one tech level, silently wrong at the others.
    """
    out: list[Entry] = []
    for entry in registry.ENTRIES:
        if entry.kind is not Kind.RULE or not entry.depends_on:
            continue
        if entry.resolved_by is not None:
            continue
        if not _is_lookup(registry.resolve(entry)):
            out.append(entry)
    return tuple(out)


def frozen_captures(graph: Graph | None = None) -> dict[str, tuple[str, ...]]:
    """Where each rule is read ONCE, at import, and cached forever after.

    Two shapes, both of which look identical to a mutation test and neither of
    which is a defect on its own:

    * a module-level constant computed from the rule --
      ``junction._KEEPOUT = tuple(sorted(_keepout()))`` and
      ``rules.SLOT_ALIGN_COS = cos(SKEW_AXIS_DEG)``.  This is Phase 2's
      "compile, don't call" pattern, working as designed.
    * a rule used as a DEFAULT ARGUMENT --
      ``addon_axis_aligned(..., limit_deg=ADDON_AXIS_DEG)``.  Same effect,
      much less obviously deliberate.

    R4 needs this because without it a frozen rule is indistinguishable from an
    ignored one, and reporting "the search does not consult ADDON_AXIS_DEG"
    when the truth is "it consults a copy taken at import" is the kind of
    confident wrong answer this whole plan exists to stop.
    """
    g = graph if graph is not None else build_graph()
    captured: dict[str, frozenset[str]] = {}
    for node, node_kind in g.kind.items():
        if node_kind not in {"const", "default"}:
            continue
        direct = g.edges.get(node, frozenset())
        run = g.closure(g.calls.get(node, frozenset()))
        captured[node] = direct | run
    out: dict[str, tuple[str, ...]] = {}
    for entry in registry.rules():
        node = entry.dotted
        holders = [n for n, reach in captured.items() if n != node and node in reach]
        if holders:
            out[entry.symbol] = tuple(sorted(holders))
    return out


def hardcoding_readers(graph: Graph | None = None) -> dict[str, tuple[str, ...]]:
    """Entries that pin a declared input, and the strategy modules reading them.

    A reader of one of these consults the rule *at an assumed tech level*, which
    the plan's tech clause distinguishes from consulting it properly.
    """
    g = graph if graph is not None else build_graph()
    out: dict[str, tuple[str, ...]] = {}
    for entry in registry.ENTRIES:
        if not entry.hardcodes:
            continue
        readers = [
            m
            for m in (*STRATEGY_MODULES, VALIDATE_MODULE)
            if entry.dotted in g.closure(g.nodes_in(m))
        ]
        out[entry.symbol] = tuple(sorted(readers))
    return out


# --- R1: the literal lint --------------------------------------------------


@dataclass(frozen=True, slots=True)
class LiteralViolation:
    module: str
    #: The top-level definition the literal sits in, or ``"<module>"``.
    where: str
    lineno: int
    literal: float
    matches: tuple[str, ...]

    @property
    def site(self) -> tuple[str, str, float]:
        """The identity an exception is keyed on.  Deliberately not the line."""
        return (self.module, self.where, self.literal)

    def __str__(self) -> str:
        return (
            f"{self.module}:{self.lineno} ({self.where}): bare literal {self.literal!r} "
            f"is the value of {', '.join(self.matches)} -- import it from flab2bp.dsp "
            f"or add a declared exception saying why it is a coincidence"
        )


def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float | Fraction):
        return float(value)
    return None


def linted_values() -> dict[float, tuple[str, ...]]:
    """Value -> the declared symbols that hold it.  R1's needle set."""
    out: dict[float, list[str]] = {}
    for entry in registry.ENTRIES:
        if not entry.lint:
            continue
        value = registry.resolve(entry)
        candidates: list[float] = []
        if entry.lint_enumerate == "model_index":
            catalog = importlib.import_module("flab2bp.dsp.catalog")
            assert callable(value)
            for building in catalog.all_buildings():
                index = getattr(building, "model_index", None)
                if index is None:
                    continue
                got = _as_float(value(index))
                if got is not None and got > 0.0:
                    candidates.append(got)
        else:
            got = _as_float(value)
            if got is not None:
                candidates.append(got)
        for candidate in candidates:
            out.setdefault(candidate, []).append(entry.symbol)
    return {k: tuple(sorted(set(v))) for k, v in out.items()}


def _literal_value(node: ast.AST) -> float | None:
    """The numeric value of a literal expression, ``Fraction(a, b)`` included."""
    if isinstance(node, ast.Constant):
        return _as_float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _literal_value(node.operand)
        return None if inner is None else -inner
    if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Fraction":
        args = [_literal_value(a) for a in node.args]
        if len(args) == 2 and args[0] is not None and args[1]:
            return args[0] / args[1]
        if len(args) == 1 and args[0] is not None:
            return args[0]
    return None


def _owner_by_line(tree: ast.Module) -> dict[int, str]:
    """Line -> the TOP-LEVEL definition it belongs to.

    Top level, not innermost, on purpose: a nested closure is renamed or
    reshaped far more often than the function that contains it, and an
    exception keyed on a name that moves every week is an exception that has to
    be re-approved every week.
    """
    out: dict[int, str] = {}
    for stmt in tree.body:
        if not isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        end = stmt.end_lineno or stmt.lineno
        for line in range(stmt.lineno, end + 1):
            out[line] = stmt.name
    return out


def scan_source(
    module: str,
    source: str,
    needles: Mapping[float, tuple[str, ...]] | None = None,
) -> tuple[LiteralViolation, ...]:
    """R1 over one module's text.  Exposed so the lint's own teeth are testable."""
    hunted = dict(needles) if needles is not None else linted_values()
    tree = ast.parse(source)
    owners = _owner_by_line(tree)
    out: list[LiteralViolation] = []
    for node in ast.walk(tree):
        value = _literal_value(node)
        if value is None:
            continue
        lineno = getattr(node, "lineno", 0)
        for needle, symbols in hunted.items():
            if math.isclose(value, needle, rel_tol=1e-9, abs_tol=1e-12):
                out.append(
                    LiteralViolation(
                        module=module,
                        where=owners.get(lineno, "<module>"),
                        lineno=lineno,
                        literal=value,
                        matches=symbols,
                    )
                )
                break
    return tuple(out)


def literal_violations() -> tuple[LiteralViolation, ...]:
    """Every bare literal outside ``dsp`` that equals a declared rule constant."""
    needles = linted_values()
    out: list[LiteralViolation] = []
    for module, path in _source_files().items():
        if not any(module.startswith(p) for p in LINT_PACKAGES):
            continue
        out.extend(scan_source(module, path.read_text(encoding="utf-8"), needles))
    return tuple(sorted(out, key=lambda v: (v.module, v.lineno)))


def _excepted_sites() -> frozenset[tuple[str, str, float]]:
    return frozenset((e.module, e.where, e.value) for e in registry.LINT_EXCEPTIONS)


def unexplained_literals() -> tuple[LiteralViolation, ...]:
    """R1's verdict: violations with no declared coincidence behind them."""
    excepted = _excepted_sites()
    return tuple(v for v in literal_violations() if v.site not in excepted)


def stale_lint_exceptions() -> tuple[registry.LintException, ...]:
    """Declared coincidences that no longer match any site.

    Reported, never fatal.  A lint that fails because somebody else renamed a
    function is a lint that gets deleted.
    """
    live = {v.site for v in literal_violations()}
    return tuple(e for e in registry.LINT_EXCEPTIONS if (e.module, e.where, e.value) not in live)
