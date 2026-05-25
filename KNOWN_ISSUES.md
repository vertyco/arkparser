# Known Issues

Open issues for future investigation. Triage and migrate to GitHub issues as needed.

---

## ASA: `__UNKNOWN_CLASS_<int>__` leaking from name table

**Symptom:** Wild / tamed creatures exported from ASA saves occasionally carry
`class_name` values like `__UNKNOWN_CLASS_-1704488797__` or
`__UNKNOWN_CLASS_1249459011__` instead of a real blueprint class name. These
leak through `export_wild` / `export_tamed` and downstream consumers (arkviewer
→ arktools, etc.) eventually surface them as "unknown dino" alerts the
operator cannot do anything about.

**Source:** `arkparser/files/world_save.py:790`

```python
class_idx = reader.read_int32()
obj.class_name = nt.get(class_idx, f"__UNKNOWN_CLASS_{class_idx}__")
```

The fallback fires whenever the parsed `class_idx` is not a key in the
per-save name-table dict built by
`_read_asa_data_files_and_name_table` (lines ~702-712).

**Observed example (live cluster, May 2026):**

```
__UNKNOWN_CLASS_-1704488797__
__UNKNOWN_CLASS_-594345399__
__UNKNOWN_CLASS_1249459011__
__UNKNOWN_CLASS_399176035__
__UNKNOWN_CLASS_288632527__
__UNKNOWN_CLASS_1199128191__
__UNKNOWN_CLASS_86912946__
__UNKNOWN_CLASS_1567204254__
__UNKNOWN_CLASS_56265707__
__UNKNOWN_CLASS_1941739011__
```

Mix of negative and positive int32 values - consistent with signed-int32
wrap of large uint hashes. Writer and reader both use signed `read_int32`,
so sign itself is not the bug. The dict simply lacks those keys.

**Hypotheses to investigate (ranked by likelihood):**

1. **Sentinel-skip misalignment.** Name-table loader (line 708) skips a
   trailing 4 bytes when `idx == 1`. If a legitimate non-sentinel entry ever
   has `idx == 1` by hash collision, the extra `reader.skip(4)` shifts every
   subsequent read by 4 bytes, corrupting all later names. Add an assertion
   that the next `read_string` length is plausible (< 1KB), and log when the
   sentinel branch fires so we can see how often it triggers.
2. **Engine-level FName interning.** ASA may serialize class references using
   FName hashes that were interned at engine boot but never persisted to the
   per-save name table. These would never be resolvable from save data alone.
   Fix would require cross-referencing the `data_files` strings (raw BP
   paths) and hashing them locally as a fallback - same FName hash algorithm
   the engine uses (likely FNV-1a or CRC32 over the lowercased string).
3. **Modded creature classes.** Custom dinos added by server mods whose class
   names are referenced by game objects but never appear in the save's
   public name table. Same fallback as (2) would help if the data_files
   strings cover them.

**Diagnostic next steps:**

- Instrument `_read_asa_data_files_and_name_table` to log `name_count` vs
  final `len(nt)` and compare against the number of distinct `class_idx`
  values referenced across all parsed `GameObject`s. Quantifies the gap.
- Dump the full set of unresolved `class_idx` values from a real save, then
  bruteforce them against `data_files` strings using likely hash algorithms
  to confirm or rule out hypothesis (2).
- Add a unit test fixture using a save that reliably produces
  `__UNKNOWN_CLASS_` entries (the live cluster save under
  `/home/pokuser/asa/Instance_pve-*` should have several).

**Pragmatic mitigation already deployed:** arktools 5.51.0 adds the
known-good ASA class names that were leaking through (Burrowbuck, Deinotherium,
Summer Drakeling) to its creature map. arkviewer could additionally filter
`__UNKNOWN_CLASS_` prefixed entries out of `ASV_Wild` / `ASV_Tamed` exports
once the root cause here is understood (so we don't mask a real bug that
should be fixed in arkparser).

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

**arkviewer-side mitigation already in place (does NOT fix the drop):** arkviewer
parses each cluster file in its own `try/except` (one bad file can't abort the whole
reparse) and skips `< 16` byte stubs silently. Uploads in a drifting file remain
lost until the parser is fixed here. See
`references/Documents/UPSTREAM_arkviewer_memory_streaming.md` for the related
memory work.
