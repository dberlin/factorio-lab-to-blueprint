"""Lossless identity and explicit configuration scope for audit JSONL cells.

Legacy per-URL regression and A/B sample schemas have different contracts;
only audit-shaped rows belong here. Source commits are provenance, not keys.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import TypedDict


@dataclass(frozen=True, slots=True, order=True)
class AuditCellKey:
    strategy: str
    url_id: str
    spec_index: int
    spec_label: str
    budget: float
    power: bool


class AuditCellRow(TypedDict):
    strategy: str
    url_id: str
    spec_index: int
    spec_label: str
    budget: float
    power: bool
    machine_rank: str
    power_tower: str


TREATMENT_FIELDS = frozenset(
    {"spec_label", "machine_rank", "power_tower", "route_backend", "coater_arm", "arrangements"}
)
_REQUIRED = tuple(AuditCellRow.__required_keys__)
_CONFIGURATION = ("machine_rank", "power_tower", "route_backend", "coater_arm", "arrangements")


def index_audit_cells[Row: Mapping[str, object]](
    rows: Iterable[Row],
) -> dict[AuditCellKey, Row]:
    """Reject insufficient or duplicate identities before any outcome is credited."""
    indexed: dict[AuditCellKey, Row] = {}
    for row in rows:
        missing = sorted(set(_REQUIRED) - row.keys())
        if missing:
            raise ValueError(f"missing exact audit identity/configuration fields: {missing}")
        for field in ("strategy", "url_id", "spec_label", "machine_rank", "power_tower"):
            value = row[field]
            if not isinstance(value, str) or not value.strip() or value == "?":
                raise ValueError(f"insufficient exact audit identity: {field}={value!r}")
        index, budget, power = row["spec_index"], row["budget"], row["power"]
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ValueError("audit spec_index must be a nonnegative integer")
        if (
            isinstance(budget, bool)
            or not isinstance(budget, (int, float))
            or not math.isfinite(budget)
            or budget <= 0
        ):
            raise ValueError("audit budget must be finite and positive")
        if not isinstance(power, bool):
            raise ValueError("audit power must be a boolean")
        # The explicit reads preserve the original row, including consumer metrics.
        strategy, url_id, spec_label = row["strategy"], row["url_id"], row["spec_label"]
        assert isinstance(strategy, str) and isinstance(url_id, str) and isinstance(spec_label, str)
        key = AuditCellKey(strategy, url_id, index, spec_label, float(budget), power)
        if key in indexed:
            raise ValueError(f"duplicate audit cell: {key}")
        indexed[key] = row
    return indexed


def pair_audit_cells(
    baseline: Mapping[AuditCellKey, Mapping[str, object]],
    candidate: Mapping[AuditCellKey, Mapping[str, object]],
    *,
    treatment_fields: frozenset[str] = frozenset(),
) -> dict[AuditCellKey, AuditCellKey]:
    """Pair exact cells, allowing only explicitly declared treatment differences.

    Candidate-label treatments align the same candidate slot; ambiguity still
    fails. Returned keys retain BOTH actual labels, never a fabricated identity.
    Missing cells remain unpaired so each consumer can enforce its own coverage.
    """
    unknown = treatment_fields - TREATMENT_FIELDS
    if unknown:
        raise ValueError(f"unknown audit treatment fields: {sorted(unknown)}")
    # Reserve exact matches before considering a label treatment. Two full keys
    # may legitimately share a slot, and row order must not steal an exact peer.
    pairs = {key: key for key in candidate if key in baseline}
    if len(pairs) != len(candidate):
        baseline_slots: dict[AuditCellKey, list[AuditCellKey]] = {}
        for key in baseline:
            if key not in pairs:
                baseline_slots.setdefault(replace(key, spec_label=""), []).append(key)
        for key in candidate:
            if key in pairs:
                continue
            slot = replace(key, spec_label="")
            choices = baseline_slots.get(slot)
            if not choices:
                continue
            if len(choices) != 1:
                raise ValueError(f"incompatible audit candidate slot: {key}")
            base_key = choices[0]
            if "spec_label" not in treatment_fields:
                raise ValueError(f"incompatible audit candidate labels: {base_key} -> {key}")
            pairs[key] = base_key
            del baseline_slots[slot]
    for key, base_key in pairs.items():
        row, base_row = candidate[key], baseline[base_key]
        for field in _CONFIGURATION:
            if field not in base_row and field not in row:
                continue
            if field not in base_row or field not in row:
                raise ValueError(f"missing audit configuration field {field!r} for {key}")
            if field not in treatment_fields and base_row[field] != row[field]:
                raise ValueError(
                    f"incompatible audit {field} for {key}: {base_row[field]!r} -> {row[field]!r}"
                )
    return pairs
