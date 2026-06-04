"""Discovery + loading of the local save fixtures used by the golden suite.

Mirrors the loading pipeline in ``references/scripts/validate_exports.py``
(WorldSave + sibling ``.arkprofile`` / ``.arktribe`` files, wrapped so the
exporters see ``profiles`` / ``tribes``) but **without** the NAS cluster. The
cluster lives off-repo and may be unmounted, which would make goldens
non-deterministic. Cluster splicing is covered separately by ``test_cloud_*``
and ``test_cluster_*``.

Test glue, not a parser hot path → Pythonic style (a ``__getattr__`` proxy is
used here, which the parser core forbids; see CLAUDE.md).

A *target* is one ``(name, ark_path)`` pair. ``name`` is also the golden file
stem (``tests/golden/<name>.json``) and the manifest's ``target`` label.
"""

from __future__ import annotations

import typing as t
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVOLVED_DIR = PROJECT_ROOT / "references" / "map_dumps" / "evolved"
ASA_DIR = PROJECT_ROOT / "references" / "local_saves" / "survival_ascended"
GOLDEN_DIR = PROJECT_ROOT / "tests" / "golden"

MAX_TARGETS = 256


class SaveWithFiles:
    """Glue ``WorldSave`` with its profiles + tribes for the exporters.

    The exporters read ``save.profiles`` / ``save.tribes`` for player + tribe
    data and fall back to every other attribute on the underlying save.
    """

    def __init__(self, save: t.Any, profiles: list[t.Any], tribes: list[t.Any]):
        assert profiles is not None and tribes is not None, "lists required"
        self._save = save
        self.profiles = profiles
        self.tribes = tribes

    def __getattr__(self, name: str) -> t.Any:  # noqa: D401 - proxy
        return getattr(self._save, name)


def discover_targets() -> list[tuple[str, Path]]:
    """Return sorted ``(name, ark_path)`` for every present local save.

    ASE maps live under ``references/map_dumps/evolved/<map>/<X>.ark``; ASA maps
    under ``references/local_saves/survival_ascended/<map>_wp/<X>_WP.ark``.
    Absent dirs are silently skipped so the suite degrades to whatever the
    machine actually has on disk.
    """
    targets: list[tuple[str, Path]] = []
    if EVOLVED_DIR.is_dir():
        for sub in sorted(p for p in EVOLVED_DIR.iterdir() if p.is_dir()):
            arks = sorted(sub.glob("*.ark"))
            if arks:
                targets.append((f"ase_{sub.name}", arks[0]))
    if ASA_DIR.is_dir():
        for sub in sorted(p for p in ASA_DIR.iterdir() if p.is_dir()):
            arks = sorted(sub.glob("*_WP.ark"))
            if arks:
                targets.append((f"asa_{sub.name}", arks[0]))
    assert len(targets) < MAX_TARGETS, "target count exceeded bound"
    return targets


def load_profiles(map_dir: Path) -> list[t.Any]:
    """Load every ``.arkprofile`` beside the save; skip ones that fail to parse."""
    from arkparser import Profile

    out: list[t.Any] = []
    files = sorted(map_dir.glob("*.arkprofile"))
    for i, path in enumerate(files):
        assert i < MAX_TARGETS * 4096, "profile count exceeded bound"
        try:
            out.append(Profile.load(path))
        except Exception:  # noqa: BLE001 - corrupt fixture must not abort the run
            continue
    return out


def load_tribes(map_dir: Path) -> list[t.Any]:
    """Load every ``.arktribe`` beside the save, de-duplicated by stem."""
    from arkparser import Tribe

    out: list[t.Any] = []
    seen: set[str] = set()
    files = sorted(map_dir.glob("*.arktribe"))
    for i, path in enumerate(files):
        assert i < MAX_TARGETS * 4096, "tribe count exceeded bound"
        if path.stem in seen:
            continue
        try:
            out.append(Tribe.load(path))
            seen.add(path.stem)
        except Exception:  # noqa: BLE001
            continue
    return out


def load_target(ark_path: Path, lazy: bool = False) -> tuple[t.Any, t.Any, int]:
    """Load a save target → ``(wrapped_save, map_config, object_count)``.

    ``lazy=True`` loads ASE saves with deferred property parsing
    (``lazy_properties``) so the golden suite can prove the lazy+evict export
    path produces content-identical output to the eager oracle.
    """
    from arkparser import WorldSave, get_map_config

    assert ark_path.exists(), f"save not found: {ark_path}"
    save = WorldSave.load(ark_path, lazy_properties=lazy)
    profiles = load_profiles(ark_path.parent)
    tribes = load_tribes(ark_path.parent)
    try:
        map_config = get_map_config(ark_path.name)
    except Exception:  # noqa: BLE001 - unknown map name → no GPS config
        map_config = None
    wrapped = SaveWithFiles(save, profiles, tribes)
    return wrapped, map_config, int(getattr(save, "object_count", 0))
