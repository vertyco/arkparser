"""
Comprehensive tests for WorldSave parsing across multiple maps and formats.

Baselines (verified against reference example save files):

    ASE Aberration   – objects=111192, tamed=190,  wild=17142,  pawns=72
                     terminals=4,  artifacts=3,  resources=172
    ASE Extinction   – objects=83965,  tamed=70,   wild=14855,  pawns=99
                     terminals=32, artifacts=3,  resources=27
    ASE Fjordur      – objects=171866, tamed=338,  wild=28161,  pawns=130
                     terminals=15, artifacts=10, resources=91
    ASE LostIsland   – objects=257402, tamed=622,  wild=39847,  pawns=159
                     terminals=3,  artifacts=11, resources=22
    ASE Ragnarok     – objects=212071, tamed=254,  wild=26251,  pawns=193
                     terminals=3,  artifacts=11, resources=161
    ASE ScorchedEarth– objects=54495,  tamed=37,   wild=12169,  pawns=54
                     terminals=3,  artifacts=3,  resources=71
    ASE TheCenter    – objects=195269, tamed=247,  wild=33704,  pawns=98
                     terminals=3,  artifacts=11, resources=55
    ASE TheIsland    – objects=204107, tamed=300,  wild=26556,  pawns=162
                     terminals=4,  artifacts=10, resources=19
    ASE Valguero     – objects=220397, tamed=328,  wild=32616,  pawns=116
                     terminals=3,  artifacts=10, resources=135

    ASA Aberration   – objects=95743,  tamed=126,  wild=16415,  pawns=61
                     terminals=4,  artifacts=3,  resources=169
    ASA Center       – objects=310439, tamed=432,  wild=38330,  pawns=113
                     terminals=3,  artifacts=11, resources=79
    ASA Extinction   – objects=128751, tamed=184,  wild=16042,  pawns=67
                     terminals=31, artifacts=3,  resources=18
    ASA Valguero     – objects=224929, tamed=418,  wild=36780,  pawns=79
                     terminals=3,  artifacts=10, resources=85
"""

from pathlib import Path

import pytest

from arkparser import WorldSave
from arkparser.game_objects.game_object import GameObject
from arkparser.game_objects.location import LocationData
from arkparser.export import _ancestor_parent, _combine_dino_id

_EXAMPLES = Path(__file__).parent.parent / "references" / "examples"

# ASE paths
_ASE = _EXAMPLES / "ase" / "maps"
_ASE_ABERRATION = _ASE / "aberration" / "Aberration_P.ark"
_ASE_EXTINCTION = _ASE / "extinction" / "Extinction.ark"
_ASE_FJORDUR = _ASE / "fjordur" / "Fjordur.ark"
_ASE_LOSTISLAND = _ASE / "lostisland" / "LostIsland.ark"
_ASE_RAGNAROK = _ASE / "ragnarok" / "Ragnarok.ark"
_ASE_SCORCHEDEARTH = _ASE / "scorchedearth" / "ScorchedEarth_P.ark"
_ASE_THECENTER = _ASE / "thecenter" / "TheCenter.ark"
_ASE_THEISLAND = _ASE / "theisland" / "TheIsland.ark"
_ASE_VALGUERO = _ASE / "valguero" / "Valguero_P.ark"

# ASA paths
_ASA = _EXAMPLES / "asa" / "maps"
_ASA_ABERRATION = _ASA / "aberration" / "Aberration_WP.ark"
_ASA_CENTER = _ASA / "center" / "TheCenter_WP.ark"
_ASA_EXTINCTION = _ASA / "extinction" / "Extinction_WP.ark"
_ASA_VALGUERO = _ASA / "valguero" / "Valguero_WP.ark"


# ---------------------------------------------------------------------------
# Session-scoped fixtures – world saves are expensive; load once per session.
# Fixture files are not committed; each fixture skips its tests if absent.
# ---------------------------------------------------------------------------


def _load_or_skip(path: Path) -> WorldSave:
    if not path.exists():
        pytest.skip(f"Fixture not available: {path}")
    return WorldSave.load(path)


@pytest.fixture(scope="session")
def ase_aberration() -> WorldSave:
    return _load_or_skip(_ASE_ABERRATION)


@pytest.fixture(scope="session")
def ase_extinction() -> WorldSave:
    return _load_or_skip(_ASE_EXTINCTION)


@pytest.fixture(scope="session")
def ase_fjordur() -> WorldSave:
    return _load_or_skip(_ASE_FJORDUR)


