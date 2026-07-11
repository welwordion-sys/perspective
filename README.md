# Perspective

Sorry this was Ai drafted and is still not completely right

**A system that explores representation space explicitly, instead of learning a
representation as a byproduct of optimization — with arithmetic as the current
proving ground, not the goal.**

Most machine learning treats representation as something a model backs into while
optimizing for a task. Perspective inverts that: representation *is* the object
being built and searched over. Everything else — including the arithmetic engine
that currently lives in this repo — exists to test whether a given representation
holds up.

---

## The core idea

A number isn't stored as an integer here — it's encoded as a small graph: a chain of
nodes (a **spine**) ending in leaves that carry bit values. Two numbers linked at an
operator node form the input to an operation. Computing `a + b` doesn't mean
evaluating anything in the traditional sense — it means searching the graph for a
**subgraph isomorphism** (via a VF2-based matcher) that matches the left-hand side of
some known rule, then rewriting that region into the rule's right-hand side. Do this
enough times and the graph settles into a new spine: the result.

Arithmetic is the **test domain**, not the point. The original test domain was
actually MNIST digit recognition — arithmetic replaced it because it has a
known-correct ground truth you can check a representation against unambiguously.
Addition is built and validated (213 confirmed `bit_add` rules); subtraction is under
active construction.

## Why this way: the actual target

The bigger design is a **Representation Space Traversal Architecture**: two systems
sharing a library. A *Data Transformation System* — the **traveler** — explores
representation space directly, growing structure and looking for matches rather than
optimizing a fixed objective. A *Logic Rewriting System* improves the traveler's own
rules over time via a genetic algorithm operating on rule graphs, not on data.

The exploration model (internally called the **Quantum Traveler**) doesn't search
for *a* path — it grows a population of structures in parallel, branching like moss
through representation space. Branches that explode structurally get pruned; branches
that dead-end just stop, cheaply, no backtracking; a branch that reaches the target
cleanly exits and becomes a strong fitness signal for the rules that got it there.

The endpoint vision is self-similar: a **traveler** explores representation space, an
**overseer** manages a population of travelers and reads their paths as data to
direct the population, a **senior overseer** does the same one level up for
overseers, and a **human** holds a deliberately non-automated threshold gate — the
system doesn't get to decide for itself when it's ready to advance. The same graph
matching and rewriting machinery runs at every one of those levels.

## Rules that write rules

The rule library for arithmetic is hand-built today. The design target is a genetic
algorithm that generates new rules itself — recombining a donor rule's input pattern
with another donor's output pattern, then repairing the connecting mapping between
them by mutation (mutation is a repair operator here, not a rival generator). Its
search target, in the arithmetic domain, is solving equations down to `x = number`,
with commutation and rearrangement as required waypoints, not the objective itself.

Legality for a GA-generated move splits by reversibility. An *irreversible* (upward)
move has to preserve correctness against a fixed, known-correct arithmetic reducer.
A *reversible* (sideways) move only has to prove it's invertible — cheaper, and it's
allowed to produce encodings the reducer can't even process, because sideways moves
are exactly how alternate representations get explored. Sideways moves don't make
direct progress toward a solution, so they're scored indirectly: rewind the sideways
step after a following upward move, and score the combined path in the reducer — this
is exact whenever the sideways move's inverse still applies after the upward step.

Perspective's reversibility classifier — which determines whether a rule can run
backwards as a valid rule in its own right, purely from what crosses its boundary —
is what makes the "sideways" half of that split checkable at all, rather than assumed.

## What's built vs. what's designed

| Area | State |
|---|---|
| Addition (spine graphs, bit rules) | Built and validated — 213 confirmed `bit_add` rules |
| Subtraction | Init-stage rules validated; full bit-level build in progress |
| Reversibility classifier | Designed and implemented; confirmed against a real production rule |
| GA architecture (search target, legality, generator, recombination, fitness) | Designed (five-node model); implementation not started |
| Traveler / overseer / senior-overseer levels | Long-term architecture; not built |

## The origin story

Perspective didn't start as an arithmetic engine. It started with an artificial-life
game — hand-crafting organisms, including their neural networks, by hand. Eyes took
input from four directions, and the genetic representation let axons be coded with
rotational symmetry across all four — but not dendrites. A technique for tunable
excitation levels was discovered by looping tendrils back on themselves, but because
the directional asymmetry had to be encoded separately from the rest of the
structure, the design broke easily under mutation.

That was the real discovery, and it had nothing to do with arithmetic: **the GA
didn't fail to find the solution. A human found it, and the GA couldn't preserve
it.** Representation determines what a genetic algorithm can *maintain*, not just
what it can search for. A bad representation doesn't just search slowly — it
actively destroys solutions that exploit structure the representation itself
doesn't respect.

Perspective is the answer to that problem, generalized. Arithmetic is the proving
ground, not the point: it's a domain with a known-correct ground truth, so you can
tell, unambiguously, whether a representation choice holds up. Every encoding
decision in this repo — unique cycle sizes per operator, uniform anchors regardless
of state, marker chains instead of overloaded edges — exists to produce a
representation where hand-crafted, correct-by-construction rules are
*mutation-stable by design*. The goal is a substrate where a GA, once it's finally
turned loose on it, finds solutions the way a human did — and, unlike that first
alife game, doesn't tear them apart the moment it starts mutating.

---

*Perspective is designed and built by Sven ([welwordion-sys](https://github.com/welwordion-sys)).
Design decisions and rationale are tracked in a project knowledge base alongside the code.*
