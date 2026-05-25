# Known Issues

Open issues for future investigation. Triage and migrate to GitHub issues as needed.

_No open issues currently. Resolved items are logged below for reference._

---

## Resolved

### ASE cloud/cluster inventory cursor drift -> dropped uploads (fixed 2026-05-25, v0.4.4)

**Was:** On a live ASE Ragnarok PvE cluster, certain cluster files raised
`EndOfDataError` mid-parse ("Attempted to read 8519680 bytes, but only 104300
available") and were skipped entirely, silently dropping all their uploaded
creatures/items from `ASV_Tamed` and the per-player upload splice, plus WARNING
spam every reparse.

**Root cause:** ASE struct arrays whose elements are *native* fixed-size structs
(e.g. `CustomItemColors` = `Color[]`) carry no per-element type tag - the element
type is implied by the array name. arkparser only mapped a couple of names
(`CustomColors`) in `ARRAY_NAME_TO_STRUCT_TYPE`; any unmapped native-struct array
(like `CustomItemColors`) was read as a property-list struct, so color bytes were
misread as a property-name length, the cursor drifted, and a later property-name
read exploded with a garbage length. The legacy reader (`ArkArrayStruct.Init`)
avoids this by *inferring* the native element type from the array body size when
the name is unmapped.

**Fix:** `_read_array_elements` now mirrors legacy for ASE struct arrays - when
the array name is unmapped, infer the native element type from the body size:
`count*4 + 4 == data_size` -> Color, `*12` -> Vector, `*16` -> LinearColor; else
fall back to property-list structs. Gated to ASE (`not is_asa`) so the ASA v6
path is untouched. Verified: all 7 previously-failing files in the live `pve`
cluster now parse, and a full scan of 1867 cluster files parses 0 errors
(recovering 3221 creatures + 42923 items). See `arkparser/properties/compound.py`
(`_read_array_elements`) and `tests/test_ase_cluster_drift.py`.

### ASA `__UNKNOWN_CLASS_<int>__` name-table leak (fixed 2026-05-25, v0.4.4)

**Was:** Wild / tamed creatures from some ASA saves carried `class_name` values
like `__UNKNOWN_CLASS_-1704488797__`, surfacing downstream (arkviewer -> arktools)
as bogus "unknown dino" alerts the operator could not act on.

**Root cause:** the v14 ASA `SaveHeader` stores the name table at an explicit
absolute offset (`actual_offset` - the 2nd int32 after `legacy_offset`).
`_read_asa_header` read that offset but **discarded** it and instead read the
name table *sequentially* after the data-files section. The bytes between the
parts section and the real offset are not a fixed pad pair, so on busy/modded
maps the cursor landed short of the table (measured: Ragnarok -26 B, Scorched
Earth -31 B), reading a truncated table that resolved only ~half the class
hashes. The old `idx == 1` sentinel `skip(4)` was a band-aid for this drift.

**Fix:** seek to the offset on v14+ before reading the table, mirroring the C#
reference (`AsaSavegame.readNametable`: `archive.Position = nameTableOffset`).
Verified on real saves: Ragnarok 1333 -> 0 and Scorched Earth 10565 -> 0 leaked
classes; TheIsland / Aberration / Extinction (gap already zero) byte-identical.
The sentinel hack is retained only on the unverified v13 sequential path (no
live v13 fixture to validate a seek against). See `arkparser/files/world_save.py`
(`_read_asa_header` / `_read_asa_name_table`) and `tests/test_asa_name_table.py`.