@pytest.fixture(scope="session")
def ase_lostisland() -> WorldSave:
    return _load_or_skip(_ASE_LOSTISLAND)


@pytest.fixture(scope="session")
def ase_ragnarok() -> WorldSave:
    return _load_or_skip(_ASE_RAGNAROK)


@pytest.fixture(scope="session")
def ase_scorchedearth() -> WorldSave:
    return _load_or_skip(_ASE_SCORCHEDEARTH)


@pytest.fixture(scope="session")
def ase_thecenter() -> WorldSave:
    return _load_or_skip(_ASE_THECENTER)


@pytest.fixture(scope="session")
def ase_theisland() -> WorldSave:
    return _load_or_skip(_ASE_THEISLAND)


@pytest.fixture(scope="session")
def ase_valguero() -> WorldSave:
    return _load_or_skip(_ASE_VALGUERO)


@pytest.fixture(scope="session")
def asa_aberration() -> WorldSave:
    return _load_or_skip(_ASA_ABERRATION)


@pytest.fixture(scope="session")
def asa_center() -> WorldSave:
    return _load_or_skip(_ASA_CENTER)


@pytest.fixture(scope="session")
def asa_extinction() -> WorldSave:
    return _load_or_skip(_ASA_EXTINCTION)


@pytest.fixture(scope="session")
def asa_valguero() -> WorldSave:
    return _load_or_skip(_ASA_VALGUERO)


# ---------------------------------------------------------------------------
# ASE Extinction  (detailed – includes structural / class-name checks)
# ---------------------------------------------------------------------------


class TestASEWorldSaveExtinction:
    """Tests against the ASE Extinction world save (Extinction.ark)."""

    def test_loads(self, ase_extinction: WorldSave) -> None:
        assert ase_extinction is not None

    def test_is_not_asa(self, ase_extinction: WorldSave) -> None:
        assert not ase_extinction.is_asa

    def test_object_count(self, ase_extinction: WorldSave) -> None:
        assert len(ase_extinction.objects) == 83965

    def test_zero_parse_errors(self, ase_extinction: WorldSave) -> None:
        assert ase_extinction.parse_error_count == 0

    def test_tamed_creature_count(self, ase_extinction: WorldSave) -> None:
        assert len(ase_extinction.get_tamed_creatures()) == 70

    def test_wild_creature_count(self, ase_extinction: WorldSave) -> None:
        assert len(ase_extinction.get_wild_creatures()) == 14855

    def test_player_pawn_count(self, ase_extinction: WorldSave) -> None:
        assert len(ase_extinction.get_player_pawns()) == 99

    def test_terminal_count(self, ase_extinction: WorldSave) -> None:
        assert len(ase_extinction.get_terminals()) == 32

    def test_artifact_crate_count(self, ase_extinction: WorldSave) -> None:
        assert len(ase_extinction.get_artifact_crates()) == 3

    def test_map_resource_count(self, ase_extinction: WorldSave) -> None:
        assert len(ase_extinction.get_map_resources()) == 27

    def test_supply_drops_empty(self, ase_extinction: WorldSave) -> None:
        """No active supply drops in this save."""
        assert len(ase_extinction.get_supply_drops()) == 0

    def test_creatures_have_class_name(self, ase_extinction: WorldSave) -> None:
        for creature in ase_extinction.get_tamed_creatures():
            assert isinstance(creature.class_name, str) and len(creature.class_name) > 0

    def test_tamed_creatures_have_location(self, ase_extinction: WorldSave) -> None:
        for creature in ase_extinction.get_tamed_creatures():
            assert isinstance(creature.location, LocationData)

    def test_wild_creature_is_game_object(self, ase_extinction: WorldSave) -> None:
        for c in ase_extinction.get_wild_creatures()[:10]:
            assert isinstance(c, GameObject)

    def test_terminals_have_class_name(self, ase_extinction: WorldSave) -> None:
        for terminal in ase_extinction.get_terminals():
            cn = terminal.class_name.lower()
            assert "terminal" in cn or "tribute" in cn or "city" in cn

    def test_artifacts_have_class_name(self, ase_extinction: WorldSave) -> None:
        for art in ase_extinction.get_artifact_crates():
            assert "artifact" in art.class_name.lower()

    def test_resources_have_class_name(self, ase_extinction: WorldSave) -> None:
        valid_patterns = ("oilvein", "watervein", "gasvein", "chargenode", "elementvein", "beaverdam")
        for r in ase_extinction.get_map_resources():
            cn = r.class_name.lower()
            assert any(p in cn for p in valid_patterns), f"Unexpected resource: {r.class_name}"

    def test_version_is_valid_ase(self, ase_extinction: WorldSave) -> None:
        assert ase_extinction.version in (5, 6, 7, 8, 9, 10, 11, 12)
        assert not ase_extinction.is_asa

    def test_to_dict(self, ase_extinction: WorldSave) -> None:
        d = ase_extinction.to_dict()
        assert isinstance(d, dict)
        assert d["version"] == ase_extinction.version
        assert d["is_asa"] is False


