"""Regression tests for export helpers against real parser objects."""

import datetime as dt
import os
import shutil
import typing as t
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


def test_export_tribes_active_falls_back_to_file_mtime(tmp_path: Path) -> None:
    """With no member login data, ``active`` falls back to the .arktribe
    file's write time (D1-b: login wins when present, file date otherwise).
    The last_member_login fields stay null and are still emitted."""
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
    assert rec["last_member_login"] is None
    assert rec["last_member_login_player_id"] is None
    assert rec["last_member_login_game_seconds"] is None


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
    """A LastLoginTime past the world's game clock is dropped on the
    game_time rule: even with file_mtime pushed weeks into the past (so the
    anchored candidate lands before now and the old real-domain filter would
    keep it), the member is dropped and game_seconds never goes negative."""
    profile = _profile_with_last_login()
    local_tz = dt.datetime.now().astimezone().tzinfo
    stale_mtime = dt.datetime.now(tz=local_tz) - dt.timedelta(weeks=6)
    game_time = max(float(profile.last_login_time) - 100_000_000.0, 1.0)
    holder = type(
        "Holder",
        (),
        {"tribes": [], "profiles": [profile], "file_mtime": stale_mtime, "game_time": game_time},
    )()
    exported = export_tribes(holder)
    rec = next(r for r in exported if r["tribeid"] == profile.player_id)
    assert rec.get("active") is None
    assert rec["last_member_login"] is None
    assert rec["last_member_login_game_seconds"] is None


def test_allocate_profiles_ignores_stale_profile_tribe_id() -> None:
    """A profile whose TribeID names a tribe that no longer lists the player
    in its member roster must NOT be allocated to that tribe (the game leaves
    TribeID stale in profiles of members removed while offline). It falls
    through to a solo tribe keyed on the player id."""
    from arkparser.export import _allocate_profiles

    current = t.cast(Profile, type("P", (), {"player_id": 1, "raw_tribe_id": 555})())
    stale = t.cast(Profile, type("P", (), {"player_id": 987, "raw_tribe_id": 555})())
    member_index = {1: 555, 2: 555}
    tribe_members = {555: {1, 2}}
    profile_tribeid, players_by_tribe = _allocate_profiles(
        [current, stale], {555}, member_index, tribe_members
    )
    assert profile_tribeid[1] == 555
    assert profile_tribeid[987] == 987
    assert players_by_tribe[555] == [1]
    assert players_by_tribe[987] == [987]


def test_allocate_profiles_member_list_still_wins_without_explicit_id() -> None:
    """A profile with no usable TribeID but present in a tribe's roster is
    still allocated to that tribe via the member-list fallback."""
    from arkparser.export import _allocate_profiles

    prof = t.cast(Profile, type("P", (), {"player_id": 2, "raw_tribe_id": 0})())
    profile_tribeid, players_by_tribe = _allocate_profiles(
        [prof], {555}, {2: 555}, {555: {2}}
    )
    assert profile_tribeid[2] == 555
    assert players_by_tribe[555] == [2]


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


def test_profile_actives_returns_anchored_and_raw_maps() -> None:
    """_profile_actives yields both the anchored datetime map (legacy) and a
    raw LastLoginTime seconds map keyed by player id."""
    from arkparser.export import _profile_actives

    profile = _profile_with_last_login()
    local_tz = dt.datetime.now().astimezone().tzinfo
    now = dt.datetime.now(tz=local_tz)
    game_time = float(profile.last_login_time) + 3_600.0
    holder = type("Holder", (), {"file_mtime": now, "game_time": game_time})()
    anchored, raw = _profile_actives([profile], holder)
    pid = int(profile.player_id)
    assert pid in anchored and pid in raw
    assert raw[pid] == pytest.approx(float(profile.last_login_time))
    assert isinstance(anchored[pid], dt.datetime)


def test_tribe_last_login_game_domain_argmax() -> None:
    """Winner is the max raw LastLoginTime <= game_time; all three outputs
    describe that one member; game_seconds is a non-negative int."""
    from arkparser.export import _tribe_last_login

    local_tz = dt.datetime.now().astimezone().tzinfo
    t1 = dt.datetime(2024, 1, 1, tzinfo=local_tz)
    t2 = dt.datetime(2024, 6, 1, tzinfo=local_tz)
    anchored = {1: t1, 2: t2}
    raw = {1: 1_000.0, 2: 5_000.5}
    iso, pid, secs = _tribe_last_login([1, 2], anchored, raw, 9_000.0)
    assert pid == 2
    assert iso == t2.isoformat()
    assert secs == 3_999  # int(9000.0 - 5000.5) floors, stays int
    assert isinstance(secs, int) and not isinstance(secs, bool)


def test_tribe_last_login_drops_future_on_game_time_not_wall_clock() -> None:
    """A login past the world's game clock is dropped, not clamped, even when
    its anchored datetime lands safely in the past (stale-mtime case the
    real-domain filter gets wrong). Never emits negative game_seconds."""
    from arkparser.export import _tribe_last_login

    local_tz = dt.datetime.now().astimezone().tzinfo
    long_ago = dt.datetime(2020, 1, 1, tzinfo=local_tz)
    iso, pid, secs = _tribe_last_login([7], {7: long_ago}, {7: 10_000.0}, 9_000.0)
    assert (iso, pid, secs) == (None, None, None)


