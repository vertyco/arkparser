"""
Tests for cloud inventory (obelisk) parsing - both ASE and ASA formats.
"""

from pathlib import Path

import pytest

from arkparser import CloudInventory


class TestASECloudInventory:
    """Tests for ASE cloud inventory parsing."""

    def test_load_ase_obelisk(self, ase_obelisk_path: Path) -> None:
        """ASE obelisk file should load successfully."""
        inv = CloudInventory.load(ase_obelisk_path)
        assert inv is not None

    def test_ase_format_version(self, ase_obelisk_path: Path) -> None:
        """ASE obelisk should be detected as ASE format."""
        inv = CloudInventory.load(ase_obelisk_path)
        assert not inv.is_asa

    def test_ase_has_creature(self, ase_obelisk_path: Path) -> None:
        """ASE obelisk should contain exactly 1 uploaded creature (Dodo)."""
        inv = CloudInventory.load(ase_obelisk_path)
        assert inv.creature_count == 1

    def test_ase_creature_name(self, ase_obelisk_path: Path) -> None:
        """First creature in the ASE obelisk should be named Rex (case-insensitive)."""
        inv = CloudInventory.load(ase_obelisk_path)
        assert inv.creature_count >= 1
        creature = inv.uploaded_creatures[0]
        assert creature.name.lower() == "rex"

    def test_ase_creature_level(self, ase_obelisk_path: Path) -> None:
        """The Dodo should be level 226."""
        inv = CloudInventory.load(ase_obelisk_path)
        assert inv.creature_count >= 1
        creature = inv.uploaded_creatures[0]
        assert creature.level == 226

    def test_ase_has_items(self, ase_obelisk_path: Path) -> None:
        """ASE obelisk should contain at least 2 items (longneck + cryopod)."""
        inv = CloudInventory.load(ase_obelisk_path)
        assert inv.item_count >= 2

    def test_ase_item_has_blueprint(self, ase_obelisk_path: Path) -> None:
        """Uploaded items should have a non-empty blueprint path."""
        inv = CloudInventory.load(ase_obelisk_path)
        for item in inv.uploaded_items:
            assert isinstance(item.blueprint, str)
            assert len(item.blueprint) > 0

    def test_ase_longneck_is_mastercraft(self, ase_obelisk_path: Path) -> None:
        """The longneck rifle should be Mastercraft (quality_index=4)."""
        inv = CloudInventory.load(ase_obelisk_path)
        longneck = next(
            (i for i in inv.uploaded_items if "LongNeck" in i.blueprint or "RifleBase" in i.blueprint),
            None,
        )
        if longneck is not None:
            assert longneck.quality_index == 4
            assert longneck.quality_name == "Mastercraft"


class TestASACloudInventory:
    """Tests for ASA cloud inventory parsing."""

    def test_load_asa_obelisk(self, asa_obelisk_path: Path) -> None:
        """ASA obelisk file should load successfully."""
        inv = CloudInventory.load(asa_obelisk_path)
        assert inv is not None

    def test_asa_format_version(self, asa_obelisk_path: Path) -> None:
        """ASA obelisk should be detected as ASA format."""
        inv = CloudInventory.load(asa_obelisk_path)
        assert inv.is_asa

    def test_asa_has_creature(self, asa_obelisk_path: Path) -> None:
        """ASA obelisk should contain exactly 1 uploaded creature (Dodo)."""
        inv = CloudInventory.load(asa_obelisk_path)
        assert inv.creature_count == 1

    def test_asa_creature_name(self, asa_obelisk_path: Path) -> None:
        """First creature in the ASA obelisk should be named Rex (case-insensitive)."""
        inv = CloudInventory.load(asa_obelisk_path)
        assert inv.creature_count >= 1
        creature = inv.uploaded_creatures[0]
        assert creature.name.lower() == "rex"

    def test_asa_creature_level(self, asa_obelisk_path: Path) -> None:
        """The Dodo should be level 226."""
        inv = CloudInventory.load(asa_obelisk_path)
        assert inv.creature_count >= 1
        creature = inv.uploaded_creatures[0]
        assert creature.level == 226

    def test_asa_has_items(self, asa_obelisk_path: Path) -> None:
        """ASA obelisk should contain at least 2 items (longneck + cryopod)."""
        inv = CloudInventory.load(asa_obelisk_path)
        assert inv.item_count >= 2

    def test_asa_item_has_blueprint(self, asa_obelisk_path: Path) -> None:
        """Uploaded items should have a non-empty blueprint path."""
        inv = CloudInventory.load(asa_obelisk_path)
        for item in inv.uploaded_items:
            assert isinstance(item.blueprint, str)
            assert len(item.blueprint) > 0

    def test_asa_longneck_is_mastercraft(self, asa_obelisk_path: Path) -> None:
        """The longneck rifle should be Mastercraft (quality_index=4)."""
        inv = CloudInventory.load(asa_obelisk_path)
        longneck = next(
            (i for i in inv.uploaded_items if "LongNeck" in i.blueprint or "RifleBase" in i.blueprint),
            None,
        )
        if longneck is not None:
            assert longneck.quality_index == 4
            assert longneck.quality_name == "Mastercraft"

    def test_asa_uploaded_items_are_decoded_from_index_wrapped_data(self, asa_obelisk_path: Path) -> None:
        """ASA obelisk items should decode into structured item models."""
        inv = CloudInventory.load(asa_obelisk_path)
        first_item = inv.uploaded_items[0]
        assert first_item.blueprint.startswith("BlueprintGeneratedClass ")
        assert isinstance(first_item.raw_data, dict)

    def test_asa_cryopod_creature_is_decoded(self, asa_obelisk_path: Path) -> None:
        """ASA cryopod items should expose the stored creature."""
        inv = CloudInventory.load(asa_obelisk_path)
        cryopod = next(item for item in inv.uploaded_items if item.is_cryopod)
        creature = cryopod.cryopod_creature
        assert creature is not None
        assert creature.name == "bluey"
        assert creature.species == "Raptor"


