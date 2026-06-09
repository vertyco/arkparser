"""
Legacy-parity JSON export for ARK save data.

Produces dicts matching the C# ``ASVExport.exe`` output schema for the seven
canonical exports:

- Tamed creatures (``ASV_Tamed``)
- Wild creatures (``ASV_Wild``)
- Players (``ASV_Players``)
- Tribes (``ASV_Tribes``)
- Structures (``ASV_Structures``)
- Tribe logs (``ASV_TribeLogs``)
- Map structures (``ASV_MapStructures``)

Each ``export_*`` function reads directly from ``GameObject`` (or the relevant
file parser) and returns a flat dict matching the legacy keys.

Parser-only fields (data the legacy exporter could not produce) are added
alongside the legacy keys with their own descriptive names (no namespace
prefix). The full per-export field list is documented in ``README.md``.

Performance:

- ``WorldSave``-level export functions share a single object-lookup dict
  built once per ``WorldSave`` via :func:`_save_lookup`. Subsequent calls in
  the same export run reuse it instead of rebuilding (key win on maps with
  50k+ objects).
- Status / inventory component pointers are resolved once per creature and
  reused across the export shape.
"""

from __future__ import annotations

import datetime as dt
import functools
import itertools
import json
import logging
import math
import re
import typing as t
from pathlib import Path

from arkparser.common.exceptions import ArkParseError
from arkparser.common.map_config import MapConfig
from arkparser.common.normalization import normalize_indexed_data, normalize_indexed_list
from arkparser.data_models import CryopodCreature
from arkparser.files import CloudInventory, Profile, Tribe

logger = logging.getLogger(__name__)

_CRYOPOD_CLASS_PATTERNS: tuple[str, ...] = (
    "Cryopod",
    "SoulTrap",
    "Vivarium",
    "DinoBall",
)


def _is_cryopod_class(class_name: str) -> bool:
    return any(p in class_name for p in _CRYOPOD_CLASS_PATTERNS)


def _decode_inventory_cryopod(item_obj: t.Any) -> CryopodCreature | None:
    """Decode the dino blob embedded in an inventory-stored cryopod item.

    Cryopod items carry the serialized creature snapshot in ``CustomItemDatas``
    (byte-blob form on ASE, structured-dict form on ASA). Returns ``None`` for
    empty cryopods or unrecognized payloads. Mirrors the logic in
    :meth:`WorldSave.iter_cryopod_creatures` but operates on a single item
    object so we can decode cryopods discovered inside other containers
    (cryofridges, vaults, dedicated storage, etc.).
    """
    custom_datas_raw = item_obj.get_property_value("CustomItemDatas")
    if custom_datas_raw is None:
        return None
    custom_datas = normalize_indexed_list(custom_datas_raw)
    for entry in custom_datas:
        if not isinstance(entry, dict) or entry.get("CustomDataName") != "Dino":
            continue
        cryo_bytes_wrapper = normalize_indexed_data(entry.get("CustomDataBytes", {}))
        if isinstance(cryo_bytes_wrapper, dict):
            byte_arrays = normalize_indexed_list(cryo_bytes_wrapper.get("ByteArrays"))
            if byte_arrays and isinstance(byte_arrays[0], dict) and "Bytes" in byte_arrays[0]:
                cryo = CryopodCreature.from_cryopod_bytes(byte_arrays[0]["Bytes"])
                if cryo is not None:
                    strings = normalize_indexed_list(entry.get("CustomDataStrings"))
                    if len(strings) > 9 and strings[9]:
                        cryo.species = strings[9]
                    return cryo
        if entry.get("CustomDataStrings"):
            cryo = CryopodCreature.from_asa_cryopod_data(entry)
            if cryo is not None:
                return cryo
    return None


def _cryo_summary(cryo: t.Any) -> tuple[int, str, str] | None:
    """Distill a decoded cryopod to the (dino_id, creature, name) fields an
    inventory entry displays. ``None`` for empty/undecodable pods."""
    if cryo is None:
        return None
    props = getattr(cryo, "creature_props", {}) or {}
    id1 = props.get("DinoID1", props.get("DinoID1_0", 0))
    id2 = props.get("DinoID2", props.get("DinoID2_0", 0))
    dino_id = _combine_dino_id(id1, id2) or 0
    creature = str(getattr(cryo, "species", "") or getattr(cryo, "class_name", "") or "")
    name = str(props.get("TamedName") or props.get("TamedName_0") or "")
    return (dino_id, creature, name)


def _cryo_summary_cache(save: t.Any) -> dict[int, tuple[int, str, str] | None] | None:
    """The save's pod-summary cache, or ``None`` for saves without one.

    The tamed pass fully decodes every pod for its ASV_Tamed record and
    stores the summary here; inventory listings (structures, pawns, map
    terminals) read it instead of re-decoding the blob.
    """
    cache = getattr(save, "_cryo_summaries", None)
    return cache if isinstance(cache, dict) else None


_RICH_COLOR_RE = re.compile(r"<RichColor[^>]*>|</>")
_LOG_RE = re.compile(r"Day\s+(\d+),?\s+([\d:]+):\s*(.*)", re.DOTALL)

_STAT_NAMES: tuple[str, ...] = (
    "hp",
    "stam",
    "torp",
    "oxy",
    "food",
    "water",
    "temp",
    "weight",
    "melee",
    "speed",
    "fort",
    "craft",
)
_STAT_INDEX: dict[str, int] = {name: i for i, name in enumerate(_STAT_NAMES)}
# Legacy ASVExport keeps stats in this order in JSON; the trailing four were
# never emitted by legacy and are appended after the legacy block.
_LEGACY_STAT_ORDER: tuple[str, ...] = (
    "hp",
    "stam",
    "melee",
    "weight",
    "speed",
    "food",
    "oxy",
    "craft",
)
_EXTRA_STAT_ORDER: tuple[str, ...] = ("torp", "water", "temp", "fort")
_FLAT_STAT_ORDER: tuple[str, ...] = _LEGACY_STAT_ORDER + _EXTRA_STAT_ORDER


def _prop(obj: t.Any, name: str, default: t.Any = None, index: int | None = None) -> t.Any:
    if obj is None:
        return default
    if index is None:
        return obj.get_property_value(name, default=default)
    return obj.get_property_value(name, default=default, index=index)


def _int(val: t.Any, default: int = 0) -> int:
    if val is None or val is False:
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _float(val: t.Any, default: float = 0.0) -> float:
    if val is None or val is False:
        return default
    try:
        result = float(val)
    except (TypeError, ValueError):
        return default
    # inf/nan (corrupt or extreme bit patterns) are not valid JSON tokens and
    # crash strict downstream parsers (JS JSON.parse, Pydantic). Coerce to default.
    return result if math.isfinite(result) else default


def _str(val: t.Any) -> str:
    """Coerce to stripped string. Empty for falsy values."""
    if val is None or val is False:
        return ""
    return str(val).strip()


# Empty defaults that get pruned from parser-added fields. Legacy keys
# (preserved via LEGACY_*_KEYS frozensets below) are emitted unconditionally
# so ASVExport-schema consumers never see a missing key.
_EMPTY_DEFAULTS: tuple[t.Any, ...] = (None, "", 0, 0.0, False, [])


def _compact(data: dict[str, t.Any], legacy: frozenset[str]) -> dict[str, t.Any]:
    """Drop parser-added keys whose value is an ARK-default empty.

    Keys in ``legacy`` are kept regardless of value (ASVExport.exe schema
    parity). Everything else is dropped when the value is ``None``, an empty
    string, an empty list, ``False``, or numeric zero.
    """
    return {k: v for k, v in data.items() if k in legacy or v not in _EMPTY_DEFAULTS}


LEGACY_TAMED_KEYS: frozenset[str] = frozenset(
    {
        "id",
        "tribeid",
        "tribe",
        "tamer",
        "imprinter",
        "imprint",
        "creature",
        "name",
        "sex",
        "base",
        "lvl",
        "lat",
        "lon",
        "hp-w",
        "stam-w",
        "melee-w",
        "weight-w",
        "speed-w",
        "food-w",
        "oxy-w",
        "craft-w",
        "hp-t",
        "stam-t",
        "melee-t",
        "weight-t",
        "speed-t",
        "food-t",
        "oxy-t",
        "craft-t",
        "c0",
        "c1",
        "c2",
        "c3",
        "c4",
        "c5",
        "mut-f",
        "mut-m",
        "cryo",
        "ccc",
        "dinoid",
        "isMating",
        "isNeutered",
        "isClone",
        "tamedServer",
        "uploadedServer",
        "maturation",
        "traits",
        "inventory",
    }
)
LEGACY_WILD_KEYS: frozenset[str] = frozenset(
    {
        "id",
        "creature",
        "sex",
        "lvl",
        "lat",
        "lon",
        "hp",
        "stam",
        "melee",
        "weight",
        "speed",
        "food",
        "oxy",
        "craft",
        "c0",
        "c1",
        "c2",
        "c3",
        "c4",
        "c5",
        "ccc",
        "dinoid",
        "tameable",
        "trait",
    }
)
LEGACY_PLAYER_KEYS: frozenset[str] = frozenset(
    {
        "playerid",
        "steam",
        "name",
        "tribeid",
        "tribe",
        "sex",
        "lvl",
        "lat",
        "lon",
        "hp",
        "stam",
        "melee",
        "weight",
        "speed",
        "food",
        "water",
        "oxy",
        "craft",
        "fort",
        "active",
        "ccc",
        "achievements",
        "inventory",
        "netAddress",
        "steamid",
        "dataFile",
    }
)
LEGACY_TRIBE_KEYS: frozenset[str] = frozenset(
    {
        "tribeid",
        "tribe",
        "players",
        "members",
        "tames",
        "uploadedTames",
        "structures",
        "active",
        "dataFile",
    }
)
LEGACY_STRUCT_KEYS: frozenset[str] = frozenset(
    {
        "id",
        "tribeid",
        "tribe",
        "struct",
        "name",
        "locked",
        "created",
        "inventory",
        "lat",
        "lon",
        "ccc",
        "isSwitchedOn",
    }
)
LEGACY_MAP_STRUCT_KEYS: frozenset[str] = frozenset(
    {
        "struct",
        "inventory",
        "lat",
        "lon",
        "ccc",
    }
)


def _stat_array(status: t.Any, prop_name: str) -> list[int]:
    if status is None:
        return [0] * 12
    out = [0] * 12
    getter = getattr(status, "get_properties_by_name", None)
    if callable(getter):
        for prop in getter(prop_name):
            idx = getattr(prop, "index", 0)
            if 0 <= idx < 12:
                out[idx] = _int(getattr(prop, "value", 0))
        return out
    for i in range(12):
        out[i] = _int(_prop(status, prop_name, default=0, index=i))
    return out


def _current_stat_floats(status: t.Any) -> list[float] | None:
    """Read ``CurrentStatusValues[0..11]`` from a character status component.

    Status components persist the live in-world values of all 12 stats. The
    array is indexed by ARK's ``EPrimalCharacterStatusValue`` enum:
    0=hp, 1=stam, 2=torpor, 3=oxy, 4=food, 5=water, 6=temp, 7=weight,
    8=melee, 9=speed, 10=temp-fortitude, 11=crafting.

    Returns ``None`` when the status component is missing or carries no
    CurrentStatusValues entries (e.g. uninitialised baby actor) so callers
    can distinguish "no data" from "all zeros".
    """
    if status is None:
        return None
    out: list[float] = [0.0] * 12
    seen = False
    getter = getattr(status, "get_properties_by_name", None)
    if callable(getter):
        # Real GameObject: get_properties_by_name surfaces every indexed
        # entry. Empty result == component carries no CurrentStatusValues
        # at all (uninitialised); return None so callers can distinguish
        # "no data" from "all zeros".
        for prop in getter("CurrentStatusValues"):
            idx = getattr(prop, "index", 0)
            if 0 <= idx < 12:
                out[idx] = _float(getattr(prop, "value", 0.0))
                seen = True
        return out if seen else None
    # Synthetic / cryopod stand-in: per-index get_property_value lookups.
    for i in range(12):
        val = _prop(status, "CurrentStatusValues", default=None, index=i)
        if val is not None:
            out[i] = _float(val)
            seen = True
    return out if seen else None


def _current_stats_dict(status: t.Any) -> dict[str, float] | None:
    """Return current stat values keyed by short stat name.

    Pre-conditions: ``status`` is the character status component (creature or
    player). May be ``None`` (e.g. offline player with no spawned pawn).
    Post-conditions: returns a dict ``{hp, stam, ..., craft}`` of floats, or
    ``None`` when no CurrentStatusValues are persisted on the component.
    """
    floats = _current_stat_floats(status)
    if floats is None:
        return None
    return {_STAT_NAMES[i]: floats[i] for i in range(12)}


def _flat_stats(points: list[int], suffix: str = "") -> dict[str, int]:
    """Emit all 12 stats as a flat dict.

    With ``suffix`` (``"w"`` / ``"t"`` / ``"m"``) emits ``hp-{suffix}`` â€¦
    ``fort-{suffix}``. Without a suffix emits unsuffixed legacy wild keys
    (``hp``, ``stam``, â€¦). The legacy ASVExport 8-stat block (hp, stam,
    melee, weight, speed, food, oxy, craft) is emitted first to preserve
    legacy diff order; the four stats legacy never surfaced (torp, water,
    temp, fort) are appended at the end.
    """
    sep = "-" if suffix else ""
    return {f"{name}{sep}{suffix}": points[_STAT_INDEX[name]] for name in _FLAT_STAT_ORDER}


def _gps_payload(
    obj: t.Any,
    map_config: MapConfig | None,
    ndigits: int | None = 2,
) -> dict[str, t.Any]:
    """Return ``ccc`` / ``lat`` / ``lon`` keys for a GameObject.

    ``ndigits`` rounds each ccc component and lat/lon to that many decimals.
    Defaults to ``2`` (matches legacy ASVExport's typical precision; passing
    ``None`` disables rounding).
    """
    loc = getattr(obj, "location", None)
    if loc is None:
        return {"ccc": "0 0 0", "lat": 0.0, "lon": 0.0}
    # _float coerces non-finite (inf/nan) coords to 0.0; those are invalid
    # JSON tokens that crash strict downstream parsers.
    x = _float(getattr(loc, "x", 0.0))
    y = _float(getattr(loc, "y", 0.0))
    z = _float(getattr(loc, "z", 0.0))
    if ndigits is not None:
        x = round(x, ndigits)
        y = round(y, ndigits)
        z = round(z, ndigits)
    out: dict[str, t.Any] = {"ccc": f"{x} {y} {z}"}
    if map_config is not None:
        lat = _float(map_config.ue_to_lat(y))
        lon = _float(map_config.ue_to_lon(x))
        if ndigits is not None:
            lat = round(lat, ndigits)
            lon = round(lon, ndigits)
        out["lat"] = lat
        out["lon"] = lon
    else:
        out["lat"] = 0.0
        out["lon"] = 0.0
    return out


def _approx_real_datetime(
    in_game_time: t.Any,
    save: t.Any,
) -> dt.datetime | None:
    """Mirror legacy ContentContainer.GetApproxDateTimeOf.

    Returns the real-world datetime for an ``OriginalCreationTime`` /
    ``TamedAtTime``-style in-game seconds value, computed as::

        save.file_mtime + (in_game_time - save.game_time)

    Returns ``None`` if the conversion can't be made (no mtime, no game
    time, or non-numeric input).
    """
    if not in_game_time:
        return None
    mtime: dt.datetime | None = getattr(save, "file_mtime", None) if save else None
    if mtime is None:
        return None
    game_time = _float(getattr(save, "game_time", 0.0)) if save else 0.0
    if game_time <= 0:
        return None
    try:
        offset = float(in_game_time) - game_time
        return mtime + dt.timedelta(seconds=offset)
    except (TypeError, ValueError, OverflowError, OSError):
        # Mirror legacy GetApproxDateTimeOf's try/catch: a garbage/huge in-game
        # time overflows datetime arithmetic; legacy returns null, so do we.
        return None


def _combine_dino_id(id1: t.Any, id2: t.Any) -> int:
    a, b = _int(id1), _int(id2)
    if a == 0 and b == 0:
        return 0
    return (a << 32) | (b & 0xFFFFFFFF)


def _dino_id_str(id1: t.Any, id2: t.Any, is_asa: bool) -> str:
    """Legacy ``dinoid`` string form (engine-dependent).

    ASA emits the decimal of the combined 64-bit id (legacy
    ``ContentCreature.cs:224`` ``DinoId = Id.ToString()``). ASE concatenates the
    two id halves as *signed* int32 decimals (legacy ``ContentCreature.cs:378``
    ``DinoID1.ToString() + DinoID2.ToString()``, where ``GetPropertyValue<int>``
    reinterprets each stored uint32 as a signed int). The forms differ, so the
    engine must be known; passing the wrong flag re-introduces the divergence.
    """
    assert isinstance(is_asa, bool), "is_asa must be bool"
    a, b = _int(id1), _int(id2)
    if a == 0 and b == 0:
        return "0"
    if is_asa:
        return str((a << 32) | (b & 0xFFFFFFFF))
    a32 = a & 0xFFFFFFFF
    b32 = b & 0xFFFFFFFF
    a32 = a32 - 0x100000000 if a32 & 0x80000000 else a32
    b32 = b32 - 0x100000000 if b32 & 0x80000000 else b32
    result = f"{a32}{b32}"
    assert result, "dinoid string must be non-empty"
    return result


