# Profiler metrics

[Documentation](../README.md) · [Profiler guide](README.md) · [Results and analysis](results.md)

The denominator for access percentages is the number of observed eight-byte
cell touches. One callback can touch more than one cell.

| Metric | Meaning |
| --- | --- |
| Private cells | Cell lifetimes that never changed owner. |
| Private accesses | Touches by the current owner before the first owner change. |
| ContainsSameAccess | Touches already covered by stock TSan's exact-access check. |
| Exact-note absorbed | Touches whose complete history still fits in the simulated one-word note. |
| Exact note beyond CSA | Note-absorbed touches not already covered by `ContainsSameAccess`. |
| Exact shadow hit | Eligible touches matching one of the four ordinary shadow slots. |
| Potentially avoidable page | Reached page containing absorbed touches and no fallback touch. |
| Mixed page | Reached page containing both absorbed and fallback touches. |

For 4 KiB Linux pages, one TSan v3 shadow page represents 256 application
cells. The reporting buckets are:

- Sparse: 1–64 touched cells, at most 25%.
- Middle: 65–192 touched cells.
- Dense: 193–256 touched cells, more than 75%.

These are reporting categories, not TSan decisions. Zero-touch pages do not
appear. A potentially avoidable page is an estimate from access traffic;
allocator clearing or other runtime work can still materialize it.

`shadow_exact_slot0_hits / shadow_exact_eligible` is the measured slot-0 hit
rate. `peak_shadow_rss_kib` and `peak_ownership_profile_rss_kib` come from
Linux `/proc/<pid>/smaps` sampling.
