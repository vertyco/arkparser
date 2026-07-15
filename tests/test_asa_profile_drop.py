"""Regression tests for the ASA profile drop (~12% of the live PvE playerbase).

Two independent defects made ``Profile.load`` raise on real ASA profiles, and
because every consumer skips a profile that fails to parse, the affected players
survived only as tribe-file stubs with a blank EOS id, invisible to anything that
matches on that id.

1. A terminator-skip heuristic in the ASA object header sniffed the upcoming byte
   and consumed it when it was 0x00. For every object but the last that byte is
   the first byte of the *next* object's GUID, so ~1 in 256 profiles drifted one
   byte and died on a garbage string length.
2. ``EnumProperty`` (Unreal's scoped enum, carried by the Dragon Horn) had no
   reader, so any player holding one lost their whole profile.

Fixtures under ``asa_pve_rag_profiles`` are staged off a live server and are
gitignored, so every test that needs them skips cleanly when they are absent.
"""

from __future__ import annotations

import typing as t
from pathlib import Path
from uuid import UUID

import pytest

from arkparser import Profile
from arkparser.common.binary_reader import BinaryReader
from arkparser.common.exceptions import ArkParseError
from arkparser.properties import ByteProperty, EnumProperty
from arkparser.properties.base import PropertyHeader

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASA_DIR = PROJECT_ROOT / "references" / "local_saves" / "survival_ascended"
PVE_RAG_DIR = PROJECT_ROOT / "references" / "local_saves" / "asa_pve_rag_profiles"

# Reproduces defect 1 on its own: object 1's GUID starts with 0x00, so the old
# heuristic ate it. Lives in the regular ASA snapshot, so this guard holds even
# without the staged live fixtures.
DRIFT_FIXTURE = ASA_DIR / "ragnarok_wp" / "00025da8dfe647d08e8cc55dc09228df.arkprofile"

# Staged live fixtures, from the handoff. The 3 EnumProperty carriers, and the
# control that always parsed.
ENUM_FIXTURES = (
    "0002b4979928425cbfb0751cf6ba615d",
    "000233c5118447119bd608975a16e01b",
    "000258582e594c1f89aa8584833b5d26",
)
DRIFT_FIXTURES = (
    "00025da8dfe647d08e8cc55dc09228df",
    "000274f09cae4b05a8b819082498d46f",
    "00028651190a4946aaabe01f0172faca",
    "00029cac9b9741f489776a58d0f53e19",
)
CONTROL_FIXTURE = "0002009b5c8a46a996e2b651c290bcff"
ALL_FIXTURES = (*ENUM_FIXTURES, *DRIFT_FIXTURES, CONTROL_FIXTURE)

MAX_PROFILES = 100_000


def _staged(game_id: str) -> Path:
    path = PVE_RAG_DIR / f"{game_id}.arkprofile"
    if not path.is_file():
        pytest.skip(f"live PvE fixture not staged: {path.name}")
    return path


def _enum_props(profile: Profile) -> list[EnumProperty]:
    return [p for obj in profile.objects for p in obj.properties if isinstance(p, EnumProperty)]


def test_next_object_guid_starting_with_zero_still_parses() -> None:
    """A 0x00-leading GUID on a following object must not drift the reader.

    This is the whole of defect 1: the header block is fixed-width, so the byte
    after one header is the next header's first GUID byte, never a terminator to
    be consumed.
    """
    if not DRIFT_FIXTURE.is_file():
        pytest.skip(f"fixture not present: {DRIFT_FIXTURE}")

    profile = Profile.load(DRIFT_FIXTURE)

    assert len(profile.objects) == 2, "fixture should carry a player object plus a buff"
    # GUIDs are read little-endian, so the on-disk first byte is bytes_le[0].
    on_disk_first_byte = UUID(profile.objects[1].guid).bytes_le[0]
    assert on_disk_first_byte == 0x00, "fixture must keep its 0x00-leading GUID to be a regression"
    assert profile.unique_id, "player must resolve an EOS id, not a blank stub"


