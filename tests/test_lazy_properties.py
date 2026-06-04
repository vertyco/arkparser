"""Foundation tests for lazy property loading + eviction (ASE and ASA).

These exercise the primitives the chunked single-pass export is built on:

- ``WorldSave.load(..., lazy_properties=True)`` parses object headers but defers
  property blocks (ASE retains the file reader; ASA retains the SQLite
  connection and re-fetches row blobs by GUID).
- ``WorldSave.materialize_object(obj)`` loads one object's properties on demand,
  producing **exactly** what the eager pass produces.
- ``GameObject.evict_properties()`` releases them and they can be re-materialized.

The eager load is the oracle: lazy + materialize must match it property-for-property.
"""

from __future__ import annotations

import typing as t

import pytest

from arkparser import WorldSave

from .golden_manifest import build_manifest, diff_manifest, load_manifest
from .golden_targets import GOLDEN_DIR, discover_targets, load_target


def _first_with_prefix(prefix: str) -> t.Any:
    for name, ark in discover_targets():
        if name.startswith(prefix):
            return ark
    return None


_ASE = _first_with_prefix("ase_")
_ASA = _first_with_prefix("asa_")


def _props(obj: t.Any) -> list[tuple[t.Any, ...]]:
    """Comparable view of an object's parsed properties."""
    return [(p.name, p.index, p.type_name, repr(p.value)) for p in obj.properties]


@pytest.mark.skipif(_ASE is None, reason="no ASE save fixture present")
def test_lazy_materialize_matches_eager() -> None:
    eager = WorldSave.load(_ASE)
    lazy = WorldSave.load(_ASE, lazy_properties=True)

    assert len(lazy.objects) == len(eager.objects), "object count differs"
    assert lazy._lazy_reader is not None, "lazy reader not retained"
    # Properties are deferred until materialized.
    assert all(not o.properties for o in lazy.objects), "lazy load parsed properties eagerly"

    mismatches = 0
    materialized = 0
    for lazy_obj, eager_obj in zip(lazy.objects, eager.objects, strict=True):
        lazy.materialize_object(lazy_obj)
        if eager_obj.properties or lazy_obj.properties:
            materialized += 1
        if _props(lazy_obj) != _props(eager_obj):
            mismatches += 1

    assert mismatches == 0, f"{mismatches} objects had differing properties"
    assert materialized > 0, "no objects carried properties (fixture looks wrong)"


@pytest.mark.skipif(_ASE is None, reason="no ASE save fixture present")
def test_evict_then_rematerialize_roundtrips() -> None:
    lazy = WorldSave.load(_ASE, lazy_properties=True)
    # Find an object that actually has properties.
    target = None
    for obj in lazy.objects:
        lazy.materialize_object(obj)
        if obj.properties:
            target = obj
            break
    assert target is not None, "no property-bearing object found"

    before = _props(target)
    target.evict_properties()
    assert target.properties == [], "evict did not clear properties"
    assert target._prop_index is None, "evict did not clear prop index"

    lazy.materialize_object(target)
    assert _props(target) == before, "re-materialized properties differ from pre-evict"


@pytest.mark.skipif(_ASE is None, reason="no ASE save fixture present")
def test_lazy_export_matches_golden() -> None:
    """The full lazy+evict export must be content-identical to the eager oracle.

    Loads the smallest ASE map lazily, runs the real ``export_all`` pipeline
    (auto-materialize on access, drains after every record), and compares the
    resulting manifest to the committed golden produced by the eager path.
    """
    name = "ase_scorchedearth"
    ark = dict(discover_targets()).get(name)
    golden = load_manifest(GOLDEN_DIR / f"{name}.json")
    if ark is None or golden is None:
        pytest.skip(f"fixture or golden missing for {name}")

    save, map_config, obj_count = load_target(ark, lazy=True)
    actual = build_manifest(save, map_config, name, obj_count)
    problems = diff_manifest(golden, actual)
    assert not problems, "lazy export drift vs eager golden:\n  " + "\n  ".join(problems)


@pytest.mark.skipif(_ASA is None, reason="no ASA save fixture present")
def test_asa_lazy_materialize_matches_eager() -> None:
    eager = WorldSave.load(_ASA)
    lazy = WorldSave.load(_ASA, lazy_properties=True)

    assert len(lazy.objects) == len(eager.objects), "object count differs"
    assert lazy._lazy_conn is not None, "lazy SQLite connection not retained"
    assert all(not o.properties for o in lazy.objects), "lazy load parsed properties eagerly"

    mismatches = 0
    materialized = 0
    for lazy_obj, eager_obj in zip(lazy.objects, eager.objects, strict=True):
        lazy_obj._ensure_loaded()
        if eager_obj.properties or lazy_obj.properties:
            materialized += 1
        if _props(lazy_obj) != _props(eager_obj):
            mismatches += 1
        lazy.evict_materialized()

    assert mismatches == 0, f"{mismatches} objects had differing properties"
    assert materialized > 0, "no objects carried properties (fixture looks wrong)"
    assert lazy._parse_errors == eager._parse_errors, "parse error lists differ"


@pytest.mark.skipif(_ASA is None, reason="no ASA save fixture present")
def test_asa_evict_then_rematerialize_roundtrips() -> None:
    lazy = WorldSave.load(_ASA, lazy_properties=True)
    target = None
    for obj in lazy.objects:
        if obj._lazy_source is None:
            continue
        lazy.materialize_object(obj)
        if obj.properties:
            target = obj
            break
    assert target is not None, "no property-bearing object found"

    before = _props(target)
    target.evict_properties()
    assert target.properties == [], "evict did not clear properties"

    lazy.materialize_object(target)
    assert _props(target) == before, "re-materialized properties differ from pre-evict"


@pytest.mark.skipif(_ASA is None, reason="no ASA save fixture present")
def test_asa_lazy_export_matches_golden() -> None:
    """Full ASA lazy+evict export must be content-identical to the eager oracle."""
    name = "asa_scorchedearth_wp"
    ark = dict(discover_targets()).get(name)
    golden = load_manifest(GOLDEN_DIR / f"{name}.json")
    if ark is None or golden is None:
        pytest.skip(f"fixture or golden missing for {name}")

    save, map_config, obj_count = load_target(ark, lazy=True)
    actual = build_manifest(save, map_config, name, obj_count)
    problems = diff_manifest(golden, actual)
    assert not problems, "ASA lazy export drift vs eager golden:\n  " + "\n  ".join(problems)
