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