# ---------------------------------------------------------------------------
# ASE Ragnarok
# ---------------------------------------------------------------------------


class TestASEWorldSaveRagnarok:
    """Tests against the ASE Ragnarok world save (Ragnarok.ark)."""

    def test_loads(self, ase_ragnarok: WorldSave) -> None:
        assert ase_ragnarok is not None

    def test_is_not_asa(self, ase_ragnarok: WorldSave) -> None:
        assert not ase_ragnarok.is_asa

    def test_object_count(self, ase_ragnarok: WorldSave) -> None:
        assert len(ase_ragnarok.objects) == 212071

    def test_zero_parse_errors(self, ase_ragnarok: WorldSave) -> None:
        assert ase_ragnarok.parse_error_count == 0

    def test_tamed_creature_count(self, ase_ragnarok: WorldSave) -> None:
        assert len(ase_ragnarok.get_tamed_creatures()) == 254

    def test_wild_creature_count(self, ase_ragnarok: WorldSave) -> None:
        assert len(ase_ragnarok.get_wild_creatures()) == 26251

    def test_player_pawn_count(self, ase_ragnarok: WorldSave) -> None:
        assert len(ase_ragnarok.get_player_pawns()) == 193

    def test_terminal_count(self, ase_ragnarok: WorldSave) -> None:
        assert len(ase_ragnarok.get_terminals()) == 3

    def test_artifact_crate_count(self, ase_ragnarok: WorldSave) -> None:
        assert len(ase_ragnarok.get_artifact_crates()) == 11

    def test_map_resource_count(self, ase_ragnarok: WorldSave) -> None:
        assert len(ase_ragnarok.get_map_resources()) == 161

    def test_supply_drops_empty(self, ase_ragnarok: WorldSave) -> None:
        assert len(ase_ragnarok.get_supply_drops()) == 0

    def test_version_is_valid_ase(self, ase_ragnarok: WorldSave) -> None:
        assert ase_ragnarok.version in (5, 6, 7, 8, 9, 10, 11, 12)

    def test_to_dict(self, ase_ragnarok: WorldSave) -> None:
        d = ase_ragnarok.to_dict()
        assert isinstance(d, dict)
        assert d["is_asa"] is False


# ---------------------------------------------------------------------------
# ASE Aberration
# ---------------------------------------------------------------------------


class TestASEWorldSaveAberration:
    """Tests against the ASE Aberration world save (Aberration_P.ark)."""

    def test_loads(self, ase_aberration: WorldSave) -> None:
        assert ase_aberration is not None

    def test_is_not_asa(self, ase_aberration: WorldSave) -> None:
        assert not ase_aberration.is_asa

    def test_object_count(self, ase_aberration: WorldSave) -> None:
        assert len(ase_aberration.objects) == 111192

    def test_zero_parse_errors(self, ase_aberration: WorldSave) -> None:
        assert ase_aberration.parse_error_count == 0

    def test_tamed_creature_count(self, ase_aberration: WorldSave) -> None:
        assert len(ase_aberration.get_tamed_creatures()) == 190

    def test_wild_creature_count(self, ase_aberration: WorldSave) -> None:
        assert len(ase_aberration.get_wild_creatures()) == 17142

    def test_player_pawn_count(self, ase_aberration: WorldSave) -> None:
        assert len(ase_aberration.get_player_pawns()) == 72

    def test_terminal_count(self, ase_aberration: WorldSave) -> None:
        assert len(ase_aberration.get_terminals()) == 4

    def test_artifact_crate_count(self, ase_aberration: WorldSave) -> None:
        assert len(ase_aberration.get_artifact_crates()) == 3

    def test_map_resource_count(self, ase_aberration: WorldSave) -> None:
        assert len(ase_aberration.get_map_resources()) == 172

    def test_version_is_valid_ase(self, ase_aberration: WorldSave) -> None:
        assert ase_aberration.version in (5, 6, 7, 8, 9, 10, 11, 12)

    def test_to_dict(self, ase_aberration: WorldSave) -> None:
        d = ase_aberration.to_dict()
        assert isinstance(d, dict)
        assert d["is_asa"] is False


