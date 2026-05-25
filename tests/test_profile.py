"""
Tests for player profile parsing - both ASE and ASA formats.
"""

from pathlib import Path


from arkparser import Profile


class TestASEProfile:
    """Tests for ASE profile parsing."""

    def test_load_ase_profile(self, ase_profile_path: Path) -> None:
        """ASE profile file should load successfully."""
        profile = Profile.load(ase_profile_path)
        assert profile is not None

    def test_ase_format_version(self, ase_profile_path: Path) -> None:
        """ASE profile should be detected as ASE format."""
        profile = Profile.load(ase_profile_path)
        assert not profile.is_asa

    def test_ase_player_name(self, ase_profile_path: Path) -> None:
        """ASE profile should have a player name."""
        profile = Profile.load(ase_profile_path)
        assert profile.player_name is not None
        assert isinstance(profile.player_name, str)
        assert len(profile.player_name) > 0

    def test_ase_character_name(self, ase_profile_path: Path) -> None:
        """ASE profile should expose the in-game character name separately."""
        profile = Profile.load(ase_profile_path)
        assert profile.character_name == "neg"
        assert profile.character_name != profile.player_name

    def test_ase_is_female(self, ase_profile_path: Path) -> None:
        """ASE profile should expose the parsed gender flag when present."""
        profile = Profile.load(ase_profile_path)
        assert profile.is_female is True

    def test_ase_player_id(self, ase_profile_path: Path) -> None:
        """ASE profile should have a numeric player ID."""
        profile = Profile.load(ase_profile_path)
        assert profile.player_id is not None
        assert isinstance(profile.player_id, int)
        assert profile.player_id > 0

    def test_ase_profile_level(self, ase_profile_path: Path) -> None:
        """ASE profile should have a valid level (>= 1)."""
        profile = Profile.load(ase_profile_path)
        assert profile.level >= 1

    def test_ase_profile_to_dict(self, ase_profile_path: Path) -> None:
        """ASE profile to_dict should include key fields."""
        profile = Profile.load(ase_profile_path)
        d = profile.to_dict()
        assert isinstance(d, dict)
        assert "player_name" in d
        assert d["character_name"] == profile.character_name
        assert d["is_female"] is True
        assert "player_id" in d


class TestASAProfile:
    """Tests for ASA profile parsing."""

    def test_load_asa_profile(self, asa_profile_path: Path) -> None:
        """ASA profile file should load successfully."""
        profile = Profile.load(asa_profile_path)
        assert profile is not None

    def test_asa_format_version(self, asa_profile_path: Path) -> None:
        """ASA profile should be detected as ASA format."""
        profile = Profile.load(asa_profile_path)
        assert profile.is_asa

    def test_asa_player_name(self, asa_profile_path: Path) -> None:
        """ASA profile should have a player name."""
        profile = Profile.load(asa_profile_path)
        assert profile.player_name is not None
        assert isinstance(profile.player_name, str)
        assert len(profile.player_name) > 0

    def test_asa_character_name_falls_back_to_player_name(self, asa_profile_path: Path) -> None:
        """ASA profile should fall back to the platform name when character config is absent."""
        profile = Profile.load(asa_profile_path)
        assert profile.character_name == profile.player_name

    def test_asa_is_female_can_be_unknown(self, asa_profile_path: Path) -> None:
        """ASA profile should return None when the gender flag is absent."""
        profile = Profile.load(asa_profile_path)
        assert profile.is_female is None

    def test_asa_player_id(self, asa_profile_path: Path) -> None:
        """ASA profile should have a numeric player ID."""
        profile = Profile.load(asa_profile_path)
        assert profile.player_id is not None
        assert isinstance(profile.player_id, int)
        assert profile.player_id > 0

    def test_asa_profile_level(self, asa_profile_path: Path) -> None:
        """ASA profile should have a valid level (>= 1)."""
        profile = Profile.load(asa_profile_path)
        assert profile.level >= 1

    def test_asa_profile_to_dict(self, asa_profile_path: Path) -> None:
        """ASA profile to_dict should include key fields."""
        profile = Profile.load(asa_profile_path)
        d = profile.to_dict()
        assert isinstance(d, dict)
        assert "player_name" in d
        assert d["character_name"] == profile.character_name
        assert d["is_female"] is None
        assert "player_id" in d

    def test_asa_engram_blueprints(self, asa_profile_path: Path) -> None:
        """ASA profile should expose learned engram blueprints."""
        profile = Profile.load(asa_profile_path)
        engrams = profile.engram_blueprints
        assert isinstance(engrams, list)
        assert len(engrams) > 0

    def test_asa_get_stat_level_up_points(self, asa_profile_path: Path) -> None:
        """ASA profile stat lookup should return parsed level-up points."""
        profile = Profile.load(asa_profile_path)
        stat = profile.get_stat(0)
        assert isinstance(stat, dict)
        assert stat["stat_index"] == 0
        assert isinstance(stat["added"], int)
        assert stat["added"] >= 0

    def test_asa_unique_id_is_extracted_from_indexed_struct(self, asa_profile_path: Path) -> None:
        """ASA profile should expose the normalized network unique ID."""
        profile = Profile.load(asa_profile_path)
        assert profile.unique_id == "00020fa8fb0c41289b5f1e276cf3d291"