def test_every_local_asa_profile_parses() -> None:
    """No ASA profile in the local snapshot may fail to parse.

    Guards the class of bug rather than one fixture: both defects presented as a
    small, silent fraction of an otherwise healthy corpus.
    """
    if not ASA_DIR.is_dir():
        pytest.skip(f"ASA snapshot not present: {ASA_DIR}")

    files = sorted(ASA_DIR.glob("*/*.arkprofile"))
    if not files:
        pytest.skip("no ASA profiles on disk")
    assert len(files) < MAX_PROFILES, "profile count exceeded bound"

    failures: list[str] = []
    for path in files:
        try:
            Profile.load(path)
        except Exception as exc:  # noqa: BLE001 - collecting, so one bad file does not mask the rest
            failures.append(f"{path.parent.name}/{path.name}: {type(exc).__name__}: {exc}")

    assert not failures, f"{len(failures)} of {len(files)} ASA profiles failed to parse:\n  " + "\n  ".join(
        failures[:10]
    )


@pytest.mark.parametrize("game_id", ALL_FIXTURES)
def test_reported_fixture_loads_with_identity(game_id: str) -> None:
    """Every fixture from the handoff loads and resolves its EOS id.

    The blank id is what actually broke ``.mybase``: a stub carries no id, so the
    player can never be matched back to their tribe.
    """
    profile = Profile.load(_staged(game_id))

    assert profile.unique_id == game_id, f"EOS id should round-trip to the filename stem, got {profile.unique_id!r}"
    assert profile.level > 0, "a real profile has a level; 0 means a stub"


@pytest.mark.parametrize("game_id", ENUM_FIXTURES)
def test_dragon_horn_enum_property(game_id: str) -> None:
    """A Dragon Horn's LinkState decodes as a scoped enum.

    Wire layout differs from an enum-form ByteProperty by a nested tag naming the
    underlying storage type, so this pins the reader, not just the registration.
    """
    profile = Profile.load(_staged(game_id))

    enums = _enum_props(profile)
    assert enums, f"{game_id} should carry a Dragon Horn EnumProperty"

    for prop in enums:
        assert prop.type_name == "EnumProperty", "must not be reported as a ByteProperty"
        assert prop.is_enum is True
        assert prop.enum_name == "EDragonHornLinkState"
        assert prop.enum_value is not None
        assert prop.enum_value.startswith("EDragonHornLinkState::"), f"unexpected enum value {prop.enum_value!r}"
        assert prop.byte_value is None, "a scoped enum carries a name, not a raw byte"


def test_enum_property_is_a_byte_property_subclass() -> None:
    """``isinstance(prop, ByteProperty)`` must keep holding for existing consumers."""
    assert issubclass(EnumProperty, ByteProperty)
    assert EnumProperty.__slots__ == (), (
        "subclass must stay free per instance; ByteProperty is allocated in the millions"
    )


def test_enum_property_rejects_unverified_layouts() -> None:
    """ASE and worldsave EnumProperty layouts are unverified, so they must fail loudly.

    EnumProperty appears in no ASE fixture and in no ASA worldsave name table.
    Guessing a layout there would desync the stream silently; raising keeps the
    failure as loud as it was before the type existed.
    """
    header = PropertyHeader(name="LinkState", type_name="EnumProperty", data_size=2, index=0, position=21)
    reader = BinaryReader.from_bytes(b"\x00" * 64)

    with pytest.raises(ArkParseError, match="layout unverified"):
        EnumProperty.read(reader, header, is_asa=True, worldsave_format=True)
    with pytest.raises(ArkParseError, match="layout unverified"):
        EnumProperty.read(reader, header, is_asa=False)


def test_dragon_horn_stream_stays_aligned() -> None:
    """Properties after the EnumProperty must still decode.

    A wrong body length would not raise here, it would silently shift every later
    property, so assert on a known field that sits after the Dragon Horn.
    """
    profile = Profile.load(_staged(ENUM_FIXTURES[0]))

    assert _enum_props(profile), "fixture must actually carry the enum for this to prove alignment"
    stats: dict[str, t.Any] = profile._persistent_stats
    assert stats, "persistent character stats parse after the Dragon Horn, proving the reader stayed aligned"
    assert profile.level == 105, "known level for this fixture"