# ---------------------------------------------------------------------------
# ASE Fjordur
# ---------------------------------------------------------------------------


class TestASEWorldSaveFjordur:
    """Tests against the ASE Fjordur world save (Fjordur.ark)."""

    def test_loads(self, ase_fjordur: WorldSave) -> None:
        assert ase_fjordur is not None

    def test_is_not_asa(self, ase_fjordur: WorldSave) -> None:
        assert not ase_fjordur.is_asa

    def test_object_count(self, ase_fjordur: WorldSave) -> None:
        assert len(ase_fjordur.objects) == 171866

    def test_zero_parse_errors(self, ase_fjordur: WorldSave) -> None:
        assert ase_fjordur.parse_error_count == 0

    def test_tamed_creature_count(self, ase_fjordur: WorldSave) -> None:
        assert len(ase_fjordur.get_tamed_creatures()) == 338

    def test_wild_creature_count(self, ase_fjordur: WorldSave) -> None:
        assert len(ase_fjordur.get_wild_creatures()) == 28161

    def test_player_pawn_count(self, ase_fjordur: WorldSave) -> None:
        assert len(ase_fjordur.get_player_pawns()) == 130

    def test_terminal_count(self, ase_fjordur: WorldSave) -> None:
        assert len(ase_fjordur.get_terminals()) == 15

    def test_artifact_crate_count(self, ase_fjordur: WorldSave) -> None:
        assert len(ase_fjordur.get_artifact_crates()) == 10

    def test_map_resource_count(self, ase_fjordur: WorldSave) -> None:
        assert len(ase_fjordur.get_map_resources()) == 91

    def test_version_is_valid_ase(self, ase_fjordur: WorldSave) -> None:
        assert ase_fjordur.version in (5, 6, 7, 8, 9, 10, 11, 12)

    def test_to_dict(self, ase_fjordur: WorldSave) -> None:
        d = ase_fjordur.to_dict()
        assert isinstance(d, dict)
        assert d["is_asa"] is False


# ---------------------------------------------------------------------------
# ASE LostIsland
# ---------------------------------------------------------------------------


class TestASEWorldSaveLostIsland:
    """Tests against the ASE LostIsland world save (LostIsland.ark)."""

    def test_loads(self, ase_lostisland: WorldSave) -> None:
        assert ase_lostisland is not None

    def test_is_not_asa(self, ase_lostisland: WorldSave) -> None:
        assert not ase_lostisland.is_asa

    def test_object_count(self, ase_lostisland: WorldSave) -> None:
        assert len(ase_lostisland.objects) == 257402

    def test_zero_parse_errors(self, ase_lostisland: WorldSave) -> None:
        assert ase_lostisland.parse_error_count == 0

    def test_tamed_creature_count(self, ase_lostisland: WorldSave) -> None:
        assert len(ase_lostisland.get_tamed_creatures()) == 622

    def test_wild_creature_count(self, ase_lostisland: WorldSave) -> None:
        assert len(ase_lostisland.get_wild_creatures()) == 39847

    def test_player_pawn_count(self, ase_lostisland: WorldSave) -> None:
        assert len(ase_lostisland.get_player_pawns()) == 159

    def test_terminal_count(self, ase_lostisland: WorldSave) -> None:
        assert len(ase_lostisland.get_terminals()) == 3

    def test_artifact_crate_count(self, ase_lostisland: WorldSave) -> None:
        assert len(ase_lostisland.get_artifact_crates()) == 11

    def test_map_resource_count(self, ase_lostisland: WorldSave) -> None:
        assert len(ase_lostisland.get_map_resources()) == 22

    def test_version_is_valid_ase(self, ase_lostisland: WorldSave) -> None:
        assert ase_lostisland.version in (5, 6, 7, 8, 9, 10, 11, 12)

    def test_to_dict(self, ase_lostisland: WorldSave) -> None:
        d = ase_lostisland.to_dict()
        assert isinstance(d, dict)
        assert d["is_asa"] is False


# ---------------------------------------------------------------------------
# ASE ScorchedEarth
# ---------------------------------------------------------------------------


