"""Parse a FactorioLab URL into a typed :class:`LabRequest`.

This mirrors the read path of FactorioLab's ``RouterSync`` -- ``unzipObjectives``,
``unzipItems``, ``unzipRecipes``, ``unzipMachines``, ``unzipModules``,
``unzipBeacons`` and ``unzipSettings`` -- plus the parts of ``Migration.migrate``
that decide how a URL is encoded.

Two things here are easy to get wrong and worth stating plainly:

* **Bare vs hash is decided by the presence of ``z``, not by the version.**
  ``Migration.migrate`` computes ``isBare = params['z'] == null`` *before*
  anything else.  Inside a ``z`` payload every id is a base-64 index into
  ``hash.json``; in a bare URL ids are written out in full.

* **Range-encoded sets always need the mod hash.**  ``unzipSettings`` passes
  ``modHash`` (not the bare-conditional ``hash``) to ``parseSubset``, so
  ``iex``/``ich``/``rex``/``rch``/``tre``/``loc`` are positional indices even
  in an otherwise-bare URL.

Ids are left as plain strings.  Resolving them against ``data.json`` is the
job of :mod:`flab2bp.lab.data`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import IntEnum
from fractions import Fraction
from urllib.parse import unquote, urlparse

from flab2bp.lab import params as P
from flab2bp.lab.params import LabUrlError, ModHash

__all__ = [
    "BeaconSetting",
    "CostSettings",
    "DisplayRate",
    "ItemSetting",
    "LabRequest",
    "LabUrlError",
    "MachineSetting",
    "ModuleSetting",
    "Objective",
    "ObjectiveType",
    "ObjectiveUnit",
    "Preset",
    "UnsupportedDatasetError",
    "UnsupportedZipVersionError",
    "parse_url",
]

#: The only dataset this tool builds blueprints for.
DSP_MOD_ID = "dsp"

#: The only URL encoding version we read.  Porting the V0-V10 migration chain
#: (~1000 lines) would buy very little: FactorioLab rewrites the URL to V11 on
#: every navigation, so old links are re-shared as V11 almost immediately.
SUPPORTED_ZIP_VERSION = "11"

#: Repeatable params.  ``Migration.migrate`` coerces a lone string into a list.
_ARRAY_KEYS = ("o", "i", "r", "m", "e", "b")

#: Params whose values are range-encoded index sets.
_SUBSET_KEYS = ("och", "iex", "ich", "rex", "rch", "tre", "loc")


class ObjectiveUnit(IntEnum):
    Items = 0
    Belts = 1
    Wagons = 2
    Machines = 3


class ObjectiveType(IntEnum):
    Output = 0
    Input = 1
    Maximize = 2
    Limit = 3


class DisplayRate(IntEnum):
    PerSecond = 0
    PerMinute = 1
    PerHour = 2


class Preset(IntEnum):
    Minimum = 0
    Modules = 1
    Beacon8 = 2
    Beacon12 = 3


class UnsupportedZipVersionError(LabUrlError):
    """The URL uses an encoding version this tool does not read."""


class UnsupportedDatasetError(LabUrlError):
    """The URL is not for the Dyson Sphere Program dataset."""


@dataclass(frozen=True, slots=True)
class ModuleSetting:
    count: Fraction | None = None
    id: str | None = None


@dataclass(frozen=True, slots=True)
class BeaconSetting:
    count: Fraction | None = None
    modules: tuple[ModuleSetting, ...] | None = None
    id: str | None = None
    total: Fraction | None = None


@dataclass(frozen=True, slots=True)
class Objective:
    """One production target.

    ``target_id`` names an *item* unless ``unit`` is
    :attr:`ObjectiveUnit.Machines`, in which case it names a *recipe*.
    """

    id: str
    target_id: str
    value: Fraction = Fraction(1)
    unit: ObjectiveUnit = ObjectiveUnit.Items
    type: ObjectiveType = ObjectiveType.Output
    machine_id: str | None = None
    modules: tuple[ModuleSetting, ...] | None = None
    beacons: tuple[BeaconSetting, ...] | None = None
    overclock: Fraction | None = None
    fuel_id: str | None = None

    @property
    def is_recipe_objective(self) -> bool:
        return self.unit is ObjectiveUnit.Machines


@dataclass(frozen=True, slots=True)
class ItemSetting:
    belt_id: str | None = None
    wagon_id: str | None = None
    stack: Fraction | None = None
    exclude_rockets: bool | None = None


@dataclass(frozen=True, slots=True)
class RecipeSetting:
    machine_id: str | None = None
    modules: tuple[ModuleSetting, ...] | None = None
    beacons: tuple[BeaconSetting, ...] | None = None
    overclock: Fraction | None = None
    cost: Fraction | None = None
    fuel_id: str | None = None
    productivity: Fraction | None = None


@dataclass(frozen=True, slots=True)
class MachineSetting:
    modules: tuple[ModuleSetting, ...] | None = None
    beacons: tuple[BeaconSetting, ...] | None = None
    fuel_id: str | None = None
    overclock: Fraction | None = None


@dataclass(frozen=True, slots=True)
class CostSettings:
    factor: Fraction | None = None
    machine: Fraction | None = None
    footprint: Fraction | None = None
    unproduceable: Fraction | None = None
    excluded: Fraction | None = None
    surplus: Fraction | None = None
    maximize: Fraction | None = None
    recycling: Fraction | None = None


@dataclass(frozen=True, slots=True)
class LabRequest:
    """Everything a FactorioLab URL says, in typed form."""

    mod_id: str
    objectives: tuple[Objective, ...]

    items: dict[str, ItemSetting] = field(default_factory=dict)
    recipes: dict[str, RecipeSetting] = field(default_factory=dict)
    machines: dict[str, MachineSetting] = field(default_factory=dict)
    modules: tuple[ModuleSetting, ...] = ()
    beacons: tuple[BeaconSetting, ...] = ()

    # Objectives section
    checked_objective_ids: set[str] | None = None
    maximize_type: int | None = None
    require_machines_output: bool | None = None
    display_rate: DisplayRate = DisplayRate.PerMinute

    # Items section
    excluded_item_ids: set[str] | None = None
    checked_item_ids: set[str] | None = None
    belt_id: str | None = None
    pipe_id: str | None = None
    cargo_wagon_id: str | None = None
    fluid_wagon_id: str | None = None
    flow_rate: Fraction | None = None
    stack: Fraction | None = None

    # Recipes section
    excluded_recipe_ids: set[str] | None = None
    checked_recipe_ids: set[str] | None = None
    recipe_cost_multiplier: Fraction | None = None
    net_production_only: bool | None = None

    # Machines section
    preset: Preset | None = None
    machine_rank_ids: list[str] | None = None
    fuel_rank_ids: list[str] | None = None
    module_rank_ids: list[str] | None = None
    default_beacons: tuple[BeaconSetting, ...] | None = None
    overclock: Fraction | None = None
    beacon_receivers: Fraction | None = None
    proliferator_spray_id: str | None = None

    # Bonuses
    mining_bonus: Fraction | None = None
    research_bonus: Fraction | None = None
    research_productivity: Fraction | None = None
    researched_technology_ids: set[str] | None = None
    location_ids: set[str] | None = None

    costs: CostSettings = field(default_factory=CostSettings)

    # Provenance
    zip_version: str = SUPPORTED_ZIP_VERSION
    is_bare: bool = True
    source_url: str = ""


# --- query-string handling ---------------------------------------------------


def _split_query(query: str) -> dict[str, P.ParamValue]:
    """Decode a URL query the way a browser router does.

    Deliberately not :func:`urllib.parse.parse_qsl`: that applies
    form-encoding rules and turns ``+`` into a space, which would corrupt the
    legacy ``z`` payloads that still contain raw ``+``.  Browsers use
    ``decodeURIComponent``, which leaves ``+`` alone.
    """
    result: dict[str, P.ParamValue] = {}
    for section in query.split("&"):
        if not section:
            continue
        key, sep, raw = section.partition("=")
        value = unquote(raw) if sep else ""
        key = unquote(key)
        existing = result.get(key)
        if existing is None:
            result[key] = value
        elif isinstance(existing, list):
            existing.append(value)
        else:
            result[key] = [existing, value]
    return result


def _as_list(value: P.ParamValue | None) -> list[str]:
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def _scalar(params: Mapping[str, P.ParamValue], key: str) -> str | None:
    """A scalar param, taking the last value if the key was repeated."""
    value = params.get(key)
    if isinstance(value, list):
        return value[-1] if value else None
    return value


# --- record parsers ----------------------------------------------------------


def _parse_modules(
    params: Mapping[str, P.ParamValue], mh: ModHash | None
) -> tuple[ModuleSetting, ...]:
    out: list[ModuleSetting] = []
    for entry in _as_list(params.get("e")):
        f = P.split_fields(entry)
        out.append(
            ModuleSetting(
                count=P.parse_rational(_get(f, 0)),
                id=P.parse_string(_get(f, 1), mh.modules if mh else None),
            )
        )
    return tuple(out)


def _parse_beacons(
    params: Mapping[str, P.ParamValue],
    modules: tuple[ModuleSetting, ...],
    mh: ModHash | None,
) -> tuple[BeaconSetting, ...]:
    out: list[BeaconSetting] = []
    for entry in _as_list(params.get("b")):
        f = P.split_fields(entry)
        out.append(
            BeaconSetting(
                count=P.parse_rational(_get(f, 0)),
                modules=_indices(_get(f, 1), modules, ModuleSetting),
                id=P.parse_string(_get(f, 2), mh.beacons if mh else None),
                total=P.parse_rational(_get(f, 3)),
            )
        )
    return tuple(out)


def _parse_objectives(
    params: Mapping[str, P.ParamValue],
    modules: tuple[ModuleSetting, ...],
    beacons: tuple[BeaconSetting, ...],
    mh: ModHash | None,
) -> tuple[Objective, ...]:
    out: list[Objective] = []
    for index, entry in enumerate(_as_list(params.get("o")), start=1):
        f = P.split_fields(entry)
        target_id = _get(f, 0) or ""
        unit_raw = P.parse_number(_get(f, 2))
        unit = ObjectiveUnit(int(unit_raw)) if unit_raw is not None else ObjectiveUnit.Items
        type_raw = P.parse_number(_get(f, 3))
        obj_type = ObjectiveType(int(type_raw)) if type_raw is not None else ObjectiveType.Output

        if mh is not None:
            table = mh.recipes if unit is ObjectiveUnit.Machines else mh.items
            target_id = P.parse_n_string(target_id, table) or ""

        out.append(
            Objective(
                id=str(index),
                target_id=target_id,
                value=P.parse_rational(_get(f, 1)) or Fraction(1),
                unit=unit,
                type=obj_type,
                machine_id=P.parse_string(_get(f, 4), mh.machines if mh else None),
                modules=_indices(_get(f, 5), modules, ModuleSetting),
                beacons=_indices(_get(f, 6), beacons, BeaconSetting),
                overclock=P.parse_rational(_get(f, 7)),
                fuel_id=P.parse_string(_get(f, 8), mh.fuels if mh else None),
            )
        )
    return tuple(out)


def _parse_items(params: Mapping[str, P.ParamValue], mh: ModHash | None) -> dict[str, ItemSetting]:
    out: dict[str, ItemSetting] = {}
    for entry in _as_list(params.get("i")):
        f = P.split_fields(entry)
        key = P.parse_string(_get(f, 0), mh.items if mh else None) or ""
        out[key] = ItemSetting(
            belt_id=P.parse_string(_get(f, 1), mh.belts if mh else None),
            wagon_id=P.parse_string(_get(f, 2), mh.wagons if mh else None),
            stack=P.parse_rational(_get(f, 3)),
            exclude_rockets=P.parse_bool(_get(f, 4)),
        )
    return out


def _parse_recipes(
    params: Mapping[str, P.ParamValue],
    modules: tuple[ModuleSetting, ...],
    beacons: tuple[BeaconSetting, ...],
    mh: ModHash | None,
) -> dict[str, RecipeSetting]:
    out: dict[str, RecipeSetting] = {}
    for entry in _as_list(params.get("r")):
        f = P.split_fields(entry)
        key = P.parse_string(_get(f, 0), mh.recipes if mh else None) or ""
        out[key] = RecipeSetting(
            machine_id=P.parse_string(_get(f, 1), mh.machines if mh else None),
            modules=_indices(_get(f, 2), modules, ModuleSetting),
            beacons=_indices(_get(f, 3), beacons, BeaconSetting),
            overclock=P.parse_rational(_get(f, 4)),
            cost=P.parse_rational(_get(f, 5)),
            fuel_id=P.parse_string(_get(f, 6), mh.fuels if mh else None),
            productivity=P.parse_rational(_get(f, 7)),
        )
    return out


def _parse_machines(
    params: Mapping[str, P.ParamValue],
    modules: tuple[ModuleSetting, ...],
    beacons: tuple[BeaconSetting, ...],
    mh: ModHash | None,
) -> dict[str, MachineSetting]:
    out: dict[str, MachineSetting] = {}
    for entry in _as_list(params.get("m")):
        f = P.split_fields(entry)
        key = P.parse_string(_get(f, 0), mh.machines if mh else None) or ""
        out[key] = MachineSetting(
            modules=_indices(_get(f, 1), modules, ModuleSetting),
            beacons=_indices(_get(f, 2), beacons, BeaconSetting),
            fuel_id=P.parse_string(_get(f, 3), mh.fuels if mh else None),
            overclock=P.parse_rational(_get(f, 4)),
        )
    return out


def _get(fields: list[str], index: int) -> str | None:
    """Field *index*, or ``None`` if it was stripped as a trailing empty."""
    return fields[index] if index < len(fields) else None


def _indices[T](
    value: str | None,
    arr: Sequence[T],
    empty: Callable[[], T],
) -> tuple[T, ...] | None:
    parsed = P.parse_indices(value, arr, empty=empty)
    return None if parsed is None else tuple(parsed)


# --- entry point -------------------------------------------------------------


def parse_url(url: str, *, mod_hash: ModHash | None = None) -> LabRequest:
    """Parse a FactorioLab DSP URL.

    :param mod_hash: override the vendored ``hash.json`` (for tests).
    :raises UnsupportedDatasetError: the URL is not for the DSP dataset.
    :raises UnsupportedZipVersionError: the URL predates encoding version 11.
    :raises LabUrlError: the URL is malformed or its payload cannot be decoded.
    """
    parsed = urlparse(url)
    segments = [s for s in parsed.path.split("/") if s]
    if not segments:
        raise UnsupportedDatasetError(
            f"no dataset in URL path {parsed.path!r}; expected a {DSP_MOD_ID!r} path "
            f"such as https://factoriolab.github.io/{DSP_MOD_ID}/flow?..."
        )
    mod_id = segments[0]
    if mod_id != DSP_MOD_ID:
        raise UnsupportedDatasetError(
            f"dataset {mod_id!r} is not supported; this tool builds Dyson Sphere "
            f"Program blueprints and needs a {DSP_MOD_ID!r} URL"
        )

    raw = _split_query(parsed.query)

    # `Migration.migrate` decides bare-vs-hash from the *original* params.
    zipped = _scalar(raw, "z")
    is_bare = zipped is None

    if zipped is not None:
        params: dict[str, P.ParamValue] = dict(P.to_params(P.inflate_query_value(zipped)))
        params["z"] = zipped
    else:
        params = dict(raw)

    version = _scalar(params, "v") or "0"
    if version != SUPPORTED_ZIP_VERSION:
        raise UnsupportedZipVersionError(
            f"URL uses encoding version {version!r}; only version "
            f"{SUPPORTED_ZIP_VERSION!r} is supported. Open the link in "
            f"FactorioLab and copy the refreshed URL, which will be v"
            f"{SUPPORTED_ZIP_VERSION}."
        )

    if is_bare:
        # FactorioLab decodes bare params a second time; harmless for the
        # kebab-case ids DSP uses, and it matches upstream behaviour.
        params = {
            k: ([unquote(x) for x in v] if isinstance(v, list) else unquote(v))
            for k, v in params.items()
        }

    for key in _ARRAY_KEYS:
        value = params.get(key)
        if isinstance(value, str):
            params[key] = [value]

    # The hash tables are needed for *any* range-encoded set, and for every id
    # inside a compressed payload.
    needs_hash = not is_bare or any(_scalar(params, k) for k in _SUBSET_KEYS)
    tables = mod_hash if mod_hash is not None else (P.load_mod_hash(mod_id) if needs_hash else None)
    #: Only compressed URLs hash their *ids*; subsets index positionally regardless.
    id_hash = tables if not is_bare else None

    modules = _parse_modules(params, id_hash)
    beacons = _parse_beacons(params, modules, id_hash)
    objectives = _parse_objectives(params, modules, beacons, id_hash)
    if not objectives:
        raise ValueError(
            "URL contains no objective (`o` parameter); nothing to build a blueprint for"
        )

    def sub(key: str, table: list[str | None] | None) -> set[str] | None:
        if table is None:
            return None
        return P.parse_subset(_scalar(params, key), table)

    def rat(key: str) -> Fraction | None:
        return P.parse_rational(_scalar(params, key))

    def num(key: str) -> int | None:
        value = P.parse_number(_scalar(params, key))
        return None if value is None else int(value)

    display_rate_raw = num("odr")
    preset_raw = num("mpr")

    return LabRequest(
        mod_id=mod_id,
        objectives=objectives,
        items=_parse_items(params, id_hash),
        recipes=_parse_recipes(params, modules, beacons, id_hash),
        machines=_parse_machines(params, modules, beacons, id_hash),
        modules=modules,
        beacons=beacons,
        checked_objective_ids=P.parse_subset(_scalar(params, "och"), [o.id for o in objectives]),
        maximize_type=num("omt"),
        require_machines_output=P.parse_bool(_scalar(params, "orm")),
        display_rate=(
            DisplayRate(display_rate_raw) if display_rate_raw is not None else DisplayRate.PerMinute
        ),
        excluded_item_ids=sub("iex", tables.items if tables else None),
        checked_item_ids=sub("ich", tables.items if tables else None),
        belt_id=P.parse_string(_scalar(params, "ibe"), id_hash.belts if id_hash else None),
        pipe_id=P.parse_string(_scalar(params, "ipi"), id_hash.belts if id_hash else None),
        cargo_wagon_id=P.parse_string(_scalar(params, "icw"), id_hash.wagons if id_hash else None),
        fluid_wagon_id=P.parse_string(_scalar(params, "ifw"), id_hash.wagons if id_hash else None),
        flow_rate=rat("ifr"),
        stack=rat("ist"),
        excluded_recipe_ids=sub("rex", tables.recipes if tables else None),
        checked_recipe_ids=sub("rch", tables.recipes if tables else None),
        recipe_cost_multiplier=rat("rcm"),
        net_production_only=P.parse_bool(_scalar(params, "rnp")),
        preset=Preset(preset_raw) if preset_raw is not None else None,
        machine_rank_ids=P.parse_array(
            _scalar(params, "mmr"), id_hash.machines if id_hash else None
        ),
        fuel_rank_ids=P.parse_array(_scalar(params, "mfr"), id_hash.fuels if id_hash else None),
        module_rank_ids=P.parse_array(_scalar(params, "mer"), id_hash.modules if id_hash else None),
        default_beacons=_indices(_scalar(params, "mbe"), beacons, BeaconSetting),
        overclock=rat("moc"),
        beacon_receivers=rat("mbr"),
        proliferator_spray_id=P.parse_string(
            _scalar(params, "mps"), id_hash.modules if id_hash else None
        ),
        mining_bonus=rat("bmi"),
        research_bonus=rat("bre"),
        research_productivity=rat("brp"),
        researched_technology_ids=sub("tre", tables.technologies if tables else None),
        location_ids=sub("loc", tables.locations if tables else None),
        costs=CostSettings(
            factor=rat("cfa"),
            machine=rat("cma"),
            footprint=rat("cfp"),
            unproduceable=rat("cun"),
            excluded=rat("cex"),
            surplus=rat("csu"),
            maximize=rat("cmx"),
            recycling=rat("cre"),
        ),
        zip_version=version,
        is_bare=is_bare,
        source_url=url,
    )
