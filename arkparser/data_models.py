"""
Data Models for extracted ARK data.

These dataclasses provide clean, typed access to the nested
property data from ARK save files.
"""

from __future__ import annotations

import logging
import math
import re
import typing as t
from dataclasses import dataclass, field

from .common.binary_reader import BinaryReader
from .common.normalization import normalize_indexed_data, normalize_indexed_list
from .common.types import CRYOPOD_CLASS_PATTERNS
from .properties.registry import read_properties

logger = logging.getLogger(__name__)

# Uploaded items match against lowercased blueprint paths.
_CRYOPOD_PATTERNS_LOWER: tuple[str, ...] = tuple(p.lower() for p in CRYOPOD_CLASS_PATTERNS)

# Trailing UE actor spawn-instance suffix on cryopod class names, e.g.
# "Raptor_Character_BP_C_2145673735". ARK stores the full instance name in the
# cryopod CustomDataStrings/SoftClasses blob; the worldsave name-table path
# discards this instance int32, so non-cryo tames never carry it. Strip it to
# match the canonical class name ("Raptor_Character_BP_C") and legacy parity.
_INSTANCE_SUFFIX_RE = re.compile(r"_\d+$")


def _strip_instance_suffix(class_name: str) -> str:
    """Drop a trailing ``_<digits>`` actor-instance suffix from a class name.

    Pre: ``class_name`` is a str. Post: returns the same string with at most one
    trailing ``_<digits>`` group removed. Legit variant suffixes (``_Aberrant_C``,
    ``_Fire_C``) end in a letter, so they are never touched.
    """
    assert isinstance(class_name, str), "class_name must be str"
    stripped = _INSTANCE_SUFFIX_RE.sub("", class_name)
    assert len(stripped) <= len(class_name), "strip must not grow the string"
    return stripped


def _finite(value: t.Any, default: float) -> float:
    """Coerce to a finite float; NaN / inf / non-numeric collapse to ``default``.

    Non-finite floats are invalid JSON tokens that crash strict serializers
    (``json.dumps(allow_nan=False)``, JS ``JSON.parse``, pydantic). Legacy
    ASVExport substitutes ``0.0001`` for a NaN item rating (ContentItem.cs:62);
    other non-finite floats fall back to ``0.0``.
    """
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


@dataclass
class DinoStats:
    """Statistics for a creature."""

    health: float = 0.0
    max_health: float = 0.0
    stamina: float = 0.0
    max_stamina: float = 0.0
    torpidity: float = 0.0
    max_torpidity: float = 0.0
    oxygen: float = 0.0
    max_oxygen: float = 0.0
    food: float = 0.0
    max_food: float = 0.0
    water: float = 0.0
    max_water: float = 0.0
    weight: float = 0.0
    max_weight: float = 0.0
    melee_damage: float = 100.0  # Percentage
    movement_speed: float = 100.0  # Percentage
    crafting_skill: float = 100.0  # Percentage

    @classmethod
    def from_stat_strings(cls, stat_strings: list[str] | None) -> DinoStats:
        """
        Parse stats from the DinoStats string array format.

        Format examples:
        - "Health: 365.0 / 404.0"
        - "Melee Damage: 369.6 %"
        """
        stats = cls()
        if not stat_strings:
            return stats

        for stat_str in stat_strings:
            if ": " not in stat_str:
                continue

            name, value_part = stat_str.split(": ", 1)
            name = name.lower().replace(" ", "_")

            try:
                if " / " in value_part:
                    # Current / Max format
                    current, maximum = value_part.split(" / ")
                    current = float(current)
                    maximum = float(maximum)

                    if name == "health":
                        stats.health = current
                        stats.max_health = maximum
                    elif name == "stamina":
                        stats.stamina = current
                        stats.max_stamina = maximum
                    elif name == "torpidity":
                        stats.torpidity = current
                        stats.max_torpidity = maximum
                    elif name == "oxygen":
                        stats.oxygen = current
                        stats.max_oxygen = maximum
                    elif name == "food":
                        stats.food = current
                        stats.max_food = maximum
                    elif name == "water":
                        stats.water = current
                        stats.max_water = maximum
                    elif name == "weight":
                        stats.weight = current
                        stats.max_weight = maximum

                elif value_part.endswith(" %"):
                    # Percentage format
                    pct = float(value_part.replace(" %", ""))
                    if name == "melee_damage":
                        stats.melee_damage = pct
                    elif name == "movement_speed":
                        stats.movement_speed = pct
                    elif name == "crafting_skill":
                        stats.crafting_skill = pct

            except (ValueError, IndexError):
                continue

        return stats

    def to_dict(self) -> dict[str, float]:
        """Convert to dictionary."""
        return {
            "health": self.health,
            "max_health": self.max_health,
            "stamina": self.stamina,
            "max_stamina": self.max_stamina,
            "torpidity": self.torpidity,
            "max_torpidity": self.max_torpidity,
            "oxygen": self.oxygen,
            "max_oxygen": self.max_oxygen,
            "food": self.food,
            "max_food": self.max_food,
            "water": self.water,
            "max_water": self.max_water,
            "weight": self.weight,
            "max_weight": self.max_weight,
            "melee_damage": self.melee_damage,
            "movement_speed": self.movement_speed,
            "crafting_skill": self.crafting_skill,
        }