def _colors(obj: t.Any) -> list[int]:
    out = [0] * 6
    getter = getattr(obj, "get_properties_by_name", None)
    if callable(getter):
        for prop in getter("ColorSetIndices"):
            idx = getattr(prop, "index", 0)
            if 0 <= idx < 6:
                out[idx] = _int(getattr(prop, "value", 0))
        return out
    for i in range(6):
        out[i] = _int(_prop(obj, "ColorSetIndices", default=0, index=i))
    return out


def _ancestor_parent(obj: t.Any, prefix: str) -> tuple[int | None, str]:
    """Extract parent dino_id + name from the first DinoAncestors entry."""
    ancestors = _prop(obj, "DinoAncestors")
    if not isinstance(ancestors, list) or not ancestors:
        return None, ""
    first = ancestors[0]
    if not isinstance(first, dict):
        return None, ""
    id1 = first.get(f"{prefix}DinoID1", 0)
    id2 = first.get(f"{prefix}DinoID2", 0)
    combined = _combine_dino_id(id1, id2) if (id1 or id2) else None
    name = first.get(f"{prefix}Name", "") or first.get("DinoName", "") or ""
    return combined, str(name).strip()


def _traits(obj: t.Any) -> list[str]:
    """Tamed/wild creature trait list (mutation traits, ASA + late ASE)."""
    val = _prop(obj, "CreatureTraits")
    if isinstance(val, list):
        return [str(v).strip() for v in val if v]
    getter = getattr(obj, "get_properties_by_name", None)
    if callable(getter):
        return [str(p.value).strip() for p in getter("CreatureTraits") if p.value]
    return []


def _save_lookup(save: t.Any) -> dict[t.Any, t.Any]:
    """Return cached id/guid/name â†’ GameObject lookup, building once per save."""
    cached = getattr(save, "_export_lookup", None)
    if isinstance(cached, dict):
        return cached
    objects = getattr(save, "objects", None) or []
    iterable = objects.values() if isinstance(objects, dict) else objects
    result: dict[t.Any, t.Any] = {}
    for obj in iterable:
        oid = getattr(obj, "id", None)
        guid = getattr(obj, "guid", None)
        names = getattr(obj, "names", None) or ()
        if oid is not None:
            result[oid] = obj
        if guid:
            result[guid] = obj
        for nm in names:
            result[nm] = obj
    try:
        save._export_lookup = result
    except (AttributeError, TypeError):
        pass
    return result


def _ref_name(ref: t.Any) -> t.Any:
    """Best-effort identifier for an object reference property value.

    Object refs in the parser come through as ``(class_name, key)`` tuples;
    the key is either a numeric GameObject id (matches ``GameObject.id``)
    or a string name / blueprint path. Numeric ids are returned as ``int``
    so they cross-reference cleanly against the structures export's ``id``
    field. String keys are returned as ``str``. Empty / ``None`` â†’ ``""``.
    """
    if ref is None or ref == "":
        return ""
    if isinstance(ref, tuple) and len(ref) == 2:
        val = ref[1]
        return val if isinstance(val, int) else str(val)
    return ref if isinstance(ref, int) else str(ref)


def _ref_list(val: t.Any) -> list[t.Any]:
    """Resolve a list of object refs to ids/names (used by LinkedStructures, etc.)."""
    if not isinstance(val, list):
        return []
    return [name for name in (_ref_name(v) for v in val) if name != ""]


def _saddle_structure_refs(val: t.Any) -> list[str]:
    """Extract the ``MyStructure`` ref from each entry of ``SaddleStructures``.

    Each entry is a struct with relative-location + bone-name + a structure
    object reference. Only the reference is useful for cross-linking, so
    drop the rest to keep export size sane.
    """
    if not isinstance(val, list):
        return []
    out: list[str] = []
    for entry in val:
        if isinstance(entry, dict):
            ref = entry.get("MyStructure")
            if ref:
                out.append(_ref_name(ref))
    return out


def _pin_code(obj: t.Any) -> int:
    """Return the active PIN code (or ``0`` for "no PIN").

    ARK serializes PINs in two forms; only one is ever populated:

    - ``CurrentPinCode`` (singular): a scalar carrying the actual code.
      This is where every observed non-zero PIN lives on real saves.
    - ``CurrentPinCodes`` (plural): an ``ArrayProperty`` of ints. In
      practice this is always zero-filled across every reference dump
      (ASE + Primitive+); historical PINs from earlier ARK versions are
      not persisted. The plural form is checked as a fallback only.

    Returns ``0`` (pruned by ``_compact``) when no PIN is set.

    Note: PIN codes are sensitive credentials. Exposed for tribe-admin
    auditing and inventory recovery; downstream tooling should not surface
    them to non-tribe players.
    """
    singular = _int(_prop(obj, "CurrentPinCode"))
    if singular:
        return singular
    raw = _prop(obj, "CurrentPinCodes")
    if isinstance(raw, list):
        for v in raw:
            i = _int(v)
            if i:
                return i
    elif isinstance(raw, dict):
        for k in sorted(k for k in raw if isinstance(k, int)):
            i = _int(raw[k])
            if i:
                return i
    elif raw:
        return _int(raw)
    return 0


def _harvest_levels(val: t.Any) -> list[int]:
    """Flatten ``HarvestResourceLevels`` into a list of ints.

    Returns ``[]`` (pruned by ``_compact``) when every level is zero.
    """
    if isinstance(val, list):
        out = [_int(v) for v in val]
    elif isinstance(val, dict):
        out = [_int(val[k]) for k in sorted(k for k in val if isinstance(k, int))]
    else:
        return []
    return out if any(out) else []


def _iso_pair(obj: t.Any, prop_name: str, save: t.Any) -> tuple[float, str | None]:
    """Return ``(seconds, iso)`` for an in-game-time property.

    ``seconds`` is the raw float (0.0 if missing/non-numeric); ``iso`` is the
    converted ISO 8601 datetime via :func:`_approx_real_datetime`, or
    ``None`` when the conversion can't be made (no anchor, zero value).
    """
    raw = _float(_prop(obj, prop_name))
    if not raw:
        return raw, None
    d = _approx_real_datetime(raw, save)
    return raw, d.isoformat() if d is not None else None


def _resolve(ref: t.Any, lookup: dict[t.Any, t.Any]) -> t.Any:
    if ref is None:
        return None
    if isinstance(ref, tuple) and len(ref) == 2:
        return lookup.get(ref[1])
    return lookup.get(ref)


def _drain_lazy(save: t.Any) -> None:
    """Release every lazily-materialized property block since the last drain.

    No-op for eager saves (and wrapper objects without the method). Called by
    record iterators and full-graph walks after each visited record so a lazy
    save's resident property set stays bounded to the current working set:
    eviction is always correctness-safe because a later access re-materializes.
    """
    if (
        getattr(save, "_lazy_reader", None) is None
        and getattr(save, "_lazy_conn", None) is None
    ):
        return
    drain = getattr(save, "evict_materialized", None)
    if callable(drain):
        _ = drain()  # eviction count is RAM bookkeeping only


# Per-record-kind property whitelists for partial decodes on ASA v14+ lazy
# saves. Collected empirically (references/scripts/collect_names_by_kind
# .py instruments every getter read during full eager exports) and
# self-correcting: a getter read outside the set transparently upgrades the
# object to a full decode (GameObject._ensure_name), so a missing entry costs
# one extra parse, never output. Keep sorted for diffability.
_STRUCTURE_RECORD_NAMES: frozenset[str] = frozenset({
    "AttachedToDinoID1", "AttachedToDinoID2", "BabyCuddleFood", "BabyCuddleType",
    "BabyNextCuddleTime", "BoxName", "ColorSetIndices", "CreatureTraits",
    "CurrentItemCount", "CurrentPinCode", "CurrentPinCodes", "CurrentVariant",
    "DinoAncestors", "DinoDownloadedAtTime", "DinoFeedingListType", "DinoID1",
    "DinoID2", "FeedingDinoList", "FollowStoppingDistance", "HarvestResourceLevels",
    "Health", "ImprinterName", "ImprinterPlayerDataID", "ImprinterPlayerUniqueNetId",
    "IsInCryo", "IsInVivarium", "ItemColorID", "ItemQuantity", "ItemStatValues",
    "LastActivatedTime", "LastCheckedFuelTime", "LastDeactivatedTime",
    "LastEnterStasisTime", "LastFireTime", "LastInAllyRangeSerialized",
    "LastInAllyRangeTime", "LastInAllyRangeTimeSerialized", "LastLongReloadStartTime",
    "LastUpdatedBabyAgeAtTime", "LastUpdatedGestationAtTime",
    "LatestUploadedFromServerName", "LinkedPlayerDataID", "LinkedStructures",
    "MaxHealth", "MaxItemCount", "MyInventoryComponent", "NextAllowedMatingTime",
    "NumBullets", "OriginalCreationTime", "OriginalNPCVolumeName", "OwnerName",
    "OwningPlayerID", "OwningPlayerName", "PaintingComponent",
    "PreviousUploadedFromServerName", "RandomMutationsFemale", "RandomMutationsMale",
    "RangeSetting", "ResourceCount", "SaddleDino", "SaddleStructures",
    "SavedDedicatedStorageVersion", "SelectedResourceClass", "StructureColors",
    "TamedAITargetingRange", "TamedAggressionLevel", "TamedAtTime", "TamedName",
    "TamedOnServerName", "TamerString", "TamingTeamID", "TargetingTeam", "TribeName",
    "UniquePaintingId", "UploadedFromServerName", "bAttackTeamMemberDinos",
    "bContainerActivated", "bEnableTamedMating", "bEnableTamedWandering",
    "bForceDisablingTaming", "bHasFuel", "bHasResetDecayTime", "bIgnoreAllWhistles",
    "bIsBaby", "bIsBlueprint", "bIsClone", "bIsCloneDino", "bIsEngram", "bIsFemale",
    "bIsFlying", "bIsFoundation", "bIsInTurretMode", "bIsLocked", "bIsPinLocked",
    "bIsPowered", "bNeutered", "bOnlyTargetConscious", "bServerInitializedDino",
    "bWasPlacementSnapped",
})

_CREATURE_RECORD_NAMES: frozenset[str] = frozenset({
    "BabyAge", "BabyCuddleFood", "BabyCuddleType", "BabyNextCuddleTime",
    "BaseCharacterLevel", "ColorSetIndices", "CreatureTraits", "CurrentStatusValues",
    "DinoAncestors", "DinoDownloadedAtTime", "DinoID1", "DinoID2",
    "DinoImprintingQuality", "ExperiencePoints", "ExtraCharacterLevel",
    "FollowStoppingDistance", "HarvestResourceLevels", "ImprinterName",
    "ImprinterPlayerDataID", "ImprinterPlayerUniqueNetId", "IsInCryo",
    "IsInVivarium", "LastEnterStasisTime", "LastInAllyRangeSerialized",
    "LastInAllyRangeTime", "LastUpdatedBabyAgeAtTime", "LastUpdatedGestationAtTime",
    "LatestUploadedFromServerName", "MyCharacterStatusComponent",
    "MyInventoryComponent", "NextAllowedMatingTime", "NumberOfLevelUpPointsApplied",
    "NumberOfLevelUpPointsAppliedTamed", "NumberOfMutationsAppliedTamed",
    "OriginalCreationTime", "OriginalNPCVolumeName", "OwnerName", "OwningPlayerID",
    "OwningPlayerName", "PreviousUploadedFromServerName", "RandomMutationsFemale",
    "RandomMutationsMale", "SaddleStructures", "TamedAITargetingRange",
    "TamedAggressionLevel", "TamedAtTime", "TamedName", "TamedOnServerName",
    "TamerString", "TamingTeamID", "TargetingTeam", "TribeName",
    "UploadedFromServerName", "bAttackTeamMemberDinos", "bEnableTamedMating",
    "bEnableTamedWandering", "bForceDisablingTaming", "bIgnoreAllWhistles",
    "bIsBaby", "bIsClone", "bIsCloneDino", "bIsFemale", "bIsFlying",
    "bIsInTurretMode", "bNeutered", "bOnlyTargetConscious", "bServerInitializedDino",
})

_STATUS_RECORD_NAMES: frozenset[str] = frozenset({
    "BaseCharacterLevel", "CurrentStatusValues", "DinoImprintingQuality",
    "ExperiencePoints", "ExtraCharacterLevel", "LinkedPlayerDataID",
    "NumberOfLevelUpPointsApplied", "NumberOfLevelUpPointsAppliedTamed",
    "NumberOfMutationsAppliedTamed",
})

_INVENTORY_COMPONENT_NAMES: frozenset[str] = frozenset({
    "EquippedItems", "InventoryItems",
})


def _materialize_partial(obj: t.Any, names: frozenset[str]) -> None:
    """Partial-decode hint before a record build (ASA v14+ lazy saves only).

    No-op unless ``obj`` is an unloaded lazy object; ASE and v13 saves parse
    fully inside materialize_object regardless of the hint. Safe by design:
    reads outside ``names`` upgrade to the full block transparently.
    """
    src = getattr(obj, "_lazy_source", None)
    if src is not None and not obj._props_loaded:
        src.materialize_object(obj, names=names)


def _world_objects(save: t.Any, getter: str, legacy_attr: str) -> list[t.Any]:
    """Return a category list from save, cached per save instance.

    Without caching, each export type re-walks ``save.objects`` and reapplies
    the per-category filter (tamed, wild, structures, players, ...). On a
    360k-object save that adds up to several extra full passes per
    ``export_all`` call. The cache is keyed by getter name so each category
    materializes exactly once and is reused across every subsequent export.
    """
    cache = getattr(save, "_world_objects_cache", None)
    if cache is None:
        cache = {}
        try:
            save._world_objects_cache = cache
        except (AttributeError, TypeError):
            cache = None  # save instance doesn't allow attribute write; bypass cache
    if cache is not None and getter in cache:
        return cache[getter]
    fn = getattr(save, getter, None)
    if callable(fn):
        result = list(fn())
    else:
        val = getattr(save, legacy_attr, None)
        result = list(val) if isinstance(val, list) else []
    if cache is not None:
        cache[getter] = result
    return result


def _collection(source: t.Any, attr: str, kind: type[t.Any]) -> list[t.Any]:
    if isinstance(source, kind):
        return [source]
    if isinstance(source, (list, tuple)):
        return list(source)
    val = getattr(source, attr, None)
    if isinstance(val, (list, tuple)):
        return list(val)
    return [] if val is None else [val]


def _status_for(obj: t.Any, lookup: dict[t.Any, t.Any]) -> t.Any:
    """Find a creature's status component (partial-decoded on lazy ASA saves)."""
    comps = getattr(obj, "components", None)
    status = None
    if isinstance(comps, dict):
        status = comps.get("status")
    if status is None:
        status = _resolve(_prop(obj, "MyCharacterStatusComponent"), lookup)
    if status is not None:
        _materialize_partial(status, _STATUS_RECORD_NAMES)
    return status


def _inventory_component(obj: t.Any, lookup: dict[t.Any, t.Any]) -> t.Any:
    inv = _resolve(_prop(obj, "MyInventoryComponent"), lookup)
    if inv is None:
        comps = getattr(obj, "components", None)
        if isinstance(comps, dict):
            inv = comps.get("inventory")
    if inv is not None:
        _materialize_partial(inv, _INVENTORY_COMPONENT_NAMES)
    return inv


