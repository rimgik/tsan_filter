# Parallel Meta-Shadow Filtering for ThreadSanitizer

## Objective

ThreadSanitizer records recent accesses in shadow memory and compares each new
access against that history. This project asks whether accesses to memory that
still has a compact, single-thread history can avoid the normal four-slot
shadow path.

## Implemented MVP

The MVP reserves a parallel note region with one 32-bit word per eight bytes of
application memory. Allocation interceptors initialise eligible heap cells with
the allocating thread's access state. The runtime attempts to merge later
accesses into the note only when the result is an exact representation of both
histories.

The LLVM TSan pass optionally emits an inline lookup before ordinary aligned
loads and stores. If the note already covers the access, the generated code
skips the runtime callback. Otherwise, the callback updates the note or hands
its history to standard TSan shadow memory.

## Soundness requirement

The note cannot simply remember an owner SID. At the first foreign access, TSan
must still compare against the owner's earlier access. The exact design keeps
that earlier shadow word and transfers it to normal shadow memory before
continuing. A cell leaves the filtered state whenever its history needs more
than one exact word.

## Evaluation questions

1. How many instrumented accesses are absorbed without entering the runtime?
2. Does the smaller note working set offset the extra lookup and branches?
3. How much resident and virtual memory does the parallel mapping add?
4. Which private-data patterns benefit, and how quickly do real workloads
   transition to the normal TSan path?
5. Are race reports identical to stock TSan across regression and stress tests?

## Current result

The exact design demonstrates a narrow performance opportunity but does not
beat stock TSan on the tested real-world and proxy workloads. The parallel note
also increases memory use. These results motivate treating exact filtering as
a measured design boundary rather than assuming ownership metadata is free.

An approximate SID-only variant is a possible follow-up experiment. It could
avoid creating normal shadow during the exclusive phase and trade memory and
speed for delayed detection, but it must be presented as an approximate race
detector: it can miss the first conflict at ownership transition.
