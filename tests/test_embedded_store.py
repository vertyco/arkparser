"""Tests for the player/tribe store packed inside ASA world saves.

Layout tests build stores in an in-memory SQLite database and need no files.
Content tests pack real sidecar files from the ScorchedEarth reference bundle
(skipped when absent). The real Nitrado sample is local-only and never
committed: it holds a third party's player data.
"""

import shutil
import sqlite3
import struct
from pathlib import Path

import pytest

from arkparser import EmbeddedStore, Profile, Tribe, WorldSave, export_all
from arkparser.files.embedded_store import STORE_KEY, load_embedded_store

ASA_SAVES = Path(__file__).parent.parent / "references" / "local_saves" / "survival_ascended"
SCORCHED_DIR = ASA_SAVES / "scorchedearth_wp"
# Outside survival_ascended/ so the golden suite never discovers it.
NITRADO_SAMPLE = ASA_SAVES.parent / "third_party" / "nitrado_store_ragnarok" / "Ragnarok_WP.ark"

Entry = tuple[bytes, bytes]  # (8-byte key, packed file bytes)


def pack_section(entries: list[Entry]) -> bytes:
    """One section: size, count, files back to back, then the index."""
    files = b"".join(data for _, data in entries)
    index = b""
    offset = 0
    for key, data in entries:
        index += struct.pack("<8sii", key, offset, len(data))
        offset += len(data)
    return struct.pack("<2i", len(files), len(entries)) + files + index


def pack_store(*sections: bytes, fmt: int = 1, terminator: bool = True) -> bytes:
    return struct.pack("<i", fmt) + b"".join(sections) + (b"\x00" * 8 if terminator else b"")


def store_db(blob: bytes | None) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE custom (key VARCHAR(64) primary key not null, value blob not null)")
    if blob is not None:
        conn.execute("INSERT INTO custom VALUES (?, ?)", (STORE_KEY, blob))
    return conn


def key(n: int) -> bytes:
    return struct.pack("<q", n)


# ---------------------------------------------------------------- layout


@pytest.mark.parametrize("blob", [None, b"\x00" * 20, b"\x00" * 28, b"\x01" * 8])
def test_missing_or_tiny_store_is_empty(blob: bytes | None) -> None:
    store = load_embedded_store(store_db(blob))
    assert (store.profiles, store.tribes, store.errors) == ([], [], [])


def test_unknown_format_reports_one_error() -> None:
    store = load_embedded_store(store_db(pack_store(pack_section([]), fmt=2)))
    assert store.tribes == [] and len(store.errors) == 1
    assert "format 2" in store.errors[0]


def test_truncated_index_reports_one_error() -> None:
    blob = pack_store(pack_section([(key(1), b"x" * 40)]), terminator=False)[:-8]
    store = load_embedded_store(store_db(blob))
    assert store.tribes == [] and len(store.errors) == 1


def test_missing_terminator_reports_one_error() -> None:
    blob = pack_store(pack_section([(key(1), b"z" * 40)]), terminator=False)
    store = load_embedded_store(store_db(blob))
    assert len(store.errors) == 1


def test_too_many_sections_reports_one_error() -> None:
    section = pack_section([(key(1), b"y" * 40)])
    store = load_embedded_store(store_db(pack_store(section, section, section, section)))
    assert store.tribes == [] and len(store.errors) == 1
    assert "sections" in store.errors[0]


def test_unknown_section_content_is_skipped() -> None:
    junk = b"\x07\x00\x00\x00" + b"\x00" * 28 + struct.pack("<i", 8) + b"Unknown\x00"
    store = load_embedded_store(store_db(pack_store(pack_section([(key(1), junk)]))))
    assert store.tribes == [] and store.profiles == []
    assert store.errors == ["section 0: unknown content, skipped"]


def test_ase_save_has_no_store() -> None:
    assert WorldSave().read_embedded_store() == EmbeddedStore()


# ---------------------------------------------------------------- content


@pytest.fixture
def scorched_sidecars() -> tuple[list[bytes], list[bytes]]:
    if not SCORCHED_DIR.exists():
        pytest.skip(f"Fixture not available: {SCORCHED_DIR}")
    tribes = [p.read_bytes() for p in sorted(SCORCHED_DIR.glob("*.arktribe"))[:2]]
    profiles = [p.read_bytes() for p in sorted(SCORCHED_DIR.glob("*.arkprofile"))[:3]]
    assert len(tribes) == 2 and len(profiles) == 3
    return tribes, profiles