# Item properties already surfaced at top-level of an inventory entry or
# representing internal save plumbing we strip from the ``stats`` subdict.
# Stripping these is the difference between meaningful per-item stats and
# unbounded snake_case dumps of UE4 internals.
_ITEM_STATS_SKIP: frozenset[str] = frozenset(
    {
        # Already surfaced at top level of inventory entry.
        # (ItemID is kept and combined into ``stats.id`` for unique tracking)
        "ItemQuantity",
        "bIsBlueprint",
        # Internal save plumbing / object refs.
        "OwnerInventory",
        "ItemCustomClass",
        "CustomItemDatas",  # cryopod blob, surfaced via dino_* keys
        "CustomItemData",
        "CustomItemName",
        "CustomItemDescription",
        # Internal timestamps / versioning, opaque to consumers.
        "LastAutoDurabilityDecreaseTime",
        "ItemVersion",
        "CreationTime",
        "LastUseTime",
        # UI / engine state flags. Not item state, not actionable downstream.
        "bAllowRemovalFromInventory",
        "bHideFromInventoryDisplay",
        "bHideFromRemoteInventoryDisplay",
        "bCanSlot",
        "bAllowEquppingItem",  # sic, ARK typo preserved in save format
        "bIsInitialItem",
        "bForcePreventGrinding",
        "bIsEngram",  # redundant with item class
        "bIsCustomRecipe",
        "bIsFoodRecipe",
        "bIsRepairing",
        "bIsEquipped",
        "bIsSlot",
        "bAllowRemovalFromSteamInventory",
        "bIsFromAllClustersInventory",
        "bFromSteamInventory",
        # Cloud / tribute internals.
        "ItemArchetype",  # blueprint path, redundant with itemId
        "SteamUserItemID",  # always empty array on cluster items
        "UploadEarliestValidTime",
        "ExpirationTimeUTC",  # tribute expiry, opaque UTC seconds
        "ClusterSpoilingTimeUTC",
        "CraftingSkill",  # 0 on uploaded items
        "ItemProfileVersion",  # internal versioning
        "bNetInfoFromClient",  # net replication flag
        "OwnerPlayerDataID",  # 0 on uploaded items
        "LastOwnerPlayer",  # -1 sentinel on uploaded items
        "ItemStatClampsMultiplier",
        "OwnerPlayerDataId",  # ASA casing variant of OwnerPlayerDataID
        # ASA cosmetic / cluster noise.
        "CustomCosmeticAuthVars",
        "CustomCosmeticModSkinReplacementID",
        "CustomCosmeticModSkinVariantID",
        "bDoApplyOriginalColorsWhenUnskinned",
        "bIsFromClubArk",
    }
)

# Egg-genetic fields in ArkTributeItem are populated with garbage struct
# overlap bytes for non-egg items. Only surface them when the item is
# actually an egg.
_EGG_ONLY_FIELDS: frozenset[str] = frozenset(
    {
        "egg_number_of_level_up_points_applied",
        "egg_tamed_ineffectiveness_modifier",
        "egg_color_set_indices",
        "egg_gender_override",
        "egg_dino_ancestors",
        "egg_dino_ancestors_male",
        "egg_random_mutations_female",
        "egg_random_mutations_male",
        "egg_number_mutations_applied",
        "egg_number_of_mutations_applied",  # "NumberOf" variant (matches EggNumberOfLevelUpPointsApplied naming)
        "egg_dino_gene_traits",
    }
)


def _is_meaningful_value(value: t.Any) -> bool:
    """Filter no-op default values from item stat output.

    Empty containers and empty strings carry no information; surfacing them
    just adds JSON noise. NaN floats are treated as missing (ARK uses NaN
    for "no expiration / never spoils"). Numeric zeros are kept (a stat
    value of 0 is legitimate, e.g. unequipped saddle slot).
    """
    if value is None:
        return False
    if isinstance(value, (list, dict, str)) and len(value) == 0:
        return False
    if isinstance(value, float) and not math.isfinite(value):  # NaN or +/-inf
        return False
    if isinstance(value, str) and value == "Unknown":
        return False
    return True


# Per-key default sentinels. When a stat surfaces a value equal to its
# sentinel, that field carries no signal (skin -1 = no skin applied, etc).
# Drop the key entirely rather than spamming JSON output with no-ops.
_STAT_KEY_DEFAULTS: dict[str, t.Any] = {
    "skin": -1,
    "craft_queue": 0,
    "craft_at": 0.0,
    "custom_id": 0,
    "slot": 0,
    "temp_slot": 0,
    "loaded_ammo": 0,
    "skill_bonus": 0.0,
    "spoils_at": 0.0,
    "spoiled_at": 0.0,
    "rating": 0.0,
    "color_pre_skin": [0, 0, 0, 0, 0, 0],
    "drop_location": {"x": 0.0, "y": 0.0, "z": 0.0},
    "quality": 0,
    "item_durability": 0.0,
    "associated_dino_id": 0,
}


def _is_default(key: str, value: t.Any) -> bool:
    """True if ``value`` matches the documented no-signal sentinel for ``key``."""
    if key not in _STAT_KEY_DEFAULTS:
        return False
    default = _STAT_KEY_DEFAULTS[key]
    if isinstance(default, list) and isinstance(value, list):
        return len(value) == len(default) and all(a == b for a, b in zip(value, default, strict=True))
    if isinstance(default, dict) and isinstance(value, dict):
        # Vector structs are sometimes keyed X/Y/Z (ASA) instead of x/y/z;
        # compare case-insensitively so a zero drop_location still prunes.
        lowered = {str(k).lower(): v for k, v in value.items()}
        return all(lowered.get(k, 0) == v for k, v in default.items())
    return value == default


def _flatten_color_array(value: t.Any) -> dict[str, int]:
    """``color: [c0..c5]`` (or dict[idx â†’ c]) â†’ ``{c0, c1, ..., c5}``.

    Mirrors how tame exports surface region colors (``c0`` .. ``c5``).
    Non-zero entries only; all-zero color arrays return ``{}`` so the
    caller can skip emission.
    """
    out: dict[str, int] = {}
    iterable: t.Iterable[tuple[int, t.Any]]
    if isinstance(value, dict):
        iterable = ((int(k), v) for k, v in value.items() if isinstance(k, (int, str)) and str(k).lstrip("-").isdigit())
    elif isinstance(value, list):
        iterable = enumerate(value)
    else:
        return out
    for idx, v in iterable:
        if 0 <= idx < 6 and v:
            try:
                out[f"c{idx}"] = int(v)
            except (TypeError, ValueError):
                continue  # struct-valued color (LinearColor) etc; not a palette index
    return out


# ARK universal 8-slot ItemStatValues map. Each slot is raw uint16; the
# displayed percentage = raw * per-blueprint multiplier (in the item's UE
# blueprint, not the save). Slot semantics stable across all item classes;
# names disambiguated from top-level entries (e.g. ``durability_max`` for
# the multiplier slot vs ``durability`` for current condition 0-1).
_ITEM_STAT_SLOT_NAMES: tuple[str, ...] = (
    "gen_quality",  # rarely populated
    "armor",
    "durability_max",
    "damage",  # weapon damage %
    "clip_size",  # weapon clip multiplier (NOT currently-loaded ammo)
    "hypo",  # hypothermal insulation
    "weight",
    "hyper",  # hyperthermal insulation
)

# Snake_case property name â†’ shorter consumer-facing name. Applied after
# pascalâ†’snake conversion. Anything not in the table keeps its snake_case
# name so newly-added ASA props still surface automatically.
_STAT_NAME_ALIASES: dict[str, str] = {
    "item_rating": "rating",
    "item_quality_index": "quality",
    "saved_durability": "durability",
    "item_color_id": "color",
    "pre_skin_item_color_id": "color_pre_skin",
    "item_skin_template": "skin",
    "weapon_clip_ammo": "loaded_ammo",
    "crafter_character_name": "crafter",
    "crafter_tribe_name": "crafter_tribe",
    "crafted_skill_bonus": "skill_bonus",
    "custom_item_id": "custom_id",
    "last_spoiling_time": "spoiled_at",
    "next_spoiling_time": "spoils_at",
    "next_craft_completion_time": "craft_at",
    "slot_index": "slot",
    "temp_slot_index": "temp_slot",
    "accessory_slot_override": "accessory_slot",
    "original_item_drop_location": "drop_location",
    "chibi_xp": "chibi_xp",
}


def _combine_item_id(value: t.Any) -> str | None:
    """Combine ItemID struct ``{ItemID1, ItemID2}`` to single string.

    Uses explicit ``is None`` fallback (not ``or``) so a legitimate
    ``ItemID1 == 0`` is not silently replaced by an ``ItemID1_0`` variant
    key. Non-numeric / corrupt id components return ``None`` rather than
    raising and aborting the whole inventory export.
    """
    if not isinstance(value, dict):
        return None
    id1 = value.get("ItemID1")
    if id1 is None:
        id1 = value.get("ItemID1_0")
    id2 = value.get("ItemID2")
    if id2 is None:
        id2 = value.get("ItemID2_0")
    if id1 is None and id2 is None:
        return None
    try:
        return f"{int(id1 or 0)}_{int(id2 or 0)}"
    except (TypeError, ValueError):
        return None


def _normalize_stat_value(name: str, value: t.Any) -> t.Any:
    """Collapse single-index dicts. ItemStatValues handled separately."""
    if isinstance(value, dict) and len(value) == 1 and 0 in value:
        return value[0]
    if isinstance(value, dict) and len(value) == 1 and "0" in value:
        return value["0"]
    return value


def _apply_stat_aliases(
    stats: dict[str, t.Any],
    *,
    item_class: str = "",
) -> dict[str, t.Any]:
    """Flatten item_stat_values + item_id; apply short-name aliases.

    Filters egg_* fields when ``item_class`` isn't an egg (those fields
    are bit-leaked struct overlap garbage on non-egg items in ASA cloud
    tribute data). Also filters empty containers/strings universally.
    """
    is_egg = "Egg" in item_class
    out: dict[str, t.Any] = {}
    raw_slot_values = stats.pop("item_stat_values", None)
    item_id = stats.pop("item_id", None)
    combined_id = _combine_item_id(item_id) if item_id is not None else None
    if combined_id:
        out["id"] = combined_id
    dino_id1 = stats.pop("associated_dino_id1", None)
    dino_id2 = stats.pop("associated_dino_id2", None)
    combined_dino = _combine_dino_id(dino_id1, dino_id2) if (dino_id1 or dino_id2) else 0
    if combined_dino:
        out["associated_dino_id"] = combined_dino
    color_raw = stats.pop("item_color_id", None)
    if color_raw is not None:
        out.update(_flatten_color_array(color_raw))
    for key, val in stats.items():
        if key in _EGG_ONLY_FIELDS and not is_egg:
            continue
        if not _is_meaningful_value(val):
            continue
        alias = _STAT_NAME_ALIASES.get(key, key)
        if _is_default(alias, val):
            continue
        out[alias] = val
    out.update(_expand_stat_slots(raw_slot_values))
    return out


def _expand_stat_slots(raw_slot_values: t.Any) -> dict[str, t.Any]:
    """Map raw ItemStatValues to named slots, accepting either input shape.

    Two shapes occur in practice:

    - GameObject inventory path â†’ a sparse ``{index: value}`` dict (see
      :func:`_indexed_property_map`, which preserves the index even for a
      single populated slot).
    - Cloud / uploaded path â†’ a dense 8-element ``list`` indexed 0..7
      (``normalize_indexed_data`` collapses the indexed property to a list).

    Anything else (a bare scalar from an upstream single-entry collapse that
    lost its index) carries no recoverable slot and is ignored. Raw 0 means
    "no stat roll", so zero slots are skipped.
    """
    pairs: t.Iterable[tuple[t.Any, t.Any]]
    if isinstance(raw_slot_values, dict):
        pairs = raw_slot_values.items()
    elif isinstance(raw_slot_values, list):
        pairs = enumerate(raw_slot_values)
    else:
        return {}
    out: dict[str, t.Any] = {}
    for k, v in pairs:
        try:
            idx = int(k)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(_ITEM_STAT_SLOT_NAMES) and v:
            out[_ITEM_STAT_SLOT_NAMES[idx]] = v
    return out


_PASCAL_SNAKE_RE_1 = re.compile(r"(.)([A-Z][a-z]+)")
_PASCAL_SNAKE_RE_2 = re.compile(r"([a-z0-9])([A-Z])")


@functools.lru_cache(maxsize=4096)
def _pascal_to_snake(name: str) -> str:
    """``ItemStatValues`` â†’ ``item_stat_values``, ``bIsBlueprint`` â†’ ``b_is_blueprint``.

    Cached: called once per property per inventory item (millions of calls
    per big save) over a vocabulary of a few hundred property names.
    """
    s = _PASCAL_SNAKE_RE_1.sub(r"\1_\2", name)
    return _PASCAL_SNAKE_RE_2.sub(r"\1_\2", s).lower()


def _indexed_property_map(item_obj: t.Any, prop_name: str) -> dict[int, t.Any]:
    """Read a multi-index property as ``{index: value}`` straight from the object.

    ``_serialize_properties`` collapses a single-entry non-Byte property group
    to a bare scalar, which destroys the slot index for indexed arrays such as
    ``ItemStatValues`` / ``ItemColorID`` (an item with only one populated stat
    slot would otherwise lose both the value and which slot it was). Reading the
    raw ``Property`` list keeps every index, mirroring :func:`_colors`.
    """
    getter = getattr(item_obj, "get_properties_by_name", None)
    if not callable(getter):
        return {}
    out: dict[int, t.Any] = {}
    for prop in getter(prop_name):
        idx = int(getattr(prop, "index", 0) or 0)
        val = getattr(prop, "value", None)
        if val is not None:
            out[idx] = val
    return out


def _item_stats_dict(item_obj: t.Any, item_class: str = "") -> dict[str, t.Any]:
    """Surface every parseable property on an inventory item as snake_case.

    Walks the GameObject's serialized property map (object refs already
    stripped by ``_serialize_properties``), converts each property name to
    snake_case, and drops a small denylist of fields that are either
    redundant with the top-level entry (qty, blueprint), internal plumbing
    (ItemID, OwnerInventory), or huge embedded blobs surfaced elsewhere
    (CustomItemDatas).

    Returns ``{}`` if the object cannot be introspected (synthetic / no
    properties).
    """
    serializer = getattr(item_obj, "_serialize_properties", None)
    if not callable(serializer):
        return {}
    try:
        raw = serializer()
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    pre: dict[str, t.Any] = {}
    for name, value in raw.items():
        if name in _ITEM_STATS_SKIP:
            continue
        snake = _pascal_to_snake(name)
        pre[snake] = _normalize_stat_value(snake, value)
    # ItemStatValues / ItemColorID are indexed UInt16 arrays. _serialize_properties
    # collapses a single populated slot to a bare scalar (losing the index), so
    # re-read them straight from the object to preserve {index: value}; a
    # single-stat saddle/weapon would otherwise drop its only roll.
    isv = _indexed_property_map(item_obj, "ItemStatValues")
    if isv:
        pre["item_stat_values"] = isv
    color = _indexed_property_map(item_obj, "ItemColorID")
    if color:
        pre["item_color_id"] = color
    return _apply_stat_aliases(pre, item_class=item_class)


def _inventory_items(
    obj: t.Any,
    lookup: dict[t.Any, t.Any],
    cryo_cache: dict[int, tuple[int, str, str] | None] | None = None,
) -> list[dict[str, t.Any]]:
    inv = _inventory_component(obj, lookup)
    if inv is None:
        return []
    # Legacy builds each holder's inventory from BOTH InventoryItems and
    # EquippedItems (ContentContainer.cs:1355-1420): saddles / armor / costumes
    # live in EquippedItems and would otherwise be dropped. Inventory first,
    # then equipped, matching legacy order.
    refs: list[t.Any] = []
    inv_refs = _prop(inv, "InventoryItems")
    if isinstance(inv_refs, list):
        refs.extend(inv_refs)
    equipped_refs = _prop(inv, "EquippedItems")
    if isinstance(equipped_refs, list):
        refs.extend(equipped_refs)
    if not refs:
        return []
    items: list[dict[str, t.Any]] = []
    for ref in refs:
        item_obj = _resolve(ref, lookup)
        if item_obj is None:
            continue
        # Legacy skips engram entries when building inventory (ContentPack.cs:747
        # ``if (!invItem.IsEngram)``): they are recipe placeholders, not items.
        if bool(_prop(item_obj, "bIsEngram", default=False)):
            continue
        class_name = str(getattr(item_obj, "class_name", "") or "")
        entry: dict[str, t.Any] = {
            "itemId": class_name,
            "qty": _int(_prop(item_obj, "ItemQuantity"), default=1) or 1,
            "blueprint": bool(_prop(item_obj, "bIsBlueprint", default=False)),
        }
        if _is_cryopod_class(class_name):
            # Pod blobs are expensive to decode (zlib + full property parse).
            # The tamed pass already decoded every pod it exported and left a
            # display summary in the save's cache; only decode here on a miss
            # (pods the tamed pass skipped), and cache that result too.
            item_id = getattr(item_obj, "id", None)
            if cryo_cache is not None and item_id in cryo_cache:
                summary = cryo_cache[item_id]
            else:
                summary = _cryo_summary(_decode_inventory_cryopod(item_obj))
                if cryo_cache is not None and item_id is not None:
                    cryo_cache[item_id] = summary
            if summary is not None:
                dino_id, creature, name = summary
                if dino_id:
                    entry["dino_id"] = dino_id
                if creature:
                    entry["dino_creature"] = creature
                if name:
                    entry["dino_name"] = name
        entry.update(_item_stats_dict(item_obj, class_name))
        items.append(entry)
    return items


