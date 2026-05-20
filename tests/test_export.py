"""Regression tests for export helpers against real parser objects."""

from pathlib import Path

import pytest

from arkparser import Profile, Tribe, WorldSave
from arkparser.export import (
    export_all,
    export_players,
    export_structures,
    export_tamed,
    export_to_files,
    export_tribe_logs,
    export_tribes,
    export_wild,
)

_EXAMPLES = Path(__file__).parent.parent / "references" / "examples"
_ASE_SCORCHED_EARTH = _EXAMPLES / "ase" / "maps" / "scorchedearth" / "ScorchedEarth_P.ark"

_ASV_NAMES = {
    "ASV_Tamed",
    "ASV_Wild",
    "ASV_Players",
    "ASV_Tribes",
    "ASV_Structures",
    "ASV_TribeLogs",
    "ASV_MapStructures",
}


@pytest.fixture(scope="session")
def ase_export_world_save() -> WorldSave:
    if not _ASE_SCORCHED_EARTH.exists():
        pytest.skip(f"Fixture not available: {_ASE_SCORCHED_EARTH}")
    return WorldSave.load(_ASE_SCORCHED_EARTH)


def test_export_tamed_matches_world_save(ase_export_world_save: WorldSave) -> None:
    exported = export_tamed(ase_export_world_save)
    assert len(exported) == len(ase_export_world_save.get_tamed_creatures())
    assert any(creature.get("name") == "escobar" for creature in exported)


def test_export_wild_matches_world_save(ase_export_world_save: WorldSave) -> None:
    exported = export_wild(ase_export_world_save)
    assert len(exported) == len(ase_export_world_save.get_wild_creatures())
    assert all(creature.get("tamer", "") == "" for creature in exported[:100])


def test_export_structures_matches_world_save(ase_export_world_save: WorldSave) -> None:
    exported = export_structures(ase_export_world_save)
    assert len(exported) == len(ase_export_world_save.get_structures())


def test_export_players_uses_profile_parser(ase_profile_path: Path) -> None:
    profile = Profile.load(ase_profile_path)
    exported = export_players(type("Holder", (), {"profiles": [profile]})())
    assert exported[0]["playerid"] == profile.player_id
    assert exported[0]["steam"] == profile.player_name
    assert exported[0]["name"] == profile.character_name
    assert exported[0]["sex"] == ("Female" if profile.is_female else "Male")
    assert exported[0]["tribeid"] == profile.tribe_id


def test_export_tribes_uses_tribe_parser(ase_tribe_path: Path) -> None:
    tribe = Tribe.load(ase_tribe_path)
    exported = export_tribes(type("Holder", (), {"tribes": [tribe]})())
    assert exported[0]["tribeid"] == tribe.tribe_id
    assert exported[0]["tribe"] == tribe.name
    assert exported[0]["players"] == tribe.member_count


def test_export_tribe_logs_uses_tribe_parser(ase_tribe_path: Path) -> None:
    tribe = Tribe.load(ase_tribe_path)
    exported = export_tribe_logs(type("Holder", (), {"tribes": [tribe]})())
    assert exported[0]["tribeid"] == tribe.tribe_id
    assert exported[0]["tribe"] == tribe.name
    assert exported[0]["logs"] == tribe.log_entries


def test_export_all_uses_asv_names(ase_export_world_save: WorldSave) -> None:
    exported = export_all(ase_export_world_save)
    assert set(exported) == _ASV_NAMES


def test_export_to_files_uses_asv_names(
    ase_export_world_save: WorldSave, tmp_path: Path
) -> None:
    created = export_to_files(ase_export_world_save, tmp_path)
    assert {path.name for path in created} == {f"{name}.json" for name in _ASV_NAMES}
