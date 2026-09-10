# Profiler metrics

[Documentation](../README.md) · [Profiler guide](README.md) · [Results and analysis](results.md)

One callback can touch more than one eight-byte cell. The result tables use the
metric names below without shortening them.

| Metric | Calculation | Meaning |
| --- | --- | --- |
| Private cells | `private_cells / first_touches` | Cell lifetimes that never changed owner. |
| Private-phase accesses | `private_accesses / cell_touches` | Touches by the current owner before the first owner change. |
| Private accesses beyond CSA | `(private_accesses - private_csa_hits) / cell_touches` | Private-phase touches not already handled by stock `ContainsSameAccess`. |
| Exact-note absorbed accesses | `note_absorbed_accesses / cell_touches` | Touches for which the complete history still fits in the simulated one-word note. |
| Exact-note accesses beyond CSA | `(note_absorbed_accesses - note_absorbed_csa_hits) / cell_touches` | Note-absorbed touches not already handled by `ContainsSameAccess`. |
| Exact-shadow hits among eligible accesses | `(shadow_exact_slot0_hits + shadow_exact_late_hits) / shadow_exact_eligible` | Eligible touches matching one of the four ordinary shadow slots. |
| Potentially avoidable shadow pages | `potentially_avoidable_shadow_pages / shadow_pages` | Reached pages containing absorbed touches and no fallback touch. |
| Mixed-path shadow pages | `mixed_path_shadow_pages / shadow_pages` | Reached pages containing both absorbed and fallback touches. |
| Fallback-only shadow pages | `fallback_only_shadow_pages / shadow_pages` | Reached pages containing fallback touches and no absorbed touch. |
| Sparse shadow pages | sparse page buckets divided by `shadow_pages` | Reached pages containing 1–64 touched application cells. |
| Dense shadow pages | dense page buckets divided by `shadow_pages` | Reached pages containing 193–256 touched application cells. |

For 4 KiB Linux pages, one TSan v3 shadow page represents 256 application
cells. The reporting buckets are:

- Sparse: 1–64 touched cells, at most 25%.
- Middle: 65–192 touched cells.
- Dense: 193–256 touched cells, more than 75%.

These are reporting categories, not TSan decisions. Zero-touch pages do not
appear. A potentially avoidable page is an estimate from access traffic;
allocator clearing or other runtime work can still materialize it.

`shadow_exact_slot0_hits / shadow_exact_eligible` is the slot-0 hit rate. Peak
total RSS, peak shadow RSS, and peak profiler RSS come from Linux
`/proc/<pid>/smaps` sampling.
