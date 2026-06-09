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

## Features

- **Player Profiles** (`.arkprofile`): platform gamertag, character name, level, stats, engrams
- **Tribe Data** (`.arktribe`): members, ranks, logs, alliances
- **Cloud Inventory / Obelisk**: uploaded creatures, items, cryopod contents
- **World Saves** (`.ark`): full map state (creatures, structures, items, players)
- **Dual format**: automatic ASE (v5-12) / ASA (v13-14+, SQLite) detection
- **Legacy-parity export**: drop-in JSON output matching `ASVExport.exe` schema, plus parser-only extras under descriptive snake_case keys (no namespace prefix; never overloading a legacy key)
- **Fast**: pure-Python `BinaryReader` (`int.from_bytes` + `struct.Struct` unpackers, slots-based dataclasses), a 30 MB ASE save (65k objects) loads in ~3s on CPython 3.14
- **Memory-bounded**: streaming JSON export plus an opt-in lazy parse mode (`lazy_properties=True`, ASE and ASA) that materializes property blocks on demand and evicts them as records stream to disk; a 1.8 GB / 1.79M-object busy-PvE ASE save exports in 2.5 GB peak RSS instead of 7.1 GB, and a 217k-object ASA save in 307 MB instead of 853 MB (and slightly faster)

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

print(profile.player_name)         # Platform gamertag / display name
print(profile.character_name)      # In-game character name
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
    print(f"  {member['name']} (ID: {member['player_id']})")
print(tribe.log_entries)    # ["Day 45: Tamed a Rex", ...]
```

### Cloud Inventory / Obelisk

```python
from arkparser import CloudInventory

inv = CloudInventory.load("path/to/obelisk_file")  # or use Obelisk alias

for creature in inv.uploaded_creatures:
    print(f"  {creature.species} Lv{creature.level} - {creature.name}")

for item in inv.uploaded_items:
    print(f"  {item.display_name} x{item.quantity} ({item.quality_name})")
    if item.is_cryopod and item.cryopod_creature:
        cryo = item.cryopod_creature
        print(f"    Contains: {cryo.species} Lv{cryo.level}")
```

### World Save

```python
from arkparser import WorldSave

save = WorldSave.load("path/to/Extinction.ark")       # ASE
save = WorldSave.load("path/to/Extinction_WP.ark")    # ASA

print(f"Objects: {save.object_count}")
print(f"Creatures: {len(save.get_creatures())}")
print(f"Structures: {len(save.get_structures())}")
print(f"Parse errors: {save.parse_error_count}")
print(f"Is ASA: {save.is_asa}")
```

### Low-memory parsing (large saves)

By default every object's property block is parsed up front, which on a busy
multi-GB PvE save means a multi-GB resident object graph. `lazy_properties=True`
parses object headers eagerly but defers each property block until something
reads it, then the export drivers evict it again once the record has been
written:

```python
from arkparser import WorldSave, export_to_files
from arkparser.common import get_map_config

save = WorldSave.load("path/to/Fjordur.ark", lazy_properties=True)       # ASE
save = WorldSave.load("path/to/TheIsland_WP.ark", lazy_properties=True)  # ASA
export_to_files(save, "output/", get_map_config("fjordur.ark"))
```

Output is identical to eager mode (validated record-for-record). ASE retains
the file reader and re-seeks each object's block on demand; ASA retains the
SQLite connection (one held read transaction) and re-fetches row blobs by
GUID. On ASA v14+ saves the export pipeline additionally uses partial decodes:
a verified byte-exact skip walk that parses only the property names a record
needs, with any out-of-whitelist read transparently upgrading to the full
block.

Measured load + export, same machine: a 1.8 GB Fjordur PvE ASE save (1.79M
objects) drops from ~7.1 GB peak RSS / 348 s eager to ~2.5 GB / 287 s lazy; a
233 MB ASA TheIsland save (217k objects) drops from 853 MB / 38 s eager to
307 MB / ~36 s lazy. Property access on a lazy save is transparent: any
`get_property_value` call materializes the block on demand, so all getters and
exports work unchanged.

### Cryopod-stored Creatures

Tamed creatures stored inside in-world cryopods aren't returned by `get_tamed_creatures()`. Iterate them via `WorldSave.iter_cryopod_creatures()`:

```python
for item_obj, cryo in save.iter_cryopod_creatures():
    print(f"{cryo.species} Lv{cryo.level} (in {item_obj.class_name})")
```

### Direct GameObject Access

`arkparser` exposes the raw `GameObject` graph for callers that need flexibility beyond the default exports:

```python
for obj in save.get_tamed_creatures():
    name = obj.get_property_value("TamedName") or "<unnamed>"
    tribe = obj.get_property_value("TargetingTeam") or 0
    print(f"{obj.class_name} - {name} (tribe {tribe})")
```

### JSON Export (Legacy ASV Schema)

```python
from arkparser import export_all, export_to_files
from arkparser.common import get_map_config

map_config = get_map_config("extinction.ark")

data = export_all(save, map_config)
# {"ASV_Tamed": [...], "ASV_Wild": [...], "ASV_Players": [...],
#  "ASV_Tribes": [...], "ASV_Structures": [...], "ASV_TribeLogs": [...],
#  "ASV_MapStructures": [...]}