class TestASEWorldSaveScorchedEarth:
    """Tests against the ASE ScorchedEarth world save (ScorchedEarth_P.ark)."""

    def test_loads(self, ase_scorchedearth: WorldSave) -> None:
        assert ase_scorchedearth is not None

    def test_is_not_asa(self, ase_scorchedearth: WorldSave) -> None:
        assert not ase_scorchedearth.is_asa

    def test_object_count(self, ase_scorchedearth: WorldSave) -> None:
        assert len(ase_scorchedearth.objects) == 54495

    def test_zero_parse_errors(self, ase_scorchedearth: WorldSave) -> None:
        assert ase_scorchedearth.parse_error_count == 0

    def test_tamed_creature_count(self, ase_scorchedearth: WorldSave) -> None:
        assert len(ase_scorchedearth.get_tamed_creatures()) == 37

    def test_wild_creature_count(self, ase_scorchedearth: WorldSave) -> None:
        assert len(ase_scorchedearth.get_wild_creatures()) == 12169

    def test_reported_archa_is_not_in_wild_list(self, ase_scorchedearth: WorldSave) -> None:
        wild_names = {obj.names[0] for obj in ase_scorchedearth.get_wild_creatures() if obj.names}
        tamed_names = {obj.names[0] for obj in ase_scorchedearth.get_tamed_creatures() if obj.names}

        assert "Archa_Character_BP_C_207" not in wild_names
        assert "Archa_Character_BP_C_207" in tamed_names

    def test_creature_lists_exclude_status_components(self, ase_scorchedearth: WorldSave) -> None:
        creatures = ase_scorchedearth.get_creatures()
        assert all("StatusComponent" not in creature.class_name for creature in creatures)

    def test_wild_creatures_do_not_have_tame_markers(self, ase_scorchedearth: WorldSave) -> None:
        wild_creatures = ase_scorchedearth.get_wild_creatures()
        assert all(not creature.get_property_value("TamedName") for creature in wild_creatures)
        assert all(not creature.get_property_value("TamerString") for creature in wild_creatures)

    def test_tamed_ancestor_names_and_ids(self, ase_scorchedearth: WorldSave) -> None:
        creature_obj = next(
            obj
            for obj in ase_scorchedearth.get_tamed_creatures()
            if obj.names and obj.names[0] == "Spindles_Character_BP_C_231"
        )
        status_obj = next(
            obj
            for obj in ase_scorchedearth.objects
            if "StatusComponent" in obj.class_name and obj.names and obj.names[-1] == "Spindles_Character_BP_C_231"
        )
        father_id, father_name = _ancestor_parent(creature_obj, "Male")
        mother_id, mother_name = _ancestor_parent(creature_obj, "Female")

        assert father_name == "Velonasaur - Lvl 209"
        assert mother_name == "Velonasaur - Lvl 202"
        assert father_id == 1690875190935886321
        assert mother_id == 292497409279269540
        _ = status_obj  # unused after refactor; ancestors live on the actor

    def test_player_pawn_count(self, ase_scorchedearth: WorldSave) -> None:
        assert len(ase_scorchedearth.get_player_pawns()) == 54

    def test_terminal_count(self, ase_scorchedearth: WorldSave) -> None:
        assert len(ase_scorchedearth.get_terminals()) == 3

    def test_artifact_crate_count(self, ase_scorchedearth: WorldSave) -> None:
        assert len(ase_scorchedearth.get_artifact_crates()) == 3

    def test_map_resource_count(self, ase_scorchedearth: WorldSave) -> None:
        assert len(ase_scorchedearth.get_map_resources()) == 71

    def test_version_is_valid_ase(self, ase_scorchedearth: WorldSave) -> None:
        assert ase_scorchedearth.version in (5, 6, 7, 8, 9, 10, 11, 12)

    def test_to_dict(self, ase_scorchedearth: WorldSave) -> None:
        d = ase_scorchedearth.to_dict()
        assert isinstance(d, dict)
        assert d["is_asa"] is False


# ---------------------------------------------------------------------------
# ASE TheCenter
# ---------------------------------------------------------------------------