def build_blob(tribes: list[bytes], profiles: list[bytes]) -> bytes:
    """Store with one stale (zero-key) copy per section ahead of the live ones."""
    zero = b"\x00" * 8
    tribe_entries = [(zero, tribes[0])] + [(key(i + 1), data) for i, data in enumerate(tribes)]
    profile_entries = [(zero, profiles[0])] + [(key(i + 10), data) for i, data in enumerate(profiles)]
    return pack_store(pack_section(tribe_entries), pack_section(profile_entries))


def test_current_entries_load(scorched_sidecars: tuple[list[bytes], list[bytes]]) -> None:
    tribes, profiles = scorched_sidecars
    store = load_embedded_store(store_db(build_blob(tribes, profiles)))
    assert store.errors == []
    assert (len(store.tribes), len(store.profiles)) == (2, 3)
    assert (store.superseded_tribes, store.superseded_profiles) == (1, 1)
    assert {t.tribe_id for t in store.tribes} == {Tribe.load(b).tribe_id for b in tribes}
    assert {p.unique_id for p in store.profiles} == {Profile.load(b).unique_id for b in profiles}
    assert all(p.source_path is None for p in store.profiles)


def test_duplicate_live_entries_keep_the_last(scorched_sidecars: tuple[list[bytes], list[bytes]]) -> None:
    tribes = scorched_sidecars[0]
    section = pack_section([(key(1), tribes[0]), (key(2), tribes[0])])
    store = load_embedded_store(store_db(pack_store(section)))
    assert len(store.tribes) == 1 and store.errors == []


def test_bad_entry_is_skipped_rest_load(scorched_sidecars: tuple[list[bytes], list[bytes]]) -> None:
    tribes = scorched_sidecars[0]
    good = pack_section([(key(1), tribes[0]), (key(2), tribes[1])])
    # Point the second index entry past the end of the section's data.
    bad_offset = len(good) - 8
    broken = good[:bad_offset] + struct.pack("<ii", 10_000_000, 64)
    store = load_embedded_store(store_db(pack_store(broken)))
    assert len(store.tribes) == 1
    assert len(store.errors) == 1 and store.errors[0].startswith("tribe #1:")


def minimal_save(tmp_path: Path, blob: bytes) -> Path:
    """An ASA save with a real SaveHeader, no objects, and the given store."""
    src = next(SCORCHED_DIR.glob("*_WP.ark"))
    with sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True) as ref:
        header = ref.execute("SELECT value FROM custom WHERE key = 'SaveHeader'").fetchone()[0]
    path = tmp_path / "Store_WP.ark"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE game (key BLOB primary key not null, value blob not null)")
    conn.execute("CREATE TABLE custom (key VARCHAR(64) primary key not null, value blob not null)")
    conn.executemany("INSERT INTO custom VALUES (?, ?)", [("SaveHeader", header), (STORE_KEY, blob)])
    conn.commit()
    conn.close()
    return path


@pytest.mark.parametrize("lazy", [False, True])
def test_world_save_reads_store_and_exports(
    tmp_path: Path, scorched_sidecars: tuple[list[bytes], list[bytes]], lazy: bool
) -> None:
    tribes, profiles = scorched_sidecars
    save = WorldSave.load(minimal_save(tmp_path, build_blob(tribes, profiles)), lazy_properties=lazy)
    store = save.read_embedded_store()
    assert (len(store.tribes), len(store.profiles), store.errors) == (2, 3, [])
    save.tribes, save.profiles = store.tribes, store.profiles
    data = export_all(save)
    # Tribe members without a profile also get player rows, so check inclusion.
    exported_ids = {str(r["playerid"]) for r in data["ASV_Players"]}
    assert {str(p.player_id) for p in store.profiles} <= exported_ids
    assert {r["tribeid"] for r in data["ASV_Tribes"]} >= {t.tribe_id for t in store.tribes}
    if save._lazy_conn is not None:
        save._lazy_conn.close()


# ---------------------------------------------------------------- real sample


def test_nitrado_sample(tmp_path: Path) -> None:
    if not NITRADO_SAMPLE.exists():
        pytest.skip(f"Local-only sample not available: {NITRADO_SAMPLE}")
    copy = Path(shutil.copy2(NITRADO_SAMPLE, tmp_path / NITRADO_SAMPLE.name))
    save = WorldSave.load(copy, lazy_properties=True)
    store = save.read_embedded_store()
    assert (len(store.tribes), len(store.profiles)) == (6, 8)
    assert (store.superseded_tribes, store.superseded_profiles) == (13, 14)
    save.tribes, save.profiles = store.tribes, store.profiles
    logs = export_all(save)["ASV_TribeLogs"]
    assert sum(len(r.get("logs") or []) for r in logs) == 835
    assert save._lazy_conn is not None
    save._lazy_conn.close()
