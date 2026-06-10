# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); the project uses semantic
versioning on its **public Python API** (the output JSON schema is additive;
legacy `ASVExport.exe` keys are frozen and never removed/renamed).

## [0.7.1]

Hardening round from a full-codebase parsing review (ASE + ASA). No output or
schema changes; the golden suite (17 maps) is byte-identical before and after.

### Changed

- Cryopod/creature-storage class-name patterns (`Cryopod`, `SoulTrap`,
  `Vivarium`, `DinoBall`) consolidated into a single source of truth,
  `arkparser.common.types.CRYOPOD_CLASS_PATTERNS`. Previously three hand-kept
  copies (world-save iteration, export inventory filtering,
  `UploadedItem.is_cryopod`) could silently drift.
- The indexed-property walks in tribe export (`MembersPlayerDataID`,
  `TribeAlliances`, `TribeLog`) now use statically bounded loops
  (`_MAX_TRIBE_MEMBERS`) instead of unbounded `while True`.
- Import-time asserts guard the hand-maintained stat-order tuples in
  `export.py` against drifting out of sync with `_STAT_NAMES`.

### Added

- DEBUG-level log line when an ASE object's property block terminates early
  and the remainder is preserved as `extra_data` (previously silent), showing
  the class name, the number of properties kept, and the original error.

## [0.7.0]

### Added

- **Live player coordinates on profile-built `ASV_Players` records**: profile
  records now join `PlayerDataID == LinkedPlayerDataID` against the world
  save's in-world player pawns, so online players get real `lat`/`lon`/`ccc`
  from the pawn's location instead of always exporting 0/0. Players with no
  in-world body (logged out, dead with corpse cleared) correctly stay at zero.
  Legacy `ASVExport.exe` never had these coords at all.

### Changed

- `tests/golden/*.json` manifests are no longer tracked in git (derived
  fingerprints; regenerate locally with `references/scripts/gen_golden.py`).

## [0.6.0]

Chunked/lazy-parse round: memory-bounded parsing for large ASE saves plus the
performance work that came with it. Output is unchanged (guarded by the new
golden suite); the public API grows one keyword argument.

### Added

- **Lazy property parsing (ASE)**: `WorldSave.load(path, lazy_properties=True)`
  parses object headers eagerly and defers every property block until first
  access (`GameObject` getters materialize transparently); export drivers evict
  blocks again as records stream to disk. New: `WorldSave.materialize_object`,
  `WorldSave.evict_materialized`, `GameObject.evict_properties`,
  `BinaryReader.from_file_mmap`, `BinaryReader.trim_working_set`. Fjordur PvE
  (1.8 GB ark, 1.79M objects) load+export: **~7.1 GB peak RSS / 348 s eager →
  ~2.5 GB / 287 s lazy**; legacy `ASVExport.exe` needs 8.2 GB / 217 s on the
  same save.
- **Lazy property parsing (ASA)**: the same flag now covers SQLite saves. The
  loader parses headers from each `game` row blob, drops the blob, and retains
  the connection (one held read transaction; per-statement implicit
  transactions cost a Windows file lock/unlock per fetch, ~16x slower);
  `materialize_object` re-fetches a row by GUID on demand. On v14+ saves the
  classification pass and the record builders use **partial decodes**: a skip
  walk that decodes only a whitelisted name set per record kind and skips
  every other property body via verified byte-exact layout arithmetic
  (`read_properties_partial`; proven against the full parser over 1.49M
  objects across all 7 local ASA fixtures by
  `references/scripts/verify_partial_walk.py`). Reads outside the whitelist
  transparently upgrade to a full decode, so the whitelists are perf hints,
  never correctness inputs. ASA TheIsland (233 MB, 217k objects) load+export:
  **853 MB peak RSS / 38 s eager → 307 MB / ~36 s lazy**; output identical
  (goldens + record-for-record comparison on scorchedearth / theisland /
  ragnarok).
- **Golden export manifests**: `tests/golden/*.json` fingerprint `export_all`
  for 17 real saves (count + field-key union + order-independent sha256);
  `tests/test_golden_exports.py` fails on any output drift. Lazy-vs-eager
  parity covered by `tests/test_lazy_properties.py`.

### Changed (performance, output-identical)

- Fused creature/structure classification into one walk with a header-data
  pre-filter: items and status/inventory components are never property-probed
  (component patterns are deliberately tighter than bare "Inventory" so modded
  structures like `StructureBP_InventoryCars_C` still classify via OwnerName).
- Cryopod display summaries: each pod blob is fully decoded once (for its
  ASV_Tamed record); inventory listings (cryofridges, pawns, vaults) reuse a
  per-pod `(dino_id, creature, name)` summary instead of re-decoding. Was 35%
  of a busy-PvE export.
- ASE property-header fast path (single fused 4-int32 unpack + inlined
  name-table lookups), interned name tables, cached `_pascal_to_snake`,
  frozenset property-type dispatch, inlined scalar leaf case in
  `normalize_indexed_data`.
- ASA worldsave hot path: fused int32-pair reads in the property header and
  simple-value prefix, direct hex GUID formatting (`guid_str_le`, ~2.5x
  cheaper than `str(uuid.UUID(bytes_le=...))`, asserted equivalent in tests),
  captured OwnerName/TamerString/TribeName during classification so the tribe
  synthesis walks re-parse nothing, and a single ordered table scan feeding
  classification blobs instead of one SELECT per object.

## [0.5.4]

### Fixed

- **ASA cryopod class names**: strip the trailing UE actor instance suffix
  (`Raptor_Character_BP_C_2145673735` → `Raptor_Character_BP_C`) sourced from
  `CustomItemDatas`; the spawn id leaked into the ASV_Tamed `creature` field.
  Variant suffixes (`_Aberrant_C`, ...) are untouched.

