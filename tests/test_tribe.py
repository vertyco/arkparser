"""
Tests for tribe (.arktribe) parsing - both ASE and ASA formats.
"""

from pathlib import Path

import pytest

from arkparser import Tribe


class TestASETribe:
    """Tests for ASE tribe file parsing."""

    def test_load_ase_tribe(self, ase_tribe_path: Path) -> None:
        """ASE tribe file should load successfully."""
        tribe = Tribe.load(ase_tribe_path)
        assert tribe is not None

    def test_ase_format_version(self, ase_tribe_path: Path) -> None:
        """ASE tribe should be detected as ASE format."""
        tribe = Tribe.load(ase_tribe_path)
        assert not tribe.is_asa

    def test_ase_tribe_name(self, ase_tribe_path: Path) -> None:
        """ASE tribe should have a name."""
        tribe = Tribe.load(ase_tribe_path)
        assert tribe.name is not None
        assert isinstance(tribe.name, str)
        assert len(tribe.name) > 0

    def test_ase_tribe_id(self, ase_tribe_path: Path) -> None:
        """ASE tribe should have a numeric tribe ID."""
        tribe = Tribe.load(ase_tribe_path)
        assert tribe.tribe_id is not None
        assert isinstance(tribe.tribe_id, int)
        assert tribe.tribe_id > 0

    def test_ase_tribe_has_members(self, ase_tribe_path: Path) -> None:
        """ASE tribe should have at least one member."""
        tribe = Tribe.load(ase_tribe_path)
        assert tribe.member_count >= 1

    def test_ase_tribe_member_lists(self, ase_tribe_path: Path) -> None:
        """ASE tribe member_ids and member_names should be consistent."""
        tribe = Tribe.load(ase_tribe_path)
        assert isinstance(tribe.member_ids, list)
        assert isinstance(tribe.member_names, list)
        assert isinstance(tribe.member_ranks, list)
        # All lists should have the same length as member_count
        assert len(tribe.member_ids) == tribe.member_count

    def test_ase_tribe_to_dict(self, ase_tribe_path: Path) -> None:
        """ASE tribe to_dict should contain expected fields."""
        tribe = Tribe.load(ase_tribe_path)
        d = tribe.to_dict()
        assert isinstance(d, dict)
        assert "tribe_id" in d
        assert "name" in d


class TestASATribe:
    """Tests for ASA tribe file parsing."""

    def test_load_asa_tribe(self, asa_tribe_path: Path) -> None:
        """ASA tribe file should load successfully."""
        tribe = Tribe.load(asa_tribe_path)
        assert tribe is not None

    def test_asa_format_version(self, asa_tribe_path: Path) -> None:
        """ASA tribe should be detected as ASA format."""
        tribe = Tribe.load(asa_tribe_path)
        assert tribe.is_asa

    def test_asa_tribe_name(self, asa_tribe_path: Path) -> None:
        """ASA tribe should have a name."""
        tribe = Tribe.load(asa_tribe_path)
        assert tribe.name is not None
        assert isinstance(tribe.name, str)
        assert len(tribe.name) > 0

    def test_asa_tribe_id(self, asa_tribe_path: Path) -> None:
        """ASA tribe should have a numeric tribe ID."""
        tribe = Tribe.load(asa_tribe_path)
        assert tribe.tribe_id is not None
        assert isinstance(tribe.tribe_id, int)
        assert tribe.tribe_id > 0

    def test_asa_tribe_has_members(self, asa_tribe_path: Path) -> None:
        """ASA tribe should have at least one member."""
        tribe = Tribe.load(asa_tribe_path)
        assert tribe.member_count >= 1

    def test_asa_tribe_member_lists(self, asa_tribe_path: Path) -> None:
        """ASA tribe member_ids and member_names should be consistent."""
        tribe = Tribe.load(asa_tribe_path)
        assert isinstance(tribe.member_ids, list)
        assert isinstance(tribe.member_names, list)
        assert isinstance(tribe.member_ranks, list)
        assert len(tribe.member_ids) == tribe.member_count

    def test_asa_log_entries_are_normalized_to_strings(self, asa_tribe_path: Path) -> None:
        """ASA tribe logs should be exposed as a flat string list."""
        tribe = Tribe.load(asa_tribe_path)
        assert isinstance(tribe.log_entries, list)
        assert tribe.log_entries
        assert all(isinstance(entry, str) for entry in tribe.log_entries)

    def test_asa_tribe_to_dict(self, asa_tribe_path: Path) -> None:
        """ASA tribe to_dict should contain expected fields."""
        tribe = Tribe.load(asa_tribe_path)
        d = tribe.to_dict()
        assert isinstance(d, dict)
        assert "tribe_id" in d
        assert "name" in d
