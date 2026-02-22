"""
Map configuration for UE coordinate to GPS lat/lon conversion.

Formula (from C# reference):
    latitude  = lat_shift + (y / lat_div)
    longitude = lon_shift + (x / lon_div)

Where x, y are Unreal Engine world coordinates.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass


@dataclass
class MapConfig:
    """
    Configuration for a specific ARK map.

    Used to convert Unreal Engine coordinates to GPS lat/lon.

    Attributes:
        name: Human-readable map name.
        filename: Save file name (e.g., "theisland.ark").
        lat_shift: Latitude origin offset.
        lat_div: Latitude divisor (scale).
        lon_shift: Longitude origin offset.
        lon_div: Longitude divisor (scale).
    """

    name: str
    filename: str
    lat_shift: float = 50.0
    lat_div: float = 8000.0
    lon_shift: float = 50.0
    lon_div: float = 8000.0

    def ue_to_lat(self, y: float) -> float:
        """Convert UE Y coordinate to latitude."""
        return self.lat_shift + (y / self.lat_div)

    def ue_to_lon(self, x: float) -> float:
        """Convert UE X coordinate to longitude."""
        return self.lon_shift + (x / self.lon_div)

    def ue_to_gps(self, x: float, y: float) -> tuple[float, float]:
        """
        Convert UE coordinates to GPS (latitude, longitude).

        Returns:
            Tuple of (latitude, longitude).
        """
        return (self.ue_to_lat(y), self.ue_to_lon(x))

    def ccc_string(self, x: float, y: float, z: float) -> str:
        """Format coordinates as a cheat setplayerpos string."""
        return f"{x} {y} {z}"


# ============================================================================
# Built-in map configurations from C# ArkViewer maps.json
# ============================================================================

# fmt: off
_MAP_CONFIGS: list[MapConfig] = [
    # Official ASE Maps
    MapConfig("The Island (Evolved)", "theisland.ark", 50.0, 8000.0, 50.0, 8000.0),
    MapConfig("Scorched Earth", "scorchedearth_p.ark", 50.0, 8000.0, 50.0, 8000.0),
    MapConfig("Aberration (Evolved)", "aberration_p.ark", 50.0, 8000.0, 50.0, 8000.0),
    MapConfig("Extinction (Evolved)", "extinction.ark", 50.0, 8000.0, 50.0, 8000.0),
    MapConfig("The Center (Evolved)", "thecenter.ark", 30.34223747253418, 9584.0, 55.10416793823242, 9600.0),
    MapConfig("Ragnarok", "ragnarok.ark", 50.009388, 13100.0, 50.009388, 13100.0),
    MapConfig("Valguero", "valguero_p.ark", 50.0, 8161.0, 50.0, 8161.0),
    MapConfig("Crystal Isles", "crystalisles.ark", 48.687, 15882.02, 49.9481, 16988.76),
    MapConfig("Genesis", "genesis.ark", 50.0, 10500.0, 50.0, 10500.0),
    MapConfig("Genesis 2", "gen2.ark", 49.6, 14500.0, 49.6, 14500.0),
    MapConfig("Lost Island", "lostisland.ark", 51.6, 15300.0, 49.0, 15300.0),
    MapConfig("Fjordur", "fjordur.ark", 50.0, 7140.0, 50.0, 7140.0),

    # Official ASA Maps
    MapConfig("The Island (Ascended)", "theisland_wp.ark", 50.0, 6850.0, 50.0, 6850.0),
    MapConfig("The Center (Ascended)", "thecenter_wp.ark", 32.5, 10380.52, 50.5, 10374.29),
    MapConfig("Scorched Earth (Ascended)", "scorchedearth_wp.ark", 50.0, 8000.0, 50.0, 8000.0),
    MapConfig("Aberration (Ascended)", "aberration_wp.ark", 50.0, 8000.0, 50.0, 8000.0),
    MapConfig("Extinction (Ascended)", "extinction_wp.ark", 50.0, 6850.0, 50.0, 6850.0),
    MapConfig("Ragnarok (Ascended)", "ragnarok_wp.ark", 50.009388, 13100.0, 50.009388, 13100.0),
    MapConfig("Valguero (Ascended)", "valguero_wp.ark", 50.0, 8161.0, 50.0, 8161.0),

    # Community / Modded Maps
    MapConfig("Astral ARK", "astralark.ark", 50.0, 2000.0, 50.0, 2000.0),
    MapConfig("Hope", "hope.ark", 50.0, 6850.0, 50.0, 6850.0),
    MapConfig("Tunguska", "tunguska_p.ark", 46.8, 14000.0, 49.29, 13300.0),
    MapConfig("Caballus", "caballus_p.ark", 50.0, 8125.0, 50.0, 8125.0),
    MapConfig("Tiamat Prime", "tiamatprime.ark", 50.0, 8000.0, 50.0, 8000.0),
    MapConfig("Glacius", "glacius_p.ark", 50.0, 16250.0, 50.0, 16250.0),
    MapConfig("Antartika", "antartika.ark", 50.0, 8000.0, 50.0, 8000.0),
    MapConfig("Amissa (Evolved)", "amissa.ark", 49.9, 10900.0, 49.9, 10850.0),
    MapConfig("Amissa (Ascended)", "amissa_wp.ark", 46.9, 11375.0, 48.1, 11400.0),
    MapConfig("Olympus", "olympus.ark", 0.0, 8130.0, 0.0, 8130.0),
    MapConfig("Ebenus Astrum", "ebenusastrum.ark", 52.9, 8650.0, 25.0, 18500.0),
    MapConfig("ARKForum Event Map", "arkforum_eventmap.ark", 50.0, 1500.0, 50.0, 1500.0),
    MapConfig("The Volcano", "thevolcano.ark", 50.0, 9200.0, 50.0, 9200.0),
    MapConfig("The Earrion", "earrion_p.ark", 50.0, 6250.0, 50.0, 6250.0),
    MapConfig("Alemia", "Alemia_P.ark", 50.0, 8150.0, 50.0, 8150.0),
    MapConfig("Velius", "Velius_P.ark", 50.0, 8575.0, 50.0, 8575.0),
    MapConfig("Svartalfheim (Evolved)", "Svartalfheim.ark", 50.0, 4065.0, 50.0, 4065.0),
    MapConfig("Svartalfheim (Ascended)", "Svartalfheim_WP.ark", 50.0, 4055.0, 50.0, 4055.0),
    MapConfig("TaeniaStella", "TaeniaStella.ark", 48.9, 15500.0, 48.9, 15500.0),
    MapConfig("Forglar (Ascended)", "forglar_wp.ark", 61.4, 7150.0, 69.8, 7945.0),
    MapConfig("Insaluna (Ascended)", "insaluna_wp.ark", 50.0, 9400.0, 50.0, 9400.0),
    MapConfig("Temptress Lagoon (Ascended)", "temptress_wp.ark", 50.0, 8150.0, 50.0, 8150.0),
    MapConfig("Reverence (Ascended)", "reverence_wp.ark", 50.0, 8125.0, 50.0, 8125.0),
    MapConfig("Nyrandil (Ascended)", "nyrandil.ark", 50.0, 8175.0, 50.0, 8175.0),
    MapConfig("Astraeos (Ascended)", "astraeos_wp.ark", 50.0, 16000.0, 50.0, 16000.0),
    MapConfig("Gun Smoke", "gunsmoke.ark", 12.1, 7900.0, 10.8, 7850.0),
    MapConfig("Fjell", "viking_p.ark", 50.0, 7140.0, 50.0, 7140.0),
]
# fmt: on

# Build lookup by filename (case-insensitive)
_MAP_BY_FILENAME: dict[str, MapConfig] = {cfg.filename.lower(): cfg for cfg in _MAP_CONFIGS}

# Default config for unknown maps
DEFAULT_MAP_CONFIG = MapConfig("Unknown", "unknown.ark", 50.0, 8000.0, 50.0, 8000.0)


def get_map_config(filename: str) -> MapConfig:
    """
    Get map configuration by save filename.

    Args:
        filename: The save file name (e.g., "ragnarok.ark").

    Returns:
        MapConfig for the map, or DEFAULT_MAP_CONFIG if not found.
    """
    return _MAP_BY_FILENAME.get(filename.lower(), DEFAULT_MAP_CONFIG)


def get_map_config_by_name(name: str) -> MapConfig:
    """
    Get map configuration by display name (case-insensitive partial match).

    Args:
        name: Map display name or partial match (e.g., "Ragnarok", "The Island").

    Returns:
        MapConfig for the map, or DEFAULT_MAP_CONFIG if not found.
    """
    name_lower = name.lower()
    for cfg in _MAP_CONFIGS:
        if name_lower in cfg.name.lower():
            return cfg
    return DEFAULT_MAP_CONFIG


def list_maps() -> list[MapConfig]:
    """
    Get all available map configurations.

    Returns:
        List of all registered MapConfig instances.
    """
    return list(_MAP_CONFIGS)