## [0.5.3]

### Fixed

- **Tribe member ranks on busy saves**: `normalize_indexed_list` now expands
  `bytes`/`bytearray` values element-wise to `list[int]`, restoring the
  pre-0.5.2 shape for iterating consumers (`MembersRankGroups` crashed the
  full export on live PvE saves). Cryopod byte blobs keep the `bytes` memory
  win (they are key-accessed, never iterated through this path).

## [0.5.2]

### Changed (memory)

- `@dataclass(slots=True)` on `Property`, all 20 subclasses, and
  `PropertyHeader` (drops per-instance `__dict__`).
- Raw `ByteProperty` arrays are stored as one `bytes` blob instead of
  `list[int]` (8x smaller; cryopod blobs dominate busy saves). Fjordur ASE
  (302k objects) load+export peak: 1228 MB → 899 MB (-27%); output
  byte-identical.

## [0.5.1]

### Changed (memory)

- `export_to_files` streams each record straight to the file (exporters became
  `_iter_*` generators); `export_all` still materializes for in-memory callers.
  Eliminates the multi-GB export-phase spike from holding all seven record
  lists plus a whole-file `json.dumps` string (Ragnarok PvE peak 7.4 GB → 5.0 GB).

## [0.5.0]

Major legacy-parity pass driven by a full-codebase review and validated against
`ASVExport.exe` on every ASE map (plus parser-only ASA validation on all 7 ASA
maps). The public Python API is unchanged; legacy keys are unchanged. **Several
exports now emit more records / different field values to match legacy**, see
"Behavioral changes" before upgrading a downstream consumer.

### Added / Fixed (legacy parity)

- **Tribe / TribeLog synthesis.** `export_tribes` / `export_tribe_logs` now build
  the full legacy tribe superset (mirroring `ContentContainer`): two sentinels
  (`[ASV Unclaimed]` `2000000000`, `[ASV Abandoned]` `-2147483648`), the loaded
  `.arktribe` files, a solo `Tribe of <name>` per profile, and stub tribes for
  every distinct structure (`TargetingTeam >= 50000`) and in-world tame team,
  deduped by id. Previously only file-backed tribes were emitted (theisland
  306 → 1936 matched of legacy's 2180; primitive_plus 570 → **6012/6012 exact**).
- **Player synthesis + tribe resolution.** Tribe members with no `.arkprofile`
  now surface as stub player records (legacy member back-fill); a player's
  `tribeid` is resolved from the containing tribe (membership), not the profile's
  own field. Players-missing dropped to **0 on every map**.
- **Structures.** `tribe` now resolves to the owning tribe's name (file
  `TribeName`, else `OwnerName`/`TamerString`) instead of the raw `OwnerName`;
  unowned structures fall to `[ASV Abandoned]` (`tribeid = -2147483648`); unowned
  map elements / crates / debug actors (`Button_*`, `*Vein_*`, `*Nest_*`,
  `*Beaver*`, `BeeHive_C`, `ArtifactCrate_*`, `TributeTerminal_*`, `SupplyCrate_*`)
  are excluded from `ASV_Structures` (surfaced via `ASV_MapStructures`).
- **Inventory.** Each holder's inventory now merges `EquippedItems` (saddles /
  armor / costumes) in addition to `InventoryItems`, and skips engram
  placeholders (`bIsEngram`), matching legacy.
- **Wild / tamed classification.** Removed a marker-property fallback in
  `_is_tamed_creature`; classification is now the pure legacy team rule
  (`TargetingTeam >= 50000`). Fixes wild creatures carrying a leftover
  `TamingTeamID` being mis-counted as tamed (wild is now exact on every map).

### Added (API)

- `Profile.raw_tribe_id`, the explicit stored tribe id (no `player_id`
  fallback), used by the player→tribe allocation.

### Robustness / internals

- `read_properties` is now bounded by an explicit iteration cap (Power-of-10).
- The cryopod-decode property failure path now logs instead of silently
  swallowing.
- `_is_default` color/vector comparison uses `zip(strict=True)`.

### Docs

- README: corrected the `extra_*` claim (parser uses descriptive snake_case, no
  prefix), removed duplicate `ASV_Players` rows and a phantom
  `last_ally_in_range_seconds` field, documented the tribe-synthesis behavior.

### Behavioral changes (read before upgrading a consumer)

- **`ASV_Tribes` / `ASV_TribeLogs` record counts increase substantially** (≈3-10×
  on busy maps), mostly stub tribes (`tribeid` + name, `players: 0`). Consumers
  that ingest these (e.g. ArkViewer → SQLite) will see many more rows.
- **Abandoned structures now report `tribeid = -2147483648`** (was `0`). A filter
  testing `tribeid == 0` for "no tribe" must be updated.
- **`ASV_Structures.tribe`** is the resolved tribe name (e.g. `Tribe of Bob`),
  not the raw `OwnerName` (`Bob`).
- `ASV_Players` includes additional member-stub records; some player `tribeid`
  values change to the containing tribe id.
- Inventory item lists may grow (equipped items) or shrink (engrams removed).

### Known limitations

- Cluster-only cross-server tribes (present only in cloud-inventory files, no map
  presence) are not synthesized (~244 of legacy's count per ASE map on the test
  cluster). In-world / file / solo tribes are exact (primitive_plus 6012/6012).
- ASA cryopod-embedded creatures still expose only species / level / colors /
  current stats; `DinoID` / tribe / tamer remain undecoded (`tribeid: 0`).
- Cross-server duplicate-`DinoID` cluster tames are de-duplicated (legacy keeps
  every copy), so a few tamed `lvl`/`base`/`tribeid`/`tamer` values differ from
  legacy on cluster-heavy maps; the parser's value is generally the more correct.