class TestASEWorldSaveTheCenter:
    """Tests against the ASE TheCenter world save (TheCenter.ark)."""

    def test_loads(self, ase_thecenter: WorldSave) -> None:
        assert ase_thecenter is not None

    def test_is_not_asa(self, ase_thecenter: WorldSave) -> None:
        assert not ase_thecenter.is_asa

    def test_object_count(self, ase_thecenter: WorldSave) -> None:
        assert len(ase_thecenter.objects) == 195269

    def test_zero_parse_errors(self, ase_thecenter: WorldSave) -> None:
        assert ase_thecenter.parse_error_count == 0

    def test_tamed_creature_count(self, ase_thecenter: WorldSave) -> None:
        assert len(ase_thecenter.get_tamed_creatures()) == 247

    def test_wild_creature_count(self, ase_thecenter: WorldSave) -> None:
        assert len(ase_thecenter.get_wild_creatures()) == 33704

    def test_player_pawn_count(self, ase_thecenter: WorldSave) -> None:
        assert len(ase_thecenter.get_player_pawns()) == 98

    def test_terminal_count(self, ase_thecenter: WorldSave) -> None:
        assert len(ase_thecenter.get_terminals()) == 3

    def test_artifact_crate_count(self, ase_thecenter: WorldSave) -> None:
        assert len(ase_thecenter.get_artifact_crates()) == 11

    def test_map_resource_count(self, ase_thecenter: WorldSave) -> None:
        assert len(ase_thecenter.get_map_resources()) == 55

    def test_version_is_valid_ase(self, ase_thecenter: WorldSave) -> None:
        assert ase_thecenter.version in (5, 6, 7, 8, 9, 10, 11, 12)

    def test_to_dict(self, ase_thecenter: WorldSave) -> None:
        d = ase_thecenter.to_dict()
        assert isinstance(d, dict)
        assert d["is_asa"] is False


# ---------------------------------------------------------------------------
# ASE TheIsland
# ---------------------------------------------------------------------------


class TestASEWorldSaveTheIsland:
    """Tests against the ASE TheIsland world save (TheIsland.ark)."""

    def test_loads(self, ase_theisland: WorldSave) -> None:
        assert ase_theisland is not None

    def test_is_not_asa(self, ase_theisland: WorldSave) -> None:
        assert not ase_theisland.is_asa

    def test_object_count(self, ase_theisland: WorldSave) -> None:
        assert len(ase_theisland.objects) == 204107

    def test_zero_parse_errors(self, ase_theisland: WorldSave) -> None:
        assert ase_theisland.parse_error_count == 0

    def test_tamed_creature_count(self, ase_theisland: WorldSave) -> None:
        assert len(ase_theisland.get_tamed_creatures()) == 300

    def test_wild_creature_count(self, ase_theisland: WorldSave) -> None:
        assert len(ase_theisland.get_wild_creatures()) == 26556

    def test_player_pawn_count(self, ase_theisland: WorldSave) -> None:
        assert len(ase_theisland.get_player_pawns()) == 162

    def test_terminal_count(self, ase_theisland: WorldSave) -> None:
        assert len(ase_theisland.get_terminals()) == 4

    def test_artifact_crate_count(self, ase_theisland: WorldSave) -> None:
        assert len(ase_theisland.get_artifact_crates()) == 10

    def test_map_resource_count(self, ase_theisland: WorldSave) -> None:
        assert len(ase_theisland.get_map_resources()) == 19

    def test_version_is_valid_ase(self, ase_theisland: WorldSave) -> None:
        assert ase_theisland.version in (5, 6, 7, 8, 9, 10, 11, 12)

    def test_to_dict(self, ase_theisland: WorldSave) -> None:
        d = ase_theisland.to_dict()
        assert isinstance(d, dict)
        assert d["is_asa"] is False


# ---------------------------------------------------------------------------
# ASE Valguero
# ---------------------------------------------------------------------------


class TestASEWorldSaveValguero:
    """Tests against the ASE Valguero world save (Valguero_P.ark)."""

    def test_loads(self, ase_valguero: WorldSave) -> None:
        assert ase_valguero is not None

    def test_is_not_asa(self, ase_valguero: WorldSave) -> None:
        assert not ase_valguero.is_asa

    def test_object_count(self, ase_valguero: WorldSave) -> None:
        assert len(ase_valguero.objects) == 220397

    def test_zero_parse_errors(self, ase_valguero: WorldSave) -> None:
        assert ase_valguero.parse_error_count == 0

    def test_tamed_creature_count(self, ase_valguero: WorldSave) -> None:
        assert len(ase_valguero.get_tamed_creatures()) == 328

    def test_wild_creature_count(self, ase_valguero: WorldSave) -> None:
        assert len(ase_valguero.get_wild_creatures()) == 32616

    def test_player_pawn_count(self, ase_valguero: WorldSave) -> None:
        assert len(ase_valguero.get_player_pawns()) == 116

    def test_terminal_count(self, ase_valguero: WorldSave) -> None:
        assert len(ase_valguero.get_terminals()) == 3

    def test_artifact_crate_count(self, ase_valguero: WorldSave) -> None:
        assert len(ase_valguero.get_artifact_crates()) == 10

    def test_map_resource_count(self, ase_valguero: WorldSave) -> None:
        assert len(ase_valguero.get_map_resources()) == 135

    def test_version_is_valid_ase(self, ase_valguero: WorldSave) -> None:
        assert ase_valguero.version in (5, 6, 7, 8, 9, 10, 11, 12)

    def test_to_dict(self, ase_valguero: WorldSave) -> None:
        d = ase_valguero.to_dict()
        assert isinstance(d, dict)
        assert d["is_asa"] is False