@dataclass
class UploadedCreature:
    """
    An uploaded creature from cloud inventory.

    Provides clean access to creature properties.
    """

    # Core identification
    class_name: str = ""
    blueprint: str = ""
    name: str = ""
    species: str = ""

    # IDs
    dino_id1: int = 0
    dino_id2: int = 0

    # Stats
    level: int = 1
    experience: float = 0.0
    stats: DinoStats = field(default_factory=DinoStats)

    # Upload info
    upload_time: int = 0
    version: float = 0.0

    # Raw data for advanced access
    raw_data: dict[str, t.Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_ark_data(cls, data: dict[str, t.Any]) -> UploadedCreature:
        """
        Create from ArkTamedDinosData struct.

        Args:
            data: The raw dino data dictionary from parsing.
        """
        data = t.cast(dict[str, t.Any], normalize_indexed_data(data))

        # Parse species from name like "Rex - Lvl 226 (Dodo)"
        dino_name = data.get("DinoName", "")
        species = ""
        tame_name = ""
        level = 1

        if dino_name:
            # Format: "TameName - Lvl N (Species)"
            if " - Lvl " in dino_name and "(" in dino_name:
                parts = dino_name.split(" - Lvl ")
                tame_name = parts[0] if parts else ""
                if len(parts) > 1:
                    lvl_species = parts[1]
                    if " (" in lvl_species:
                        lvl_str, species_part = lvl_species.split(" (", 1)
                        try:
                            level = int(lvl_str)
                        except ValueError:
                            pass
                        species = species_part.rstrip(")")
            else:
                tame_name = dino_name

        # Parse stats
        stats = DinoStats.from_stat_strings(normalize_indexed_list(data.get("DinoStats")))

        return cls(
            class_name=data.get("DinoClass", ""),
            blueprint=data.get("DinoClassName", ""),
            name=tame_name,
            species=species,
            dino_id1=data.get("DinoID1", 0),
            dino_id2=data.get("DinoID2", 0),
            level=level,
            experience=_finite(data.get("DinoExperiencePoints", 0.0), 0.0),
            stats=stats,
            upload_time=data.get("UploadTime", 0),
            version=data.get("Version", 0.0),
            raw_data=data,
        )

    @property
    def unique_id(self) -> str:
        """Get unique ID as combined string."""
        return f"{self.dino_id1}_{self.dino_id2}"

    def to_dict(self) -> dict[str, t.Any]:
        """Convert to dictionary."""
        return {
            "class_name": self.class_name,
            "blueprint": self.blueprint,
            "name": self.name,
            "species": self.species,
            "dino_id1": self.dino_id1,
            "dino_id2": self.dino_id2,
            "unique_id": self.unique_id,
            "level": self.level,
            "experience": self.experience,
            "stats": self.stats.to_dict(),
            "upload_time": self.upload_time,
            "version": self.version,
        }


@dataclass
class CryopodCreature:
    """
    A creature stored inside a cryopod.

    Contains parsed creature data from the cryopod's CustomItemDatas byte array.
    """

    # Core identification
    class_name: str = ""
    name: str = ""
    species: str = ""

    # IDs
    dino_id1: int = 0
    dino_id2: int = 0

    # Stats
    level: int = 1
    experience: float = 0.0

    # Owner info
    tamer_name: str = ""
    owner_name: str = ""
    taming_team_id: int = 0
    owning_player_id: int = 0

    # Server info
    tamed_on_server: str = ""
    uploaded_from_server: str = ""

    # Colors (6 color regions)
    colors: list[int] = field(default_factory=list)
    color_names: list[str] = field(default_factory=list)

    # Stats - current and max values
    current_stats: dict[str, float] = field(default_factory=dict)
    max_stats: dict[str, float] = field(default_factory=dict)
    base_stats: dict[str, float] = field(default_factory=dict)
    level_ups_wild: dict[str, int] = field(default_factory=dict)
    level_ups_tamed: dict[str, int] = field(default_factory=dict)

    # Raw parsed properties for advanced access
    creature_props: dict[str, t.Any] = field(default_factory=dict, repr=False)
    status_props: dict[str, t.Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_cryopod_bytes(cls, byte_data: list[int]) -> CryopodCreature | None:
        """
        Parse creature data from cryopod CustomDataBytes.

        Args:
            byte_data: The raw bytes from CustomDataBytes.ByteArrays[0].Bytes

        Returns:
            CryopodCreature with parsed data, or None if parsing fails.
        """
        try:
            reader = BinaryReader.from_bytes(bytes(byte_data))

            # First int32 is object count
            obj_count = reader.read_int32()
            if obj_count < 1:
                return None

            # Read object headers
            # Format: GUID(16) + ClassName(string) + IsItem(int32) + NamesCount(int32)
            #         + Names(strings, no instance index) + FromDataFile(int32)
            #         + DataFileIndex(int32) + HasLocation(int32) + [LocationData(24)]
            #         + PropsOffset(int32) + Unknown(int32)
            objects: list[dict[str, t.Any]] = []
            for _ in range(obj_count):
                obj: dict[str, t.Any] = {}

                # Read GUID (16 bytes of zeros for ASE)
                obj["guid"] = reader.read_bytes(16)

                # Read class name
                obj["class_name"] = reader.read_string()

                # Read flag (whether this is an item)
                obj["is_item"] = reader.read_int32() != 0

                # Read names count and names (NO instance indices in cryopod format)
                names_count = reader.read_int32()
                obj["names"] = [reader.read_string() for _ in range(names_count)]

                # Read more header fields
                obj["from_data_file"] = reader.read_int32() != 0
                obj["data_file_index"] = reader.read_int32()

                # Read has_location flag
                has_location = reader.read_int32() != 0
                if has_location:
                    # Skip location data (6 floats: x, y, z, pitch, yaw, roll)
                    reader.skip(24)

                # Read properties offset (where this object's properties start)
                obj["props_offset"] = reader.read_int32()

                # Read unknown int (always 0)
                reader.read_int32()

                objects.append(obj)

            # Now read properties for each object by seeking to props_offset
            for obj in objects:
                try:
                    reader.position = obj["props_offset"]
                    props = read_properties(reader, is_asa=False)
                    # Convert to dict, handling duplicate property names (indexed props)
                    props_dict: dict[str, t.Any] = {}
                    for p in props:
                        key = f"{p.name}_{p.index}" if p.index > 0 else p.name
                        props_dict[key] = p.value
                    obj["properties"] = props_dict
                except Exception:
                    # Don't let one drifted object silently zero out: log it so
                    # cryopod decode regressions surface instead of returning
                    # empty stats with no diagnostic (was a blind swallow).
                    logger.debug(
                        "Failed to parse cryopod object properties at offset %s",
                        obj.get("props_offset"),
                        exc_info=True,
                    )
                    obj["properties"] = {}

            # Find creature object (first one) and status component
            creature_obj = objects[0] if objects else None
            status_obj = None
            for obj in objects:
                class_name = obj.get("class_name", "")
                if "DinoCharacterStatus" in class_name:
                    status_obj = obj
                    break

            if not creature_obj:
                return None

            creature_props = creature_obj.get("properties", {})
            status_props = status_obj.get("properties", {}) if status_obj else {}

            # Extract creature data
            cryo = cls()
            cryo.class_name = creature_obj.get("class_name", "")

            # Extract species from class name
            # e.g., "Raptor_Character_BP_C" -> "Raptor"
            if cryo.class_name:
                species = cryo.class_name.replace("_Character_BP_C", "").replace("_C", "")
                cryo.species = species.replace("_", " ")

            # Basic creature properties
            cryo.name = creature_props.get("TamedName", "")
            cryo.tamer_name = creature_props.get("TamerString", "")
            cryo.owner_name = creature_props.get("OwningPlayerName", "")
            cryo.taming_team_id = creature_props.get("TamingTeamID", 0)
            cryo.owning_player_id = creature_props.get("OwningPlayerID", 0)
            cryo.dino_id1 = creature_props.get("DinoID1", 0)
            cryo.dino_id2 = creature_props.get("DinoID2", 0)
            cryo.tamed_on_server = creature_props.get("TamedOnServerName", "")
            cryo.uploaded_from_server = creature_props.get("UploadedFromServerName", "")

            # Color data (indexed properties)
            cryo.colors = []
            cryo.color_names = []
            for i in range(6):
                # Check both indexed and non-indexed keys
                color_key = f"ColorSetIndices_{i}" if i > 0 else "ColorSetIndices"
                color = creature_props.get(color_key, 0)
                if isinstance(color, (int, float)):
                    cryo.colors.append(int(color))

                name_key = f"ColorSetNames_{i}" if i > 0 else "ColorSetNames"
                color_name = creature_props.get(name_key, "")
                if color_name:
                    cryo.color_names.append(str(color_name))

            # Status component stats
            stat_names = [
                "Health",
                "Stamina",
                "Torpidity",
                "Oxygen",
                "Food",
                "Water",
                "Temperature",
                "Weight",
                "MeleeDamage",
                "MovementSpeed",
                "Fortitude",
                "CraftingSkill",
            ]

            for i, stat_name in enumerate(stat_names):
                # Current values (indexed properties)
                current_key = f"CurrentStatusValues_{i}" if i > 0 else "CurrentStatusValues"
                current = status_props.get(current_key, None)
                if current is not None:
                    cryo.current_stats[stat_name] = float(current)

                # Max values
                max_key = f"MaxStatusValues_{i}" if i > 0 else "MaxStatusValues"
                max_val = status_props.get(max_key, None)
                if max_val is not None:
                    cryo.max_stats[stat_name] = float(max_val)

                # Base level max values
                base_key = f"BaseLevelMaxStatusValues_{i}" if i > 0 else "BaseLevelMaxStatusValues"
                base_val = status_props.get(base_key, None)
                if base_val is not None:
                    cryo.base_stats[stat_name] = float(base_val)

                # Level ups (wild)
                wild_key = f"NumberOfLevelUpPointsApplied_{i}" if i > 0 else "NumberOfLevelUpPointsApplied"
                wild_ups = status_props.get(wild_key, None)
                if wild_ups is not None:
                    cryo.level_ups_wild[stat_name] = int(wild_ups)

                # Level ups (tamed)
                tamed_key = f"NumberOfLevelUpPointsAppliedTamed_{i}" if i > 0 else "NumberOfLevelUpPointsAppliedTamed"
                tamed_ups = status_props.get(tamed_key, None)
                if tamed_ups is not None:
                    cryo.level_ups_tamed[stat_name] = int(tamed_ups)

            # Calculate level from status component
            base_level = status_props.get("BaseCharacterLevel", 1)
            extra_level = status_props.get("ExtraCharacterLevel", 0)
            cryo.level = int(base_level) + int(extra_level)
            cryo.experience = float(status_props.get("ExperiencePoints", 0.0))

            # Store raw props for advanced access
            cryo.creature_props = creature_props
            cryo.status_props = status_props

            return cryo

        except Exception:
            logger.debug("Failed to parse cryopod creature from bytes", exc_info=True)
            return None

    @classmethod
    def from_asa_cryopod_data(cls, custom_data: dict[str, t.Any]) -> CryopodCreature | None:
        """
        Parse creature data from ASA/ASE cryopod CustomItemDatas entry.

        Both ASA and ASE store cryopod creature data using:
        - CustomDataStrings: [class_name, display_name, colors_str, ?, gender, ?, ?, ...]
          - ASE has 7 strings, ASA has 10+ strings (with species at index 9)
        - CustomDataFloats: ASE = [current x 12, max x 12, +1] (25); ASA = [current
          x 11 (no CraftingSkill), max x 11, extras] (36). See the per-format
          branch below; the layouts genuinely differ in current-stat width.
        - CustomDataNames: Color names for the 6 color regions

        Args:
            custom_data: The CustomItemDatas entry with CustomDataName == "Dino"

        Returns:
            CryopodCreature with parsed data, or None if parsing fails.
        """
        try:
            custom_data = t.cast(dict[str, t.Any], normalize_indexed_data(custom_data))
            cryo = cls()

            # Parse strings - need at least 3 for basic info
            strings = normalize_indexed_list(custom_data.get("CustomDataStrings"))
            if len(strings) >= 3:
                cryo.class_name = _strip_instance_suffix(strings[0])  # raw: "Raptor_Character_BP_C_2145673735"
                display_name = strings[1]  # e.g., "bluey - Lvl 228 (Raptor)"
                colors_str = strings[2]  # e.g., "2,2,2,2,2,2,"

                # Parse display name for tame name, level, and species
                # Format: "Bluey - Lvl 226 (Raptor)"
                if " - Lvl " in display_name:
                    parts = display_name.split(" - Lvl ")
                    cryo.name = parts[0]
                    if len(parts) > 1:
                        lvl_species = parts[1]
                        if " (" in lvl_species:
                            lvl_part, species_part = lvl_species.split(" (", 1)
                            try:
                                cryo.level = int(lvl_part)
                            except ValueError:
                                pass
                            # Extract species from "(Raptor)"
                            cryo.species = species_part.rstrip(")")

                # If we have index 9 with species name (ASA format), use it
                if len(strings) > 9 and strings[9]:
                    cryo.species = strings[9]
                elif not cryo.species and cryo.class_name:
                    # Fall back to class name parsing
                    species = cryo.class_name.split("_Character_BP")[0]
                    cryo.species = species.replace("_", " ")

                # Parse colors from string "2,2,2,2,2,2,"
                if colors_str:
                    color_parts = colors_str.strip(",").split(",")
                    cryo.colors = [int(c) for c in color_parts if c.strip().isdigit()]

            # Parse color names
            color_names = normalize_indexed_list(custom_data.get("CustomDataNames"))
            if color_names:
                cryo.color_names = list(color_names)

            # Parse stats from floats
            # Format varies by version:
            # - ASE: 25 floats - current[0-11], max[12-23], extra[24]
            # - ASA: 36 floats - current[0-10], max[11-21], extra[22-35]
            floats = [float(value) for value in normalize_indexed_list(custom_data.get("CustomDataFloats"))]
            stat_names = [
                "Health",
                "Stamina",
                "Torpidity",
                "Oxygen",
                "Food",
                "Water",
                "Temperature",
                "Weight",
                "MeleeDamage",
                "MovementSpeed",
                "Fortitude",
                "CraftingSkill",
            ]

            if len(floats) >= 22:
                # ASA cryopod blob: 11 current stats + 11 max stats + extras (36 floats).
                # ASE cryopod blob: 12 current stats + 12 max stats + 1 extra (25 floats).
                # Without the per-format count, the ASA loop walks 12 names against an
                # 11-wide current block, leaking max[0] (which equals current[0] at full
                # HP) into current_stats["CraftingSkill"] and surfacing hp=craft on every
                # cryopod tame in exports.
                if len(floats) >= 36:
                    current_count = 11
                    max_offset = 11
                else:
                    current_count = 12
                    max_offset = 12

                # Current stats: only consume the per-format slot count
                for i in range(min(current_count, len(stat_names))):
                    if i < len(floats):
                        cryo.current_stats[stat_names[i]] = floats[i]

                # Max stats: same count, starting at offset
                for i in range(min(current_count, len(stat_names))):
                    max_idx = i + max_offset
                    if max_idx < len(floats):
                        cryo.max_stats[stat_names[i]] = floats[max_idx]

            # Parse soft class for blueprint reference
            soft_classes = normalize_indexed_list(custom_data.get("CustomDataSoftClasses"))
            if soft_classes:
                first_class = soft_classes[0]
                if isinstance(first_class, dict):
                    cryo.class_name = _strip_instance_suffix(
                        first_class.get("name", cryo.class_name)
                    )

            # Populate raw creature_props / status_props so the export
            # pipeline's _SyntheticGameObject adapter (which calls
            # ``get_property_value``) sees the fields it expects. ARK
            # cryopod CustomItemDatas blobs only carry a small subset of
            # the original creature properties (no DinoID, no TribeID, no
            # tamer string, etc.); surface what we have, leave the rest
            # absent so consumers can detect the gap.
            _stat_to_idx = {
                "Health": 0, "Stamina": 1, "Torpidity": 2, "Oxygen": 3,
                "Food": 4, "Water": 5, "Temperature": 6, "Weight": 7,
                "MeleeDamage": 8, "MovementSpeed": 9, "Fortitude": 10,
                "CraftingSkill": 11,
            }
            if cryo.name:
                cryo.creature_props["TamedName"] = cryo.name
            for i, color in enumerate(cryo.colors[:6]):
                cryo.creature_props[f"ColorSetIndices_{i}" if i > 0 else "ColorSetIndices"] = color
            if cryo.level:
                cryo.status_props["BaseCharacterLevel"] = cryo.level
            for stat_name, value in cryo.current_stats.items():
                idx = _stat_to_idx.get(stat_name)
                if idx is None:
                    continue
                key = "CurrentStatusValues" if idx == 0 else f"CurrentStatusValues_{idx}"
                cryo.status_props[key] = value

            return cryo

        except Exception:
            logger.debug("Failed to parse ASA cryopod creature data", exc_info=True)
            return None

    @property
    def unique_id(self) -> str:
        """Get unique ID as combined string."""
        return f"{self.dino_id1}_{self.dino_id2}"

    @property
    def stats(self) -> DinoStats:
        """Get stats in DinoStats format for compatibility."""
        return DinoStats(
            health=self.current_stats.get("Health", 0.0),
            max_health=self.max_stats.get("Health", 0.0),
            stamina=self.current_stats.get("Stamina", 0.0),
            max_stamina=self.max_stats.get("Stamina", 0.0),
            torpidity=self.current_stats.get("Torpidity", 0.0),
            max_torpidity=self.max_stats.get("Torpidity", 0.0),
            oxygen=self.current_stats.get("Oxygen", 0.0),
            max_oxygen=self.max_stats.get("Oxygen", 0.0),
            food=self.current_stats.get("Food", 0.0),
            max_food=self.max_stats.get("Food", 0.0),
            water=self.current_stats.get("Water", 0.0),
            max_water=self.max_stats.get("Water", 0.0),
            weight=self.current_stats.get("Weight", 0.0),
            max_weight=self.max_stats.get("Weight", 0.0),
            melee_damage=self.current_stats.get("MeleeDamage", 0.0) * 100 + 100,
            movement_speed=self.current_stats.get("MovementSpeed", 0.0) * 100 + 100,
            crafting_skill=self.current_stats.get("CraftingSkill", 1.0) * 100,
        )

    def to_dict(self) -> dict[str, t.Any]:
        """Convert to dictionary."""
        return {
            "class_name": self.class_name,
            "name": self.name,
            "species": self.species,
            "level": self.level,
            "experience": self.experience,
            "unique_id": self.unique_id,
            "dino_id1": self.dino_id1,
            "dino_id2": self.dino_id2,
            "tamer_name": self.tamer_name,
            "owner_name": self.owner_name,
            "taming_team_id": self.taming_team_id,
            "owning_player_id": self.owning_player_id,
            "tamed_on_server": self.tamed_on_server,
            "uploaded_from_server": self.uploaded_from_server,
            "colors": self.colors,
            "color_names": self.color_names,
            "current_stats": self.current_stats,
            "max_stats": self.max_stats,
            "base_stats": self.base_stats,
            "level_ups_wild": self.level_ups_wild,
            "level_ups_tamed": self.level_ups_tamed,
        }


@dataclass
class UploadedItem:
    """
    An uploaded item from cloud inventory.

    Provides clean access to item properties.
    """

    # Core identification
    blueprint: str = ""
    name: str = ""
    custom_name: str = ""

    # IDs
    item_id1: int = 0
    item_id2: int = 0

    # Item properties
    quantity: int = 1
    quality_index: int = 0
    durability: float = 0.0
    rating: float = 0.0
    slot_index: int = 0

    # Flags
    is_blueprint: bool = False
    is_engram: bool = False

    # Upload info
    upload_time: float = 0.0

    # Raw data for advanced access
    raw_data: dict[str, t.Any] = field(default_factory=dict, repr=False)

    # Cached cryopod creature
    _cryopod_creature: CryopodCreature | None = field(default=None, repr=False, init=False)

    @classmethod
    def from_ark_data(cls, data: dict[str, t.Any]) -> UploadedItem:
        """
        Create from ArkItems struct.

        Args:
            data: The raw item data dictionary from parsing.
        """
        data = t.cast(dict[str, t.Any], normalize_indexed_data(data))
        ark_tribute = t.cast(dict[str, t.Any], normalize_indexed_data(data.get("ArkTributeItem", {})))
        item_id = ark_tribute.get("ItemId", {})

        # Extract item name from blueprint path. Corrupted/legacy cluster
        # entries occasionally store ItemArchetype as a non-string sentinel
        # (int 0, None, etc.); coerce so the downstream ``"." in blueprint``
        # doesn't TypeError out the whole CloudInventory.uploaded_items call.
        raw_blueprint = ark_tribute.get("ItemArchetype", "")
        blueprint = raw_blueprint if isinstance(raw_blueprint, str) else ""
        name = ""
        if blueprint and "." in blueprint:
            # Extract class name from path like "BlueprintGeneratedClass /Game/.../WeaponTek.WeaponTek_C"
            name = blueprint.rsplit(".", 1)[-1].replace("_C", "")

        return cls(
            blueprint=blueprint,
            name=name,
            custom_name=ark_tribute.get("CustomItemName", ""),
            item_id1=item_id.get("ItemID1", 0) if isinstance(item_id, dict) else 0,
            item_id2=item_id.get("ItemID2", 0) if isinstance(item_id, dict) else 0,
            quantity=ark_tribute.get("ItemQuantity", 1) or 1,
            quality_index=ark_tribute.get("ItemQualityIndex", 0),
            durability=_finite(ark_tribute.get("ItemDurability", 0.0), 0.0),
            rating=_finite(ark_tribute.get("ItemRating", 0.0), 0.0001),
            slot_index=ark_tribute.get("SlotIndex", 0),
            is_blueprint=ark_tribute.get("bIsBlueprint", False),
            is_engram=ark_tribute.get("bIsEngram", False),
            upload_time=data.get("UploadTime", 0.0),
            raw_data=data,
        )

    @property
    def unique_id(self) -> str:
        """Get unique ID as combined string."""
        return f"{self.item_id1}_{self.item_id2}"

    @property
    def quality_name(self) -> str:
        """Get quality tier name."""
        qualities = [
            "Primitive",
            "Ramshackle",
            "Apprentice",
            "Journeyman",
            "Mastercraft",
            "Ascendant",
        ]
        if 0 <= self.quality_index < len(qualities):
            return qualities[self.quality_index]
        return "Unknown"

    @property
    def display_name(self) -> str:
        """Get display name (custom name or extracted name)."""
        return self.custom_name or self.name

    @property
    def is_cryopod(self) -> bool:
        """Check if this item is a cryopod (or similar creature storage item)."""
        bp_lower = self.blueprint.lower()
        return any(x in bp_lower for x in _CRYOPOD_PATTERNS_LOWER)

    @property
    def cryopod_creature(self) -> CryopodCreature | None:
        """
        Get the creature stored in this cryopod.

        Returns:
            CryopodCreature with parsed creature data, or None if not a cryopod
            or if parsing fails.
        """
        if not self.is_cryopod:
            return None

        # Return cached if already parsed
        if self._cryopod_creature is not None:
            return self._cryopod_creature

        # Try to parse from CustomItemDatas
        ark_tribute = t.cast(dict[str, t.Any], normalize_indexed_data(self.raw_data.get("ArkTributeItem", {})))
        custom_datas = normalize_indexed_list(ark_tribute.get("CustomItemDatas"))

        for entry in custom_datas:
            # Look for the "Dino" data entry
            if entry.get("CustomDataName") == "Dino":
                # Prefer byte blob parsing (gives full creature/status properties)
                cryo_bytes = t.cast(dict[str, t.Any], normalize_indexed_data(entry.get("CustomDataBytes", {})))
                byte_arrays = normalize_indexed_list(cryo_bytes.get("ByteArrays"))

                if byte_arrays and "Bytes" in byte_arrays[0]:
                    byte_data = byte_arrays[0]["Bytes"]
                    self._cryopod_creature = CryopodCreature.from_cryopod_bytes(byte_data)
                    if self._cryopod_creature:
                        # Supplement with CustomDataStrings/Names if available
                        # (species name at index 9, color names from CustomDataNames)
                        strings = normalize_indexed_list(entry.get("CustomDataStrings"))
                        if len(strings) > 9 and strings[9]:
                            self._cryopod_creature.species = strings[9]
                        color_names = normalize_indexed_list(entry.get("CustomDataNames"))
                        if color_names:
                            self._cryopod_creature.color_names = list(color_names)
                        return self._cryopod_creature

                # Fall back to CustomDataStrings/Floats parsing
                if entry.get("CustomDataStrings"):
                    self._cryopod_creature = CryopodCreature.from_asa_cryopod_data(entry)
                    if self._cryopod_creature:
                        return self._cryopod_creature

        return None

    def to_dict(self) -> dict[str, t.Any]:
        """Convert to dictionary."""
        return {
            "blueprint": self.blueprint,
            "name": self.name,
            "custom_name": self.custom_name,
            "display_name": self.display_name,
            "item_id1": self.item_id1,
            "item_id2": self.item_id2,
            "unique_id": self.unique_id,
            "quantity": self.quantity,
            "quality_index": self.quality_index,
            "quality_name": self.quality_name,
            "durability": self.durability,
            "rating": self.rating,
            "slot_index": self.slot_index,
            "is_blueprint": self.is_blueprint,
            "is_engram": self.is_engram,
            "upload_time": self.upload_time,
        }
