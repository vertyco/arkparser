# ARK Save Parser

[![Python 3.10](https://img.shields.io/badge/python-3.10-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Python 3.14](https://img.shields.io/badge/python-3.14-blue?logo=python&logoColor=white)](https://www.python.org/)

![Typed](https://img.shields.io/badge/typing-py.typed-brightgreen)
![No Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)
![Ruff](https://img.shields.io/badge/style-ruff-D7FF64?logo=ruff&logoColor=D7FF64)
![license](https://img.shields.io/github/license/Vertyco/arkparser)

A pure-Python library for parsing ARK: Survival Evolved (ASE) and ARK: Survival Ascended (ASA) save files. Zero third-party dependencies.

---

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Quick Start](#quick-start)
  - [Player Profile](#player-profile)
  - [Tribe Data](#tribe-data)
  - [Cloud Inventory / Obelisk](#cloud-inventory--obelisk)
  - [World Save](#world-save)
  - [World Save Models](#world-save-models)
  - [JSON Export (ASV-compatible)](#json-export-asv-compatible)
- [Package Structure](#package-structure)
- [API Reference](#api-reference)
  - [File Parsers](#file-parsers)
    - [Profile](#profile)
    - [Tribe (File Parser)](#tribe-file-parser)
    - [CloudInventory](#cloudinventory)
    - [WorldSave](#worldsave)
  - [Game Objects](#game-objects)
    - [GameObject](#gameobject)
    - [GameObjectContainer](#gameobjectcontainer)
    - [LocationData](#locationdata)
  - [Models](#models)
    - [TamedCreature](#tamedcreature)
    - [WildCreature](#wildcreature)
    - [Player](#player)
    - [Character](#character)
    - [Structure](#structure)
    - [Item](#item)
    - [TribeModel](#tribemodel)
    - [TribeMember](#tribemember)
    - [TribeLogEntry](#tribelogentry)
    - [CreatureStats](#creaturestats)
    - [Location](#location)
  - [Data Models](#data-models)
    - [UploadedCreature](#uploadedcreature)
    - [UploadedItem](#uploadeditem)
    - [CryopodCreature](#cryopodcreature)
    - [DinoStats](#dinostats)
  - [Export Functions](#export-functions)
  - [Map Config](#map-config)
  - [Version Detection](#version-detection)
  - [Exceptions](#exceptions)
- [Format Support](#format-support)
- [Credits](#credits)

## Features

- **Player Profiles** (`.arkprofile`) — character name, level, stats, engrams
- **Tribe Data** (`.arktribe`) — members, ranks, logs, alliances
- **Cloud Inventory / Obelisk** — uploaded creatures, items, cryopod contents
- **World Saves** (`.ark`) — full map state: creatures, structures, items, players
- **Dual Format** — automatic ASE (v5-6) / ASA (v7+, SQLite) detection
- **Export** — ASV-compatible JSON export with GPS coordinate conversion
- **Typed** — full type annotations, `py.typed` marker

## Installation

```bash
pip install arkparser
# or editable install for development
pip install -e .
```

## Quick Start

### Player Profile

```python
from arkparser import Profile

profile = Profile.load("path/to/player.arkprofile")  # auto-detects ASE/ASA

print(profile.player_name)         # "SomePlayer"
print(profile.level)               # 105
print(profile.tribe_id)            # 1729028872
print(profile.engram_blueprints)   # ["EngramEntry_Campfire_C", ...]
print(profile.get_stat(0))         # Health level-up points
print(profile.to_dict())           # Full dict export
```

### Tribe Data

```python
from arkparser import Tribe

tribe = Tribe.load("path/to/tribe.arktribe")

print(tribe.name)           # "My Tribe"
print(tribe.tribe_id)       # 1729028872
print(tribe.member_count)   # 3
for member in tribe.get_members():
    print(f"  {member['name']} (ID: {member['id']})")
print(tribe.log_entries)    # ["Day 45: Tamed a Rex", ...]
```

### Cloud Inventory / Obelisk

```python
from arkparser import CloudInventory

inv = CloudInventory.load("path/to/obelisk_file")  # or use Obelisk alias

print(f"Creatures: {inv.creature_count}")
print(f"Items: {inv.item_count}")

for creature in inv.uploaded_creatures:
    print(f"  {creature.species} Lv{creature.level} - {creature.name}")
    print(f"  Stats: {creature.stats.to_dict()}")

for item in inv.uploaded_items:
    print(f"  {item.display_name} x{item.quantity} ({item.quality_name})")
    if item.is_cryopod and item.cryopod_creature:
        cryo = item.cryopod_creature
        print(f"    Contains: {cryo.species} Lv{cryo.level}")
```

### World Save

```python
from arkparser import WorldSave

# Works with both ASE (binary) and ASA (SQLite) — auto-detected
save = WorldSave.load("path/to/Extinction.ark")       # ASE
save = WorldSave.load("path/to/Extinction_WP.ark")    # ASA

print(f"Objects: {save.object_count}")
print(f"Creatures: {len(save.get_creatures())}")
print(f"Structures: {len(save.get_structures())}")
print(f"Parse errors: {save.parse_error_count}")
print(f"Is ASA: {save.is_asa}")
```

### World Save Models

Extract typed models from parsed world saves:

```python
from arkparser.models import TamedCreature, WildCreature, Player, Structure

# From game objects in a world save
for obj in save.objects:
    class_name = obj.class_name or ""
    if "DinoCharacterStatusComponent" not in class_name:
        tamed = TamedCreature.from_game_object(obj, status_component)
        print(f"{tamed.name} Lv{tamed.level}")
```

### JSON Export (ASV-compatible)

```python
from arkparser import export_all
from arkparser.common import get_map_config

map_config = get_map_config("extinction.ark")
data = export_all(save, map_config)
# Returns: {"ASV_Tamed": [...], "ASV_Wild": [...], "ASV_Players": [...], ...}
```

Or export to files:

```python
from arkparser import export_to_files

export_to_files(save, "output/", map_config)
# Creates: ASV_Tamed.json, ASV_Wild.json, ASV_Players.json, etc.
```

## Package Structure

```
arkparser/
├── __init__.py          # Public API
├── data_models.py       # UploadedCreature, UploadedItem, CryopodCreature, DinoStats
├── export.py            # ASV-compatible JSON export functions
├── common/              # Binary reader, types, exceptions, map configs
├── files/               # File parsers (Profile, Tribe, CloudInventory, WorldSave)
├── game_objects/        # GameObject, GameObjectContainer, LocationData
├── models/              # High-level typed wrappers (Creature, Player, Structure, etc.)
├── properties/          # Property parsing system (ArrayProperty, StructProperty, etc.)
└── structs/             # Struct types (Vector, Color, Guid, etc.)
```

---

## API Reference

### File Parsers

All file parsers support `load(source)` which accepts `str`, `Path`, or `bytes` and auto-detects ASE/ASA format.

#### Profile

`arkparser.files.profile.Profile` — Parser for `.arkprofile` player profile files.

| Property | Type | Description |
|---|---|---|
| `player_name` | `str \| None` | Character name |
| `player_id` | `int \| None` | Unique player ID |
| `unique_id` | `str \| None` | Platform ID (Steam/Xbox numeric ID) |
| `tribe_id` | `int \| None` | Tribe ID (handles ASE `TribeId` / ASA `TribeID`) |
| `tribe_name` | `str \| None` | Always `None` — tribe name is not stored in profiles |
| `level` | `int` | Current level (`ExtraCharacterLevel + 1`) |
| `experience` | `float` | Total XP |
| `total_engram_points` | `int` | Engram points spent |
| `engram_blueprints` | `list[str]` | Learned engram blueprint paths |
| `version` | `int` | Save format version |
| `is_asa` | `bool` | Whether ASA format |
| `objects` | `list[GameObject]` | All parsed game objects |

| Method | Returns | Description |
|---|---|---|
| `load(source: str \| Path \| bytes)` | `Profile` | Load and parse a profile file |
| `get_stat(stat_index: int)` | `dict[str, Any]` | Stat value by index (0=Health … 11=Crafting) |
| `get_property_value(name, default=None)` | `Any` | Get property from the main object |
| `to_dict()` | `dict` | Full dictionary export |

#### Tribe (File Parser)

`arkparser.files.tribe.Tribe` — Parser for `.arktribe` tribe data files.

| Property | Type | Description |
|---|---|---|
| `name` | `str \| None` | Tribe name |
| `tribe_id` | `int \| None` | Unique tribe ID |
| `owner_player_id` | `int \| None` | Tribe owner's player ID |
| `member_ids` | `list[int]` | Member player IDs |
| `member_names` | `list[str]` | Member player names |
| `member_ranks` | `list[int]` | Member rank indices |
| `member_count` | `int` | Number of members |
| `log_entries` | `list[str]` | Raw tribe log strings |
| `rank_groups` | `list[dict]` | Rank definitions |
| `alliance_ids` | `list[int]` | Allied tribe IDs |
| `government_type` | `int` | Governance type (0=Player, 1=Tribe, 2=Personal) |

| Method | Returns | Description |
|---|---|---|
| `load(source: str \| Path \| bytes)` | `Tribe` | Load and parse a tribe file |
| `get_members()` | `list[dict]` | Detailed member info: `{player_id, name, rank}` |
| `to_dict()` | `dict` | Full dictionary export |

#### CloudInventory

`arkparser.files.cloud_inventory.CloudInventory` — Parser for obelisk/cloud inventory files. Also available as `Obelisk`.

| Property | Type | Description |
|---|---|---|
| `uploaded_creatures` | `list[UploadedCreature]` | Uploaded creatures with stats |
| `uploaded_items` | `list[UploadedItem]` | Uploaded items (includes cryopods) |
| `creature_count` | `int` | Number of uploaded creatures |
| `item_count` | `int` | Number of uploaded items |
| `creatures` | `list[GameObject]` | Raw creature GameObjects |
| `items` | `list[GameObject]` | Raw item GameObjects |
| `characters` | `list[GameObject]` | Uploaded player characters |
| `character_count` | `int` | Number of uploaded characters |

| Method | Returns | Description |
|---|---|---|
| `load(source: str \| Path \| bytes)` | `CloudInventory` | Load and parse an obelisk file |
| `to_dict()` | `dict` | Full dictionary export |

#### WorldSave

`arkparser.files.world_save.WorldSave` — Unified parser for `.ark` world save files. Auto-detects ASE binary vs ASA SQLite.

| Property | Type | Description |
|---|---|---|
| `version` | `int` | Save format version |
| `game_time` | `float` | In-game time in seconds |
| `save_count` | `int` | Times the map has been saved (ASE v9+) |
| `is_asa` | `bool` | Whether ASA SQLite format |
| `objects` | `list[GameObject]` | All parsed game objects |
| `object_count` | `int` | Total object count |
| `parse_error_count` | `int` | Number of parsing errors |
| `parse_errors` | `list[str]` | Error messages (read-only) |
| `container` | `GameObjectContainer \| None` | Relationship-aware container (ASE only) |
| `actor_locations` | `dict[str, LocationData]` | GUID → location map (ASA only) |
| `location_count` | `int` | Number of actor locations (ASA only) |
| `data_files` | `list[str]` | External data file references |
| `name_table` | `list[str] \| dict[int, str]` | Deduplicated name strings |

| Method | Returns | Description |
|---|---|---|
| `load(source, load_properties=True, max_objects=None)` | `WorldSave` | Load and parse a world save |
| `get_creatures()` | `list[GameObject]` | All creatures (tamed and wild) |
| `get_tamed_creatures()` | `list[GameObject]` | Tamed creatures only |
| `get_wild_creatures()` | `list[GameObject]` | Wild creatures only |
| `get_structures()` | `list[GameObject]` | Tribe-owned placed structures |
| `get_player_pawns()` | `list[GameObject]` | Player characters on the map |
| `get_items()` | `list[GameObject]` | Item objects |
| `get_objects_by_class(class_name: str)` | `list[GameObject]` | Objects matching class name substring |
| `get_object_by_guid(guid: str)` | `GameObject \| None` | Lookup by GUID (ASA) |
| `get_actor_location(guid: str)` | `LocationData \| None` | Actor location by GUID (ASA) |
| `to_dict()` | `dict` | Metadata dictionary |

---

### Game Objects

#### GameObject

`arkparser.game_objects.game_object.GameObject` — The fundamental entity in ARK saves representing creatures, items, structures, players, etc.

| Field | Type | Description |
|---|---|---|
| `id` | `int` | Object index within the save |
| `guid` | `str` | 16-byte GUID (ASA only, empty for ASE) |
| `class_name` | `str` | UE4 class name |
| `is_item` | `bool` | Whether this is an item/blueprint/engram |
| `names` | `list[str]` | ArkName list (1 for actors, 2+ for components) |
| `location` | `LocationData \| None` | World position and rotation |
| `properties` | `list[Property]` | Parsed property list |
| `extra_data` | `bytes \| None` | Additional data after properties |
| `parent` | `GameObject \| None` | Parent object (set by container) |
| `components` | `dict[str, GameObject]` | Child component objects |

| Method | Returns | Description |
|---|---|---|
| `get_property(name, index=None)` | `Property \| None` | Get property by name and optional index |
| `get_property_value(name, default=None, index=None)` | `Any` | Get property value |
| `get_properties_by_name(name)` | `list[Property]` | All properties with given name |
| `has_property(name)` | `bool` | Check if property exists |
| `add_component(component)` | `None` | Add a child component |
| `to_dict()` | `dict` | Serialize to dictionary |

#### GameObjectContainer

`arkparser.game_objects.container.GameObjectContainer` — Relationship-aware container for game objects. Supports `len()`, iteration, and indexing.

| Method | Returns | Description |
|---|---|---|
| `add(obj)` | `None` | Add an object |
| `get_by_id(obj_id)` | `GameObject \| None` | Lookup by numeric ID |
| `get_by_guid(guid)` | `GameObject \| None` | Lookup by GUID |
| `get_by_name(name)` | `GameObject \| None` | Lookup by primary name |
| `get_by_class(class_name)` | `list[GameObject]` | Exact class name match |
| `find_by_class_pattern(pattern)` | `list[GameObject]` | Substring class name match |
| `build_relationships()` | `None` | Build parent/component relationships |
| `get_creatures()` | `list[GameObject]` | All creatures |
| `get_structures()` | `list[GameObject]` | Tribe-owned structures |
| `get_player_pawns()` | `list[GameObject]` | Player characters on map |
| `get_players()` | `list[GameObject]` | Player data objects |
| `get_items()` | `list[GameObject]` | Item objects |

#### LocationData

`arkparser.game_objects.location.LocationData` — 3D position and rotation.

| Field | Type | Description |
|---|---|---|
| `x` | `float` | X position |
| `y` | `float` | Y position |
| `z` | `float` | Z position |
| `pitch` | `float` | Pitch rotation |
| `yaw` | `float` | Yaw rotation |
| `roll` | `float` | Roll rotation |

| Property / Method | Returns | Description |
|---|---|---|
| `position` | `tuple[float, float, float]` | `(x, y, z)` tuple |
| `rotation` | `tuple[float, float, float]` | `(pitch, yaw, roll)` tuple |
| `to_dict()` | `dict[str, float]` | All 6 fields |

---

### Models

High-level typed wrappers created from `GameObject` instances via `from_game_object()`.

#### TamedCreature

`arkparser.models.creature.TamedCreature` — Tamed creature with full stats, breeding, and ownership data.

| Property | Type | Description |
|---|---|---|
| `class_name` | `str` | Blueprint class name |
| `name` | `str` | Player-given name |
| `tribe_name` | `str` | Owning tribe |
| `tamer_name` | `str` | Player who tamed it |
| `level` | `int` | Total level (base + extra) |
| `base_level` | `int` | Wild/base level |
| `extra_level` | `int` | Levels gained after taming |
| `experience` | `float` | Current XP |
| `is_female` | `bool` | Gender |
| `is_baby` | `bool` | Whether a baby |
| `is_neutered` | `bool` | Whether neutered/spayed |
| `is_clone` | `bool` | Whether cloned |
| `is_cryo` | `bool` | Whether in a cryopod |
| `is_wandering` | `bool` | Wandering enabled |
| `is_mating` | `bool` | Mating enabled |
| `imprint_quality` | `float` | Imprint percentage (0.0–1.0) |
| `imprinter_name` | `str` | Player who imprinted |
| `colors` | `list[int]` | 6 color region indices |
| `base_stats` | `CreatureStats` | Wild stat points |
| `tamed_stats` | `CreatureStats` | Post-tame stat points |
| `mutated_stats` | `CreatureStats` | Mutation stat points |
| `total_mutations` | `int` | Total mutations (female + male) |
| `mutations_female` | `int` | Female line mutations |
| `mutations_male` | `int` | Male line mutations |
| `father_id` | `int \| None` | Father's dino ID |
| `mother_id` | `int \| None` | Mother's dino ID |
| `father_name` | `str` | Father's name |
| `mother_name` | `str` | Mother's name |
| `targeting_team` | `int` | Tribe ID |
| `location` | `Location \| None` | World position |

| Method | Returns | Description |
|---|---|---|
| `from_game_object(game_object, status_object=None)` | `TamedCreature` | Create from game object + status component |
| `to_dict()` | `dict` | ASV_Tamed export format |

#### WildCreature

`arkparser.models.creature.WildCreature` — Wild creature with level and stats.

| Property | Type | Description |
|---|---|---|
| `class_name` | `str` | Blueprint class name |
| `level` | `int` | Creature level |
| `base_level` | `int` | Same as level for wild |
| `base_stats` | `CreatureStats` | Wild stat points |
| `is_female` | `bool` | Gender |
| `colors` | `list[int]` | 6 color region indices |
| `tameable` | `bool` | Whether tameable |
| `location` | `Location \| None` | World position |

| Method | Returns | Description |
|---|---|---|
| `from_game_object(game_object, status_object=None)` | `WildCreature` | Create from game object + status component |
| `to_dict()` | `dict` | ASV_Wild export format |

#### Player

`arkparser.models.player.Player` — In-world player entity built from profile data.

| Property | Type | Description |
|---|---|---|
| `player_id` | `int` | Player data ID |
| `name` | `str` | Character name |
| `steam_name` | `str` | Platform gamertag |
| `steam_id` | `str` | Platform unique ID |
| `tribe_id` | `int` | Tribe ID |
| `tribe_name` | `str` | Tribe name |
| `level` | `int` | Total level |
| `experience` | `float` | Current XP |
| `is_female` | `bool` | Gender |
| `stats` | `CreatureStats` | Player stat points |
| `engram_points` | `int` | Engram points available |
| `location` | `Location \| None` | World position |
| `data_file` | `str` | Profile filename |

| Method | Returns | Description |
|---|---|---|
| `from_game_object(game_object, status_object=None)` | `Player` | Create from game object + status component |
| `to_dict()` | `dict` | ASV_Players export format |

#### Character

`arkparser.models.character.Character` — Player character from the world save (`PlayerPawnTest_*` objects).

| Property | Type | Description |
|---|---|---|
| `player_id` | `int` | Player ID |
| `player_name` | `str` | Character name |
| `steam_name` | `str` | Platform gamertag |
| `tribe_id` | `int` | Tribe ID |
| `tribe_name` | `str` | Tribe name |
| `level` | `int` | Total level |
| `is_female` | `bool` | Gender |
| `is_sleeping` | `bool` | Whether offline/sleeping |
| `stats` | `CreatureStats` | Character stat points |
| `location` | `Location \| None` | World position |

| Method | Returns | Description |
|---|---|---|
| `from_game_object(game_object, status_object=None)` | `Character` | Create from game object + status component |
| `to_dict()` | `dict` | Dictionary export |

#### Structure

`arkparser.models.structure.Structure` — Placed structure with ownership and state.

| Property | Type | Description |
|---|---|---|
| `class_name` | `str` | Blueprint class name |
| `owner_tribe_id` | `int` | Owning tribe ID |
| `owner_tribe_name` | `str` | Owning tribe name |
| `owner_name` | `str` | Placing player name |
| `health` | `float` | Current health |
| `max_health` | `float` | Maximum health |
| `is_powered` | `bool` | Whether powered |
| `is_locked` | `bool` | Whether locked |
| `decay_time` | `float` | Seconds until decay |
| `custom_name` | `str` | Renamed structure name |
| `location` | `Location \| None` | World position |

| Method | Returns | Description |
|---|---|---|
| `from_game_object(game_object)` | `Structure` | Create from game object |
| `to_dict()` | `dict` | ASV_Structures export format |

#### Item

`arkparser.models.item.Item` — Inventory item with quality and stats.

| Property | Type | Description |
|---|---|---|
| `class_name` | `str` | Blueprint class name |
| `name` | `str` | Custom name (if renamed) |
| `quantity` | `int` | Stack quantity |
| `quality_index` | `int` | Quality tier (0=Primitive … 5=Ascendant) |
| `quality_name` | `str` | Quality tier name |
| `durability` | `float` | Current durability |
| `is_blueprint` | `bool` | Whether a blueprint |
| `is_engram` | `bool` | Whether an engram |
| `is_equipped` | `bool` | Whether equipped |
| `stat_values` | `list[int]` | 8 item stat modifiers |
| `crafting_skill_bonus` | `float` | Crafting skill bonus |

| Method | Returns | Description |
|---|---|---|
| `from_game_object(game_object)` | `Item` | Create from game object |
| `to_dict()` | `dict` | Dictionary export |

#### TribeModel

`arkparser.models.tribe.Tribe` — Tribe data model (distinct from the file parser `arkparser.files.Tribe`). Imported as `TribeModel` from the top-level package.

| Property | Type | Description |
|---|---|---|
| `tribe_id` | `int` | Unique tribe ID |
| `name` | `str` | Tribe name |
| `owner_id` | `int` | Owner player ID |
| `owner_name` | `str` | Owner name |
| `member_count` | `int` | Number of members |
| `members` | `list[TribeMember]` | Member list |
| `alliance_ids` | `list[int]` | Allied tribe IDs |
| `log` | `list[TribeLogEntry]` | Parsed log entries |
| `raw_logs` | `list[str]` | Raw log strings |

| Method | Returns | Description |
|---|---|---|
| `from_game_object(game_object)` | `Tribe` | Create from game object |
| `to_dict()` | `dict` | ASV_Tribes export format |

#### TribeMember

`arkparser.models.tribe.TribeMember` — Individual tribe member.

| Field | Type | Description |
|---|---|---|
| `player_id` | `int` | Player ID |
| `name` | `str` | Player name |
| `rank` | `int` | Rank index |

#### TribeLogEntry

`arkparser.models.tribe.TribeLogEntry` — Parsed tribe log entry.

| Field / Property | Type | Description |
|---|---|---|
| `day` | `int` | In-game day number |
| `time` | `str` | Time string (`HH:MM:SS`) |
| `message` | `str` | Raw log message |
| `clean_message` | `str` | Message with RichColor tags stripped |

| Method | Returns | Description |
|---|---|---|
| `from_string(raw: str)` | `TribeLogEntry` | Parse from `"Day X, HH:MM:SS: message"` |

#### CreatureStats

`arkparser.models.stats.CreatureStats` — 12-stat named access for level-up points.

| Field | Type | Description |
|---|---|---|
| `health` | `int` | Health points |
| `stamina` | `int` | Stamina points |
| `torpidity` | `int` | Torpidity points |
| `oxygen` | `int` | Oxygen points |
| `food` | `int` | Food points |
| `water` | `int` | Water points |
| `temperature` | `int` | Temperature points |
| `weight` | `int` | Weight points |
| `melee` | `int` | Melee damage points |
| `speed` | `int` | Movement speed points |
| `fortitude` | `int` | Fortitude points |
| `crafting` | `int` | Crafting skill points |

| Property / Method | Returns | Description |
|---|---|---|
| `total` | `int` | Total points (excluding torpidity) |
| `from_array(points: list[int])` | `CreatureStats` | Create from 12-element array |
| `to_array()` | `list[int]` | Convert to 12-element array |
| `to_dict()` | `dict[str, int]` | All 12 stat fields |

#### Location

`arkparser.models.stats.Location` — 3D position with optional GPS conversion.

| Field | Type | Description |
|---|---|---|
| `x` | `float` | X position |
| `y` | `float` | Y position |
| `z` | `float` | Z position |
| `pitch` | `float` | Pitch rotation |
| `yaw` | `float` | Yaw rotation |
| `roll` | `float` | Roll rotation |

| Property / Method | Returns | Description |
|---|---|---|
| `latitude` | `float \| None` | GPS latitude (requires `with_map()`) |
| `longitude` | `float \| None` | GPS longitude (requires `with_map()`) |
| `ccc` | `str` | CCC teleport string `"x y z"` |
| `with_map(map_config)` | `Location` | Return copy with GPS conversion enabled |
| `to_dict()` | `dict` | Position + rotation + lat/lon if map attached |

---

### Data Models

Lower-level data models for cloud inventory / obelisk data.

#### UploadedCreature

`arkparser.data_models.UploadedCreature` — Uploaded creature from obelisk data.

| Property | Type | Description |
|---|---|---|
| `class_name` | `str` | Blueprint class name |
| `name` | `str` | Creature name |
| `species` | `str` | Extracted species name |
| `level` | `int` | Creature level |
| `experience` | `float` | Current XP |
| `stats` | `DinoStats` | Full stat values |
| `upload_time` | `int` | Upload timestamp |
| `unique_id` | `str` | Combined `"dinoId1_dinoId2"` |

| Method | Returns | Description |
|---|---|---|
| `from_ark_data(data: dict)` | `UploadedCreature` | Create from ArkTamedDinosData struct |
| `to_dict()` | `dict` | Full dictionary export |

#### UploadedItem

`arkparser.data_models.UploadedItem` — Uploaded item from obelisk data.

| Property | Type | Description |
|---|---|---|
| `blueprint` | `str` | Item blueprint path |
| `display_name` | `str` | Custom or extracted name |
| `quantity` | `int` | Stack size |
| `quality_index` | `int` | Quality tier (0–5) |
| `quality_name` | `str` | Quality name (Primitive … Ascendant) |
| `durability` | `float` | Current durability |
| `is_blueprint` | `bool` | Whether a blueprint |
| `is_cryopod` | `bool` | Whether a cryopod-type item |
| `cryopod_creature` | `CryopodCreature \| None` | Creature inside cryopod |

| Method | Returns | Description |
|---|---|---|
| `from_ark_data(data: dict)` | `UploadedItem` | Create from ArkItems struct |
| `to_dict()` | `dict` | Dictionary export (excludes raw_data) |

#### CryopodCreature

`arkparser.data_models.CryopodCreature` — Creature stored inside a cryopod.

| Property | Type | Description |
|---|---|---|
| `class_name` | `str` | Blueprint class name |
| `name` | `str` | Creature name |
| `species` | `str` | Species name |
| `level` | `int` | Level |
| `colors` | `list[int]` | Color region indices |
| `current_stats` | `dict[str, float]` | Current stat values |
| `base_stats` | `dict[str, float]` | Base stat values |
| `level_ups_wild` | `dict[str, int]` | Wild level-up points |
| `level_ups_tamed` | `dict[str, int]` | Tamed level-up points |
| `stats` | `DinoStats` | Stats in DinoStats format |

| Method | Returns | Description |
|---|---|---|
| `from_cryopod_bytes(byte_data: list[int])` | `CryopodCreature \| None` | Parse from raw cryopod bytes |
| `from_asa_cryopod_data(custom_data: dict)` | `CryopodCreature \| None` | Parse from ASA struct |
| `to_dict()` | `dict` | Dictionary export |

#### DinoStats

`arkparser.data_models.DinoStats` — Creature stat values (current and max).

| Field | Type | Description |
|---|---|---|
| `health` / `max_health` | `float` | Health |
| `stamina` / `max_stamina` | `float` | Stamina |
| `torpidity` / `max_torpidity` | `float` | Torpidity |
| `oxygen` / `max_oxygen` | `float` | Oxygen |
| `food` / `max_food` | `float` | Food |
| `water` / `max_water` | `float` | Water |
| `weight` / `max_weight` | `float` | Weight |
| `melee_damage` | `float` | Melee damage |
| `movement_speed` | `float` | Movement speed |
| `crafting_skill` | `float` | Crafting skill |

| Method | Returns | Description |
|---|---|---|
| `from_stat_strings(stat_strings: list[str])` | `DinoStats` | Parse from `"Health: 365.0 / 404.0"` format |
| `to_dict()` | `dict[str, float]` | All stat fields |

---

### Export Functions

`arkparser.export` — ASV-compatible JSON export. All functions accept a `WorldSave` and optional `MapConfig` for GPS conversion.

| Function | Returns | Description |
|---|---|---|
| `export_tamed(save, map_config=None)` | `list[dict]` | Tamed creatures (ASV_Tamed format) |
| `export_wild(save, map_config=None)` | `list[dict]` | Wild creatures (ASV_Wild format) |
| `export_players(save, map_config=None)` | `list[dict]` | Players (ASV_Players format) |
| `export_tribes(save)` | `list[dict]` | Tribes (ASV_Tribes format) |
| `export_structures(save, map_config=None)` | `list[dict]` | Structures (ASV_Structures format) |
| `export_tribe_logs(save)` | `list[dict]` | Tribe logs (ASV_TribeLogs format) |
| `export_all(save, map_config=None)` | `dict[str, list[dict]]` | All 7 formats keyed by name |
| `export_to_files(save, output_dir, map_config=None)` | `list[Path]` | Write all 7 formats to JSON files |

---

### Map Config

`arkparser.common.map_config` — GPS coordinate conversion for ARK maps.

| Function | Returns | Description |
|---|---|---|
| `get_map_config(filename: str)` | `MapConfig` | Lookup by save filename (case-insensitive) |
| `get_map_config_by_name(name: str)` | `MapConfig` | Lookup by display name |
| `list_maps()` | `list[MapConfig]` | All registered map configs |

`MapConfig` methods: `ue_to_lat(y)`, `ue_to_lon(x)`, `ue_to_gps(x, y)`, `ccc_string(x, y, z)`.

---

### Version Detection

`arkparser.common.version_detection` — File format identification.

| Function | Returns | Description |
|---|---|---|
| `detect_format(source: bytes \| str \| Path)` | `ArkFileFormat` | `ASE`, `ASA`, or `UNKNOWN` |
| `detect_file_type(source: bytes \| str \| Path)` | `ArkFileType` | `PROFILE`, `TRIBE`, `CLOUD_INVENTORY`, `WORLD_SAVE`, or `UNKNOWN` |
| `get_save_version(source: bytes \| str \| Path)` | `int` | Version number (-1 if invalid) |

---

### Exceptions

`arkparser.common.exceptions` — All exceptions inherit from `ArkParseError`.

| Exception | Description |
|---|---|
| `ArkParseError` | Base exception for all parsing errors |
| `CorruptDataError` | File data appears corrupted or invalid |
| `UnknownPropertyError` | Unrecognized property type encountered |
| `UnknownStructError` | Unrecognized struct type encountered |
| `UnexpectedDataError` | Data doesn't match expected values |
| `EndOfDataError` | Attempted to read past end of data |

---

## Format Support

| Feature | ASE (v5-6) | ASA (v7+) |
|---------|-----------|-----------|
| Vectors | Float (4 bytes) | Double (8 bytes) |
| Object IDs | Int32 index | 16-byte GUID |
| Booleans | Int32 | Int16 |
| World Save | Binary file | SQLite database |
| Compression | None | zlib + custom RLE |

## Credits

This library was built by reverse-engineering ARK save formats with heavy reference to [ASV (Ark Save Visualizer)](https://github.com/miragedmuk/ASV) by **miragedmuk**. The C# implementation in ASV served as the primary reference for porting the binary parsing logic to Python.
