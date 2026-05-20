"""
Pytest configuration and fixtures for ARK Parser tests.

Fixture files are NOT committed to the repo (saves are large and version-
specific). Each path fixture below auto-skips its dependent tests when the
file is absent, so unit tests that don't need files still run.

To exercise file-dependent tests locally, drop the referenced saves into
``references/examples/`` matching the structure below.
"""

from pathlib import Path

import pytest

# Base paths
PROJECT_ROOT = Path(__file__).parent.parent
EXAMPLES_DIR = PROJECT_ROOT / "references" / "examples"

# ASE example paths
ASE_DIR = EXAMPLES_DIR / "ase"
ASE_OBELISK_FILE = ASE_DIR / "obelisk" / "2533274922942310"
ASE_PROFILE_FILE = ASE_DIR / "maps" / "extinction" / "2533274977850953.arkprofile"
ASE_TRIBE_FILE = ASE_DIR / "maps" / "extinction" / "1034325892.arktribe"
ASE_WORLDSAVE_FILE = ASE_DIR / "maps" / "extinction" / "Extinction.ark"
ASE_RAGNAROK_FILE = ASE_DIR / "maps" / "ragnarok" / "Ragnarok.ark"

# ASA example paths
ASA_DIR = EXAMPLES_DIR / "asa"
ASA_OBELISK_FILE = ASA_DIR / "obelisk" / "0002ca6114f04de882fe84c829849c13"
ASA_PROFILE_FILE = ASA_DIR / "maps" / "extinction" / "00020fa8fb0c41289b5f1e276cf3d291.arkprofile"
ASA_TRIBE_FILE = ASA_DIR / "maps" / "extinction" / "1033091962.arktribe"
ASA_WORLDSAVE_FILE = ASA_DIR / "maps" / "extinction" / "Extinction_WP.ark"

# Solecluster directories
ASE_SOLECLUSTER_DIR = ASE_DIR / "solecluster"
ASA_SOLECLUSTER_DIR = ASA_DIR / "solecluster"


def _path_or_skip(path: Path) -> Path:
    """Return ``path`` if present, else skip the requesting test."""
    if not path.exists():
        pytest.skip(f"Fixture not available: {path}")
    return path


@pytest.fixture
def ase_obelisk_path() -> Path:
    return _path_or_skip(ASE_OBELISK_FILE)


@pytest.fixture
def ase_profile_path() -> Path:
    return _path_or_skip(ASE_PROFILE_FILE)


@pytest.fixture
def ase_tribe_path() -> Path:
    return _path_or_skip(ASE_TRIBE_FILE)


@pytest.fixture
def asa_obelisk_path() -> Path:
    return _path_or_skip(ASA_OBELISK_FILE)


@pytest.fixture
def asa_profile_path() -> Path:
    return _path_or_skip(ASA_PROFILE_FILE)


@pytest.fixture
def asa_tribe_path() -> Path:
    return _path_or_skip(ASA_TRIBE_FILE)


@pytest.fixture
def ase_worldsave_path() -> Path:
    return _path_or_skip(ASE_WORLDSAVE_FILE)


@pytest.fixture
def ase_ragnarok_path() -> Path:
    return _path_or_skip(ASE_RAGNAROK_FILE)


@pytest.fixture
def asa_worldsave_path() -> Path:
    return _path_or_skip(ASA_WORLDSAVE_FILE)


@pytest.fixture
def ase_solecluster_dir() -> Path:
    return _path_or_skip(ASE_SOLECLUSTER_DIR)


@pytest.fixture
def asa_solecluster_dir() -> Path:
    return _path_or_skip(ASA_SOLECLUSTER_DIR)
