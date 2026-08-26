"""Every ``EBuildCondition`` has exactly one verdict, and the verdict resolves.

``docs/EBUILD_COVERAGE.md`` is only worth having if it cannot silently fall
behind the game.  Three things can make it lie, and there is a test for each:

* **a value with no verdict** -- a game update adds a condition and nobody
  notices.  :func:`test_every_condition_has_exactly_one_verdict` fails the build
  instead;
* **a verdict with no value** -- a row survives a rename, so the matrix claims
  coverage of something that no longer exists;
* **a citation that does not resolve** -- the "+143582" offset that circulates
  on this project is not universal (see ``docs/RULE_LEDGER.md``), so a line
  number copied under the wrong convention lands in the wrong function and reads
  as evidence.  :func:`test_every_citation_resolves` re-greps them.

THE ENUM IS VENDORED, and that is the point rather than a convenience.
``tests/conditions/EBuildCondition.cs`` is a byte-for-byte copy of the
decompiled file, so the coverage test runs on a machine with no game dump.
:func:`test_the_vendored_enum_still_matches_the_decompiled_tree` is what keeps
the copy honest: where the dump IS present, a game update that changes the enum
fails here, which is exactly the "a new condition fails the build rather than
passing silently" the matrix promises.  Skipping when the dump is absent would
be a hole if it were the only check; it is not, because the vendored copy is
also what the coverage test reads.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

#: The decompiled tree every citation in the matrix is relative to.  Absent on
#: any machine without the dump, which is why it gates a skip rather than a
#: failure.
DECOMPILED = Path("/home/dannyb/.claude/jobs/66c2051c/tmp/poseless/full")

REPO = Path(__file__).resolve().parents[2]
MATRIX = REPO / "docs" / "EBUILD_COVERAGE.md"
VENDORED_ENUM = Path(__file__).resolve().parent / "EBuildCondition.cs"

VERDICTS = frozenset({"IMPLEMENTED", "INAPPLICABLE", "MISSING"})

_MEMBER = re.compile(r"^\t(?P<name>\w+) = (?P<value>\d+),?$", re.MULTILINE)
_ROW = re.compile(
    r"^\|\s*(?P<value>\d+)\s*\|\s*`(?P<name>\w+)`\s*\|\s*(?P<verdict>[A-Z]+)\s*"
    r"\|\s*(?P<where>[^|]+?)\s*\|",
    re.MULTILINE,
)
_COUNT_ROW = re.compile(
    r"^\|\s*\*\*(?P<verdict>IMPLEMENTED|INAPPLICABLE|MISSING)\*\*[^|]*\|\s*(?P<n>\d+)\s*\|",
    re.MULTILINE,
)
#: A citation as the matrix and the ledger both write them: ``File.cs:line``,
#: file-relative, optionally a range -- or a bare ``:line`` continuation, which
#: inherits the last file named.  Both forms appear in ``docs/RULE_LEDGER.md``
#: and both appear here, so the parser has to carry the current file rather than
#: require one per citation.
#: ``.py`` and ``.md`` are matched too, and then dropped: they are not
#: decompiled sources, but they DO have to consume the file slot, or a bare
#: continuation after ``validate.py:1511-1514`` would inherit whatever ``.cs``
#: file was named before it and resolve against the wrong file.
_CITATION = re.compile(
    r"(?:(?P<file>[\w./]+\.(?:cs|py|md)))?:(?P<line>\d+)(?:-(?P<end>\d+))?\b"
)
#: The matrix declares which file a bare ``:2586`` belongs to rather than
#: relying on the reader to infer it.
_DEFAULT_MARKER = re.compile(r"<!-- CITATIONS DEFAULT (?P<file>[\w.]+\.cs) -->")


def _citations(text: str) -> list[tuple[str, int, int]]:
    """Every citation as ``(file, first_line, last_line)``, in document order.

    A bare ``:2586`` inherits the file named earlier **on the same line**, and
    failing that the document's declared default, which the matrix states in a
    ``<!-- CITATIONS DEFAULT File.cs -->`` marker.  Inheritance stops at the
    newline on purpose: carrying it across lines makes a citation's meaning
    depend on the paragraph above it, and the first draft of this parser
    silently attributed sixteen ``BuildTool_BlueprintPaste`` line numbers to
    ``BuildTool_BlueprintCopy`` because of exactly that.
    """
    out: list[tuple[str, int, int]] = []
    default = ""
    for line in text.splitlines():
        marker = _DEFAULT_MARKER.search(line)
        if marker:
            default = marker["file"]
            continue
        current = default
        for m in _CITATION.finditer(line):
            if m["file"]:
                current = m["file"]
            if not current.endswith(".cs"):
                continue
            lo = int(m["line"])
            out.append((current, lo, int(m["end"]) if m["end"] else lo))
    return out


def _enum_members(source: str) -> dict[str, int]:
    return {m["name"]: int(m["value"]) for m in _MEMBER.finditer(source)}


@dataclass(frozen=True, slots=True)
class Row:
    """One line of the verdict table."""

    value: int
    verdict: str
    #: The section that argues it -- a letter for an INAPPLICABLE group,
    #: ``MISSING #n``, or the literal ``IMPLEMENTED``.
    where: str


def _verdict_table(text: str) -> dict[str, Row]:
    """The rows between the two HTML markers, as ``name -> Row``.

    Scoped to the markers so a table elsewhere in the file -- the band table, the
    emit-set table -- cannot accidentally become a verdict.
    """
    begin = text.index("<!-- BEGIN VERDICT TABLE -->")
    end = text.index("<!-- END VERDICT TABLE -->")
    out: dict[str, Row] = {}
    for row in _ROW.finditer(text[begin:end]):
        name = row["name"]
        assert name not in out, f"{name} has more than one row in the verdict table"
        out[name] = Row(value=int(row["value"]), verdict=row["verdict"], where=row["where"])
    return out


@pytest.fixture(scope="module")
def members() -> dict[str, int]:
    return _enum_members(VENDORED_ENUM.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def matrix() -> str:
    return MATRIX.read_text(encoding="utf-8")


def test_the_vendored_enum_still_matches_the_decompiled_tree() -> None:
    """A game update that touches the enum must fail here, not pass silently."""
    live = DECOMPILED / "EBuildCondition.cs"
    if not live.is_file():
        pytest.skip(f"no decompiled tree at {DECOMPILED}")
    assert live.read_bytes() == VENDORED_ENUM.read_bytes(), (
        f"{VENDORED_ENUM} has drifted from {live}. The game's enum is the list of "
        f"every way a paste can be refused, so a change here means "
        f"docs/EBUILD_COVERAGE.md needs a verdict for whatever moved."
    )


def test_the_enum_is_not_the_57_that_circulated(members: dict[str, int]) -> None:
    """59, not 57 -- and the discrepancy is worth pinning rather than fixing quietly.

    Values 0-54 are contiguous; then 100, 101, 201 and 202.  Counting only the
    contiguous run gives 55 and counting it plus two of the strays gives 57,
    which is where the number this audit was commissioned with came from.
    """
    assert len(members) == 59
    assert max(members.values()) == 202
    assert sorted(v for v in members.values() if v > 54) == [100, 101, 201, 202]


def test_every_condition_has_exactly_one_verdict(
    members: dict[str, int], matrix: str
) -> None:
    table = _verdict_table(matrix)
    missing = sorted(set(members) - set(table))
    assert not missing, (
        f"docs/EBUILD_COVERAGE.md has no verdict for {missing}. Every value of "
        f"EBuildCondition must carry one of {sorted(VERDICTS)}: the enum is the "
        f"complete list of refusals the game has, and a value without a row is a "
        f"rule nobody has checked we model."
    )


def test_no_verdict_names_a_condition_the_game_does_not_have(
    members: dict[str, int], matrix: str
) -> None:
    table = _verdict_table(matrix)
    unknown = sorted(set(table) - set(members))
    assert not unknown, f"verdict rows for values that are not in the enum: {unknown}"


def test_every_verdict_row_agrees_with_the_enum(
    members: dict[str, int], matrix: str
) -> None:
    for name, row in _verdict_table(matrix).items():
        assert row.verdict in VERDICTS, (
            f"{name} has verdict {row.verdict!r}, not one of {VERDICTS}"
        )
        assert members[name] == row.value, (
            f"{name} is {members[name]} in the enum but the matrix says {row.value}"
        )


def test_the_headline_counts_match_the_table(members: dict[str, int], matrix: str) -> None:
    """The three numbers the report leads with are derived, not asserted."""
    table = _verdict_table(matrix)
    actual = {v: 0 for v in VERDICTS}
    for row in table.values():
        actual[row.verdict] += 1
    declared = {m["verdict"]: int(m["n"]) for m in _COUNT_ROW.finditer(matrix)}
    assert declared == actual, (
        f"the count table at the top of docs/EBUILD_COVERAGE.md says {declared} "
        f"but the verdict table says {actual}"
    )
    assert sum(actual.values()) == len(members)


def test_every_row_points_at_a_section_that_exists_and_counts_it(matrix: str) -> None:
    """The verdict table's "argued in" column is a link, not a label.

    A row that says ``D`` and a section D that does not contain it is how a
    matrix rots: the verdict survives, the argument behind it quietly does not.
    Each lettered section states its own size in its heading, so the two can be
    reconciled without parsing the sections' bodies.
    """
    table = _verdict_table(matrix)
    sections = {
        m["letter"]: int(m["n"])
        for m in re.finditer(r"^### (?P<letter>[A-G])\. .+? — (?P<n>\d+)$", matrix, re.MULTILINE)
    }
    assert sections, "no lettered INAPPLICABLE sections found"
    counted = dict.fromkeys(sections, 0)
    for name, row in table.items():
        where = row.where
        if row.verdict == "INAPPLICABLE":
            assert where in sections, f"{name} is argued in section {where!r}, which does not exist"
            counted[where] += 1
        elif row.verdict == "MISSING":
            n = where.removeprefix("MISSING #")
            assert re.search(rf"^### {re.escape(n)}\. ", matrix, re.MULTILINE), (
                f"{name} points at {where!r}, which is not a MISSING section heading"
            )
        else:
            assert where == "IMPLEMENTED", f"{name} is IMPLEMENTED but points at {where!r}"
    assert counted == sections, (
        f"the lettered sections declare {sections} but the verdict table sends them {counted}"
    )


def test_every_citation_resolves(matrix: str) -> None:
    """Every ``File.cs:line`` names a real file and an in-bounds line.

    This is the ledger's own convention -- citations are file-relative, and the
    offset is established per citation by grepping the literal, never by applying
    a constant.  An in-bounds line number is not by itself a citation, so the
    matrix's load-bearing ones are spot-checked for content in
    :func:`test_the_load_bearing_citations_contain_what_they_are_cited_for`.
    """
    if not DECOMPILED.is_dir():
        pytest.skip(f"no decompiled tree at {DECOMPILED}")
    lengths: dict[str, int] = {}
    bad: list[str] = []
    cites = _citations(matrix)
    assert len(cites) > 80, f"only {len(cites)} citations parsed; the matrix should carry many more"
    for name, lo, hi in cites:
        if name not in lengths:
            path = DECOMPILED / name
            lengths[name] = (
                len(path.read_text(encoding="utf-8").splitlines()) if path.is_file() else -1
            )
        n = lengths[name]
        if n < 0:
            bad.append(f"{name}: no such file in the decompiled tree")
            continue
        for line in (lo, hi):
            if not 1 <= line <= n:
                bad.append(f"{name}:{line} is out of bounds ({n} lines)")
    assert not bad, "unresolvable citations in docs/EBUILD_COVERAGE.md:\n" + "\n".join(bad)


#: Citation -> a literal that must appear within +/- 3 lines of it.  These are the
#: ones a wrong offset would silently change the meaning of: the thresholds every
#: MISSING row's handoff is specified in, plus one anchor per file the matrix
#: cites, so a whole-file offset error cannot hide.
LOAD_BEARING: tuple[tuple[str, int, str], ...] = (
    # PowerTooClose: the guard and the 3.5-world-unit threshold.
    ("BuildTool_BlueprintPaste.cs", 2527, "desc.isPowerNode"),
    ("BuildTool_BlueprintPaste.cs", 2586, "num35 < 12.25f"),
    # OutOfVerticalConstructionHeight: the guard, the divisor and the comparison.
    ("BuildTool_BlueprintPaste.cs", 2036, "isSplitter"),
    ("BuildTool_BlueprintPaste.cs", 2063, "2.666667f"),
    ("BuildTool_BlueprintPaste.cs", 2065, "num13 >= num11"),
    # BlueprintNeedTech: the building-count cap.
    ("BuildTool_BlueprintPaste.cs", 1122, "blueprintLimit < blueprint.buildings.Length"),
    # TooSkew, spray-coater form.
    ("BuildTool_BlueprintPaste.cs", 1863, "isSpraycoster"),
    ("BuildTool_BlueprintPaste.cs", 1866, "0.265f"),
    # TooSkew, the two inserter forms that ARE modelled.
    ("BuildTool_BlueprintPaste.cs", 3488, "Quaternion.Angle"),
    ("BuildTool_BlueprintPaste.cs", 3499, "24f"),
    # TooFar, belt-to-belt: the cap, and the line that shows the
    # beltVerticalConstruction gate starts AFTER it.
    ("BuildTool_BlueprintPaste.cs", 2087, "sqrMagnitude > 5.3f"),
    ("BuildTool_BlueprintPaste.cs", 2093, "history.beltVerticalConstruction"),
    # The gate that makes NotEnoughItem and BlueprintBPOverlap non-refusals.
    ("BuildTool_BlueprintPaste.cs", 4816, "EBuildCondition.BlueprintBPOverlap"),
    # BlueprintBPOverlap's same-prefab guard, which is what lets a splitter and a
    # belt share a tile.
    ("BuildTool_BlueprintPaste.cs", 910, "buildPreview2.desc == buildPreview3.desc"),
    # The tropic conditions, in the file the ledger proves is offset 0.
    ("BlueprintUtils.cs", 2500, "GetAreaCount"),
    ("BlueprintUtils.cs", 2558, "0.01f"),
    ("BlueprintUtils.cs", 2048, "1.3333333f"),
    # ErrorInserterData's four clauses.
    ("BlueprintUtils.cs", 2125, "0.5f"),
    ("BlueprintUtils.cs", 2129, "1.6f"),
    # The defaults the MISSING thresholds are compared against.
    ("GameHistoryData.cs", 576, "storageLevel = 2"),
    ("GameHistoryData.cs", 577, "labLevel = 3"),
    # The spray coater's curvature model.
    ("SpraycoaterComponent.cs", 120, "GetReshapeData"),
    # Path-only conditions: the citation that retires TooBendToLift.
    ("BuildTool_Path.cs", 1982, "TooBendToLift"),
    # A condition that is text and nothing else.
    ("BuildPreview.cs", 93, "NeedTech"),
    # TooSteep, where the paste and the path state the same rule differently.
    ("BuildTool_Path.cs", 1954, "num25 > 0.8f"),
)


def test_the_load_bearing_citations_contain_what_they_are_cited_for() -> None:
    """An in-bounds line number is not a citation; this is what makes it one."""
    if not DECOMPILED.is_dir():
        pytest.skip(f"no decompiled tree at {DECOMPILED}")
    bad: list[str] = []
    cache: dict[str, list[str]] = {}
    for name, line, literal in LOAD_BEARING:
        if name not in cache:
            cache[name] = (DECOMPILED / name).read_text(encoding="utf-8").splitlines()
        lines = cache[name]
        window = "\n".join(lines[max(0, line - 4) : line + 3])
        if literal not in window:
            bad.append(f"{name}:{line} does not contain {literal!r} within +/- 3 lines")
    assert not bad, "\n".join(bad)


def test_every_load_bearing_citation_is_actually_in_the_matrix(matrix: str) -> None:
    """The spot-check list may not drift into checking citations nobody cites."""
    # A range citation covers everything between its endpoints, so a spot-check
    # that lands inside one is cited.
    cites = _citations(matrix)
    orphans = [
        f"{name}:{line}"
        for name, line, _literal in LOAD_BEARING
        if not any(f == name and lo <= line <= hi for f, lo, hi in cites)
    ]
    assert not orphans, (
        f"LOAD_BEARING spot-checks {orphans}, which docs/EBUILD_COVERAGE.md does "
        f"not cite. Either cite them or drop the spot-check."
    )