# ---------------------------------------------------------------------------
# ASA Extinction  (detailed – includes structural / class-name checks)
# ---------------------------------------------------------------------------


class TestASAWorldSaveExtinction:
    """Tests against the ASA Extinction world save (Extinction_WP.ark)."""

    def test_loads(self, asa_extinction: WorldSave) -> None:
        assert asa_extinction is not None

    def test_is_asa(self, asa_extinction: WorldSave) -> None:
        assert asa_extinction.is_asa

    def test_object_count(self, asa_extinction: WorldSave) -> None:
        assert len(asa_extinction.objects) == 128751

    def test_zero_parse_errors(self, asa_extinction: WorldSave) -> None:
        assert asa_extinction.parse_error_count == 0

    def test_tamed_creature_count(self, asa_extinction: WorldSave) -> None:
        assert len(asa_extinction.get_tamed_creatures()) == 184

    def test_wild_creature_count(self, asa_extinction: WorldSave) -> None:
        assert len(asa_extinction.get_wild_creatures()) == 16042

    def test_player_pawn_count(self, asa_extinction: WorldSave) -> None:
        assert len(asa_extinction.get_player_pawns()) == 67

    def test_terminal_count(self, asa_extinction: WorldSave) -> None:
        assert len(asa_extinction.get_terminals()) == 31

    def test_artifact_crate_count(self, asa_extinction: WorldSave) -> None:
        assert len(asa_extinction.get_artifact_crates()) == 3

    def test_map_resource_count(self, asa_extinction: WorldSave) -> None:
        assert len(asa_extinction.get_map_resources()) == 18

    def test_supply_drops_empty(self, asa_extinction: WorldSave) -> None:
        assert len(asa_extinction.get_supply_drops()) == 0

    def test_creatures_have_class_name(self, asa_extinction: WorldSave) -> None:
        for creature in asa_extinction.get_tamed_creatures()[:10]:
            assert isinstance(creature.class_name, str) and len(creature.class_name) > 0

    def test_tamed_creatures_have_location(self, asa_extinction: WorldSave) -> None:
        for creature in asa_extinction.get_tamed_creatures()[:10]:
            assert isinstance(creature.location, LocationData)

    def test_terminals_have_class_name(self, asa_extinction: WorldSave) -> None:
        for terminal in asa_extinction.get_terminals():
            cn = terminal.class_name.lower()
            assert "terminal" in cn or "tribute" in cn or "city" in cn

    def test_artifacts_have_class_name(self, asa_extinction: WorldSave) -> None:
        for art in asa_extinction.get_artifact_crates():
            assert "artifact" in art.class_name.lower()

    def test_resources_have_class_name(self, asa_extinction: WorldSave) -> None:
        valid_patterns = ("oilvein", "watervein", "gasvein", "chargenode", "elementvein", "beaverdam")
        for r in asa_extinction.get_map_resources():
            cn = r.class_name.lower()
            assert any(p in cn for p in valid_patterns), f"Unexpected resource: {r.class_name}"

    def test_version_is_asa(self, asa_extinction: WorldSave) -> None:
        assert asa_extinction.version >= 7

    def test_to_dict(self, asa_extinction: WorldSave) -> None:
        d = asa_extinction.to_dict()
        assert isinstance(d, dict)
        assert d["is_asa"] is True


# ---------------------------------------------------------------------------
# ASA Aberration
# ---------------------------------------------------------------------------