def _tribe_counts(save: t.Any) -> dict[int, dict[str, int]]:
    """Build tribe_id â†’ {tames, structures} counts from a WorldSave.

    Returns an empty dict when ``save`` lacks WorldSave getters (e.g. when
    the caller passed a SimpleNamespace of tribe parsers without world data).
    """
    cached = getattr(save, "_tribe_counts", None)
    if isinstance(cached, dict):
        return cached
    if not callable(getattr(save, "get_tamed_creatures", None)):
        return {}
    counts: dict[int, dict[str, int]] = {}
    # Route through _world_objects so the category lists classify once per save
    # (the direct getters re-ran the full classification walk, which on lazy
    # saves means a full re-parse of the object graph).
    # The fused classification pass captured every creature's and structure's
    # TargetingTeam while its property block was resident
    # (container._classified_teams); reuse it so these walks parse nothing on
    # lazy saves. The _prop fallback covers wrapper saves whose objects never
    # went through that pass.
    classified_teams = getattr(getattr(save, "container", None), "_classified_teams", None) or {}
    for obj in _world_objects(save, "get_tamed_creatures", "tamed_objects"):
        oid = getattr(obj, "id", None)
        tid = classified_teams.get(oid) if oid is not None else None
        if tid is None:
            tid = _int(_prop(obj, "TargetingTeam"))
            _drain_lazy(save)
        if not tid:
            continue
        counts.setdefault(tid, {"tames": 0, "structures": 0})["tames"] += 1
    for obj in _world_objects(save, "get_structures", "structure_objects"):
        oid = getattr(obj, "id", None)
        tid = classified_teams.get(oid) if oid is not None else None
        if tid is None:
            tid = _int(_prop(obj, "TargetingTeam"))
            _drain_lazy(save)
        if not tid:
            continue
        counts.setdefault(tid, {"tames": 0, "structures": 0})["structures"] += 1
    try:
        save._tribe_counts = counts
    except (AttributeError, TypeError):
        pass
    return counts


def _tamed_dict(
    obj: t.Any,
    status: t.Any,
    lookup: dict[t.Any, t.Any],
    map_config: MapConfig | None,
    save: t.Any = None,
    stored: bool = False,
) -> dict[str, t.Any]:
    base_pts = _stat_array(status, "NumberOfLevelUpPointsApplied")
    tamed_pts = _stat_array(status, "NumberOfLevelUpPointsAppliedTamed")
    mut_pts = _stat_array(status, "NumberOfMutationsAppliedTamed")
    base_level = _int(_prop(status, "BaseCharacterLevel"), default=1) or 1
    extra_level = _int(_prop(status, "ExtraCharacterLevel"))
    is_asa = bool(getattr(save, "is_asa", False))
    raw_id1 = _prop(obj, "DinoID1")
    raw_id2 = _prop(obj, "DinoID2")
    dino_id = _combine_dino_id(raw_id1, raw_id2)
    # Legacy negates the id of stored (cryo/vivarium) creatures so they don't
    # collide with live tames (ContentTamedCreature.cs:122-126/228-232). The
    # dinoid field stays positive (C# sets DinoId = Id.ToString() before negating).
    is_stored = stored or bool(_prop(obj, "IsInCryo", default=False)) or bool(_prop(obj, "IsInVivarium", default=False))
    display_id = -dino_id if (is_stored and dino_id != 0) else dino_id
    # Legacy blanks the tamer once a creature is imprinted (ContentTamedCreature
    # .cs:109-114/215-220): imprinted dinos report an imprinter, not a tamer.
    imprinter_player_id = _int(_prop(obj, "ImprinterPlayerDataID"))
    imprinter_name = _str(_prop(obj, "ImprinterName"))
    tamer = _str(_prop(obj, "TamerString"))
    if imprinter_player_id > 0 or imprinter_name:
        tamer = ""
    colors = _colors(obj)
    is_female = bool(_prop(obj, "bIsFemale", default=False))
    targeting_team = _int(_prop(obj, "TargetingTeam"))
    baby = bool(_prop(obj, "bIsBaby", default=False))
    # A baby with no BabyAge property is a newborn (maturation 0), not an adult.
    # Legacy reads BabyAge with default 0 (ContentCreature.cs:98). Non-babies
    # stay at 1.0 -> maturation "100".
    baby_age = _float(_prop(obj, "BabyAge"), default=0.0) if baby else 1.0
    father_id, father_name = _ancestor_parent(obj, "Male")
    mother_id, mother_name = _ancestor_parent(obj, "Female")
    tribe_name = _str(_prop(obj, "TribeName"))
    _, stasis_iso = _iso_pair(obj, "LastEnterStasisTime", save)
    _, baby_age_iso = _iso_pair(obj, "LastUpdatedBabyAgeAtTime", save)
    _, gestation_iso = _iso_pair(obj, "LastUpdatedGestationAtTime", save)
    _, cuddle_iso = _iso_pair(obj, "BabyNextCuddleTime", save)

    data: dict[str, t.Any] = {
        "id": display_id,
        "tribeid": targeting_team,
        "tribe": tribe_name or None,
        "tamer": tamer,
        "imprinter": imprinter_name,
        "imprint": _float(_prop(status, "DinoImprintingQuality")),
        "creature": getattr(obj, "class_name", "") or "",
        "name": _str(_prop(obj, "TamedName")),
        "sex": "Female" if is_female else "Male",
        "base": base_level,
        "lvl": base_level + extra_level,
        **_flat_stats(base_pts, "w"),
        **_flat_stats(tamed_pts, "t"),
        **{f"c{i}": colors[i] for i in range(6)},
        "mut-f": _int(_prop(obj, "RandomMutationsFemale")),
        "mut-m": _int(_prop(obj, "RandomMutationsMale")),
        "cryo": bool(_prop(obj, "IsInCryo", default=False)),
        "dinoid": _dino_id_str(raw_id1, raw_id2, is_asa),
        "isMating": bool(_prop(obj, "bEnableTamedMating", default=False)),
        "isNeutered": bool(_prop(obj, "bNeutered", default=False)),
        "isClone": bool(_prop(obj, "bIsClone", default=False)) or bool(_prop(obj, "bIsCloneDino", default=False)),
        "tamedServer": _str(_prop(obj, "TamedOnServerName")),
        "uploadedServer": _str(_prop(obj, "UploadedFromServerName")),
        "maturation": str(int(baby_age * 100)),
        **_flat_stats(mut_pts, "m"),
        # Legacy emits tamed traits as a list of objects ([{"trait": <class>}]),
        # not a flat string list (ContentPack.cs:723-735). Match that shape.
        "traits": [{"trait": tr} for tr in _traits(obj)],
        "inventory": _inventory_items(obj, lookup, _cryo_summary_cache(save)),
        "father_id": father_id,
        "mother_id": mother_id,
        "father_name": father_name,
        "mother_name": mother_name,
        "level_added": extra_level,
        "experience": _int(_prop(status, "ExperiencePoints")),
        "wandering": bool(_prop(obj, "bEnableTamedWandering", default=False)),
        "tamed_at": (
            d.isoformat() if (d := _approx_real_datetime(_prop(obj, "TamedAtTime"), save)) is not None else None
        ),
        "last_ally_in_range": (
            d.isoformat()
            if (
                d := _approx_real_datetime(
                    _prop(obj, "LastInAllyRangeTime") or _prop(obj, "LastInAllyRangeSerialized"),
                    save,
                )
            )
            is not None
            else None
        ),
        "current_stats": _current_stats_dict(status),
        "imprinter_player_id": imprinter_player_id,
        "imprinter_net_id": _str(_prop(obj, "ImprinterPlayerUniqueNetId")),
        "taming_team_id": _int(_prop(obj, "TamingTeamID")),
        "owning_player_id": _int(_prop(obj, "OwningPlayerID")),
        "owning_player_name": _str(_prop(obj, "OwningPlayerName")),
        "aggression_level": _int(_prop(obj, "TamedAggressionLevel")),
        "ai_targeting_range": _float(_prop(obj, "TamedAITargetingRange")),
        "follow_stopping_distance": _float(_prop(obj, "FollowStoppingDistance")),
        "is_flying": bool(_prop(obj, "bIsFlying", default=False)),
        "is_turret_mode": bool(_prop(obj, "bIsInTurretMode", default=False)),
        "ignore_whistles": bool(_prop(obj, "bIgnoreAllWhistles", default=False)),
        "only_target_conscious": bool(_prop(obj, "bOnlyTargetConscious", default=False)),
        "attack_team_member_dinos": bool(_prop(obj, "bAttackTeamMemberDinos", default=False)),
        "next_cuddle_food": _str(_prop(obj, "BabyCuddleFood")),
        "next_cuddle_type": _int(_prop(obj, "BabyCuddleType")),
        "latest_uploaded_server": _str(_prop(obj, "LatestUploadedFromServerName")),
        "previous_uploaded_server": _str(_prop(obj, "PreviousUploadedFromServerName")),
        "saddle_structures": _saddle_structure_refs(_prop(obj, "SaddleStructures")),
        "harvest_resource_levels": _harvest_levels(_prop(obj, "HarvestResourceLevels")),
        "wild_spawn_region": _str(_prop(obj, "OriginalNPCVolumeName")),
        "downloaded_at": (
            d.isoformat()
            if (d := _approx_real_datetime(_prop(obj, "DinoDownloadedAtTime"), save)) is not None
            else None
        ),
        "original_created": (
            d.isoformat()
            if (d := _approx_real_datetime(_prop(obj, "OriginalCreationTime"), save)) is not None
            else None
        ),
        "next_mating_at": (
            d.isoformat()
            if (d := _approx_real_datetime(_prop(obj, "NextAllowedMatingTime"), save)) is not None
            else None
        ),
        "last_stasis": stasis_iso,
        "last_baby_age_update": baby_age_iso,
        "last_gestation_update": gestation_iso,
        "next_cuddle": cuddle_iso,
    }
    data.update(_gps_payload(obj, map_config, ndigits=2))
    return _compact(data, LEGACY_TAMED_KEYS)


def export_tamed(save: t.Any, map_config: MapConfig | None = None) -> list[dict[str, t.Any]]:
    """Emit ASV_Tamed records.

    Pre-conditions: ``save`` exposes ``get_tamed_creatures()`` (in-world
    tames) and ideally ``iter_cryopod_creatures()`` (creatures whose actor
    has been removed from the world and re-embedded inside a cryopod /
    soultrap / vivarium / dinoball item).

    Post-conditions: returned list combines (a) every in-world tame and
    (b) every cryopod-embedded tame, with the latter carrying ``cryo=True``
    and inheriting the cryopod item's world location for GPS fields.
    """
    return list(_iter_tamed(save, map_config))


def _iter_tamed(save: t.Any, map_config: MapConfig | None) -> t.Iterator[dict[str, t.Any]]:
    """Yield ASV_Tamed records one at a time (see :func:`export_tamed`).

    Generator form so :func:`export_to_files` can stream each record to disk
    and release it instead of materializing the whole list (the list is the
    dominant export-time allocation on large PvE saves).
    """
    objects = _world_objects(save, "get_tamed_creatures", "tamed_objects")
    lookup = _save_lookup(save)
    for obj in objects:
        _materialize_partial(obj, _CREATURE_RECORD_NAMES)
        yield _tamed_dict(obj, _status_for(obj, lookup), lookup, map_config, save)
        _drain_lazy(save)
    yield from _export_world_cryopods(save, map_config)


def _build_item_owner_lookup(save: t.Any, lookup: dict[t.Any, t.Any]) -> dict[t.Any, dict[str, t.Any]]:
    """Map inventory-item id â†’ owning container info.

    For every object that has an ``InventoryItems`` property (structures,
    player pawns, dino inventory components), walk its contained item refs
    and record the owner's tribe id + display names. Used to infer tribe
    affiliation for ASA cryopod creatures whose embedded property blocks
    we cannot decode, but whose containing cryopod item lives in a
    structure or player inventory we *can* read.
    """
    out: dict[t.Any, dict[str, t.Any]] = {}
    # The fused classification pass captured (inv ref, team, tribe, owner) for
    # every non-item actor carrying MyInventoryComponent while its property
    # block was resident, so the actor side of this walk needs no parsing at
    # all; only each inventory component is materialized (to read its
    # InventoryItems) and drained. Insertion order matches object order, so
    # first-wins per item id is preserved. The full actor walk below covers
    # wrapper saves whose objects never went through that pass.
    container = getattr(save, "container", None)
    if container is not None and getattr(container, "_classify_cache", None) is not None:
        actor_infos = container._inv_actor_info.items()
    else:
        actor_infos = _iter_inv_actor_info(save)
    for _actor_id, (inv_ref, team_raw, tribe_raw, owner_raw) in actor_infos:
        inv = _resolve(inv_ref, lookup)
        if inv is None:
            continue
        _materialize_partial(inv, _INVENTORY_COMPONENT_NAMES)
        refs = _prop(inv, "InventoryItems")
        if not isinstance(refs, list) or not refs:
            continue
        info = {
            "TargetingTeam": _int(team_raw),
            "TribeName": _str(tribe_raw) or _str(owner_raw),
        }
        for ref in refs:
            item_obj = _resolve(ref, lookup)
            if item_obj is None:
                continue
            item_id = getattr(item_obj, "id", None)
            if item_id is None:
                continue
            if item_id not in out:
                out[item_id] = info
        _drain_lazy(save)
    return out


def _iter_inv_actor_info(
    save: t.Any,
) -> t.Iterator[tuple[t.Any, tuple[t.Any, t.Any, t.Any, t.Any]]]:
    """Fallback actor walk for saves without a fused classification capture.

    Yields the same ``(actor_id, (inv_ref, team, tribe, owner))`` shape the
    container capture stores, walking every non-item, non-component actor.
    Items are contained, never containers, and status/inventory component
    objects never own an inventory themselves, so both are skipped on header
    data alone (no property parse).
    """
    objects = getattr(save, "objects", None) or []
    iterable = objects.values() if isinstance(objects, dict) else objects
    for actor in iterable:
        if getattr(actor, "is_item", False):
            continue
        cn = getattr(actor, "class_name", "") or ""
        # Component patterns mirror container._classify_world's pre-filter:
        # tight enough to spare modded structures whose class names merely
        # contain "Inventory" (e.g. StructureBP_InventoryCars_C).
        if "StatusComponent" in cn or "PrimalInventory" in cn or "InventoryComponent" in cn:
            continue
        inv_ref = _prop(actor, "MyInventoryComponent")
        if inv_ref is None:
            _drain_lazy(save)
            continue
        yield (
            getattr(actor, "id", None),
            (
                inv_ref,
                _prop(actor, "TargetingTeam"),
                _prop(actor, "TribeName"),
                _prop(actor, "OwnerName"),
            ),
        )


def _export_world_cryopods(
    save: t.Any,
    map_config: MapConfig | None,
) -> list[dict[str, t.Any]]:
    """Build ASV_Tamed records for cryopod-embedded creatures on the map.

    ARK strips the actor for any creature stuffed into a cryopod / soultrap
    / vivarium / dinoball and serialises a snapshot into the item's
    ``CustomItemDatas``. ``get_tamed_creatures()`` therefore misses them
    entirely. We walk ``iter_cryopod_creatures()`` (when available),
    decode each embedded blob, and produce ``ASV_Tamed`` entries with
    ``cryo=True`` and the cryopod item's location. When the embedded
    blob does not yield a tribe id (ASA, partial decode), we infer it
    from the cryopod item's containing inventory (structure or pawn).
    """
    iter_cryos = getattr(save, "iter_cryopod_creatures", None)
    if not callable(iter_cryos):
        return []
    lookup = _save_lookup(save)
    owner_lookup = _build_item_owner_lookup(save, lookup)
    summaries = _cryo_summary_cache(save)
    out: list[dict[str, t.Any]] = []
    empty_lookup: dict[t.Any, t.Any] = {}
    for item_obj, cryo in iter_cryos():
        actor, status = _cryo_props_to_synthetic(cryo)
        # Inherit the cryopod's world location so GPS fields populate.
        actor.location = getattr(item_obj, "location", None)
        # Infer tribe/owner from containing inventory when the decoded
        # creature blob did not supply them (ASA partial decode path).
        item_id = getattr(item_obj, "id", None)
        if summaries is not None and item_id is not None:
            # Leave the display summary for the inventory listings that will
            # encounter this same pod later (cryofridges, pawns, vaults), so
            # they never re-decode the blob.
            summaries[item_id] = _cryo_summary(cryo)
        owner_info = owner_lookup.get(item_id) if item_id is not None else None
        if owner_info is not None:
            for key, val in owner_info.items():
                if val and not cryo.creature_props.get(key):
                    cryo.creature_props[key] = val
        record = _tamed_dict(actor, status, empty_lookup, map_config, save, stored=True)
        # The synthetic actor carries no IsInCryo property; force the legacy
        # flag so consumers can distinguish in-world tames from stored ones.
        record["cryo"] = True
        out.append(record)
        _drain_lazy(save)
    return out


class _SyntheticGameObject:
    """Lightweight GameObject stand-in for cryopod-blob-decoded creatures.

    Cluster-uploaded creatures live as serialized creature objects inside
    ``ArkTamedDinosData[].DinoData`` byte blobs. ``CryopodCreature`` already
    parses that blob into ``creature_props`` / ``status_props`` dicts. We
    wrap those in this adapter so the rest of the export pipeline can call
    ``get_property_value`` on them just like a real ``GameObject``.
    """

    __slots__ = ("class_name", "id", "guid", "names", "location", "properties", "components", "is_item", "_props")

    def __init__(self, class_name: str, props: dict[str, t.Any]) -> None:
        self.class_name = class_name
        self.id = 0
        self.guid = ""
        self.names: list[str] = []
        self.location = None
        self.properties: list[t.Any] = []
        self.components: dict[str, t.Any] = {}
        self.is_item = False
        self._props = props

    def get_property_value(
        self,
        name: str,
        default: t.Any = None,
        index: int | None = None,
    ) -> t.Any:
        if index is None or index == 0:
            val = self._props.get(name, self._props.get(f"{name}_0"))
            if val is None:
                return default
            return val
        val = self._props.get(f"{name}_{index}")
        return default if val is None else val


