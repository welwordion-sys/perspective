# Perspective

**What if representation weren't a byproduct of learning, but the thing being
built?**

Neural networks learn representations implicitly — buried in weights, shaped as a
side effect of optimizing something else, unreadable from the outside and fragile
under change. Perspective is an attempt to do the opposite: make representation an
explicit, inspectable structure — a graph — and make *traversal of representation
space* the primary mechanism, not an emergent accident.

---

## The founding problem

Perspective began with an artificial-life game — hand-crafting organisms, including
their neural networks. Eyes took input from four directions; the genetic
representation allowed axons to be coded with rotational symmetry across all four,
but not dendrites. A technique for tunable excitation levels was discovered by
looping tendrils back on themselves — but because the directional asymmetry had to
be encoded separately from the rest of the structure, the design broke easily under
mutation.

That was the real discovery: **the genetic algorithm didn't fail to find the
solution. A human found it, and the GA couldn't keep it.** Representation determines
what evolution can *maintain*, not just what it can search for. A bad representation
doesn't merely search slowly — it actively destroys solutions that exploit structure
the representation itself doesn't respect.

Perspective is the generalized answer to that problem: build a substrate where
knowledge is encoded so that what is found — by a human or by the system — survives
being operated on.

## The architecture

Everything in Perspective is a graph, and everything that happens to a graph is a
**rewrite**: match a pattern (by subgraph isomorphism), transform it by rule. That
uniformity is the load-bearing choice — data, the rules that transform data, and
eventually the histories of those transformations all live in the same formalism,
so the same machinery can operate on all of them.

Two systems share a library:

- **The traveler** (Data Transformation System) explores representation space
  directly. It doesn't optimize toward a fixed objective — it *grows*: a population
  of structures branching in parallel, like moss, through the space of possible
  representations. Branches that structurally explode get pruned. Branches that
  dead-end simply stop — cheap, no backtracking. A branch that reaches its target
  exits early, and its path becomes a strong fitness signal for the rules that
  produced it. The system is not searching for a path; it is growing until
  something matches.

- **The rewriter** (Logic Rewriting System) improves the traveler's own rules. Rules
  are first-class graph objects — they can be inspected, recombined, and mutated by
  a genetic algorithm operating on rule structure itself. Moves through
  representation space split into two kinds: *upward* moves that lose information
  and must preserve correctness, and *sideways* moves — reversible re-encodings —
  that owe correctness nothing and only have to prove they can be undone. Sideways
  moves are how alternate representations get explored at all; reversibility is
  what makes them safe.

## The endpoint

The mature form is self-similar. A **traveler** explores representation space. An
**overseer** manages a population of travelers, reading their travel paths *as
data* — with the same matching machinery — to direct the population. A **senior
overseer** does the same one level up, managing overseers and searching for its own
successor. And a **human** holds a deliberately non-automated threshold gate: the
system never decides for itself when it is ready to advance.

Travel paths are first-class data, encoded in the same formalism as everything
else. That is why the levels can stack: the input at every level is always graphs
and transition graphs, so one mechanism serves every scale.

## Where it stands

The substrate has to be proven before anything can be trusted to grow on it. The
current proving ground is deliberately humble: domains with known-correct ground
truth — arithmetic, for instance — where you can tell *unambiguously* whether a
representation choice holds up, whether a hand-crafted rule is
correct-by-construction, and whether it stays correct when operated on. Every
encoding decision at this stage exists to make found solutions mutation-stable by
design — so that when the system finally does its own finding, it doesn't tear its
discoveries apart the way that first alife game did.

---

*Perspective is designed and built by Sven
([welwordion-sys](https://github.com/welwordion-sys)). Design decisions and their
rationale are tracked in a project knowledge base alongside the code.*