export_to_files(save, "output/", map_config)
# Writes ASV_Tamed.json, ASV_Wild.json, ..., ASV_MapStructures.json
# Each file is wrapped with the legacy `{map, day, time, data}` envelope.
```

Each export wraps a flat list of record dicts in the legacy `{map, day, time, data}` envelope (with `wrap=True`). Tables below document every field in each record. Fields present in the original `ASVExport.exe` output are marked **legacy**; fields added by this parser are marked **added** and use plain descriptive names (no namespace prefix).

#### Stat-token convention

The parser reuses the legacy short stat tokens consistently across every export and every stat block:

`hp` `stam` `torp` `oxy` `food` `water` `temp` `weight` `melee` `speed` `fort` `craft`

These map 1:1 to in-game stat indices 0..11. Stat blocks use suffixes to disambiguate:

- **no suffix**, base wild stats (wild creatures, players)
- **`-w`**, base wild stats (tamed creatures, points the creature had before being tamed)
- **`-t`**, post-tame level-up points (tamed creatures only)
- **`-m`**, mutation points applied (tamed creatures only)

The legacy ASVExport.exe emitted only the visible 8 stats (`hp`, `stam`, `melee`, `weight`, `speed`, `food`, `oxy`, `craft`) under each suffix. The parser appends the four legacy never surfaced (`torp`, `water`, `temp`, `fort`) at the end of each block, so e.g. a tamed creature now carries `torp-w`, `water-w`, `temp-w`, `fort-w` alongside the legacy `hp-w`..`craft-w`.

#### `ASV_Tamed` schema

| Field | Origin | Source / formula |
|---|---|---|
| `id` | legacy | `(DinoID1 << 32) \| DinoID2` |
| `tribeid` | legacy | `TargetingTeam` |
| `tribe` | legacy | `TribeName` (or `null` when blank) |
| `tamer` | legacy | `TamerString` |
| `imprinter` | legacy | `ImprinterName` |
| `imprint` | legacy | `DinoImprintingQuality` (status) |
| `creature` | legacy | `GameObject.class_name` |
| `name` | legacy | `TamedName` |
| `sex` | legacy | `"Female"` if `bIsFemale` else `"Male"` |
| `base` | legacy | `BaseCharacterLevel` (status) |
| `lvl` | legacy | `BaseCharacterLevel + ExtraCharacterLevel` |
| `lat`, `lon` | legacy | `MapConfig.ue_to_lat(y)` / `ue_to_lon(x)` |
| `hp-w` .. `craft-w` | legacy | `NumberOfLevelUpPointsApplied[i]` (wild stat points) |
| `torp-w`, `water-w`, `temp-w`, `fort-w` | added | same source, indices legacy never emitted |
| `hp-t` .. `craft-t` | legacy | `NumberOfLevelUpPointsAppliedTamed[i]` |
| `torp-t`, `water-t`, `temp-t`, `fort-t` | added | same source, indices legacy never emitted |
| `hp-m` .. `fort-m` (all 12) | added | `NumberOfMutationsAppliedTamed[i]` (mutation point counts per stat) |
| `c0` .. `c5` | legacy | `ColorSetIndices[i]` |
| `mut-f`, `mut-m` | legacy | **Ancestor-line totals.** `RandomMutationsFemale` and `RandomMutationsMale`, single integers counting the total number of mutations that occurred down the maternal and paternal ancestry lines respectively. These are *not* per-stat, they share the `-m` token with the per-stat mutation block below but mean a different thing. Kept under the legacy names for ASVExport parity. |
| `cryo` | legacy | `True` for creatures embedded inside cryopod / soultrap / vivarium / dinoball items in the world save, `False` for actor-in-world tames. `export_tamed` walks `WorldSave.iter_cryopod_creatures()` and emits one ASV_Tamed record per embedded creature in addition to the actor-in-world tames; on busy PvE servers cryopodded tames are the majority of the roster (e.g. 10,277 of 11,054 on a live Ragnarok_WP). Cluster-uploaded tames also surface here (via `export_cluster_uploads`) with `cryo=True`. |
| `ccc` | legacy | `"{x} {y} {z}"` from `LocationData` |
| `dinoid` | legacy | string form of the dino id. **ASA**: decimal of the combined 64-bit `id`. **ASE**: the two halves concatenated as signed-int32 decimals (`str(DinoID1) + str(DinoID2)`), matching `ASVExport`. |
| `isMating` | legacy | `bEnableTamedMating` |
| `isNeutered` | legacy | `bNeutered` |
| `isClone` | legacy | `bIsClone` or `bIsCloneDino` |
| `tamedServer` | legacy | `TamedOnServerName` |
| `uploadedServer` | legacy | `UploadedFromServerName` |
| `maturation` | legacy | `str(int(BabyAge * 100))`, integer maturation percent (a baby with no `BabyAge` is `0`, a newborn). Note: legacy emits the full float string (e.g. `"7.5131035"`); arkparser truncates to the integer percent. Semantically equal and the downstream consumer coerces to `int` either way. |
| `traits` | legacy | `CreatureTraits` as a list of `{"trait": <class>}` objects (matches `ASVExport`'s shape, not a flat string list) |
| `inventory` | legacy | items from `MyInventoryComponent.InventoryItems`. Each entry carries `itemId`, `qty`, `blueprint`, plus a full snake_case property dump flattened in at the top level (`id`, `rating`, `durability`, `quality`, `damage`, `armor`, `durability_max`, `hypo`, `hyper`, `clip_size`, `weight`, `crafter`, `crafter_tribe`, `skill_bonus`, `loaded_ammo`, `spoils_at`, `spoiled_at`, `c0`..`c5`, `egg_*`, etc). `item_stat_values` is unpacked into the universal 8-slot ARK map (slot 0 `gen_quality`, 1 `armor`, 2 `durability_max`, 3 `damage`, 4 `clip_size`, 5 `hypo`, 6 `weight`, 7 `hyperthermal_insulation`); raw uint16s scaled by the per-blueprint multiplier (which lives in the UE blueprint, not the save). Default / unset values are filtered (no `craft_queue=0`, `skin=-1`, `color_pre_skin=[0]*6`, NaN spoil timers, etc). When the item is a **cryopod / soultrap / vivarium / dinoball** with an embedded creature, the entry is enriched with `dino_id` (combined 64-bit id matching the corresponding `ASV_Tamed` record), `dino_creature` (species / class name), and `dino_name` (`TamedName` if set). Cryopods stored in containers (cryofridges, vaults, dedicated storage) get the same enrichment. |
| `father_id`, `mother_id` | added | combined dino id from the first `DinoAncestors` entry (`null` when missing) |
| `father_name`, `mother_name` | added | name strings from the first `DinoAncestors` entry |
| `level_added` | added | `ExtraCharacterLevel` (post-tame levels, broken out from `lvl`) |
| `experience` | added | `ExperiencePoints` (status), integer |
| `wandering` | added | `bEnableTamedWandering` |
| `tamed_at` | added | ISO 8601 datetime with local TZ, converted from `TamedAtTime` (in-game seconds) via `file_mtime + (tamed_at - game_time)`. `null` when the save lacks the anchors. |
| `last_ally_in_range` | added | ISO 8601 datetime with local TZ, converted from `LastInAllyRangeTime` / `LastInAllyRangeSerialized` via the same anchor formula as `tamed_at`. `null` when the save lacks the anchors. |
| `imprinter_player_id` | added | `ImprinterPlayerDataID` |
| `imprinter_net_id` | added | `ImprinterPlayerUniqueNetId` (ASA only) |
| `taming_team_id` | added | `TamingTeamID` (fallback tribe id when `TargetingTeam` was stripped on cryo) |
| `owning_player_id`, `owning_player_name` | added | `OwningPlayerID` / `OwningPlayerName`, current owner (may differ from the original `tamer` after transfer / cryo). |
| `aggression_level` | added | `TamedAggressionLevel`, 0 Passive, 1 Neutral, 2 Aggressive, 3 Passive Flee, 4 Attack-My-Target (ARK in-game order). |
| `ai_targeting_range` | added | `TamedAITargetingRange`, aggro range (UE units). |
| `follow_stopping_distance` | added | `FollowStoppingDistance`, follow-AI stopping radius. |
| `is_flying` | added | `bIsFlying`. |
| `is_turret_mode` | added | `bIsInTurretMode`, e.g. plant Y, Tek tape sentry mode. |
| `ignore_whistles`, `only_target_conscious`, `attack_team_member_dinos` | added | `bIgnoreAllWhistles` / `bOnlyTargetConscious` / `bAttackTeamMemberDinos`, behavior toggles. |
| `next_cuddle_food`, `next_cuddle_type` | added | `BabyCuddleFood` / `BabyCuddleType`, next imprint requirement. |
| `latest_uploaded_server`, `previous_uploaded_server` | added | `LatestUploadedFromServerName` / `PreviousUploadedFromServerName`, recent upload history alongside the legacy `uploadedServer`. |
| `saddle_structures` | added | List of structure object-ref strings placed on this creature's platform saddle (paracer / brontosaurus / titanosaur etc.). |
| `harvest_resource_levels` | added | `HarvestResourceLevels`, per-resource harvest levels (mortar / feeding trough variants). |
| `wild_spawn_region` | added | `OriginalNPCVolumeName`, name of the `NPCZoneVolume` where this creature first spawned. Lets consumers answer "where on the map did this tame originate". |
| `downloaded_at` | added | ISO 8601 datetime of the last cluster/obelisk download (`DinoDownloadedAtTime`). `null` when the creature was never cluster-downloaded. |
| `original_created` | added | ISO 8601 datetime of the dino's first spawn (`OriginalCreationTime`), e.g. when the egg was laid or the wild dino spawned. Distinct from `tamed_at`. |
| `next_mating_at` | added | ISO 8601 datetime when the next mating is allowed (`NextAllowedMatingTime`). `null` when no cooldown is set. |
| `last_stasis` | added | ISO 8601 datetime of `LastEnterStasisTime` (last time the creature entered stasis). |
| `last_baby_age_update` | added | ISO 8601 datetime of `LastUpdatedBabyAgeAtTime`. |
| `last_gestation_update` | added | ISO 8601 datetime of `LastUpdatedGestationAtTime`. |
| `next_cuddle` | added | ISO 8601 datetime of `BabyNextCuddleTime`. |
| `current_stats` | added | Live in-world stat values from the dino's status component (`CurrentStatusValues[0..11]`) as a `{hp, stam, torp, oxy, food, water, temp, weight, melee, speed, fort, craft}` dict of floats. These are the *current* values (e.g. `hp: 11013.62` = current HP, drops as the dino takes damage). Max values are NOT persisted by ARK, compute downstream from species stat tables + `*-w`/`*-t` points + `imprint` + server multipliers if you need them. `null` when the status component carries no `CurrentStatusValues` entries (e.g. uninitialised baby actor). |

#### `ASV_Wild` schema

| Field | Origin | Source / formula |
|---|---|---|
| `id`, `dinoid` | legacy | `id` = `(DinoID1 << 32) \| DinoID2`. `dinoid` = its string form on **ASA**, or `str(DinoID1) + str(DinoID2)` (signed int32) on **ASE**, matching `ASVExport`. |
| `creature` | legacy | `GameObject.class_name` |
| `sex` | legacy | `"Female"` if `bIsFemale` else `"Male"` |
| `lvl` | legacy | `BaseCharacterLevel` (status) |
| `lat`, `lon`, `ccc` | legacy | location, via `MapConfig` |
| `hp` .. `craft` | legacy | `NumberOfLevelUpPointsApplied[i]` (8 visible stats) |
| `torp`, `water`, `temp`, `fort` | added | same source, indices legacy never emitted |
| `c0` .. `c5` | legacy | `ColorSetIndices[i]` |
| `tameable` | legacy | mirror of legacy `ContentWildCreature.IsTameable` rule |
| `trait` | legacy | first entry of `CreatureTraits` (or empty string) |
| `traits` | added | full `CreatureTraits` list |
| `wild_spawn_region` | added | `OriginalNPCVolumeName`, `NPCZoneVolume` the creature spawned in. |
| `current_stats` | added | Live in-world stat values from the creature's status component (`CurrentStatusValues[0..11]`) as a `{hp, stam, torp, oxy, food, water, temp, weight, melee, speed, fort, craft}` dict of floats. Max values are NOT in the save (would need species stat tables). `null` when uninitialised. |

#### Player data: `.arkprofile` vs in-world pawn

ARK keeps player data in **two distinct places**, and the parser builds `ASV_Players` records from whichever source you hand it:

| Source | Persistence | Coverage | Has location? | Has inventory? |
|---|---|---|---|---|
| **`.arkprofile`** parsed via `Profile.load(...)` | Survives logout, server restart, and character death | Every player who ever logged in | No (profile carries no in-world position) | No (profile only stores engrams / hairstyles / unlocked customizations, not the live inventory) |
| **In-world `PlayerPawn`** GameObject inside `WorldSave` | Only present while the character is spawned on the map (i.e. not logged out / dead with corpse cleared) | Currently-online or recently-disconnected players | Yes (`obj.location` → `lat`/`lon`/`ccc`) | Yes (live `MyInventoryComponent` contents) |

The export pipeline (`export_players`) loops over `save.profiles` (a list the caller assembles). For each entry:

- If it's a `Profile` instance → `_player_from_profile` runs: fills core identity (name, gender, level, stats, tribe id, engram count, experience, active datetime from `LastLoginTime`). It joins `PlayerDataID == LinkedPlayerDataID` against the world save's player pawns, so when a live pawn exists `lat`/`lon`/`ccc` come from that pawn's `.location`; players with no live pawn (dead / logged out) keep `lat`/`lon`/`ccc` at zero. `inventory` is empty and pawn-state flags (`is_sleeping`, `is_dead`, `chibi_levels`, …) absent (the profile carries neither).
- Otherwise it's treated as a wrapped `(profile, objects)` pair pointing at an in-world `PlayerPawn` → `_player_from_object` runs: fills location, inventory, pawn-state flags, body/hair cosmetics, death timestamps, and `active` from `SavedLastTimeHadController`.

For the richest output, hand `export_players` **both**, assemble a wrapper for each player that carries the `Profile` (for offline identity) *and* the in-world pawn (when present) so the merged record gets identity + live state. The current validation script only passes `Profile` instances, which is why fields like `is_sleeping` / `body_colors` / `current_weapon` show up empty in the validation output even though the parser supports them.

#### `ASV_Players` schema

| Field | Origin | Source / formula |
|---|---|---|
| `playerid` | legacy | `PlayerDataID` |
| `steam` | legacy | platform gamertag (`PlatformProfileName` / profile `PlayerName`) |
| `name` | legacy | in-game character name |
| `tribeid` | legacy | `TribeId` / `TribeID` |
| `tribe` | legacy | tribe name |
| `sex` | legacy | `"Female"` / `"Male"` |
| `lvl` | legacy | `BaseCharacterLevel + ExtraCharacterLevel` |
| `hp` .. `craft`, `fort` | legacy | `NumberOfLevelUpPointsApplied[i]` (10 visible stats) |
| `torp`, `temp` | added | same source, indices legacy never emitted |
| `achievements` | legacy | reserved array (currently empty for parity) |
| `netAddress` | legacy (now populated) | Last client IP ARK persisted (`SavedNetworkAddress` in profile `MyData`). Legacy ASVExport reads the same field (ContentPlayer.cs:157 ASE / :341 ASA). `""` when the profile lacks it (e.g. never-played placeholders). ASA stores a clean IPv4/IPv6 string; some ASE saves store an engine-truncated value (e.g. `"[2001"`) reproduced verbatim, matching legacy. |
| `steamid`, `dataFile` | legacy | platform net id and `{steamid}.arkprofile` filename |
| `active` | legacy (now populated) | ISO 8601 datetime of last login, converted from profile `LastLoginTime` or in-world pawn `SavedLastTimeHadController`. Legacy schema reserved the field but the old C# exporter only filled it for in-world pawns; the parser fills it for profiles too. `null` when neither source is present. |
| `lat`, `lon`, `ccc` | legacy (now populated) | In-world position. Built directly from a `PlayerPawn` GameObject when one is passed, and for profile-sourced records the parser joins `PlayerDataID == LinkedPlayerDataID` to the world save's player pawns and pulls the matched pawn's `.location`. Records whose player has no live pawn (dead / logged out / cluster-only) keep the legacy `0` / `"0 0 0"` placeholders since there is no world position to report. |
| `inventory` | legacy (now populated) | Items from the pawn's `MyInventoryComponent` when built from an in-world pawn. Empty list otherwise. |
| `engram_points` | added | `TotalEngramPoints` |
| `experience` | added | `ExperiencePoints` (status), integer |
| `is_sleeping`, `is_dead` | added | `bIsSleeping` / `bIsDead`, pawn state flags. Always `false` for profile-sourced records (no pawn). |
| `is_prone`, `is_crouched`, `hat_hidden` | added | `bIsProne` / `bIsCrouched` / `bHatHidden`. |
| `current_weapon` | added | `CurrentWeapon` ref, equipped weapon identifier. |
| `seated_on_ref` | added | `SeatingStructure` ref, what the player is sitting on (chair / saddle). |
| `original_hair_color` | added | `OriginalHairColor`, color index at character creation. |
| `head_hair_growth`, `facial_hair_growth` | added | `PercentOfFullHeadHairGrowth` / `PercentOfFullFacialHairGrowth`. |
| `body_colors` | added | `BodyColors`, per-region skin color indices. |
| `died_at` | added | ISO 8601 datetime of `LocalDiedAtTime`. |
| `corpse_destruction` | added | ISO 8601 datetime of `CorpseDestructionTime`. |
| `chibi_levels` | added | `NumChibiLevelUps`, bonus levels from chibi pets. |
| `ascensions_scorched` | added | `NumAscensionsScorched`, ASE ascension counter (legacy `ContentPlayer` parses the ASA ascension block differently; this is the ASE-specific field). |
| `current_stats` | added | Live in-world stat values for the player from the pawn's `MyCharacterStatusComponent` (`CurrentStatusValues[0..11]`) as a `{hp, stam, torp, oxy, food, water, temp, weight, melee, speed, fort, craft}` dict of floats. For profile-sourced records the parser joins on `PlayerDataID == LinkedPlayerDataID` to find the spawned pawn in the world save. `null` when the player has no in-world pawn (never spawned this server / corpse cleared) or the status component has no values, only currently / recently spawned characters have live stats. Max values are NOT persisted by ARK. |

#### `ASV_Tribes` schema

`ASV_Tribes` (and `ASV_TribeLogs` / `ASV_Players`, which iterate the same list) is a **superset** of the loaded `.arktribe` files, mirroring legacy `ContentContainer`: it seeds two sentinels (`[ASV Unclaimed]` id `2000000000`, `[ASV Abandoned]` id `-2147483648`), adds every file-backed tribe, then synthesizes a stub tribe for each player profile not already in a tribe (`Tribe of <name>`, id = `PlayerDataID`), each distinct structure `TargetingTeam` (`>= 50000`), and each distinct in-world tame `TargetingTeam`, deduped by id. Cross-server tribes that exist **only** in cluster cloud-inventory files (no map presence) are not synthesized.

| Field | Origin | Source / formula |
|---|---|---|
| `tribeid` | legacy | `TribeID` / parser `Tribe.tribe_id`, or a synthesized stub/sentinel id (see above) |
| `tribe` | legacy | tribe name (file `TribeName`; for stubs, `OwnerName`/`TamerString`; or `Tribe of <character>` for a solo) |
| `players` | legacy | count of players **allocated** to this tribe (profiles whose explicit team / membership / solo id resolves here, plus member back-fill), matching legacy `Players.Count`, not the raw `.arktribe` member count |
| `members` | legacy | list of `{ign, lvl, playerid, playername, steamid}` built from the allocated players. `lvl` and `steamid` populate from the matching `.arkprofile`; members with no profile (back-filled from the tribe's member list) carry `lvl=0`, `steamid=""`. |
| `tames`, `structures` | legacy | counts derived from `WorldSave` (creatures + structures whose `TargetingTeam` matches) |
| `uploadedTames` | legacy | reserved (currently `0`) |
| `active` | legacy | ISO 8601 datetime, legacy `ContentTribe.LastActive`: max of the tribe file's write time (`.arktribe` mtime; world-save mtime for in-save tribes) and the allocated members' last-active times (`LastLoginTime` via the save anchor), discarding future values. `null` when no past candidate exists. Tribe-log "Day N" stamps are game-calendar time and are deliberately not used. |
| `dataFile` | legacy | `"{tribeid}.arktribe"` filename pattern. |
| `owner_id` | added | `OwnerPlayerDataID` / parser `Tribe.owner_player_id` |
| `owner_name` | added | `OwnerPlayerName` (object form only; parser-tribe form has no equivalent) |
| `alliance_ids` | added | `TribeAlliances[i]` |

#### `ASV_TribeLogs` schema

| Field | Origin | Source / formula |
|---|---|---|
| `tribeid` | legacy | `TribeID` / `Tribe.tribe_id` |
| `tribe` | legacy | tribe name |
| `logs` | legacy | raw `TribeLog` strings (newest-first, formatted by ARK with `Day N, HH:MM:SS: <message>`) |

#### `ASV_Structures` schema

| Field | Origin | Source / formula |
|---|---|---|
| `id` | added | `GameObject.id`, internal numeric identifier. Cross-references the values in other records' `linked_structures` / `saddle_structures` / `attached_dino_id` lists. |
| `tribeid` | legacy | `TargetingTeam` for player-owned structures (`>= 50000`). Unowned structures fall to the synthetic `[ASV Abandoned]` tribe id `-2147483648` (legacy `int.MinValue`), mirroring `ContentContainer.cs`. |
| `tribe` | legacy | resolved owning-tribe name: the loaded `.arktribe` `TribeName`, else the structure's `OwnerName` / `TamerString`; `"[ASV Abandoned]"` for unowned. (Legacy emits the resolved tribe name, not the raw `OwnerName`.) |
| `struct` | legacy | `GameObject.class_name`. Unowned map elements / crates / debug actors (`Button_*`, `*Vein_*`, `*Nest_*`, `*Beaver*`, `BeeHive_C`, `ArtifactCrate_*`, `TributeTerminal_*`, `SupplyCrate_*`) are excluded; surfaced via `ASV_MapStructures` instead, matching legacy's abandoned-structure filter. |
| `name` | legacy | `BoxName` (empty when it matches the class name, mirroring legacy's no-rename strip) |
| `locked` | legacy | `bIsPinLocked` or `bIsLocked` |
| `created` | legacy (richer) | ISO 8601 datetime with the local TZ of the parser machine, computed `save.file_mtime + (OriginalCreationTime - game_time)` (mirrors legacy `ContentContainer.GetApproxDateTimeOf`). `null` when the anchors are missing. |
| `inventory` | legacy | items from `MyInventoryComponent.InventoryItems` |
| `lat`, `lon`, `ccc` | legacy | location via `MapConfig`, **rounded to 2 decimals** (parser-only nicety, not legacy parity) |
| `isSwitchedOn` | legacy | `bContainerActivated`, emitted only when the structure is powered (`bIsPowered` or `bHasFuel`); omitted otherwise. Mirrors legacy `ContentStructure.cs` / `ContentPack.cs` (`IsSwitchedOn.HasValue`). |
| `decay_reset` | added | `bHasResetDecayTime` |
| `last_ally_in_range` | added | ISO 8601 datetime with local TZ. `null` when the save lacks the anchors. |
| `painting_id` | added | `UniquePaintingId` |
| `feeding_inclusions` | added | `FeedingDinoList` class names when `DinoFeedingListType == 1` (ASA feeding troughs) |
| `feeding_exclusions` | added | `FeedingDinoList` class names when `DinoFeedingListType == 2` |
| `health` | added | `Health` (often `0.0` because ARK strips live health on save) |
| `max_health` | added | `MaxHealth` |
| `owning_player_id`, `owning_player_name` | added | `OwningPlayerID` / `OwningPlayerName`, who placed the structure (distinct from `tribe`, which is the current owning tribe). |
| `colors` | added | `StructureColors`, list of 6 color region indices (0 = unpainted). |
| `current_item_count`, `max_item_count` | added | `CurrentItemCount` / `MaxItemCount`, container fullness (e.g. dedicated storage, generators). Both `0` for non-container structures. |
| `num_bullets` | added | `NumBullets`, loaded ammo count on auto-turrets. `0` for non-turrets. |
| `range_setting` | added | `RangeSetting`, turret targeting range tier (`0` Low, `1` Med, `2` High, `3` Highest). `0` for non-turrets too, disambiguate via `num_bullets` / `struct`. |
| `has_fuel` | added | `bHasFuel`, generator / lamp fuel state. |
| `is_foundation` | added | `bIsFoundation`. |
| `placement_snapped` | added | `bWasPlacementSnapped`, placement-snap flag. |
| `variant` | added | `CurrentVariant`, structure variant index (e.g. flexible pipe / gate style). |
| `selected_resource_class` | added | `SelectedResourceClass` ref, resource type chosen on dedicated storage / similar. |
| `resource_count` | added | `ResourceCount`. |
| `dedicated_storage_version` | added | `SavedDedicatedStorageVersion`. |
| `painting_ref` | added | `PaintingComponent` ref, canvas component identifier when painted. |
| `saddle_dino_ref`, `attached_dino_id` | added | `SaddleDino` ref + `AttachedToDinoID1/2` combined, links saddle-mounted structures back to their host dino. |
| `linked_structures` | added | `LinkedStructures`, refs of network-linked structures (pipes / wires / gates → motors). Useful for reconstructing infrastructure topology. |
| `last_activated` | added | ISO 8601 datetime of `LastActivatedTime`. |
| `last_deactivated` | added | ISO 8601 datetime of `LastDeactivatedTime`. |
| `last_fire` | added | ISO 8601 datetime of `LastFireTime`, last turret discharge. |
| `last_reload` | added | ISO 8601 datetime of `LastLongReloadStartTime`. |
| `last_fuel_check` | added | ISO 8601 datetime of `LastCheckedFuelTime`. |
| `pin_code` | added | `CurrentPinCode`, the active PIN code on the structure as a single integer. Falls back to the first non-zero entry of the legacy `CurrentPinCodes` array (always zero on every observed save). Pruned when `0`. **Sensitive credential**, exposed for tribe-admin auditing; downstream UIs should gate this behind admin-only views. |

#### `ASV_MapStructures` schema

| Field | Origin | Source / formula |
|---|---|---|
| `struct` | legacy | ASV label assigned by class-name match (e.g. `ASV_Terminal`, `ASV_BeaverDam`, `ASV_Artifact`) |
| `lat`, `lon`, `ccc` | legacy | location via `MapConfig` |
| `inventory` | legacy | inventory items (only meaningful for beaver dams / dropped supply crates) |

### Cluster-uploaded creatures and items

Pass the cluster directory to `export_all` / `export_to_files` to fold cluster data into the per-map output:

```python
export_to_files(save, "output/", map_config, cluster="path/to/cluster")
# or equivalently:
data = export_all(save, map_config, cluster="path/to/cluster")
# data["ASV_Tamed"]   - now includes cluster cryopod tames (cryo=True)
# data["ASV_Players"] - each player's inventory now contains their
#                       uploaded items (entries tagged "uploaded": true),
#                       matched by cloud-file stem == the player's
#                       .arkprofile filename stem.
```

Cluster items are spliced into the owning player's `inventory`; no separate `ASV_ClusterItems` file is emitted. The match works because every cluster file and the player's `.arkprofile` share a stem (the Steam id on ASE, the hex platform UUID on ASA) so the join is keyed on the profile's source filename stem. (`Profile.unique_id` equals that stem only on ASE; on ASA it is the numeric net id, not the UUID filename, so loading profiles from real file paths (which sets `Profile.source_path`) is required for the ASA splice.)

Pre-loaded `CloudInventory` instances also work (`cluster=[inv1, inv2, ...]`).

### Standalone cloud-inventory inspection

For staff tools that need to inspect a single user's obelisk / cluster file in isolation (no worldsave context, no per-player matching), use `export_cloud_inventory`:

```python
from arkparser import CloudInventory, export_cloud_inventory

