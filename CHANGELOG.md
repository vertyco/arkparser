# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); the project uses semantic
versioning on its **public Python API** (the output JSON schema is additive —
legacy `ASVExport.exe` keys are frozen and never removed/renamed).

## [0.5.0]

Major legacy-parity pass driven by a full-codebase review and validated against
`ASVExport.exe` on every ASE map (plus parser-only ASA validation on all 7 ASA
maps). The public Python API is unchanged; legacy keys are unchanged. **Several
exports now emit more records / different field values to match legacy** — see
"Behavioral changes" before upgrading a downstream consumer.

### Added / Fixed (legacy parity)

- **Tribe / TribeLog synthesis.** `export_tribes` / `export_tribe_logs` now build
  the full legacy tribe superset (mirroring `ContentContainer`): two sentinels
  (`[ASV Unclaimed]` `2000000000`, `[ASV Abandoned]` `-2147483648`), the loaded
  `.arktribe` files, a solo `Tribe of <name>` per profile, and stub tribes for
  every distinct structure (`TargetingTeam >= 50000`) and in-world tame team —
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

- `Profile.raw_tribe_id` — the explicit stored tribe id (no `player_id`
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

- **`ASV_Tribes` / `ASV_TribeLogs` record counts increase substantially** (≈3–10×
  on busy maps) — mostly stub tribes (`tribeid` + name, `players: 0`). Consumers
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
