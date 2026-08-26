# The Minimal-State Problem for Ownership Filtering in TSan v3

This note formalises the question the whole project turns on: when a memory region does not currently need race checking, what is the least state we must maintain so that, once it does, we detect everything stock TSan v3 would have detected? It states the problem, proves a worst-case lower bound, and lists the solution space the bound leaves open.

## 1. Problem statement

Fix one 8-byte cell owned by a single thread $T$ with slot id $s$ (the single-owner phase; atomics excluded, they always fall back). An **access** is a triple $a = (m, t, e)$: byte mask $m \subseteq \{0,\dots,7\}$, type $t \in \{\mathrm{read}, \mathrm{write}\}$, epoch $e$; $T$'s epochs are non-decreasing. A **history** $H$ is the finite sequence of $T$'s accesses during the phase. A **probe** $B = (m_B, t_B, c)$ models the first foreign access: $c = \mathrm{clock}_B.\mathrm{Get}(s)$, the prober's view of $T$'s clock.

The race predicate, exactly as TSan's `CheckRaces` computes it per word:

$$\mathit{races}(H, B) \iff \exists\, a=(m,t,e) \in H :\;\; m \cap m_B \neq \emptyset \;\wedge\; (t = \mathrm{w} \vee t_B = \mathrm{w}) \;\wedge\; c < e$$

Let $\mathit{stock}(H) \subseteq H$ be the (at most 4) words TSan's cell actually holds after $H$ (after `ContainsSameAccess` dedup, the same-sid domination overwrite, and eviction), and $\mathit{races}_{\mathit{stock}}$ the same predicate over $\mathit{stock}(H)$.

A **filter** keeps state $S(H)$ and must answer $D(S(H), B)$ for every possible probe. **Parity** requires $D(S(H), B) = \mathit{races}_{\mathit{stock}}(H, B)$ for all $H, B$: no false positive stock would not raise, no miss stock would catch. (Answering the full $\mathit{races}(H, \cdot)$ is also acceptable — it is a superset of stock, like the victim slot — but no cheaper, as shown next.)

The problem: minimise the cost of $S$ — its size, and the memory traffic of maintaining it — subject to parity.

## 2. The exact sufficient statistic

**Cover lemma.** For same-thread accesses, $a$ covers $a'$ (removing $a'$ never changes $\mathit{races}(H, \cdot)$) iff