def test_tribe_last_login_zero_and_no_data() -> None:
    """Login exactly at the snapshot gives game_seconds == 0 (a real value,
    distinct from null); empty inputs and game_time <= 0 give all-None."""
    from arkparser.export import _tribe_last_login

    local_tz = dt.datetime.now().astimezone().tzinfo
    stamp = dt.datetime(2024, 3, 1, tzinfo=local_tz)
    iso, pid, secs = _tribe_last_login([3], {3: stamp}, {3: 9_000.0}, 9_000.0)
    assert (pid, secs) == (3, 0)
    assert iso == stamp.isoformat()
    assert _tribe_last_login([], {}, {}, 9_000.0) == (None, None, None)
    assert _tribe_last_login([3], {3: stamp}, {3: 9_000.0}, 0.0) == (None, None, None)


def test_tribe_last_login_iso_none_when_anchor_missing() -> None:
    """No anchored datetime (save had no usable mtime) still yields player_id
    and game_seconds; only the ISO is None."""
    from arkparser.export import _tribe_last_login

    iso, pid, secs = _tribe_last_login([4], {}, {4: 2_500.0}, 9_000.0)
    assert (iso, pid, secs) == (None, 4, 6_500)


def test_file_date_iso_past_only() -> None:
    """_file_date_iso emits past datetimes as ISO and drops future or
    non-datetime values."""
    from arkparser.export import _file_date_iso

    local_tz = dt.datetime.now().astimezone().tzinfo
    past = dt.datetime.now(tz=local_tz) - dt.timedelta(days=1)
    future = dt.datetime.now(tz=local_tz) + dt.timedelta(days=1)
    assert _file_date_iso(past) == past.isoformat()
    assert _file_date_iso(future) is None
    assert _file_date_iso(None) is None
    assert _file_date_iso("2024-01-01") is None


def test_export_tribes_last_login_ignores_world_save_mtime() -> None:
    """The claim the feature rests on: vary save.file_mtime across two
    exports of the same fixture; game_seconds and player_id are identical,
    only the anchored ISO fields (last_member_login, active) move."""
    profile = _profile_with_last_login()
    local_tz = dt.datetime.now().astimezone().tzinfo
    now = dt.datetime.now(tz=local_tz)
    game_time = float(profile.last_login_time) + 3_600.0

    def _export_with_mtime(mtime: dt.datetime) -> dict[str, t.Any]:
        holder = type(
            "Holder",
            (),
            {"tribes": [], "profiles": [profile], "file_mtime": mtime, "game_time": game_time},
        )()
        recs = export_tribes(holder)
        return next(r for r in recs if r["tribeid"] == profile.player_id)

    a = _export_with_mtime(now)
    b = _export_with_mtime(now - dt.timedelta(weeks=3))
    assert a["last_member_login_game_seconds"] == b["last_member_login_game_seconds"] == 3_600
    assert a["last_member_login_player_id"] == b["last_member_login_player_id"] == profile.player_id
    assert a["last_member_login"] != b["last_member_login"]
    assert a["active"] != b["active"]
    assert isinstance(a["last_member_login_game_seconds"], int)
    assert not isinstance(a["last_member_login_game_seconds"], bool)


def test_export_tribes_solo_login_fields_match_active() -> None:
    """Solo/profile-only tribe: active == last_member_login (D1-b, login
    wins), player_id names the member, game_seconds matches the offset."""
    profile = _profile_with_last_login()
    local_tz = dt.datetime.now().astimezone().tzinfo
    now = dt.datetime.now(tz=local_tz)
    game_time = float(profile.last_login_time) + 3_600.0
    holder = type(
        "Holder",
        (),
        {"tribes": [], "profiles": [profile], "file_mtime": now, "game_time": game_time},
    )()
    rec = next(r for r in export_tribes(holder) if r["tribeid"] == profile.player_id)
    assert rec["active"] == rec["last_member_login"]
    assert rec["last_member_login_player_id"] == profile.player_id
    assert rec["last_member_login_game_seconds"] == 3_600


def test_export_tribes_all_stub_tribe_login_fields_null() -> None:
    """A tribe whose allocated players are all profile-less stubs yields null
    login fields (never inherits a file date), and the keys still emit."""
    tribe_path = _first_dump_file("*.arktribe")
    tribe = Tribe.load(tribe_path)
    if not tribe.get_members():
        pytest.skip("fixture tribe has no members to stub")
    local_tz = dt.datetime.now().astimezone().tzinfo
    now = dt.datetime.now(tz=local_tz)
    holder = type(
        "Holder",
        (),
        {"tribes": [tribe], "profiles": [], "file_mtime": now, "game_time": 5_000.0},
    )()
    rec = next(r for r in export_tribes(holder) if r["tribeid"] == tribe.tribe_id)
    assert "last_member_login" in rec and rec["last_member_login"] is None
    assert "last_member_login_player_id" in rec
    assert "last_member_login_game_seconds" in rec
    assert rec["last_member_login_game_seconds"] is None
