"""Regression tests for export helpers against real parser objects."""

import datetime as dt
import os
import shutil
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
_MAP_DUMP_EXTINCTION = Path(__file__).parent.parent / "references" / "map_dumps" / "evolved" / "extinction"


def _first_dump_file(pattern: str) -> Path:
    """First map-dump fixture matching ``pattern``, else skip the test."""
    if _MAP_DUMP_EXTINCTION.is_dir():
        files = sorted(_MAP_DUMP_EXTINCTION.glob(pattern))
        if files:
            return files[0]
    pytest.skip(f"no {pattern} fixture under {_MAP_DUMP_EXTINCTION}")


def _profile_with_last_login() -> Profile:
    """First map-dump profile carrying LastLoginTime, else skip the test."""
    if _MAP_DUMP_EXTINCTION.is_dir():
        for path in sorted(_MAP_DUMP_EXTINCTION.glob("*.arkprofile"))[:50]:
            try:
                profile = Profile.load(path)
            except Exception:  # noqa: BLE001 - corrupt fixture must not abort
                continue
            if profile.last_login_time and profile.player_id:
                return profile
    pytest.skip(f"no profile with LastLoginTime under {_MAP_DUMP_EXTINCTION}")

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


def test_export_tribes_active_is_file_mtime(tmp_path: Path) -> None:
    """Tribe ``active`` mirrors legacy ContentTribe.LastActive: the .arktribe
    file's write time, never a value derived from in-game log day numbers
    (those use the game calendar, not real seconds, and produced far-future
    dates)."""
    tribe_path = _first_dump_file("*.arktribe")
    copy = tmp_path / tribe_path.name
    shutil.copy2(tribe_path, copy)
    local_tz = dt.datetime.now().astimezone().tzinfo
    stamp = dt.datetime(2024, 5, 1, 12, 0, 0, tzinfo=local_tz)
    os.utime(copy, (stamp.timestamp(), stamp.timestamp()))
    tribe = Tribe.load(copy)
    now = dt.datetime.now(tz=local_tz)
    holder = type("Holder", (), {"tribes": [tribe], "file_mtime": now, "game_time": 5_000.0})()
    exported = export_tribes(holder)
    rec = next(r for r in exported if r["tribeid"] == tribe.tribe_id)
    assert rec["active"] is not None
    active = dt.datetime.fromisoformat(rec["active"])
    assert active.timestamp() == pytest.approx(stamp.timestamp(), abs=2)
    assert active <= now


def test_export_tribes_solo_active_from_profile_last_login() -> None:
    """A profile-only (solo) tribe gets ``active`` from the member's
    LastLoginTime converted through the save anchor, matching legacy
    ContentTribe.LastActive over allocated players."""
    profile = _profile_with_last_login()
    local_tz = dt.datetime.now().astimezone().tzinfo
    now = dt.datetime.now(tz=local_tz)
    game_time = float(profile.last_login_time) + 3_600.0
    holder = type(
        "Holder",
        (),
        {"tribes": [], "profiles": [profile], "file_mtime": now, "game_time": game_time},
    )()
    exported = export_tribes(holder)
    rec = next(r for r in exported if r["tribeid"] == profile.player_id)
    assert rec["active"] is not None
    active = dt.datetime.fromisoformat(rec["active"])
    expected = now - dt.timedelta(seconds=3_600)
    assert active.timestamp() == pytest.approx(expected.timestamp(), abs=2)


def test_export_tribes_active_never_future() -> None:
    """Future candidates are discarded (legacy filters d <= DateTime.Now)."""
    profile = _profile_with_last_login()
    local_tz = dt.datetime.now().astimezone().tzinfo
    now = dt.datetime.now(tz=local_tz)
    game_time = max(float(profile.last_login_time) - 100_000_000.0, 1.0)
    holder = type(
        "Holder",
        (),
        {"tribes": [], "profiles": [profile], "file_mtime": now, "game_time": game_time},
    )()
    exported = export_tribes(holder)
    rec = next(r for r in exported if r["tribeid"] == profile.player_id)
    assert rec["active"] is None


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