class TestCloudInventoryStats:
    """Tests for creature stat parsing from obelisk files."""

    def test_ase_base_stats_object(self, ase_obelisk_path: Path) -> None:
        """Stats should return a DinoStats object."""
        from arkparser import DinoStats

        inv = CloudInventory.load(ase_obelisk_path)
        creature = inv.uploaded_creatures[0]
        assert isinstance(creature.stats, DinoStats)

    def test_asa_base_stats_object(self, asa_obelisk_path: Path) -> None:
        """Stats should return a DinoStats object."""
        from arkparser import DinoStats

        inv = CloudInventory.load(asa_obelisk_path)
        creature = inv.uploaded_creatures[0]
        assert isinstance(creature.stats, DinoStats)

    def test_ase_creature_stats_to_dict(self, ase_obelisk_path: Path) -> None:
        """to_dict should include all expected fields."""
        inv = CloudInventory.load(ase_obelisk_path)
        creature = inv.uploaded_creatures[0]
        d = creature.to_dict()
        assert "name" in d
        assert "level" in d
        assert "stats" in d


class TestASESolecluster:
    """
    Tests for ASE solecluster (cross-ARK transfer) files.

    The solecluster directory contains 128 files; 15 are 0-byte empties.
    All non-empty files must parse without errors.
    """

    def test_all_parse_without_errors(self, ase_solecluster_dir: Path) -> None:
        """Every non-empty ASE solecluster file should load without raising."""
        failures: list[str] = []
        for f in sorted(ase_solecluster_dir.iterdir()):
            if f.stat().st_size == 0:
                continue
            try:
                CloudInventory.load(f)
            except Exception as e:
                failures.append(f"{f.name}: {e}")
        assert failures == [], "Parse failures:\n" + "\n".join(failures)

    def test_format_is_ase(self, ase_solecluster_dir: Path) -> None:
        """All non-empty ASE solecluster files should be identified as ASE."""
        for f in sorted(ase_solecluster_dir.iterdir())[:20]:
            if f.stat().st_size == 0:
                continue
            inv = CloudInventory.load(f)
            assert not inv.is_asa, f"{f.name} was wrongly detected as ASA"

    def test_have_objects(self, ase_solecluster_dir: Path) -> None:
        """Every non-empty ASE solecluster file should contain at least 1 object."""
        for f in sorted(ase_solecluster_dir.iterdir())[:20]:
            if f.stat().st_size == 0:
                continue
            inv = CloudInventory.load(f)
            assert len(inv.objects) >= 1, f"{f.name} has no objects"

    def test_nonempty_count(self, ase_solecluster_dir: Path) -> None:
        """Sanity check: at least 100 non-empty files in the ASE solecluster dir."""
        nonempty = [f for f in ase_solecluster_dir.iterdir() if f.stat().st_size > 0]
        assert len(nonempty) >= 100


class TestASASolecluster:
    """
    Tests for ASA solecluster (cross-ARK transfer) files.

    These are version-6 ASA files: GUID-based object headers but ASE-style
    properties. The solecluster directory contains 173 files; 35 are 0-byte empties.
    All non-empty files must parse without errors.
    """

    def test_all_parse_without_errors(self, asa_solecluster_dir: Path) -> None:
        """Every non-empty ASA solecluster file should load without raising."""
        failures: list[str] = []
        for f in sorted(asa_solecluster_dir.iterdir()):
            if f.stat().st_size == 0:
                continue
            try:
                CloudInventory.load(f)
            except Exception as e:
                failures.append(f"{f.name}: {e}")
        assert failures == [], "Parse failures:\n" + "\n".join(failures)

    def test_format_is_asa(self, asa_solecluster_dir: Path) -> None:
        """All non-empty ASA solecluster files should be identified as ASA."""
        for f in sorted(asa_solecluster_dir.iterdir())[:20]:
            if f.stat().st_size == 0:
                continue
            inv = CloudInventory.load(f)
            assert inv.is_asa, f"{f.name} was wrongly detected as ASE"

    def test_have_objects(self, asa_solecluster_dir: Path) -> None:
        """Every non-empty ASA solecluster file should contain at least 1 object."""
        for f in sorted(asa_solecluster_dir.iterdir())[:20]:
            if f.stat().st_size == 0:
                continue
            inv = CloudInventory.load(f)
            assert len(inv.objects) >= 1, f"{f.name} has no objects"

    def test_nonempty_count(self, asa_solecluster_dir: Path) -> None:
        """Sanity check: at least 130 non-empty files in the ASA solecluster dir."""
        nonempty = [f for f in asa_solecluster_dir.iterdir() if f.stat().st_size > 0]
        assert len(nonempty) >= 130