class TestASAWorldSaveAberration:
    """Tests against the ASA Aberration world save (Aberration_WP.ark)."""

    def test_loads(self, asa_aberration: WorldSave) -> None:
        assert asa_aberration is not None

    def test_is_asa(self, asa_aberration: WorldSave) -> None:
        assert asa_aberration.is_asa

    def test_object_count(self, asa_aberration: WorldSave) -> None:
        assert len(asa_aberration.objects) == 95743

    def test_zero_parse_errors(self, asa_aberration: WorldSave) -> None:
        assert asa_aberration.parse_error_count == 0

    def test_tamed_creature_count(self, asa_aberration: WorldSave) -> None:
        assert len(asa_aberration.get_tamed_creatures()) == 126

    def test_wild_creature_count(self, asa_aberration: WorldSave) -> None:
        assert len(asa_aberration.get_wild_creatures()) == 16415

    def test_player_pawn_count(self, asa_aberration: WorldSave) -> None:
        assert len(asa_aberration.get_player_pawns()) == 61

    def test_terminal_count(self, asa_aberration: WorldSave) -> None:
        assert len(asa_aberration.get_terminals()) == 4

    def test_artifact_crate_count(self, asa_aberration: WorldSave) -> None:
        assert len(asa_aberration.get_artifact_crates()) == 3

    def test_map_resource_count(self, asa_aberration: WorldSave) -> None:
        assert len(asa_aberration.get_map_resources()) == 169

    def test_version_is_asa(self, asa_aberration: WorldSave) -> None:
        assert asa_aberration.version >= 7

    def test_to_dict(self, asa_aberration: WorldSave) -> None:
        d = asa_aberration.to_dict()
        assert isinstance(d, dict)
        assert d["is_asa"] is True


# ---------------------------------------------------------------------------
# ASA Center
# ---------------------------------------------------------------------------


class TestASAWorldSaveCenter:
    """Tests against the ASA The Center world save (TheCenter_WP.ark)."""

    def test_loads(self, asa_center: WorldSave) -> None:
        assert asa_center is not None

    def test_is_asa(self, asa_center: WorldSave) -> None:
        assert asa_center.is_asa

    def test_object_count(self, asa_center: WorldSave) -> None:
        assert len(asa_center.objects) == 310439

    def test_zero_parse_errors(self, asa_center: WorldSave) -> None:
        assert asa_center.parse_error_count == 0

    def test_tamed_creature_count(self, asa_center: WorldSave) -> None:
        assert len(asa_center.get_tamed_creatures()) == 432

    def test_wild_creature_count(self, asa_center: WorldSave) -> None:
        assert len(asa_center.get_wild_creatures()) == 38330

    def test_player_pawn_count(self, asa_center: WorldSave) -> None:
        assert len(asa_center.get_player_pawns()) == 113

    def test_terminal_count(self, asa_center: WorldSave) -> None:
        assert len(asa_center.get_terminals()) == 3

    def test_artifact_crate_count(self, asa_center: WorldSave) -> None:
        assert len(asa_center.get_artifact_crates()) == 11

    def test_map_resource_count(self, asa_center: WorldSave) -> None:
        assert len(asa_center.get_map_resources()) == 79

    def test_version_is_asa(self, asa_center: WorldSave) -> None:
        assert asa_center.version >= 7

    def test_to_dict(self, asa_center: WorldSave) -> None:
        d = asa_center.to_dict()
        assert isinstance(d, dict)
        assert d["is_asa"] is True


# ---------------------------------------------------------------------------
# ASA Valguero
# ---------------------------------------------------------------------------


class TestASAWorldSaveValguero:
    """Tests against the ASA Valguero world save (Valguero_WP.ark)."""

    def test_loads(self, asa_valguero: WorldSave) -> None:
        assert asa_valguero is not None

    def test_is_asa(self, asa_valguero: WorldSave) -> None:
        assert asa_valguero.is_asa

    def test_object_count(self, asa_valguero: WorldSave) -> None:
        assert len(asa_valguero.objects) == 224929

    def test_zero_parse_errors(self, asa_valguero: WorldSave) -> None:
        assert asa_valguero.parse_error_count == 0

    def test_tamed_creature_count(self, asa_valguero: WorldSave) -> None:
        assert len(asa_valguero.get_tamed_creatures()) == 418

    def test_wild_creature_count(self, asa_valguero: WorldSave) -> None:
        assert len(asa_valguero.get_wild_creatures()) == 36780

    def test_player_pawn_count(self, asa_valguero: WorldSave) -> None:
        assert len(asa_valguero.get_player_pawns()) == 79

    def test_terminal_count(self, asa_valguero: WorldSave) -> None:
        assert len(asa_valguero.get_terminals()) == 3

    def test_artifact_crate_count(self, asa_valguero: WorldSave) -> None:
        assert len(asa_valguero.get_artifact_crates()) == 10

    def test_map_resource_count(self, asa_valguero: WorldSave) -> None:
        assert len(asa_valguero.get_map_resources()) == 85

    def test_version_is_asa(self, asa_valguero: WorldSave) -> None:
        assert asa_valguero.version >= 7

    def test_to_dict(self, asa_valguero: WorldSave) -> None:
        d = asa_valguero.to_dict()
        assert isinstance(d, dict)
        assert d["is_asa"] is True
