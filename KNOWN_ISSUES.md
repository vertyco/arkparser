# Known Issues

Open issues for future investigation. Triage and migrate to GitHub issues as needed.

---

## ASE cloud/cluster inventory: parser cursor drift → dropped uploads + WARNING spam

**Symptom:** On a live ASE Ragnarok PvE server (May 2026) every full reparse logs
a burst of WARNINGs and the affected cluster files are **skipped entirely** — their
uploads never reach `ASV_Tamed` or the per-player upload splice:

```
WARNING [arkparser.export]: Skipping cluster file ...\clusters\solecluster\2533274829298794: Attempted to read 8519680 bytes, but only 104300 bytes available
WARNING [arkparser.export]: Skipping cluster file ...\2533274854487560: Attempted to read 32238572 bytes, but only 76737 bytes available
WARNING [arkparser.export]: Skipping cluster file ...\2533274905839355: Attempted to read 17038948 bytes, but only 10051 bytes available
WARNING [arkparser.export]: Skipping cluster file ...\2535426726772842: Attempted to read 8441140 bytes, but only 151765 bytes available
```

**Source:** `EndOfDataError` raised at `arkparser/common/exceptions.py:96-99`,
caught + logged at `arkparser/export.py:2382` inside `_load_cluster_inventories`.
The file is parsed by `CloudInventory.load` (`arkparser/files/cloud_inventory.py`).

**Diagnosis (from the arkviewer-side investigation, 2026-05-24):** these are **not**
genuinely-corrupt stub files. The requested byte counts (`8519680 = 0x00820000`,
`32238572 = 0x01EC85AC`, `17038948`, …) are arbitrary in-file bytes being read as an
int32 **length prefix after the parse cursor has drifted**. The file header parses
and some properties succeed, then a length read mid-object goes wildly out of range
and overruns the buffer. Classic cursor misalignment in the ASE cloud-inventory
property layout — not corruption. (Contrast: the loader's object-count sanity clamp
at `cloud_inventory.py:91-92` passes, and the failure is deep in a single object.)

**Impact:** real cluster uploads in the affected files are silently dropped from the
export (the cross-server tamed splice + player uploaded-items). On a busy PvE
cluster that can be a meaningful fraction of uploaded creatures/items. Plus WARNING
spam on every reparse.

**Hypotheses to investigate (ranked):**

1. **ASE cloud property-layout assumption.** The cloud/obelisk file lays out some
   property/struct type slightly differently from the worldsave path. Find the first
   property where the cursor diverges.
2. **Length-prefix width / encoding.** A field read as int32 that is actually
   int16/uint, or the UTF-16-vs-UTF-8 string-length sign convention in `read_string`
   (negative length = UTF-16) misapplied on the cloud path.
3. **A specific upload subtype** present only in these files (a particular
   saddle/blueprint/cryopod variant) whose body size is mis-read.

**Diagnostic next steps:**

- Pull a failing file (live Ragnarok `solecluster` dir, or ask the operator) into
  `references/local_saves/` as a fixture. Instrument `CloudInventory.load` to log the
  cursor offset + last-good property name at the bad length read — localizes the
  drift to one property type.
- Diff the same file's legacy `ASVExport.exe` cluster output (legacy parses these)
  against the arkparser attempt to see exactly what's dropped.

**Investigation 2026-05-25 — could NOT reproduce (triggering files gone):**
scanned all 490 non-empty files in the live `pvp` cluster
(`\\192.168.1.91\homes\reclaimer\Clusters\pvp`) with `CloudInventory.load` —
every one parsed cleanly (all version 4 ASE, 0 `EndOfDataError`). The four files
named above are absent from both the cluster and `.sync/Archive` (cluster uploads
are transient — players re-download, the stale upload is purged). With no failing
file the drift cannot be localized and a fix cannot be verified, so none was
attempted (a blind change risks regressing the v4 path that currently parses
490/490). **Next step:** when the WARNING recurs on the live server, copy the
named file out of the cluster *before* it is consumed, drop it into
`references/local_saves/` as a fixture, then localize the divergent property.

**arkviewer-side mitigation already in place (does NOT fix the drop):** arkviewer
parses each cluster file in its own `try/except` (one bad file can't abort the whole
reparse) and skips `< 16` byte stubs silently. Uploads in a drifting file remain
lost until the parser is fixed here. See
`references/Documents/UPSTREAM_arkviewer_memory_streaming.md` for the related
memory work.

---

## Resolved

### ASA `__UNKNOWN_CLASS_<int>__` name-table leak (fixed 2026-05-25, v0.4.4)

**Was:** Wild / tamed creatures from some ASA saves carried `class_name` values
like `__UNKNOWN_CLASS_-1704488797__`, surfacing downstream (arkviewer → arktools)
as bogus "unknown dino" alerts the operator could not act on.

**Root cause:** the v14 ASA `SaveHeader` stores the name table at an explicit
absolute offset (`actual_offset` — the 2nd int32 after `legacy_offset`).
`_read_asa_header` read that offset but **discarded** it and instead read the
name table *sequentially* after the data-files section. The bytes between the
parts section and the real offset are not a fixed pad pair, so on busy/modded
maps the cursor landed short of the table (measured: Ragnarok −26 B, Scorched
Earth −31 B), reading a truncated table that resolved only ~half the class
hashes. The old `idx == 1` sentinel `skip(4)` was a band-aid for this drift.

**Fix:** seek to the offset on v14+ before reading the table, mirroring the C#
reference (`AsaSavegame.readNametable`: `archive.Position = nameTableOffset`).
Verified on real saves: Ragnarok 1333 → 0 and Scorched Earth 10565 → 0 leaked
classes; TheIsland / Aberration / Extinction (gap already zero) byte-identical.
The sentinel hack is retained only on the unverified v13 sequential path (no
live v13 fixture to validate a seek against). See `arkparser/files/world_save.py`
(`_read_asa_header` / `_read_asa_name_table`) and `tests/test_asa_name_table.py`.