cloud = CloudInventory.load("/cluster/2533274802706466")  # ASE xuid
# or
cloud = CloudInventory.load("/cluster/000297eb6c36484ab95c75d7bbbc8629")  # ASA UUID

data = export_cloud_inventory(cloud)
# {
#   "ASV_Tamed": [ ... every dino, cryopod-embedded or otherwise ... ],
#   "ASV_Items": [ ... every uploaded item, snake_case flat stats ... ],
# }
```

Each `ASV_Items` entry carries `itemId`, `qty`, `blueprint`, `id` (combined ItemID1_ItemID2), `uploadedTime` (ISO 8601 with UTC offset), and item-class-specific stats (`durability_max`, `damage`, `armor`, `hypo`, `hyper`, `crafter`, `crafter_tribe`, `skill_bonus`, `loaded_ammo`, `quality`, `rating`, `c0`..`c5` paint regions, `drop_location`, `egg_*` for fertilized eggs, `dino_*` for cryopod items, etc). Default / unset fields are filtered, NaN floats dropped, `"Unknown"` crafter strings nulled.

The low-level helpers are also available:
- `export_cluster_uploads(cluster_invs, map_config=None) -> list[dict]` &mdash; tamed-shape records (incl. cryopod-as-item dinos) across the supplied cloud files
- `export_cluster_items(cluster_invs) -> list[dict]` &mdash; every uploaded item across the supplied cloud files

## Package Structure

```
arkparser/
├── __init__.py        # Public API
├── data_models.py     # UploadedCreature, UploadedItem, CryopodCreature, DinoStats
├── export.py          # Legacy-parity JSON export functions
├── common/            # Binary reader, types, exceptions, map configs, version detection
├── files/             # File parsers (Profile, Tribe, CloudInventory, WorldSave)
├── game_objects/      # GameObject, GameObjectContainer, LocationData
├── properties/        # Property parsing system (ArrayProperty, StructProperty, etc.)
└── structs/           # Struct types (Vector, Color, Guid, etc.)
```

## API Reference

### File Parsers

All file parsers expose `load(source)` which accepts `str`, `Path`, or `bytes` and auto-detects ASE/ASA format.

#### Profile (`arkparser.Profile`)

Parser for `.arkprofile` player profile files.

| Property | Type | Description |
|---|---|---|
| `player_name` | `str \| None` | Platform gamertag / display name |
| `character_name` | `str \| None` | In-game character name (falls back to `player_name`) |
| `player_id` | `int \| None` | Unique player ID |
| `unique_id` | `str \| None` | Platform ID (Steam/Xbox numeric ID) |
| `tribe_id` | `int \| None` | Tribe ID (auto-tribe = `player_id` when no explicit tribe) |
| `is_female` | `bool \| None` | Gender flag |
| `level` | `int` | Current level |
| `experience` | `float` | Total XP |
| `total_engram_points` | `int` | Engram points spent |
| `engram_blueprints` | `list[str]` | Learned engram blueprint paths |
| `objects` | `list[GameObject]` | Raw parsed game objects |

`get_stat(index)` returns the level-up points allocated to the given stat (0=Health … 11=Crafting). `to_dict()` returns a flat profile dictionary.

#### Tribe (`arkparser.Tribe`)

Parser for `.arktribe` tribe data files.

| Property | Type | Description |
|---|---|---|
| `name` | `str \| None` | Tribe name |
| `tribe_id` | `int \| None` | Unique tribe ID |
| `owner_player_id` | `int \| None` | Tribe owner's player ID |
| `member_ids` / `member_names` / `member_ranks` | `list[...]` | Member arrays |
| `member_count` | `int` | Number of members |
| `log_entries` | `list[str]` | Raw tribe log strings |
| `alliance_ids` | `list[int]` | Allied tribe IDs |
| `government_type` | `int` | 0=Player, 1=Tribe, 2=Personal |

`get_members()` returns a list of `{player_id, name, rank}` dicts.

#### CloudInventory (`arkparser.CloudInventory`, alias `Obelisk`)

Parser for obelisk / cloud-inventory data files.

| Property | Type | Description |
|---|---|---|
| `uploaded_creatures` | `list[UploadedCreature]` | Uploaded creatures with stats |
| `uploaded_items` | `list[UploadedItem]` | Uploaded items (includes cryopods) |
| `creatures` / `items` / `characters` | `list[GameObject]` | Raw GameObjects |
| `creature_count` / `item_count` / `character_count` | `int` | Counts |

#### WorldSave (`arkparser.WorldSave`)

Unified parser for `.ark` world save files. Auto-detects ASE binary vs ASA SQLite.

| Property | Type | Description |
|---|---|---|
| `version` | `int` | Save format version |
| `game_time` | `float` | In-game time (seconds) |
| `save_count` | `int` | Save counter (ASE v9+) |
| `is_asa` | `bool` | Whether ASA SQLite format |
| `objects` | `list[GameObject]` | All parsed game objects |
| `object_count` | `int` | Total object count |
| `parse_error_count` / `parse_errors` | `int` / `list[str]` | Errors encountered |
| `container` | `GameObjectContainer` | Relationship-aware container |
| `actor_locations` | `dict[str, LocationData]` | GUID → location (ASA only) |
| `data_files` | `list[str]` | External data file references |
| `name_table` | `list[str] \| dict[int, str]` | Deduplicated name strings |

Key methods:

| Method | Returns | Description |
|---|---|---|
| `load(source, load_properties=True, max_objects=None, lazy_properties=False)` | `WorldSave` | Load and parse a world save (`lazy_properties`: on-demand property parsing, ASE + ASA, see Quick Start) |
| `materialize_object(obj, names=None)` | `None` | Parse one lazy object's deferred property block (called automatically on property access; `names` is an ASA v14+ partial-decode hint) |
| `evict_materialized()` | `int` | Release every property block materialized since the last call (lazy saves; no-op eager) |
| `get_creatures()` | `list[GameObject]` | All creatures |
| `get_tamed_creatures()` / `get_wild_creatures()` | `list[GameObject]` | Filtered creature sets |
| `get_structures()` | `list[GameObject]` | Tribe-owned placed structures |
| `get_player_pawns()` | `list[GameObject]` | Player characters on the map |
| `get_terminals()` / `get_supply_drops()` / `get_artifact_crates()` | `list[GameObject]` | Map-element objects |
| `get_map_resources()` / `get_nests()` | `list[GameObject]` | Veins, charge nodes, beaver dams, nests |
| `get_items()` | `list[GameObject]` | Item objects |
| `get_objects_by_class(pattern)` | `list[GameObject]` | Substring class match |
| `get_object_by_guid(guid)` | `GameObject \| None` | Lookup by GUID (ASA) |
| `get_actor_location(guid)` | `LocationData \| None` | Actor location by GUID (ASA) |
| `iter_cryopod_creatures()` | `Iterator[(GameObject, CryopodCreature)]` | Walk filled cryopods |

### Game Objects

#### GameObject (`arkparser.GameObject`)

| Field | Type | Description |
|---|---|---|
| `id` | `int` | Object index within the save |
| `guid` | `str` | 16-byte GUID (ASA only) |
| `class_name` | `str` | UE4 class name |
| `is_item` | `bool` | Whether this is an item / blueprint / engram |
| `names` | `list[str]` | ArkName list (1 for actors, 2+ for components) |
| `location` | `LocationData \| None` | World position and rotation |
| `properties` | `list[Property]` | Parsed property list |
| `parent` / `components` | `GameObject \| None` / `dict[str, GameObject]` | Relationships |

Lookup helpers: `get_property(name, index=None)`, `get_property_value(name, default=None, index=None)`, `get_properties_by_name(name)`, `has_property(name)`, `to_dict()`. On lazy saves every helper materializes the deferred property block transparently; `evict_properties()` releases it again (re-access re-parses, so eviction is always safe).

#### GameObjectContainer (`arkparser.GameObjectContainer`)

Relationship-aware container. Supports `len()`, iteration, indexing. Same filter methods as `WorldSave` (`get_creatures`, `get_structures`, `get_player_pawns`, …) plus `find_by_class_pattern(pattern)`.

#### LocationData (`arkparser.LocationData`)

`x`, `y`, `z`, `pitch`, `yaw`, `roll` floats. `position` / `rotation` tuple properties, `to_dict()`.

### Cloud-Inventory Data Models

| Class | Purpose |
|---|---|
| `UploadedCreature` | Cloud creature record (class, level, stats, IDs, upload time) |
| `UploadedItem` | Cloud item record with `.is_cryopod` / `.cryopod_creature` accessors |
| `CryopodCreature` | Parsed creature snapshot from a cryopod blob (creature + status properties) |
| `DinoStats` | Current/max stat values for a creature |

All four expose `from_*` constructors and `to_dict()` for serialization.

### Export Functions

`arkparser.export` produces dicts matching the legacy `ASVExport.exe` schema. Optional `map_config` adds `lat` / `lon` GPS keys.

| Function | Returns | Description |
|---|---|---|
| `export_tamed(save, map_config=None)` | `list[dict]` | `ASV_Tamed` records |
| `export_wild(save, map_config=None)` | `list[dict]` | `ASV_Wild` records |
| `export_players(save, map_config=None, cluster_inventories=None)` | `list[dict]` | `ASV_Players` records (from Profile parsers). Pass `cluster_inventories` to splice each player's uploaded items into their `inventory` (entries tagged `uploaded: true`, matched by cloud-file stem == the player's `.arkprofile` filename stem) |
| `export_tribes(save)` | `list[dict]` | `ASV_Tribes` records |
| `export_structures(save, map_config=None)` | `list[dict]` | `ASV_Structures` records |
| `export_tribe_logs(save)` | `list[dict]` | `ASV_TribeLogs` records |
| `export_map_structures(save, map_config=None)` | `list[dict]` | `ASV_MapStructures` records |
| `export_all(save, map_config=None, cluster=None)` | `dict[str, list[dict]]` | All seven exports keyed by ASV filename stem. `cluster` accepts a directory path or pre-loaded `CloudInventory` iterable; splices cluster tames into `ASV_Tamed` and cluster items into `ASV_Players[i].inventory` |
| `export_cluster_uploads(cluster_inventories, map_config=None)` | `list[dict]` | Tamed-shape records for creatures stored in cluster `CloudInventory` files (decoded from `ArkTamedDinosData[].DinoData` blobs and `ArkItems[].CustomItemDatas` cryopod blobs) |
| `export_cluster_items(cluster_inventories)` | `list[dict]` | Every uploaded item across the supplied cloud files, snake_case flat stats included |
| `export_cloud_inventory(cloud, map_config=None)` | `dict[str, list[dict]]` | Standalone inspection of a single `CloudInventory`. Returns `{"ASV_Tamed": [...], "ASV_Items": [...]}` for staff tools that need to see one user's obelisk file without worldsave context |
| `export_to_files(save, output_dir, map_config=None, wrap=True, cluster=None, compact=False)` | `list[Path]` | Writes each export to `<dir>/<ASV_Name>.json`. `wrap=True` (default) emits the legacy `{map, day, time, data}` envelope; `wrap=False` writes the flat list |

Schema policy:

- **Legacy keys** (`hp-w`, `ccc`, `dinoid`, `mut-f`, `lat`, `lon`, `tribeid`, etc.) are frozen; they mirror `ASVExport.exe` exactly. They are emitted on every record regardless of value.
- **Empty parser-added fields are omitted.** Added keys whose value is `None`, `""`, `[]`, `false`, or numeric `0` are dropped from the output (ARK property absence already encodes the default). Consumers must read added fields with `.get(key, default)` rather than expecting the key to exist. Lists like `colors` / `body_colors` / `harvest_resource_levels` are also dropped when every element is zero.
- **Parser additions** sit alongside the legacy keys with descriptive snake_case names (no `extra_*` prefix). See the per-export schema tables above for the full list.
- **Stat tokens** are uniform across every export: `hp`, `stam`, `torp`, `oxy`, `food`, `water`, `temp`, `weight`, `melee`, `speed`, `fort`, `craft`. Stat blocks use the suffixes `-w` (wild base, tamed only), `-t` (tamed level-ups), `-m` (mutations); wild creatures and players use the unsuffixed form.

### Map Config (`arkparser.common.map_config`)

| Function | Returns | Description |
|---|---|---|
| `get_map_config(filename)` | `MapConfig` | Lookup by save filename (case-insensitive) |
| `get_map_config_by_name(name)` | `MapConfig` | Lookup by display name |
| `list_maps()` | `list[MapConfig]` | All registered map configs |

`MapConfig` methods: `ue_to_lat(y)`, `ue_to_lon(x)`, `ue_to_gps(x, y)`, `ccc_string(x, y, z)`.

### Version Detection (`arkparser.common.version_detection`)

| Function | Returns | Description |
|---|---|---|
| `detect_format(source)` | `ArkFileFormat` | `ASE`, `ASA`, or `UNKNOWN` |
| `detect_file_type(source)` | `ArkFileType` | `PROFILE`, `TRIBE`, `CLOUD_INVENTORY`, `WORLD_SAVE`, or `UNKNOWN` |
| `get_save_version(source)` | `int` | Version number (-1 if invalid) |

### Exceptions

| Exception | Description |
|---|---|
| `ArkParseError` | Base exception for all parsing errors |
| `CorruptDataError` | File data appears corrupted or invalid |
| `UnknownPropertyError` | Unrecognized property type encountered |
| `UnknownStructError` | Unrecognized struct type encountered |
| `UnexpectedDataError` | Data doesn't match expected values |
| `EndOfDataError` | Attempted to read past end of data |

## Format Support

| Feature | ASE (v5-12) | ASA (v13-14+) |
|---------|-------------|---------------|
| Vectors | Float (4 bytes) | Double (8 bytes) |
| Object IDs | Int32 index | 16-byte GUID |
| Booleans | Int32 | Int16 |
| World Save | Binary file | SQLite database |
| Compression | None | zlib + custom RLE |

ASA worldsave property layouts differ between **v13** (`TheIsland_WP` and older single-player saves, legacy `AsaSavegameToolkit`-style `dataSize + position + typeRef + byte` body) and **v14+** (current production ASA, marker-based body). Both are parsed by version-aware property readers; `WorldSave.version` is the source of truth.

### Known limitation: ASA cryopod property blocks are partially decoded

ASA cryopods (`PrimalItem_WeaponEmptyCryopod_C`, `SoulTrap`, `Vivarium`, `DinoBall`) store the embedded creature snapshot inside the item's `CustomItemDatas.CustomDataBytes.ByteArrays[0]` as a **zlib + custom-RLE compressed `AsaDataStore` blob**. The parser surfaces the snapshot via the simpler `CustomDataStrings` / `CustomDataFloats` accessors, exposing **species, tamed name, level, color regions, and `CurrentStatusValues[0..11]`** on each cryopodded creature.

What is **NOT yet extracted** from ASA cryopod blobs:

- `DinoID1` / `DinoID2` (and therefore `id` / `dinoid`)
- `TamingTeamID` / `TargetingTeam` (and therefore `tribeid`)
- `TamerString`, `OwningPlayerID`, `OwningPlayerName`
- `TamedOnServerName`, `UploadedFromServerName`
- `BaseCharacterLevel` vs `ExtraCharacterLevel` split (only the displayed total surfaces)
- Mutation counts, imprint quality, ancestors, behavioural toggles, etc.

ASA cryopod records therefore come back with `tribeid: 0`, `tamer: ""`, `dinoid: "0"`, `imprint: 0.0` on the otherwise-rich tamed schema. The compressed property block at the C#-reported `PropertyOffset + 1` decompresses cleanly through both zlib and the custom RLE (matching `AsaCompressedData.cs` byte-for-byte), and the surrounding `AsaGameObject` headers parse correctly, but the property-list bytes that follow do **not** form valid name-table references under any alignment we tried (including the layout `AsaPropertyRegistry.ReadProperty` uses). The legacy AsaSavegameToolkit wraps `ReadProperties` in a swallowing try/catch (`AsaGameObject.cs:178-193`), so it is plausible that **no current open-source tool extracts this data** either.

**ASE cryopod records are fully populated** via the in-place property-list blob, `from_cryopod_bytes` surfaces every legacy ASV_Tamed field.

If you crack the ASA cryopod block format (e.g. via UE5 source-level RE on `UPropertySerializer` for these compressed stores, or a working reference output to byte-diff against), please open a PR, the bytes are correctly decompressed and exposed in `WorldSave.iter_cryopod_creatures()`, only the property reader is missing.

## Testing

```powershell
.\.venv\Scripts\Activate.ps1
python -m pytest tests/ -v
```

Tests live in `tests/`. Byte-level layout tests (`test_v13_property_layouts.py`, `test_binary_reader_layouts.py`) pin the canonical v13/v14 property body byte sequences with no file-fixture dependency. Integration tests (`test_world_save.py`, `test_export.py`, etc.) skip cleanly when their referenced save files are not present under `references/examples/`.

Two suites guard export output against drift:

- **Golden manifests** (`tests/test_golden_exports.py` + `tests/golden/*.json`): a per-map fingerprint of `export_all` (record count, field-key union, order-independent sha256) for 17 real saves (10 ASE map dumps + 7 ASA). Any change to parsing or export that alters output fails the matching map. Regenerate intentionally with `ARKPARSER_UPDATE_GOLDEN=1`.
- **Lazy parity** (`tests/test_lazy_properties.py`): proves `lazy_properties=True` yields property-for-property identical objects (ASE and ASA), that evict/re-materialize round-trips, and that full lazy exports match the committed eager goldens. The ASA partial-decode skip walk is additionally verified byte-exact against the full parser over every object of every local ASA fixture by `references/scripts/verify_partial_walk.py`.

## Credits

Built by reverse-engineering ARK save formats with heavy reference to [ASV (Ark Save Visualizer)](https://github.com/miragedmuk/ASV) by **miragedmuk**. The C# implementation in ASV is the primary reference for porting binary parsing logic to Python.
