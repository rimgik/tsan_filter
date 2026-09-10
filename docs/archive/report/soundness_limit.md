# Soundness Limits of TSan Filtering

TSan v3 pays a 16-byte shadow-cell access on every memory operation, yet most operations touch data that is currently thread-private and cannot race. The natural idea is to keep cheap per-region ownership state and skip TSan while a region is private; this has been proposed repeatedly (OCTET and FIB in Java, our own v0.2). This note proves a limit on all such designs: no small per-cell summary can preserve TSan's detection behaviour. Any sound filter is therefore a bet on workload statistics, never a uniform improvement.

**Correctness bar (parity).** No false positive stock TSan would not raise; no race missed that stock catches. Stock's own incompleteness (4 shadow words per cell, rotation eviction) is inherited, not widened.

## 1. Model

Per 8-byte cell TSan keeps 4 shadow words of 32 bits: mask (8, bit $i$ = byte $i$), sid (8), epoch (14), is_read (1), is_atomic (1). Consider a cell during a single-owner phase: owner $T$ (slot $s$) makes accesses $a = (m, t, e)$, with mask $m \subseteq \{0,\dots,7\}$, type $t \in \{\mathrm{r},\mathrm{w}\}$, non-decreasing epoch $e$. A probe $B = (m_B, t_B, c)$ is a future foreign access, $c$ its clock entry for $s$. TSan's per-word race rule:

$$\mathit{races}(H, B) \iff \exists\, (m,t,e) \in H :\; m \cap m_B \neq \emptyset \;\wedge\; (t = \mathrm{w} \vee t_B = \mathrm{w}) \;\wedge\; c < e$$

A filter keeps state $S(H)$ per cell, built online from the history $H$, and must answer this predicate for every possible probe.

## 2. Cover lemma (what may be forgotten)

$a$ covers $a'$ (dropping $a'$ changes no answer) iff

$$m \supseteq m' \;\wedge\; e \geq e' \;\wedge\; \text{not } (t' = \mathrm{w} \text{ and } t = \mathrm{r}).$$

(⇐) A probe racing with $a'$ has $c < e' \leq e$, intersects $m' \subseteq m$, and conflicts with $a$: a write conflicts with everything, and if $a'$ was a read the probe must be a write. (⇒) If any condition fails there is a probe caught only by $a'$: an uncovered byte; a clock $c \in [e, e')$; a read probe against the dropped write. $\blacksquare$

In addition, equal-epoch same-type words merge losslessly by mask union, and epochs must be kept at full resolution, since probes take any clock value.

What survives covering is the **residue** of the phase: per byte, the latest write epoch, plus the latest read epoch where later. Worst case this is $8 \times 2$ epochs, about 28 bytes, already more than the 16-byte shadow cell the filter was trying not to touch.

## 3. The lower bound

**Theorem.** Any parity-preserving filter must, on some histories, hold state informationally equivalent to stock's full 4-word cell.

*Proof.* Construct $H^*$: accesses $w_1, \dots, w_4$ with pairwise disjoint masks and strictly increasing epochs $e_1 < \dots < e_4$. Disjointness forbids covering (mask containment fails), so all four are live and stock retains all four (four slots, nothing dominated, no eviction pressure). Disjointness also lets probes isolate each word: a probe with mask $\subseteq m_i$ intersects only $w_i$; varying $c$ flips its answer exactly at $c = e_i$; a read probe versus a write probe pins $t_i$ (read/read is exempt). Two histories differing in any $(m_i, t_i, e_i)$ therefore have different answer functions, and $S$ must distinguish them all. Hence $S$ determines all four words. $\blacksquare$

The construction uses disjoint masks for convenience, not necessity: they guarantee non-coverage and one-word isolation at the same time. Overlapping-mask families also force large state but need a longer argument.

## 4. Consequences

**C1. Every fixed small summary fails.** Ownership tags of the v0.2 family, (sid, epoch), (sid, two epochs), or any constant-size digest smaller than the cell, violate parity on some program. No amount of engineering fixes this. (In Java, OCTET and FIB avoid it only because their detectors keep growable per-location metadata underneath; TSan v3's fixed cell removes that escape.)

**C2. No sound filter dominates stock.** A filter adds its own check to every access, and on histories from the theorem it must also hold everything stock stores. So on some programs any sound filter is strictly worse than stock. "Improves some workloads, never hurts any" is unachievable. The realistic target is "improves the common case, bounded loss on the adversarial case."

**C3. Soundness pins information, not placement or timing.** The bound constrains how little state may exist, and says nothing about where it lives or when it is paid for. What remains: (a) **expected-case compression**: when a phase's residue is one word, 4 bytes is exact; (b) **relocation and amortisation**: state may sit on a denser cache line, be spilled lazily, or be checked once per region or per loop rather than per access; (c) **cross-cell deduplication**: the bound is per cell, but neighbouring cells often hold identical residues (an array initialised by one thread in one epoch), and identical state can be shared losslessly (SlimFast shows this is sound and complete for FastTrack; it has not been tried inside TSan v3). Known sound optimisations (FastTrack's epochs, RedCard's release-free spans, TSan v3's own bounded cell) are instances of these moves, and all of them are bets on real workloads.

**C4. The same argument bounds read-sharing.** A read-shared phase with $k$ distinct reader sids needs $k$ words (one probe per reader isolates it), so read-shared elision under parity is impossible with constant state. A sound design must hand read-shared data to the full detector.

## 5. Implications

The bound reframes the project. The question is not "design a filter" but "does the workload slack that any sound filter needs actually exist in C/C++ programs, and is it large enough to pay for the filter's own check?" That is a measurement question, answerable with a counting-only instrumentation build, and the answer is unpublished for C/C++ TSan workloads.

One implementation using C3 exists in this repository (`one_word_filter.md`).
It stores an exact `RawShadow` word in a parallel note while all retained
history can be merged into that word. The first SID mismatch or unmergeable
access transfers the note to ordinary shadow and permanently uses stock TSan
for that cell. The design is sound by construction, but the measurements are
negative outside a narrow private-cell microbenchmark: its hits overlap with a
case stock already handles efficiently, and shared cells pay an additional
lookup. Read it as evidence that the remaining levers are usable, not as a
general recommendation.
