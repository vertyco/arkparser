"""
Tests for file format version detection.

These tests verify automatic detection of ASE vs ASA file formats.
"""

import struct
from pathlib import Path

import pytest

from arkparser.common.version_detection import (
    ArkFileFormat,
    ArkFileType,
    detect_file_type,
    detect_format,
    get_save_version,
)


class TestFormatDetection:
    """Tests for ASE vs ASA format detection."""

    def test_detect_ase_obelisk(self, ase_obelisk_path):
        """Detect ASE format from obelisk file."""
        if not ase_obelisk_path.exists():
            pytest.skip("ASE obelisk test file not found")

        fmt = detect_format(ase_obelisk_path)
        assert fmt == ArkFileFormat.ASE

    def test_detect_ase_profile(self, ase_profile_path):
        """Detect ASE format from profile file."""
        if not ase_profile_path.exists():
            pytest.skip("ASE profile test file not found")

        fmt = detect_format(ase_profile_path)
        assert fmt == ArkFileFormat.ASE

    def test_detect_ase_tribe(self, ase_tribe_path):
        """Detect ASE format from tribe file."""
        if not ase_tribe_path.exists():
            pytest.skip("ASE tribe test file not found")

        fmt = detect_format(ase_tribe_path)
        assert fmt == ArkFileFormat.ASE

    def test_detect_asa_obelisk(self, asa_obelisk_path):
        """Detect ASA format from obelisk file."""
        if not asa_obelisk_path.exists():
            pytest.skip("ASA obelisk test file not found")

        fmt = detect_format(asa_obelisk_path)
        assert fmt == ArkFileFormat.ASA

    def test_detect_from_path_string(self, ase_profile_path):
        """Detect format from path string."""
        if not ase_profile_path.exists():
            pytest.skip("ASE profile test file not found")

        fmt = detect_format(str(ase_profile_path))
        assert fmt == ArkFileFormat.ASE


class TestFileTypeDetection:
    """Tests for file type detection (profile, tribe, cloud, etc.)."""

    def test_detect_profile_type(self):
        """Detect .arkprofile file type."""
        file_type = detect_file_type(Path("test.arkprofile"))
        assert file_type == ArkFileType.PROFILE

    def test_detect_tribe_type(self):
        """Detect .arktribe file type."""
        file_type = detect_file_type(Path("test.arktribe"))
        assert file_type == ArkFileType.TRIBE

    def test_detect_cloud_type(self):
        """Detect cloud inventory file type (no extension)."""
        file_type = detect_file_type(Path("2533274922942310"))
        assert file_type == ArkFileType.CLOUD_INVENTORY

    def test_detect_world_save_type(self):
        """Detect .ark world save file type."""
        file_type = detect_file_type(Path("Extinction.ark"))
        assert file_type == ArkFileType.WORLD_SAVE


class TestSaveVersionDetection:
    """Tests for reading raw save version numbers."""

    def test_get_save_version_world_save_v12(self):
        """World-save Int16 versions 10-12 should not be misread as Int32 values."""
        data = struct.pack("<h", 12) + b"\x00\x00\xaa\xbb"
        assert get_save_version(data) == 12

    def test_get_save_version_profile_int32(self):
        """Non-worldsave headers should still read as Int32."""
        data = struct.pack("<i", 7) + b"\x00" * 20
        assert get_save_version(data) == 7
