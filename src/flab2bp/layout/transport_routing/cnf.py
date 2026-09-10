"""Exact XY/height choices and guarded primitive-family CNF."""

from __future__ import annotations

import math
from collections.abc import Callable

from pysat.card import CardEnc, EncType

from .budget import TransportRefusal, WorkBudget
from .geometry import Family
from .paths import Domain


def negative(literal: int | bool) -> int | bool:
    return not literal if isinstance(literal, bool) else -literal


class FactorCNF:
    def __init__(
        self,
        domains: tuple[Domain, ...],
        add_clause: Callable[[list[int]], bool | None],
        budget: WorkBudget,
        maximum_rectangles: int = 20_000,
    ) -> None:
        self.budget = budget
        self.add_clause = add_clause
        self.maximum_rectangles = maximum_rectangles
        self.top_id = 0
        self.xy = [self.allocate(len(d.lengths)) for d in domains]
        self.height = [self.allocate(len(d.levels)) for d in domains]
        self.primary_variables = self.top_id
        # Primary allocation is contiguous: every XY group, then every height
        # group. Store one inclusive boundary per group, not per literal.
        self._choice_ends: list[int] = []
        end = 0
        for groups in (self.xy, self.height):
            for choices in groups:
                self.budget.charge("predicates")
                end += len(choices)
                self._choice_ends.append(end)
        self.thresholds: list[list[int | bool]] = []
        self.guards: dict[tuple[int, int], int | bool] = {}
        self.prohibitions: set[tuple[int, ...]] = set()
        self.rectangles = 0
        self.guard_count = 0
        for xy, heights in zip(self.xy, self.height, strict=True):
            self.exactly_one(xy)
            self.exactly_one(heights)
            thresholds: list[int | bool] = [True, *self.allocate(len(heights) - 1), False]
            self.thresholds.append(thresholds)
            for k in range(1, len(heights)):
                self.clause([-heights[k], thresholds[k]])
                self.clause([negative(thresholds[k + 1]), thresholds[k]])
                self.clause([negative(thresholds[k]), heights[k], thresholds[k + 1]])

    def allocate(self, count: int) -> list[int]:
        self.budget.charge("predicates", count)
        result = list(range(self.top_id + 1, self.top_id + count + 1))
        self.top_id += count
        return result

    def simplify(self, literals: list[int | bool]) -> tuple[int, ...] | None:
        self.budget.charge("predicates", 1 + len(literals))
        result: set[int] = set()
        for literal in literals:
            if literal is True:
                return None
            if literal is False:
                continue
            if -literal in result:
                return None
            result.add(literal)
        self.budget.charge("predicates", len(result) * max(1, len(result).bit_length()))
        return tuple(sorted(result))

    def clause(self, literals: list[int | bool]) -> None:
        simplified = self.simplify(literals)
        if simplified is not None:
            self.add_clause(list(simplified))

    def _binary(self, first: int, second: int) -> None:
        # Internal callers supply allocated nonzero integer literals. Preserve
        # canonical ordering without constructing a set or invoking a sort.
        self.budget.charge("predicates", 4)
        if first == -second:
            return
        if first == second:
            self.add_clause([first])
        elif first < second:
            self.add_clause([first, second])
        else:
            self.add_clause([second, first])

    def at_most_one(self, literals: list[int]) -> None:
        self.budget.charge("predicates", len(literals))
        if len(literals) < 2:
            return
        encoded = CardEnc.atmost(
            lits=literals, bound=1, top_id=self.top_id, encoding=EncType.seqcounter
        )
        self.top_id = max(self.top_id, encoded.nv)
        for clause in encoded.clauses:
            self.budget.charge("predicates", 1 + len(clause))
            self.add_clause(clause)

    def exactly_one(self, literals: list[int]) -> None:
        self.clause(list(literals))
        if len(literals) <= 1:
            return
        width = math.isqrt(len(literals) - 1) + 1
        rows = self.allocate((len(literals) + width - 1) // width)
        columns = self.allocate(width)
        self.at_most_one(rows)
        self.at_most_one(columns)
        for index, literal in enumerate(literals):
            row, column = divmod(index, width)
            self._binary(-literal, rows[row])
            self._binary(-literal, columns[column])

    def guard(self, domain: int, mask: int) -> int | bool:
        self.budget.charge("predicates", 1 + max(1, mask.bit_length() // 64 + 1))
        choices = self.xy[domain]
        if mask <= 0 or mask.bit_length() > len(choices):
            raise AssertionError("primitive membership lies outside original XY domain")
        key = domain, mask
        if key in self.guards:
            return self.guards[key]
        if mask == (1 << len(choices)) - 1:
            self.guards[key] = True
            return True
        if mask.bit_count() == 1:
            literal = choices[mask.bit_length() - 1]
            self.guards[key] = literal
            return literal
        literal = self.allocate(1)[0]
        members: list[int] = []
        rest = mask
        while rest:
            self.budget.charge("predicates", 1 + rest.bit_length() // 64)
            bit = rest & -rest
            member = choices[bit.bit_length() - 1]
            members.append(member)
            self._binary(-member, literal)
            rest ^= bit
        self.clause([-literal, *members])
        self.guards[key] = literal
        self.guard_count += 1
        return literal

    def exclude(self, domain: int, candidate: int) -> None:
        combo, height = divmod(candidate, len(self.height[domain]))
        self._binary(-self.xy[domain][combo], -self.height[domain][height])

    def forbid(self, left: int, right: int, family: Family) -> int:
        if left >= right:
            raise AssertionError("family domains must use canonical dense order")
        gl = self.guard(left, family.left_mask)
        gr = self.guard(right, family.right_mask)
        self.budget.charge("predicates", 4)
        if gl is False or gr is False:
            raise AssertionError("forbidden rectangle produced a tautology")
        guards = [-guard for guard in (gl, gr) if guard is not True]
        self.budget.charge(
            "predicates", len(guards) * max(1, len(guards).bit_length()) + 2 * len(guards)
        )
        guards.sort()
        # Multi-member guards follow every threshold variable in allocation;
        # singleton guards alias primary XY variables, which precede them.
        prefix = [literal for literal in guards if -literal > self.primary_variables]
        suffix = [literal for literal in guards if -literal <= self.primary_variables]
        left_thresholds, right_thresholds = self.thresholds[left], self.thresholds[right]
        before = self.rectangles
        for a, b, c, d in family.rectangles:
            self.budget.charge("predicates")
            if not (0 <= a <= b < len(self.height[left]) and 0 <= c <= d < len(self.height[right])):
                raise AssertionError("family rectangle lies outside original legal heights")
            # Negative thresholds are right-then-left; positives left-then-right.
            # Valid inclusive bounds cannot duplicate or complement a literal.
            self.budget.charge("predicates", 8 + len(guards))
            literals = list(prefix)
            if c:
                literals.append(-right_thresholds[c])
            if a:
                literals.append(-left_thresholds[a])
            literals.extend(suffix)
            if b + 1 < len(self.height[left]):
                literals.append(left_thresholds[b + 1])
            if d + 1 < len(self.height[right]):
                literals.append(right_thresholds[d + 1])
            self.budget.charge("predicates", len(literals))
            clause = tuple(literals)
            if clause in self.prohibitions:
                continue
            if self.rectangles >= self.maximum_rectangles:
                raise TransportRefusal("POLICY_BOUND", "CaDiCaL collision prohibition cap")
            self.add_clause(literals)
            self.prohibitions.add(clause)
            self.rectangles += 1
        return self.rectangles - before

    def select(self, model: list[int]) -> list[int]:
        self.budget.charge("predicates", len(model) + len(self._choice_ends))
        chosen = [0] * len(self._choice_ends)
        for literal in model:
            if not 0 < literal <= self.primary_variables:
                continue
            lo, hi = 0, len(self._choice_ends)
            while lo < hi:
                self.budget.charge("predicates")
                middle = (lo + hi) // 2
                if literal <= self._choice_ends[middle]:
                    hi = middle
                else:
                    lo = middle + 1
            self.budget.charge("predicates")
            previous = chosen[lo]
            if previous != 0 and previous != literal:
                raise AssertionError("SAT assignment violates exact semantic choices")
            chosen[lo] = literal
        selected: list[int] = []
        count = len(self.xy)
        for domain in range(count):
            # Two exact-choice checks and one candidate construction; no
            # primary-selector scan or positive-literal set is needed.
            self.budget.charge("predicates", 3)
            combo, level = chosen[domain], chosen[count + domain]
            if combo == 0 or level == 0:
                raise AssertionError("SAT assignment violates exact semantic choices")
            selected.append(
                (combo - self.xy[domain][0]) * len(self.height[domain])
                + level
                - self.height[domain][0]
            )
        return selected