$$m \supseteq m' \;\wedge\; e \geq e' \;\wedge\; (t' = \mathrm{r} \vee t = \mathrm{w}).$$

*Proof.* ($\Leftarrow$) Any probe racing with $a'$ has $c < e' \leq e$, intersects $m' \subseteq m$, and conflicts with $a$: if $t' = \mathrm{w}$ then $t_B$ may be a read, but $t = \mathrm{w}$ conflicts regardless; if $t' = \mathrm{r}$ the probe must be a write, conflicting with any $t$. So $a$ fires whenever $a'$ would. ($\Rightarrow$) If $m \not\supseteq m'$, probe the uncovered byte; if $e < e'$, probe with $c \in [e, e')$; if $t' = \mathrm{w} \wedge t = \mathrm{r}$, probe with a read: each yields a race $a'$ detects and $a$ does not. $\blacksquare$

Consequently $\mathit{races}(H, \cdot)$ is determined exactly by the **non-covered residue** of $H$, canonically: per byte $b$, the latest write epoch $e_w(b)$, plus the latest read epoch $e_r(b)$ when $e_r(b) > e_w(b)$. Two additional lossless moves: equal-epoch same-type accesses merge by mask union, and full-resolution epochs are required (probes take any $c$). Worst case the residue is $8 \times 2$ epochs $\times$ 14 bits $\approx$ 28 bytes — **larger than the 16-byte shadow cell the filter was meant to avoid touching.**

## 3. The lower bound

**Theorem (no uniform compression).** Any parity-preserving filter must, in the worst case, hold state informationally equivalent to stock's full cell.

*Proof.* Construct $H^*$: four accesses $w_1, \dots, w_4$ with pairwise disjoint masks $m_1, \dots, m_4$, strictly increasing epochs $e_1 < \dots < e_4$, types chosen freely (the cover lemma requires mask containment, which disjointness already forbids, so no $w_i$ covers another). Stock retains all four: four slots, none dominated, no fifth access to force eviction. For each $i$ and each candidate value of $(m_i, t_i, e_i)$, there is a probe that isolates it: a probe with mask $\subseteq m_i$ intersects only $w_i$, its answer flips exactly at $c = e_i$, and a read probe versus a write probe distinguishes $t_i$ (read/read is exempt). So two histories differing in any word's mask, type, or epoch give different answer functions $\mathit{races}_{\mathit{stock}}(H, \cdot)$, and $S$ must distinguish them. Hence $S$ determines $(m_i, t_i, e_i)$ for all four words. $\blacksquare$

**Corollary 1.** Any fixed summary smaller than the cell — in particular every scalar-tag scheme of the v0.2 family, with or without extra epochs — violates parity on some program. v0.2 was not under-engineered; it was impossible.

**Corollary 2.** The bound is worst-case. It leaves exactly two levers: (a) **expected-case compression** — when the residue of the phase so far is a single word, 4 bytes is exact; (b) **relocation** — the residue may be split as one hot word in a dense side cell plus the remainder spilled into the ordinary shadow, preserving total information while changing which cache line the common case touches. It forbids nothing about *where* state lives, only how little of it may exist.

**Corollary 3.** For a region that never leaves the single-owner phase, all retained state is insurance that is never claimed. Zero cost is achievable only by a static proof of non-escape (the Paznikov line); a runtime filter's floor is the insurance premium — with relocation, a 4-byte line instead of a 16-byte one.

## 4. Solution space under the bound

**S1 — Write-back cell (levers a+b together).** The meta cell holds one verbatim `RawShadow` word. On each owner access apply the cover lemma: covered, overwrite; equal-epoch same-type, mask union; otherwise flush the old word to real shadow, then cache the new one. On foreign access, flush and hand over to stock forever. Exact by Section 2; traffic cost = 4-byte line in the common case, stock-plus-$\varepsilon$ in the worst case. The open empirical question, and the headline number for the counting build: the fraction of single-owner accesses whose residue stays at one word. Note the cover rule is stock's own domination rule — the contribution is placement, not logic.

**S2 — Victim slot (spend the cell after handover).** Post-handover the cell receives words evicted from the 4-word scan, consulted on the slow path only. Sound by construction (only adds history stock drops); strictly-better-than-stock completeness at zero hot-path cost; addresses the eviction incompleteness that TMon (2026) attacks with hardware.

**S3 — Wider cell (u64).** Two cached words absorb read/write alternation on different bytes before any flush; doubles the premium to 8 bytes per 8. Only justified if the counting build shows residues of size 2 are common while size 3 or more is rare.

**S4 — Relaxations (rejected).** Sampling and postmortem approaches beat the bound by weakening parity or moving analysis offline; both abandon the property this project is defined by.

## 5. What remains open

The bound settles the design shape; measurement settles the value. Required numbers, all obtainable from a counting-only build on a Paznikov-enabled baseline: residue-size distribution over single-owner phases (decides S1 vs S3 vs nothing); the exclusive / read-shared / write-shared access breakdown for C/C++ (unpublished, a contribution in itself); overlap between would-be cache hits and stock's `ContainsSameAccess` hits; cache-miss profile across a working-set sweep (tests the relocation claim). One theoretical loose end: Section 3 treats the single-owner phase; the read-shared phase (multiple reader sids) admits the same style of bound — a reader set of $k$ sids needs $k$ words — and should be written out to justify excluding read-shared from elision. Related minimality precedent to cite: Charron-Bost (1991) proved vector clocks need $n$ components to characterise causality among $n$ processes; this note's theorem is a per-location, per-detector analogue.