def _cryo_props_to_synthetic(
    cryo: CryopodCreature,
    status_class: str = "DinoCharacterStatusComponent_BP_C",
) -> tuple[_SyntheticGameObject, _SyntheticGameObject]:
    """Build (actor, status) synthetic objects from a parsed cryopod blob."""
    actor = _SyntheticGameObject(cryo.class_name or "", cryo.creature_props)
    status = _SyntheticGameObject(status_class, cryo.status_props)
    return actor, status


def _cryo_tamed_record(
    cryo: CryopodCreature,
    map_config: MapConfig | None,
    empty_lookup: dict[t.Any, t.Any],
    upload_time: int = 0,
) -> dict[str, t.Any]:
    """Decode one cryopod blob into a tamed record flagged ``cryo=True``.

    ``upload_time`` (unix seconds; cluster uploads only) populates
    ``uploadedTime`` to match legacy (ContentContainer.cs:387-389); 0 omits it.
    """
    actor, status = _cryo_props_to_synthetic(cryo)
    # Cluster-UPLOADED creatures are not cryo/vivarium in legacy terms (their
    # IsInCryo is false), so legacy keeps their id positive, so do NOT negate.
    # Only genuine in-world cryopod/vivarium creatures negate, via
    # _export_world_cryopods passing stored=True directly to _tamed_dict.
    record = _tamed_dict(actor, status, empty_lookup, map_config)
    record["cryo"] = True
    ut = _int(upload_time)
    if ut:
        # uploadedTime doubles as the downstream "is uploaded" discriminator.
        try:
            record["uploadedTime"] = dt.datetime.fromtimestamp(ut, tz=dt.timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            pass
    return record


def _append_unique_tame(
    out: list[dict[str, t.Any]],
    seen_ids: set[int],
    record: dict[str, t.Any],
) -> None:
    """Append ``record`` unless a tame with the same non-zero dino id is present.

    Cluster cryopods can land in either ``ArkTamedDinosData`` or ``ArkItems``;
    a creature present in both would otherwise be emitted twice. Records whose
    dino id is 0 (unresolved, common on ASA partial decodes) are never deduped
    so distinct unidentified tames are all preserved.
    """
    did = _int(record.get("dinoid"))
    if did and did in seen_ids:
        return
    if did:
        seen_ids.add(did)
    out.append(record)


def export_cluster_uploads(
    cluster_inventories: t.Iterable[CloudInventory],
    map_config: MapConfig | None = None,
) -> list[dict[str, t.Any]]:
    """Export cluster-uploaded creatures in ``ASV_Tamed`` shape.

    Each cluster cloud-inventory file carries an ``ArkTamedDinosData`` array;
    every entry has a ``DinoData`` byte blob containing the full creature +
    status-component object pair. We decode each blob via
    :class:`CryopodCreature` and run it through the standard tamed-export
    field map.

    Cryopodded creatures inside ``ArkItems`` (uploaded cryopods) are also
    included here so a cluster export captures every cluster-resident dino
    regardless of which array it landed in.

    Args:
        cluster_inventories: ``CloudInventory`` instances loaded from a
            cluster directory.
        map_config: Optional map config (cluster uploads carry no location
            so GPS keys will be zeros).

    Returns:
        List of tamed dictionaries with ``cryo=True`` (cluster tames are
        always stored in cryopods).
    """
    out: list[dict[str, t.Any]] = []
    seen_ids: set[int] = set()
    empty_lookup: dict[t.Any, t.Any] = {}
    for inv in cluster_inventories:
        my_ark_data = normalize_indexed_data(inv.get_property_value("MyArkData"))
        if not isinstance(my_ark_data, dict):
            continue
        dino_list = normalize_indexed_list(my_ark_data.get("ArkTamedDinosData"))
        for entry in dino_list:
            entry = normalize_indexed_data(entry)
            if not isinstance(entry, dict):
                continue
            dino_data = entry.get("DinoData")
            byte_arr: list[int] | None = None
            if isinstance(dino_data, list):
                byte_arr = dino_data
            elif isinstance(dino_data, dict):
                inner = normalize_indexed_list(dino_data.get("ByteArrays"))
                if inner and isinstance(inner[0], dict):
                    byte_arr = inner[0].get("Bytes")
            if not byte_arr:
                continue
            cryo = CryopodCreature.from_cryopod_bytes(byte_arr)
            if cryo is None:
                continue
            upload_time = _int(entry.get("UploadTime"))
            _append_unique_tame(
                out,
                seen_ids,
                _cryo_tamed_record(cryo, map_config, empty_lookup, upload_time),
            )
        # Cryopods uploaded as items (rare but present, especially in ASA
        # tribute transfers) embed a CryopodCreature in CustomItemDatas.
        for item in inv.uploaded_items:
            if _is_placeholder_item(item) or not item.is_cryopod:
                continue
            cryo = item.cryopod_creature
            if cryo is None:
                continue
            _append_unique_tame(
                out,
                seen_ids,
                _cryo_tamed_record(cryo, map_config, empty_lookup, _int(item.upload_time)),
            )
    return out


def _uploaded_item_dict(item: t.Any, save: t.Any = None) -> dict[str, t.Any]:
    """Shape a single ``UploadedItem`` as an inventory-style entry.

    Mirrors ``_inventory_items``: ``itemId``/``qty``/``blueprint`` at top,
    all aliased stats flattened in. Cryopod items get ``dino_*`` keys.
    """
    blueprint = item.blueprint or ""
    class_name = blueprint.rsplit(".", 1)[-1] if "." in blueprint else (item.name or "")
    if not class_name:
        # ASA cluster items store the class via ``ItemCustomClass`` object ref
        # instead of ``ItemArchetype`` path. Use that as the itemId fallback.
        ark_tribute = normalize_indexed_data(item.raw_data.get("ArkTributeItem", {}))
        if isinstance(ark_tribute, dict):
            custom_class = ark_tribute.get("ItemCustomClass")
            if isinstance(custom_class, tuple) and len(custom_class) == 2:
                custom_class = custom_class[1]
            if isinstance(custom_class, str) and custom_class:
                class_name = custom_class.rsplit(".", 1)[-1] if "." in custom_class else custom_class
    entry: dict[str, t.Any] = {
        "itemId": class_name or item.name,
        "qty": item.quantity,
        "blueprint": item.is_blueprint,
    }
    if item.is_cryopod:
        cryo = item.cryopod_creature
        if cryo is not None:
            props = cryo.creature_props
            dino_id = _combine_dino_id(
                props.get("DinoID1", props.get("DinoID1_0", 0)),
                props.get("DinoID2", props.get("DinoID2_0", 0)),
            )
            if dino_id:
                entry["dino_id"] = dino_id
            species_or_class = cryo.species or cryo.class_name
            if species_or_class:
                entry["dino_creature"] = str(species_or_class)
            if cryo.name:
                entry["dino_name"] = cryo.name
    ark_tribute = normalize_indexed_data(item.raw_data.get("ArkTributeItem", {}))
    if isinstance(ark_tribute, dict):
        pre: dict[str, t.Any] = {}
        for name, value in ark_tribute.items():
            if name in _ITEM_STATS_SKIP:
                continue
            snake = _pascal_to_snake(name)
            pre[snake] = _normalize_stat_value(snake, value)
        entry.update(_apply_stat_aliases(pre, item_class=class_name))
    # Legacy derives item uploadedTime from the inner ArkTributeItem CreationTime
    # via the in-game anchor file_mtime + (t - game_time) (ContentItem.cs:52 +
    # ContentContainer.cs:301-303). ASA cluster items instead carry a real unix
    # epoch in the outer UploadTime (CreationTime is 0), so fall back to that.
    # Always emit an ISO string (never a raw int) so the field type is stable.
    iso: str | None = None
    creation_time = _float(ark_tribute.get("CreationTime")) if isinstance(ark_tribute, dict) else 0.0
    if creation_time and save is not None:
        anchored = _approx_real_datetime(creation_time, save)
        if anchored is not None:
            iso = anchored.isoformat()
    if iso is None and item.upload_time:
        try:
            iso = dt.datetime.fromtimestamp(float(item.upload_time), tz=dt.timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError, TypeError):
            iso = None
    if iso is not None:
        entry["uploadedTime"] = iso
    return entry


def _is_placeholder_item(item: t.Any) -> bool:
    """ASA cluster files include empty placeholder slots (no class).

    Identified by: no blueprint path, no item name, no ItemCustomClass ref
    in the underlying ArkTributeItem. ``item.quantity`` is coerced to >=1
    even when the source ``ItemQuantity`` is 0, so it isn't a reliable
    signal here.
    """
    if item.blueprint or item.name:
        return False
    ark_tribute = normalize_indexed_data(item.raw_data.get("ArkTributeItem", {}))
    if isinstance(ark_tribute, dict):
        custom_class = ark_tribute.get("ItemCustomClass")
        if isinstance(custom_class, tuple) and len(custom_class) == 2:
            custom_class = custom_class[1]
        if custom_class:
            return False
    return True


def export_cluster_items(
    cluster_inventories: t.Iterable[CloudInventory],
    save: t.Any = None,
) -> list[dict[str, t.Any]]:
    """Export every uploaded item across the supplied cloud inventories.

    Each item carries its snake_case stats flattened in at the top level
    (``itemId``/``qty``/``blueprint`` plus ``armor``/``durability_max``/
    ``damage``/``rating``/``crafter`` etc) surfacing the full
    ``ArkTributeItem`` payload. Cryopod items also include ``dino_*`` keys with the embedded
    creature's identifying info; the dino's full stats record is emitted
    by :func:`export_cluster_uploads`.
    """
    out: list[dict[str, t.Any]] = []
    for inv in cluster_inventories:
        for item in inv.uploaded_items:
            if _is_placeholder_item(item):
                continue
            out.append(_uploaded_item_dict(item, save))
    return out


def export_cloud_inventory(
    cloud: CloudInventory,
    map_config: MapConfig | None = None,
) -> dict[str, list[dict[str, t.Any]]]:
    """Inspect a single cloud-inventory file.

    Returns a dict with two ASV-shaped lists:

    - ``ASV_Tamed``: every dino in the file (both ``ArkTamedDinosData``
      entries and cryopod items in ``ArkItems``), shaped like a regular
      tamed record so consumers can reuse existing rendering.
    - ``ASV_Items``: every uploaded item, snake_case stats flattened in
      at the top level (see :func:`export_cluster_items`).

    Useful for inspecting a single user's cluster transfer file in
    isolation, without scanning a whole cluster directory.
    """
    return {
        _EXPORT_NAMES["tamed"]: export_cluster_uploads([cloud], map_config),
        "ASV_Items": export_cluster_items([cloud]),
    }


_NONTAMEABLE_CLASSES: frozenset[str] = frozenset(
    {
        "Xenomorph_Character_BP_Female_C",  # Reaper Queen
    }
)

_MEGA_ALPHA_RE = re.compile(r"Mega[A-Z]|Mega_|Alpha_")


def _is_tameable(class_name: str, obj: t.Any) -> bool:
    """Mirror C# ContentWildCreature.IsTameable rule."""
    if _prop(obj, "bForceDisablingTaming", default=False):
        return False
    if class_name in _NONTAMEABLE_CLASSES:
        return False
    return _MEGA_ALPHA_RE.search(class_name) is None


def _wild_dict(
    obj: t.Any,
    status: t.Any,
    map_config: MapConfig | None,
    is_asa: bool = False,
) -> dict[str, t.Any]:
    base_pts = _stat_array(status, "NumberOfLevelUpPointsApplied")
    base_level = _int(_prop(status, "BaseCharacterLevel"), default=1) or 1
    colors = _colors(obj)
    is_female = bool(_prop(obj, "bIsFemale", default=False))
    raw_id1 = _prop(obj, "DinoID1")
    raw_id2 = _prop(obj, "DinoID2")
    dino_id = _combine_dino_id(raw_id1, raw_id2)
    traits = _traits(obj)
    class_name = getattr(obj, "class_name", "") or ""
    tameable = _is_tameable(class_name, obj)

    data: dict[str, t.Any] = {
        "id": dino_id,
        "creature": class_name,
        "sex": "Female" if is_female else "Male",
        "lvl": base_level,
        **_flat_stats(base_pts),
        **{f"c{i}": colors[i] for i in range(6)},
        "dinoid": _dino_id_str(raw_id1, raw_id2, is_asa),
        "tameable": tameable,
        # Legacy emits the first trait as a singular ``trait``; the full
        # CreatureTraits list is exposed alongside as ``traits``.
        "trait": traits[0] if traits else "",
        "traits": traits,
        "current_stats": _current_stats_dict(status),
        "wild_spawn_region": _str(_prop(obj, "OriginalNPCVolumeName")),
    }
    data.update(_gps_payload(obj, map_config))
    return _compact(data, LEGACY_WILD_KEYS)


def export_wild(save: t.Any, map_config: MapConfig | None = None) -> list[dict[str, t.Any]]:
    return list(_iter_wild(save, map_config))


def _iter_wild(save: t.Any, map_config: MapConfig | None) -> t.Iterator[dict[str, t.Any]]:
    """Yield ASV_Wild records one at a time (streaming form of export_wild)."""
    objects = _world_objects(save, "get_wild_creatures", "wild_objects")
    is_asa = bool(getattr(save, "is_asa", False))
    lookup = _save_lookup(save)
    for obj in objects:
        _materialize_partial(obj, _CREATURE_RECORD_NAMES)
        yield _wild_dict(obj, _status_for(obj, lookup), map_config, is_asa)
        _drain_lazy(save)


def _player_from_profile(
    profile: Profile,
    save: t.Any = None,
    pawn_status_by_id: dict[int, t.Any] | None = None,
    pawn_by_data_id: dict[int, t.Any] | None = None,
    map_config: MapConfig | None = None,
) -> dict[str, t.Any]:
    stat_points = [_int(profile.get_stat(i)["added"]) for i in range(12)]
    gamertag = profile.player_name or ""
    character = profile.character_name or gamertag
    steam_id = profile.unique_id or ""
    active_dt = _approx_real_datetime(profile.last_login_time, save)

    # Live HP/stam/etc live on the player's in-world pawn's status component,
    # not in the profile. Resolve via PlayerDataID -> pawn -> status. Absent
    # when the player has no spawned body (never spawned / corpse cleared).
    status = None
    pawn = None
    if profile.player_id:
        pid = int(profile.player_id)
        if pawn_status_by_id:
            status = pawn_status_by_id.get(pid)
        if pawn_by_data_id:
            pawn = pawn_by_data_id.get(pid)

    # The profile carries no world position. When the player has a live pawn in
    # the save, pull lat/lon/ccc from it; otherwise keep the legacy 0/0 zeroes
    # (dead / logged-out players have no location to report).
    gps = _gps_payload(pawn, map_config, ndigits=2) if pawn is not None else {"ccc": "0 0 0", "lat": 0.0, "lon": 0.0}

    out: dict[str, t.Any] = {
        "playerid": profile.player_id or 0,
        "steam": _str(gamertag),
        "name": _str(character),
        "tribeid": profile.tribe_id or 0,
        "tribe": profile.tribe_name or "",
        "sex": "Female" if profile.is_female is True else "Male",
        "lvl": profile.level,
        "lat": gps["lat"],
        "lon": gps["lon"],
        **_flat_stats(stat_points),
        "active": active_dt.isoformat() if active_dt is not None else None,
        "ccc": gps["ccc"],
        "achievements": [],
        "inventory": [],
        "netAddress": _str(profile.last_net_address),
        "engram_points": profile.total_engram_points,
        "experience": _int(profile.experience),
        "current_stats": _current_stats_dict(status),
    }
    if steam_id:
        out["steamid"] = steam_id
        out["dataFile"] = f"{steam_id}.arkprofile"
    else:
        out["steamid"] = ""
        out["dataFile"] = ""
    return _compact(out, LEGACY_PLAYER_KEYS)


def _player_from_object(
    obj: t.Any,
    status: t.Any,
    lookup: dict[t.Any, t.Any] | None = None,
    map_config: MapConfig | None = None,
    save: t.Any = None,
) -> dict[str, t.Any]:
    base_level = _int(_prop(status, "BaseCharacterLevel"), default=1) or 1
    extra_level = _int(_prop(status, "ExtraCharacterLevel"))
    stat_points = _stat_array(status, "NumberOfLevelUpPointsApplied")
    player_id = _int(_prop(obj, "PlayerDataID")) or _int(_prop(obj, "LinkedPlayerDataID"))
    tribe_id = _int(_prop(obj, "TribeID")) or _int(_prop(obj, "TribeId")) or _int(_prop(obj, "TargetingTeam"))
    last_active_seconds = _float(_prop(obj, "SavedLastTimeHadController") or _prop(obj, "LastTimeHadController"))
    active_dt = _approx_real_datetime(last_active_seconds, save)
    gps = _gps_payload(obj, map_config, ndigits=2)
    inv_lookup = lookup if lookup is not None else {}
    _, died_iso = _iso_pair(obj, "LocalDiedAtTime", save)
    _, corpse_iso = _iso_pair(obj, "CorpseDestructionTime", save)
    body_colors_raw = _prop(obj, "BodyColors")
    body_colors: list[int] = []
    if isinstance(body_colors_raw, dict):
        for i in sorted(k for k in body_colors_raw if isinstance(k, int)):
            body_colors.append(_int(body_colors_raw.get(i)))
    elif isinstance(body_colors_raw, list):
        body_colors = [_int(v) for v in body_colors_raw]
    if not any(body_colors):
        body_colors = []
    data: dict[str, t.Any] = {
        "playerid": player_id,
        "steam": _str(_prop(obj, "PlatformProfileName")),
        "name": _str(_prop(obj, "PlayerName")),
        "tribeid": tribe_id,
        "tribe": _str(_prop(obj, "TribeName")),
        "sex": "Female" if _prop(obj, "bIsFemale", default=False) else "Male",
        "lvl": base_level + extra_level,
        "lat": gps["lat"],
        "lon": gps["lon"],
        **_flat_stats(stat_points),
        "active": active_dt.isoformat() if active_dt is not None else None,
        "ccc": gps["ccc"],
        "achievements": [],
        "inventory": _inventory_items(obj, inv_lookup, _cryo_summary_cache(save)),
        "netAddress": "",
        "steamid": "",
        "dataFile": "",
        "engram_points": _int(_prop(obj, "TotalEngramPoints")),
        "experience": _int(_prop(status, "ExperiencePoints")),
        "is_sleeping": bool(_prop(obj, "bIsSleeping", default=False)),
        "is_dead": bool(_prop(obj, "bIsDead", default=False)),
        "chibi_levels": _int(_prop(obj, "NumChibiLevelUps")),
        "ascensions_scorched": _int(_prop(obj, "NumAscensionsScorched")),
        "is_prone": bool(_prop(obj, "bIsProne", default=False)),
        "is_crouched": bool(_prop(obj, "bIsCrouched", default=False)),
        "hat_hidden": bool(_prop(obj, "bHatHidden", default=False)),
        "current_weapon": _ref_name(_prop(obj, "CurrentWeapon")),
        "seated_on_ref": _ref_name(_prop(obj, "SeatingStructure")),
        "original_hair_color": _int(_prop(obj, "OriginalHairColor")),
        "head_hair_growth": _float(_prop(obj, "PercentOfFullHeadHairGrowth")),
        "facial_hair_growth": _float(_prop(obj, "PercentOfFullFacialHairGrowth")),
        "body_colors": body_colors,
        "died_at": died_iso,
        "corpse_destruction": corpse_iso,
        "current_stats": _current_stats_dict(status),
    }
    return _compact(data, LEGACY_PLAYER_KEYS)


def _player_status_by_data_id(
    save: t.Any,
    lookup: dict[t.Any, t.Any],
) -> tuple[dict[int, t.Any], dict[int, t.Any]]:
    """Index per-player pawn + status component by ``LinkedPlayerDataID``.

    Walks every ``PlayerPawnTest_*_C`` / ``PlayerCharacter_*`` in the world
    save, reads its ``LinkedPlayerDataID``, follows ``MyCharacterStatusComponent``
    via ``lookup``, and stores both the resolved status object and the pawn
    itself. The status index lets profile-based player exports surface live
    HP/stamina/food/etc.; the pawn index lets them surface live lat/lon/ccc
    (the pawn carries ``.location``, the profile does not), without legacy
    ASVPack having to do the same join.

    Returns ``(status_by_id, pawn_by_id)``; a pawn appears in ``pawn_by_id``
    even when its status component fails to resolve.
    """
    status_out: dict[int, t.Any] = {}
    pawn_out: dict[int, t.Any] = {}
    objects = getattr(save, "objects", None) or []
    for obj in objects:
        cn = str(getattr(obj, "class_name", "") or "")
        if "PlayerPawn" not in cn and "PlayerCharacter" not in cn:
            continue
        pid = _int(_prop(obj, "LinkedPlayerDataID"))
        if not pid:
            continue
        pawn_out[pid] = obj
        status = _status_for(obj, lookup)
        if status is not None:
            status_out[pid] = status
    return status_out, pawn_out


def _cluster_items_by_xuid(
    cluster_inventories: t.Iterable[CloudInventory],
    save: t.Any = None,
) -> dict[str, list[dict[str, t.Any]]]:
    """Group uploaded items by cloud-file stem (= player's unique_id / xuid).

    Each cluster file is named after the owning player's Steam id (ASE) or
    platform UUID (ASA). That same stem names the player's ``.arkprofile``,
    so :func:`export_players` joins on the profile's source filename stem
    (see there), a stable key on both platforms without cracking any
    in-file ownership data. (``Profile.unique_id`` equals the stem only on
    ASE; on ASA it is the numeric net id, not the UUID filename.)
    """
    out: dict[str, list[dict[str, t.Any]]] = {}
    for inv in cluster_inventories:
        if inv.source_path is None:
            continue
        xuid = inv.source_path.stem
        if not xuid:
            continue
        bucket = out.setdefault(xuid, [])
        for item in inv.uploaded_items:
            if _is_placeholder_item(item):
                continue
            entry = _uploaded_item_dict(item, save)
            entry["uploaded"] = True
            bucket.append(entry)
    return out


def _player_record_for(
    entry: t.Any,
    save: t.Any,
    pawn_status_by_id: dict[int, t.Any],
    pawn_by_data_id: dict[int, t.Any],
    lookup: dict[t.Any, t.Any],
    map_config: MapConfig | None,
) -> tuple[dict[str, t.Any] | None, list[str]]:
    """Build ``(record, join_keys)`` for one ``save.profiles`` entry.

    ``join_keys`` are matched against the cloud-file stem (Steam id on ASE,
    hex UUID on ASA) to splice cluster uploads. Returns ``(None, [])`` when a
    wrapped pawn entry carries no usable profile object.
    """
    join_keys: list[str] = []
    if isinstance(entry, Profile):
        record = _player_from_profile(entry, save, pawn_status_by_id, pawn_by_data_id, map_config)
        if entry.source_path is not None and entry.source_path.stem:
            join_keys.append(entry.source_path.stem)
        if entry.unique_id:
            join_keys.append(entry.unique_id)
        return record, join_keys
    profile_obj = getattr(entry, "profile", None)
    if profile_obj is None and getattr(entry, "objects", None):
        profile_obj = entry.objects[0]
    if profile_obj is None:
        return None, join_keys
    status_obj = None
    for o in getattr(entry, "objects", []) or []:
        cn = str(getattr(o, "class_name", ""))
        if "StatusComponent" in cn or "CharacterStatus" in cn:
            status_obj = o
            break
    record = _player_from_object(profile_obj, status_obj, lookup, map_config, save)
    sid = record.get("steamid")
    if sid:
        join_keys.append(str(sid))
    return record, join_keys


def _member_stub_player(
    tid: int,
    pid: int,
    name: str,
    tribe_name: str,
) -> dict[str, t.Any]:
    """Stub ASV_Players record for a tribe member that has no ``.arkprofile``.

    Mirrors legacy's member back-fill (ContentContainer.cs): the player is
    known only by id + name from the tribe's member list, so every other
    field stays at its default. ``tribeid`` is the containing tribe.
    """
    assert pid, "member stub requires a non-zero player id"
    data: dict[str, t.Any] = {
        "playerid": pid,
        "steam": name,
        "name": name,
        "tribeid": tid,
        "tribe": tribe_name,
        "sex": "Male",
        "lvl": 0,
        "lat": 0.0,
        "lon": 0.0,
        **_flat_stats([0] * 12),
        "active": None,
        "ccc": "0 0 0",
        "achievements": [],
        "inventory": [],
        "netAddress": "",
        "steamid": "",
        "dataFile": "",
    }
    return _compact(data, LEGACY_PLAYER_KEYS)


def export_players(
    save: t.Any,
    map_config: MapConfig | None = None,
    cluster_inventories: t.Iterable[CloudInventory] | None = None,
) -> list[dict[str, t.Any]]:
    return list(_iter_players(save, map_config, cluster_inventories))


def _iter_players(
    save: t.Any,
    map_config: MapConfig | None,
    cluster_inventories: t.Iterable[CloudInventory] | None,
) -> t.Iterator[dict[str, t.Any]]:
    """Yield ASV_Players records one at a time (streaming form of export_players)."""
    profiles = _collection(save, "profiles", Profile)
    lookup = _save_lookup(save)
    pawn_status_by_id, pawn_by_data_id = _player_status_by_data_id(save, lookup)
    cluster_items = _cluster_items_by_xuid(cluster_inventories, save) if cluster_inventories else {}
    # Legacy emits each player's tribeid as the CONTAINING tribe's id (the one
    # whose member list / team claims them), not the profile's own field. The
    # shared assembly resolves that allocation; reuse it here for parity.
    allocation = _assemble_tribes(save)
    profile_tribeid = allocation["profile_tribeid"]
    tribe_names = allocation["names"]
    for entry in profiles:
        record, join_keys = _player_record_for(
            entry, save, pawn_status_by_id, pawn_by_data_id, lookup, map_config
        )
        if record is None:
            continue
        if isinstance(entry, Profile):
            tid = profile_tribeid.get(_int(entry.player_id))
            if tid:
                record["tribeid"] = tid
                record["tribe"] = tribe_names.get(tid) or record.get("tribe", "")
        spliced = next((cluster_items[k] for k in join_keys if k in cluster_items), None)
        if spliced:
            inv_list = record.get("inventory")
            if not isinstance(inv_list, list):
                inv_list = []
                record["inventory"] = inv_list
            inv_list.extend(spliced)
        yield record
        _drain_lazy(save)
    # Tribe members with no .arkprofile surface as stub players (legacy +N).
    for tid, pid, name in allocation["member_stubs"]:
        yield _member_stub_player(tid, pid, name, tribe_names.get(tid, ""))


def _strip_rich_color(msg: str) -> str:
    return _RICH_COLOR_RE.sub("", msg).strip()


def _parse_log(raw: str) -> dict[str, t.Any]:
    raw = raw.strip()
    m = _LOG_RE.match(raw)
    if m:
        day = int(m.group(1))
        time = m.group(2)
        clean = _strip_rich_color(m.group(3))
    else:
        day = 0
        time = ""
        clean = _strip_rich_color(raw)
    return {"day": day, "time": time, "message": raw, "clean_message": clean}


def _tribe_members_from_parser(
    tribe: Tribe,
    profile_index: dict[int, Profile] | None = None,
) -> list[dict[str, t.Any]]:
    """Legacy member shape: {ign, lvl, playerid, playername, steamid}.

    When ``profile_index`` (player_id â†’ Profile) is supplied, fills ``lvl``
    and ``steamid`` from the matching ``.arkprofile``. Tribe files don't
    carry per-member level / platform id themselves; the join is the only
    way to enrich them.
    """
    out: list[dict[str, t.Any]] = []
    for m in tribe.get_members():
        pid = _int(m.get("player_id"))
        profile = profile_index.get(pid) if profile_index else None
        out.append(
            {
                "ign": _str(m.get("name")),
                "lvl": int(profile.level) if profile is not None else 0,
                "playerid": str(pid),
                "playername": _str(m.get("name")),
                "steamid": (profile.unique_id or "") if profile is not None else "",
            }
        )
    return out


def _tribe_file_date(tribe: t.Any, save: t.Any) -> dt.datetime | None:
    """Wall-clock write time of a tribe's backing file (legacy TribeFileDate).

    File-backed tribes use the .arktribe mtime (ContentContainer.cs:1812);
    tribes parsed out of the world save fall back to the save's own mtime
    (ContentContainer.cs:734, GameSaveTime).
    """
    src = getattr(tribe, "source_path", None) if tribe is not None else None
    if src is not None:
        try:
            local_tz = dt.datetime.now().astimezone().tzinfo
            return dt.datetime.fromtimestamp(src.stat().st_mtime, tz=local_tz)
        except OSError:
            logger.debug("stat failed for tribe file %s", src)
    return getattr(save, "file_mtime", None) if save is not None else None


def _tribe_active_iso(
    file_date: t.Any,
    member_ids: t.Iterable[int],
    profile_active: dict[int, dt.datetime],
) -> str | None:
    """Legacy ContentTribe.LastActive (ContentTribe.cs:35-49): the max of the
    tribe file date and the members' last-active datetimes, discarding values
    in the future. Tribe-log "Day N" stamps are game-calendar time, not real
    seconds, so they cannot be converted with the save anchor and are unused.

    Returns ``None`` when no past candidate exists.
    """
    assert isinstance(profile_active, dict), "profile_active must be a dict"
    candidates: list[dt.datetime] = []
    if isinstance(file_date, dt.datetime):
        candidates.append(file_date if file_date.tzinfo else file_date.astimezone())
    for i, pid in enumerate(member_ids):
        assert i < _MAX_TRIBE_MEMBERS, "tribe member list exceeded bound"
        active = profile_active.get(_int(pid))
        if active is not None:
            candidates.append(active if active.tzinfo else active.astimezone())
    now = dt.datetime.now(dt.timezone.utc)
    past = [c for c in candidates if c <= now]
    if not past:
        return None
    return max(past).isoformat()


def _profile_actives(profiles: list[Profile], save: t.Any) -> dict[int, dt.datetime]:
    """``player_id -> last-active datetime`` for tribe activity rollups.

    Mirrors legacy ContentPlayer.LastActiveDateTime: the profile's
    LastLoginTime converted through the save anchor.
    """
    assert isinstance(profiles, list), "profiles must be a list"
    out: dict[int, dt.datetime] = {}
    for prof in profiles:
        pid = _int(prof.player_id)
        if not pid:
            continue
        active = _approx_real_datetime(prof.last_login_time, save)
        if active is not None:
            out[pid] = active
    return out


def _build_profile_index(save: t.Any) -> dict[int, Profile]:
    """Index ``save.profiles`` by player_id for tribe-member enrichment."""
    out: dict[int, Profile] = {}
    profiles = getattr(save, "profiles", None) or []
    for entry in profiles:
        if isinstance(entry, Profile) and entry.player_id:
            out[int(entry.player_id)] = entry
    return out


def _tribe_from_parser(
    tribe: Tribe,
    counts: dict[int, dict[str, int]],
    profile_index: dict[int, Profile] | None = None,
    save: t.Any = None,
) -> dict[str, t.Any]:
    tid = _int(tribe.tribe_id)
    c = counts.get(tid, {})
    data: dict[str, t.Any] = {
        "tribeid": tid,
        "tribe": tribe.name or "",
        "players": tribe.member_count,
        "members": _tribe_members_from_parser(tribe, profile_index),
        "tames": c.get("tames", 0),
        "uploadedTames": 0,
        "structures": c.get("structures", 0),
        "active": _tribe_file_date(tribe, save),
        "dataFile": f"{tid}.arktribe" if tid else "",
        "owner_id": tribe.owner_player_id or 0,
        "alliance_ids": tribe.alliance_ids,
    }
    return _compact(data, LEGACY_TRIBE_KEYS)


def _tribe_from_object(
    obj: t.Any,
    counts: dict[int, dict[str, int]],
    profile_index: dict[int, Profile] | None = None,
    save: t.Any = None,
) -> dict[str, t.Any]:
    tribe_id = _int(_prop(obj, "TribeID")) or _int(_prop(obj, "TribeId"))
    owner_id = _int(_prop(obj, "OwnerPlayerDataID")) or _int(_prop(obj, "OwnerPlayerDataId"))
    members: list[dict[str, t.Any]] = []
    i = 0
    while True:
        pid = _prop(obj, "MembersPlayerDataID", index=i)
        if pid is None:
            break
        name = _str(_prop(obj, "MembersPlayerName", index=i))
        pid_int = _int(pid)
        profile = profile_index.get(pid_int) if profile_index else None
        members.append(
            {
                "ign": name,
                "lvl": int(profile.level) if profile is not None else 0,
                "playerid": str(pid_int),
                "playername": name,
                "steamid": (profile.unique_id or "") if profile is not None else "",
            }
        )
        i += 1
    alliances: list[int] = []
    j = 0
    while True:
        val = _prop(obj, "TribeAlliances", index=j)
        if val is None:
            break
        alliances.append(_int(val))
        j += 1
    c = counts.get(tribe_id, {})
    data: dict[str, t.Any] = {
        "tribeid": tribe_id,
        "tribe": _str(_prop(obj, "TribeName")),
        "players": len(members),
        "members": members,
        "tames": c.get("tames", 0),
        "uploadedTames": 0,
        "structures": c.get("structures", 0),
        "active": _tribe_file_date(None, save),
        "dataFile": f"{tribe_id}.arktribe" if tribe_id else "",
        "owner_id": owner_id,
        "owner_name": _str(_prop(obj, "OwnerPlayerName")),
        "alliance_ids": alliances,
    }
    return _compact(data, LEGACY_TRIBE_KEYS)


def _tribe_object_logs(obj: t.Any) -> list[str]:
    """Read raw TribeLog entries off an in-world tribe GameObject."""
    log_val = _prop(obj, "TribeLog")
    if isinstance(log_val, list):
        return [e for e in log_val if isinstance(e, str) and e.strip()]
    out: list[str] = []
    k = 0
    while True:
        v = _prop(obj, "TribeLog", index=k)
        if v is None:
            break
        if isinstance(v, str) and v.strip():
            out.append(v)
        k += 1
    return out


# ---------------------------------------------------------------------------
# Tribe / player assembly (legacy ContentContainer parity)
#
# Legacy ASVExport builds ONE tribe list (ContentContainer.cs:686-1185) that is
# a superset of the .arktribe files: two sentinels, the file tribes, a solo
# tribe per profile, and stub tribes for every distinct structure/tame
# TargetingTeam with no file. Every profile is allocated to exactly one tribe;
# tribe members without a profile become stub players. ExportJsonPlayerTribes,
# ExportJsonPlayers and ExportJsonPlayerTribeLogs all iterate this same list,
# so tribes, players and tribe_logs stay mutually consistent. We reproduce the
# assembly once (cached on the save) and drive all three exports from it.
# ---------------------------------------------------------------------------
_UNCLAIMED_TRIBE_ID = 2_000_000_000  # legacy "[ASV Unclaimed]" sentinel
_ABANDONED_TRIBE_ID = -(2**31)  # int.MinValue, "[ASV Abandoned]"
_PLAYER_TEAM_THRESHOLD = 50_000  # ContentContainer.cs:1050
_MAX_TRIBE_MEMBERS = 100_000  # static loop bound (Power-of-10 r2)


def _profile_entries(save: t.Any) -> list[Profile]:
    """Return the ``Profile`` instances in ``save.profiles`` (skips wrapped pawns)."""
    entries = getattr(save, "profiles", None) or []
    out = [e for e in entries if isinstance(e, Profile)]
    assert isinstance(out, list), "profile entries must be a list"
    return out


def _object_tribe_members(obj: t.Any) -> list[tuple[int, str]]:
    """Read ``(player_id, name)`` member pairs off an in-world tribe object."""
    assert obj is not None, "tribe object required"
    out: list[tuple[int, str]] = []
    for i in range(_MAX_TRIBE_MEMBERS):
        pid = _prop(obj, "MembersPlayerDataID", index=i)
        if pid is None:
            break
        out.append((_int(pid), _str(_prop(obj, "MembersPlayerName", index=i))))
    assert len(out) < _MAX_TRIBE_MEMBERS, "tribe member list exceeded bound"
    return out


def _tribe_entry_info(
    entry: t.Any,
    counts: dict[int, dict[str, int]],
    profile_index: dict[int, Profile],
    save: t.Any,
) -> tuple[int, str, list[tuple[int, str]], dict[str, t.Any], list[str]] | None:
    """Normalize one ``save.tribes`` entry to ``(id, name, members, record, logs)``."""
    if isinstance(entry, Tribe):
        members = [(_int(m.get("player_id")), _str(m.get("name"))) for m in entry.get_members()]
        rec = _tribe_from_parser(entry, counts, profile_index, save)
        return _int(entry.tribe_id), entry.name or "", members, rec, list(entry.log_entries)
    obj = getattr(entry, "tribe", None)
    if obj is None and getattr(entry, "objects", None):
        obj = entry.objects[0]
    if obj is None:
        return None
    tid = _int(_prop(obj, "TribeID")) or _int(_prop(obj, "TribeId"))
    rec = _tribe_from_object(obj, counts, profile_index, save)
    return (
        tid,
        _str(_prop(obj, "TribeName")),
        _object_tribe_members(obj),
        rec,
        _tribe_object_logs(obj),
    )


def _distinct_team_names(
    save: t.Any,
    objects: t.Iterable[t.Any],
    name_props: tuple[str, ...],
    min_team: int,
) -> dict[int, str]:
    """Map each distinct ``TargetingTeam >= min_team`` to a first-seen name.

    The fused classification pass captured each classified object's
    TargetingTeam (``_classified_teams``) and its OwnerName / TamerString /
    TribeName triple (``_classified_names``) while the property block was
    resident, so on lazy saves this walk normally parses nothing. The _prop
    fallback covers wrapper saves whose objects never went through that pass.
    """
    container = getattr(save, "container", None)
    teams = getattr(container, "_classified_teams", None) or {}
    cap_names = getattr(container, "_classified_names", None) or {}
    name_slots = tuple(("OwnerName", "TamerString", "TribeName").index(p) for p in name_props)
    out: dict[int, str] = {}
    for obj in objects:
        oid = getattr(obj, "id", None)
        tid = teams.get(oid) if oid is not None else None
        if tid is None:
            tid = _int(_prop(obj, "TargetingTeam"))
            _drain_lazy(save)
        if tid < min_team or tid in out:
            continue
        captured = cap_names.get(oid) if oid is not None else None
        name = ""
        if captured is not None:
            for slot in name_slots:
                name = _str(captured[slot])
                if name:
                    break
        else:
            for prop in name_props:
                name = _str(_prop(obj, prop))
                if name:
                    break
            _drain_lazy(save)
        out[tid] = name
    return out


def _allocate_profiles(
    profiles: list[Profile],
    file_tribe_ids: set[int],
    member_index: dict[int, int],
) -> tuple[dict[int, int], dict[int, list[int]]]:
    """Allocate each profile to one tribe id (ContentContainer.cs:760-790).

    Priority: explicit profile tribe id when it names an existing tribe ->
    the tribe whose member list contains the player -> a solo tribe keyed on
    the player id. Returns ``(player_id -> tribe_id, tribe_id -> [player_id])``.
    """
    profile_tribeid: dict[int, int] = {}
    players_by_tribe: dict[int, list[int]] = {}
    for prof in profiles:
        pid = _int(prof.player_id)
        if not pid:
            continue
        explicit = _int(prof.raw_tribe_id)
        if explicit and explicit in file_tribe_ids:
            target = explicit
        elif pid in member_index:
            target = member_index[pid]
        else:
            target = pid
        profile_tribeid[pid] = target
        players_by_tribe.setdefault(target, []).append(pid)
    return profile_tribeid, players_by_tribe


def _member_backfill(
    member_index: dict[int, int],
    member_name: dict[int, str],
    profile_tribeid: dict[int, int],
    players_by_tribe: dict[int, list[int]],
) -> list[tuple[int, int, str]]:
    """Tribe members lacking a profile become stub players (legacy back-fill)."""
    stubs: list[tuple[int, int, str]] = []
    seen: set[int] = set()
    for pid, tid in member_index.items():
        if pid in profile_tribeid or pid in seen:
            continue
        seen.add(pid)
        stubs.append((tid, pid, member_name.get(pid, "")))
        players_by_tribe.setdefault(tid, []).append(pid)
    return stubs


def _assemble_tribes(save: t.Any) -> dict[str, t.Any]:
    """Build the legacy tribe superset once and cache it on the save."""
    cached = getattr(save, "_assembled_tribes", None)
    if isinstance(cached, dict):
        return cached
    counts = _tribe_counts(save)
    profile_index = _build_profile_index(save)
    names: dict[int, str] = {}
    rich: dict[int, dict[str, t.Any]] = {}
    logs: dict[int, list[str]] = {}
    member_index: dict[int, int] = {}
    member_name: dict[int, str] = {}
    order: list[int] = []
    for sid, sname in (
        (_UNCLAIMED_TRIBE_ID, "[ASV Unclaimed]"),
        (_ABANDONED_TRIBE_ID, "[ASV Abandoned]"),
    ):
        names[sid] = sname
        order.append(sid)
    for entry in _collection(save, "tribes", Tribe):
        info = _tribe_entry_info(entry, counts, profile_index, save)
        if info is None:
            continue
        tid, name, members, rec, log_entries = info
        if tid not in rich:
            order.append(tid)
        names[tid] = name or names.get(tid, "")
        rich[tid] = rec
        logs[tid] = log_entries
        for pid, mname in members:
            member_index.setdefault(pid, tid)
            if mname:
                member_name.setdefault(pid, mname)
    file_tribe_ids = set(rich) | {_UNCLAIMED_TRIBE_ID, _ABANDONED_TRIBE_ID}
    profiles = _profile_entries(save)
    profile_active = _profile_actives(profiles, save)
    profile_tribeid, players_by_tribe = _allocate_profiles(profiles, file_tribe_ids, member_index)
    for prof in profiles:
        pid = _int(prof.player_id)
        target = profile_tribeid.get(pid)
        if target is None or target in names:
            continue
        order.append(target)
        names[target] = f"Tribe of {prof.character_name or prof.player_name or ''}".strip() if target == pid else ""
    for getter, props, floor in (
        ("get_structures", ("OwnerName", "TamerString"), _PLAYER_TEAM_THRESHOLD),
        ("get_tamed_creatures", ("TribeName", "TamerString"), 1),
    ):
        team_names = _distinct_team_names(save, _world_objects(save, getter, ""), props, floor)
        for tid, nm in team_names.items():
            if tid not in names:
                order.append(tid)
                names[tid] = nm
    member_stubs = _member_backfill(member_index, member_name, profile_tribeid, players_by_tribe)
    result: dict[str, t.Any] = {
        "order": order,
        "names": names,
        "rich": rich,
        "logs": logs,
        "counts": counts,
        "profile_index": profile_index,
        "profile_active": profile_active,
        "players_by_tribe": players_by_tribe,
        "profile_tribeid": profile_tribeid,
        "member_stubs": member_stubs,
        "member_name": member_name,
    }
    try:
        save._assembled_tribes = result
    except (AttributeError, TypeError):
        pass
    return result


def _members_for(tid: int, a: dict[str, t.Any]) -> list[dict[str, t.Any]]:
    """Member dicts for a tribe from its allocated players (profiles + stubs)."""
    profile_index = a["profile_index"]
    member_name = a["member_name"]
    out: list[dict[str, t.Any]] = []
    for pid in a["players_by_tribe"].get(tid, ()):
        prof = profile_index.get(pid)
        if prof is not None:
            out.append(
                {
                    "ign": _str(prof.character_name),
                    "lvl": int(prof.level),
                    "playerid": str(pid),
                    "playername": _str(prof.player_name),
                    "steamid": prof.unique_id or "",
                }
            )
        else:
            nm = member_name.get(pid, "")
            out.append(
                {
                    "ign": nm,
                    "lvl": 0,
                    "playerid": str(pid),
                    "playername": nm,
                    "steamid": "",
                }
            )
    return out


def _tribe_record(tid: int, a: dict[str, t.Any]) -> dict[str, t.Any]:
    """Final ASV_Tribes record for one assembled tribe id.

    File-backed tribes reuse the rich record (dataFile/owner/alliances) but
    have ``players``/``members`` overridden to the allocated-player set so
    they match the legacy writer (which counts allocated profiles, not the raw
    member list). Synthesized stubs carry id + name + world-derived counts.
    ``active`` finalizes here for both shapes: max of the tribe file date and
    the allocated members' last-active times (legacy ContentTribe.LastActive).
    """
    players = a["players_by_tribe"].get(tid, [])
    base = a["rich"].get(tid)
    if base is not None:
        rec = dict(base)
        rec["players"] = len(players)
        rec["members"] = _members_for(tid, a)
        rec["active"] = _tribe_active_iso(rec.get("active"), players, a["profile_active"])
        return rec
    c = a["counts"].get(tid, {})
    data: dict[str, t.Any] = {
        "tribeid": tid,
        "tribe": a["names"].get(tid, ""),
        "players": len(players),
        "members": _members_for(tid, a),
        "tames": c.get("tames", 0),
        "uploadedTames": 0,
        "structures": c.get("structures", 0),
        "active": _tribe_active_iso(None, players, a["profile_active"]),
        "dataFile": "",
    }
    return _compact(data, LEGACY_TRIBE_KEYS)


def export_tribes(save: t.Any) -> list[dict[str, t.Any]]:
    a = _assemble_tribes(save)
    assert "order" in a, "assembled tribes missing order"
    return [_tribe_record(tid, a) for tid in a["order"]]


def export_tribe_logs(save: t.Any) -> list[dict[str, t.Any]]:
    a = _assemble_tribes(save)
    return [{"tribeid": tid, "tribe": a["names"].get(tid, ""), "logs": a["logs"].get(tid, [])} for tid in a["order"]]


def _structure_created(obj: t.Any, save: t.Any) -> str | None:
    """Best-effort real-world creation timestamp as ISO 8601 with timezone.

    Returns ``None`` when ``OriginalCreationTime`` is missing or the save
    lacks the mtime / game-time anchors needed to convert from in-game
    seconds. The timezone is the local zone of the machine that loaded the
    save (legacy ASVExport also serializes in local time).
    """
    real_dt = _approx_real_datetime(_prop(obj, "OriginalCreationTime"), save)
    return real_dt.isoformat() if real_dt is not None else None


def _feeding_lists(obj: t.Any) -> tuple[list[str], list[str]]:
    """Return (inclusions, exclusions) class-name lists for feeding troughs.

    ASA feeding troughs carry a ``DinoFeedingListType`` (1 = inclusion,
    2 = exclusion) and a ``FeedingDinoList`` array of object refs. Mirrors
    legacy ContentStructure.cs ASA constructor.
    """
    list_type = _int(_prop(obj, "DinoFeedingListType"))
    if list_type not in (1, 2):
        return [], []
    raw = _prop(obj, "FeedingDinoList")
    if not isinstance(raw, list):
        return [], []
    classes: list[str] = []
    for entry in raw:
        if isinstance(entry, tuple) and len(entry) == 2:
            classes.append(str(entry[1]))
        elif entry:
            classes.append(str(entry))
    return (classes, []) if list_type == 1 else ([], classes)


def _structure_colors(obj: t.Any) -> list[int]:
    """6-slot paint color list from ``StructureColors``.

    Returns ``[]`` (will be pruned) when the structure carries no paint
    data or every slot is the unpainted sentinel ``0``. Painted structures
    return a length-6 list of indices.
    """
    raw = _prop(obj, "StructureColors")
    if not raw:
        return []
    if isinstance(raw, dict):
        out = [_int(raw.get(i)) for i in range(6)]
    elif isinstance(raw, list):
        out = [_int(raw[i]) if i < len(raw) else 0 for i in range(6)]
    else:
        return []
    return out if any(out) else []


# Classes legacy drops from the abandoned-structure bucket (ContentContainer.cs
# :1060-1070): map elements / crates / nests / veins that are surfaced elsewhere
# (ASV_MapStructures) or are debug/test actors. Only applied to UNOWNED
# structures (TargetingTeam < 50000); player-owned ones are always emitted.
_ABANDONED_EXCLUDE_PREFIXES: tuple[str, ...] = (
    "BeeHive_C",
    "ArtifactCrate_",
    "TributeTerminal_",
    "SupplyCrate_",
)
_ABANDONED_EXCLUDE_CONTAINS: tuple[str, ...] = ("Button_", "Nest_", "Vein_", "Beaver")


def _is_excluded_abandoned(class_name: str) -> bool:
    """True when an unowned structure class is excluded from ASV_Structures."""
    return class_name.startswith(_ABANDONED_EXCLUDE_PREFIXES) or any(
        token in class_name for token in _ABANDONED_EXCLUDE_CONTAINS
    )


def _structure_tribe(
    obj: t.Any,
    tribe_names: dict[int, str],
) -> tuple[int, str]:
    """Resolve ``(tribeid, tribe)`` for a structure, matching legacy.

    Player-owned structures (``TargetingTeam >= 50000``) take that team id and
    its resolved tribe name (file ``TribeName``, else the structure/tame stub's
    ``OwnerName``/``TamerString``). Unowned structures fall to the synthetic
    ``[ASV Abandoned]`` tribe (``int.MinValue``), mirroring ContentContainer.cs.
    """
    team = _int(_prop(obj, "TargetingTeam"))
    if team >= _PLAYER_TEAM_THRESHOLD:
        name = tribe_names.get(team) or _str(_prop(obj, "OwnerName")) or _str(_prop(obj, "TamerString"))
        return team, name
    return _ABANDONED_TRIBE_ID, tribe_names.get(_ABANDONED_TRIBE_ID, "[ASV Abandoned]")


def _structure_dict(
    obj: t.Any,
    save: t.Any,
    lookup: dict[t.Any, t.Any],
    map_config: MapConfig | None,
    tribe_names: dict[int, str],
) -> dict[str, t.Any]:
    # Legacy uses BoxName for player-set labels; emit "" if it matches the
    # class name (legacy ContentPack.cs:1596 strips no-rename cases).
    class_name = getattr(obj, "class_name", "") or ""
    tribeid, tribe_name = _structure_tribe(obj, tribe_names)
    box_name = _str(_prop(obj, "BoxName"))
    if box_name == class_name:
        box_name = ""
    locked = bool(_prop(obj, "bIsPinLocked", default=False) or _prop(obj, "bIsLocked", default=False))
    powered = bool(_prop(obj, "bIsPowered", default=False) or _prop(obj, "bHasFuel", default=False))
    inclusions, exclusions = _feeding_lists(obj)
    _, activated_iso = _iso_pair(obj, "LastActivatedTime", save)
    _, deactivated_iso = _iso_pair(obj, "LastDeactivatedTime", save)
    _, fire_iso = _iso_pair(obj, "LastFireTime", save)
    _, reload_iso = _iso_pair(obj, "LastLongReloadStartTime", save)
    _, fuel_iso = _iso_pair(obj, "LastCheckedFuelTime", save)
    attached_dino_id = (
        _combine_dino_id(
            _prop(obj, "AttachedToDinoID1"),
            _prop(obj, "AttachedToDinoID2"),
        )
        or None
    )
    data: dict[str, t.Any] = {
        "id": getattr(obj, "id", 0) or 0,
        "tribeid": tribeid,
        "tribe": tribe_name,
        "struct": class_name,
        "name": box_name,
        "locked": locked,
        # Legacy CreatedDateTime is DateTime? -> a null interpolates to "" in
        # the JSON, never JSON null. Match that (avoids a null-vs-string flip
        # for structures whose creation time can't be resolved).
        "created": _structure_created(obj, save) or "",
        "inventory": _inventory_items(obj, lookup, _cryo_summary_cache(save)),
        "decay_reset": bool(_prop(obj, "bHasResetDecayTime", default=False)),
        "last_ally_in_range": (
            d.isoformat()
            if (
                d := _approx_real_datetime(
                    _prop(obj, "LastInAllyRangeTime")
                    or _prop(obj, "LastInAllyRangeTimeSerialized")
                    or _prop(obj, "LastInAllyRangeSerialized"),
                    save,
                )
            )
            is not None
            else None
        ),
        "painting_id": _int(_prop(obj, "UniquePaintingId")),
        "feeding_inclusions": inclusions,
        "feeding_exclusions": exclusions,
        "health": _float(_prop(obj, "Health")),
        "max_health": _float(_prop(obj, "MaxHealth")),
        "owning_player_id": _int(_prop(obj, "OwningPlayerID")),
        "owning_player_name": _str(_prop(obj, "OwningPlayerName")),
        "colors": _structure_colors(obj),
        "current_item_count": _int(_prop(obj, "CurrentItemCount")),
        "max_item_count": _int(_prop(obj, "MaxItemCount")),
        "num_bullets": _int(_prop(obj, "NumBullets")),
        "range_setting": _int(_prop(obj, "RangeSetting")),
        "has_fuel": bool(_prop(obj, "bHasFuel", default=False)),
        "is_foundation": bool(_prop(obj, "bIsFoundation", default=False)),
        "placement_snapped": bool(_prop(obj, "bWasPlacementSnapped", default=False)),
        "variant": _int(_prop(obj, "CurrentVariant")),
        "selected_resource_class": _ref_name(_prop(obj, "SelectedResourceClass")),
        "resource_count": _int(_prop(obj, "ResourceCount")),
        "dedicated_storage_version": _int(_prop(obj, "SavedDedicatedStorageVersion")),
        "painting_ref": _ref_name(_prop(obj, "PaintingComponent")),
        "saddle_dino_ref": _ref_name(_prop(obj, "SaddleDino")),
        "attached_dino_id": attached_dino_id,
        "linked_structures": _ref_list(_prop(obj, "LinkedStructures")),
        "last_activated": activated_iso,
        "last_deactivated": deactivated_iso,
        "last_fire": fire_iso,
        "last_reload": reload_iso,
        "last_fuel_check": fuel_iso,
        "pin_code": _pin_code(obj),
    }
    data.update(_gps_payload(obj, map_config, ndigits=2))
    # Legacy ASVExport emits isSwitchedOn only for powered structures (ContentStructure.cs:58):
    # bContainerActivated when (bIsPowered or bHasFuel), omitted otherwise. Mirror that exactly so
    # on/off state stays a single field. Kept in LEGACY_STRUCT_KEYS so a powered-but-off False is
    # not pruned by _compact.
    if powered:
        data["isSwitchedOn"] = bool(_prop(obj, "bContainerActivated", default=False))
    return _compact(data, LEGACY_STRUCT_KEYS)


def export_structures(save: t.Any, map_config: MapConfig | None = None) -> list[dict[str, t.Any]]:
    return list(_iter_structures(save, map_config))


def _iter_structures(save: t.Any, map_config: MapConfig | None) -> t.Iterator[dict[str, t.Any]]:
    """Yield ASV_Structures records one at a time (streaming form of export_structures)."""
    objects = _world_objects(save, "get_structures", "structure_objects")
    lookup = _save_lookup(save)
    # Reuse the assembled tribe-name map so a structure's ``tribe`` resolves to
    # the same name the tribes export uses (file TribeName / stub OwnerName).
    tribe_names = _assemble_tribes(save)["names"]
    for obj in objects:
        _materialize_partial(obj, _STRUCTURE_RECORD_NAMES)
        team = _int(_prop(obj, "TargetingTeam"))
        if team < _PLAYER_TEAM_THRESHOLD and _is_excluded_abandoned(getattr(obj, "class_name", "") or ""):
            # Unowned map element / crate / debug actor: legacy drops these
            # from ASV_Structures (surfaced via ASV_MapStructures instead).
            _drain_lazy(save)
            continue
        yield _structure_dict(obj, save, lookup, map_config, tribe_names)
        _drain_lazy(save)


# Mirrors C# ContentContainer.cs:846. Order matters: first match wins.
_MAP_STRUCT_RULES: tuple[tuple[str, str, str], ...] = (
    ("TributeTerminal_", "ASV_Terminal", "startswith"),
    ("CityTerminal_", "ASV_Terminal", "contains"),
    ("PowerNodeCharge", "ASV_ChargeNode", "startswith"),
    ("BeaverDam_C", "ASV_BeaverDam", "startswith"),
    ("DeinonychusNest_C", "ASV_DeinoNest", "startswith"),
    ("RockDrakeNest_C", "ASV_DrakeNest", "startswith"),
    ("CherufeNest_C", "ASV_MagmaNest", "startswith"),
    ("WyvernNest_", "ASV_WyvernNest", "startswith"),
    ("OilVein_", "ASV_OilVein", "startswith"),
    ("WaterVein_", "ASV_WaterVein", "startswith"),
    ("GasVein_", "ASV_GasVein", "startswith"),
    ("ArtifactCrate_", "ASV_Artifact", "startswith"),
    ("Structure_PlantSpeciesZ_PlayerGrown", "ASV_PlantSpeciesZ", "startswith"),
    ("BeeHive_C", "ASV_BeeHive", "startswith"),
)


def _asv_map_struct_label(class_name: str) -> str | None:
    for pattern, label, kind in _MAP_STRUCT_RULES:
        if kind == "startswith":
            if class_name.startswith(pattern):
                return label
        elif pattern in class_name:
            return label
    return None


def export_map_structures(
    save: t.Any,
    map_config: MapConfig | None = None,
) -> list[dict[str, t.Any]]:
    return list(_iter_map_structures(save, map_config))


def _iter_map_structures(save: t.Any, map_config: MapConfig | None) -> t.Iterator[dict[str, t.Any]]:
    """Yield ASV_MapStructures records one at a time (streaming form of export_map_structures)."""
    objects = getattr(save, "objects", None) or []
    all_objs = objects.values() if isinstance(objects, dict) else objects
    lookup = _save_lookup(save)
    for obj in all_objs:
        cn = getattr(obj, "class_name", "") or ""
        label = _asv_map_struct_label(cn)
        if label is None:
            continue
        loc = getattr(obj, "location", None)
        if loc is None:
            continue
        if _prop(obj, "TargetingTeam") is not None:
            _drain_lazy(save)
            continue
        data: dict[str, t.Any] = {
            "struct": label,
            "inventory": _inventory_items(obj, lookup, _cryo_summary_cache(save)),
        }
        data.update(_gps_payload(obj, map_config))
        yield data
        _drain_lazy(save)


# Legacy ASVExport.exe filenames. Single canonical schema.
_EXPORT_NAMES: dict[str, str] = {
    "tamed": "ASV_Tamed",
    "wild": "ASV_Wild",
    "players": "ASV_Players",
    "tribes": "ASV_Tribes",
    "structures": "ASV_Structures",
    "tribe_logs": "ASV_TribeLogs",
    "map_structures": "ASV_MapStructures",
}


def _meta_head(save: t.Any, map_config: MapConfig | None = None) -> dict[str, t.Any]:
    """Return the legacy envelope head ``{map, day, time}`` (no ``data`` key)."""
    map_name = getattr(map_config, "name", "") if map_config is not None else ""
    day = 0
    time_str = "00:00"
    game_time = _float(getattr(save, "game_time", 0.0))
    if game_time:
        day = int(game_time // 86400)
        rem = int(game_time % 86400)
        time_str = f"{rem // 3600:02d}:{(rem % 3600) // 60:02d}"
    return {"map": map_name, "day": day, "time": time_str}


def _wrap_with_meta(
    data: list[dict[str, t.Any]],
    save: t.Any,
    map_config: MapConfig | None = None,
) -> dict[str, t.Any]:
    """Wrap a payload in the legacy ``{map, day, time, data}`` envelope.

    Retained for callers that already hold a materialized list (e.g. the
    validation harness diffing against legacy). :func:`export_to_files`
    streams via :func:`_stream_dump` instead and does not use this.
    """
    return {**_meta_head(save, map_config), "data": data}


def _stream_dump(
    fh: t.TextIO,
    head: dict[str, t.Any] | None,
    records: t.Iterable[dict[str, t.Any]],
    dump_kwargs: dict[str, t.Any],
) -> None:
    """Stream a JSON array to ``fh``, one record at a time.

    Writes a bare ``[records...]`` array when ``head`` is ``None``, otherwise
    splices the records into ``head`` under a ``"data"`` key
    (``{..head.., "data": [records...]}``). Each record is encoded and written
    individually, then released; the full record list never co-resides in
    memory. The result round-trips identically (at the value level) to
    ``json.dump(head | {"data": list(records)}, fh, **dump_kwargs)``; only
    insignificant whitespace differs.

    Pre-conditions: ``records`` is a finite iterable of JSON-serializable
    dicts; ``dump_kwargs`` carries the same ``indent`` / ``separators`` /
    ``default`` used elsewhere. Post-conditions: ``fh`` holds one complete,
    valid JSON document.
    """
    indent = dump_kwargs.get("indent")
    rec_kwargs: dict[str, t.Any] = {"default": dump_kwargs.get("default", str)}
    if indent:
        rec_kwargs["indent"] = indent
    else:
        rec_kwargs["separators"] = (",", ":")
    nl = "\n" if indent else ""
    if head is not None:
        head_json = json.dumps(head, **rec_kwargs)
        assert head_json.endswith("}"), "envelope head must serialize to a JSON object"
        # Splice the data array in just before the head object's closing brace
        # (indented dumps leave a trailing "\n}", compact a bare "}").
        fh.write(head_json[: -2 if indent else -1])
        fh.write(f',{nl}{" " * indent}"data": [' if indent else ',"data":[')
        rec_pad = " " * (indent * 2) if indent else ""
        close_pad = " " * indent if indent else ""
    else:
        fh.write("[")
        rec_pad = " " * indent if indent else ""
        close_pad = ""
    first = True
    for rec in records:
        chunk = json.dumps(rec, **rec_kwargs)
        if indent:
            chunk = rec_pad + chunk.replace("\n", "\n" + rec_pad)
        fh.write(("" if first else ",") + nl + chunk)
        first = False
    fh.write("]" if first else nl + close_pad + "]")
    if head is not None:
        fh.write(nl + "}")


def _load_cluster_inventories(
    cluster: str | Path | t.Iterable[CloudInventory] | None,
) -> list[CloudInventory]:
    """Resolve the ``cluster`` argument for :func:`export_all`.

    Accepts ``None`` (returns ``[]``), a directory path containing
    cluster files (loads every readable file), or any iterable of
    already-loaded :class:`CloudInventory` instances.
    """
    if cluster is None:
        return []
    if isinstance(cluster, (str, Path)):
        root = Path(cluster)
        if not root.is_dir():
            return []
        loaded: list[CloudInventory] = []
        for entry in root.iterdir():
            if not entry.is_file() or entry.stat().st_size == 0:
                continue
            try:
                loaded.append(CloudInventory.load(entry))
            except (OSError, ArkParseError) as e:
                # Skip unreadable/corrupt cluster files but record which one:
                # a silent drop hides every upload in that file and looks like
                # the player simply has no uploads. Unexpected errors propagate.
                logger.warning("Skipping cluster file %s: %s", entry, e)
                continue
        return loaded
    return [inv for inv in cluster if isinstance(inv, CloudInventory)]


def export_all(
    save: t.Any,
    map_config: MapConfig | None = None,
    cluster: str | Path | t.Iterable[CloudInventory] | None = None,
) -> dict[str, list[dict[str, t.Any]]]:
    """Run every exporter and return a dict keyed by ASV filename stems.

    With ``cluster`` set (a directory path or an iterable of
    :class:`CloudInventory` instances) the tamed export is automatically
    spliced with cluster-uploaded tames via :func:`export_cluster_uploads`,
    matching the legacy ASVExport behaviour when invoked with a cluster
    directory.

    Note: returns flat lists per type (not the legacy ``{map, day, time, data}``
    envelope). ``export_to_files`` adds the envelope when writing.
    """
    return {name: list(records) for name, records in _iter_exports(save, map_config, cluster)}


def _iter_exports(
    save: t.Any,
    map_config: MapConfig | None,
    cluster: str | Path | t.Iterable[CloudInventory] | None,
) -> t.Iterator[tuple[str, t.Iterable[dict[str, t.Any]]]]:
    """Yield ``(ASV_name, record_iterable)`` one export type at a time.

    The heavy types (tamed / wild / players / structures / map_structures)
    yield **lazy generators** so :func:`export_to_files` can stream each
    record to disk and release it; the full per-type list never
    materializes (it is the dominant export-time allocation on large PvE
    saves). The small types (tribes / tribe_logs) stay eager lists.
    :func:`export_all` wraps each iterable in ``list()`` for callers that
    want every record in memory.
    """
    cluster_invs = _load_cluster_inventories(cluster)
    cluster_tamed = export_cluster_uploads(cluster_invs, map_config) if cluster_invs else []
    yield _EXPORT_NAMES["tamed"], itertools.chain(_iter_tamed(save, map_config), cluster_tamed)
    yield _EXPORT_NAMES["wild"], _iter_wild(save, map_config)
    yield _EXPORT_NAMES["players"], _iter_players(save, map_config, cluster_invs or None)
    yield _EXPORT_NAMES["tribes"], export_tribes(save)
    yield _EXPORT_NAMES["structures"], _iter_structures(save, map_config)
    yield _EXPORT_NAMES["tribe_logs"], export_tribe_logs(save)
    yield _EXPORT_NAMES["map_structures"], _iter_map_structures(save, map_config)


def export_to_files(
    save: t.Any,
    output_dir: str | Path,
    map_config: MapConfig | None = None,
    wrap: bool = True,
    cluster: str | Path | t.Iterable[CloudInventory] | None = None,
    compact: bool = False,
) -> list[Path]:
    """Write every export to ``<output_dir>/<ASV_Name>.json``.

    With ``wrap=True`` (default) each file mirrors the legacy ASVExport.exe
    ``{"map":..., "day":..., "time":..., "data":[...]}`` envelope. Set
    ``wrap=False`` to write the flat list returned by the exporter functions.

    Passing ``cluster`` (a directory path or pre-loaded ``CloudInventory``
    instances) folds cluster-uploaded tames into ``ASV_Tamed.json``.

    With ``compact=True`` the JSON is serialized without indentation or
    inter-element spaces. Roughly halves output size on large maps and cuts
    serialization time meaningfully. Default ``False`` preserves the
    human-readable ``indent=2`` format for diff-friendly output.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    if compact:
        dump_kwargs: dict[str, t.Any] = {"separators": (",", ":"), "default": str}
    else:
        dump_kwargs = {"indent": 2, "default": str}
    # Stream each export type record-by-record straight to its file: a record
    # is built, encoded, written, then released. The full per-type list never
    # materializes and no whole-file JSON string is built; both were the
    # measured peak-RAM drivers on large PvE saves (the structures list alone
    # was hundreds of MB of nested inventory dicts).
    head = _meta_head(save, map_config) if wrap else None
    for name, records in _iter_exports(save, map_config, cluster):
        path = out / f"{name}.json"
        with path.open("w", encoding="utf-8") as fh:
            _stream_dump(fh, head, records, dump_kwargs)
        created.append(path)
    return created
