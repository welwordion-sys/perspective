# Perspective

**Arithmetic as structure, not calculation.**

Perspective is a graph-rewriting system that performs arithmetic by treating numbers
as *shapes* rather than values to be crunched. A number isn't stored as an integer —
it's encoded as a small graph, and computing `a + b` means finding a pattern inside
that graph and rewriting it into another one. Addition, subtraction, and eventually
whatever a genetic algorithm invents on top of them, are all done this way: not by
running an ALU, but by recognizing structure and transforming it.

---

## The core idea

Take a number. Instead of `7`, picture a short chain of nodes — a **spine** — ending
in leaves that carry bit values. Two numbers side by side, linked at an operator node,
form the input to an operation. To *compute*, Perspective doesn't evaluate anything
in the traditional sense — it searches the graph for a **subgraph isomorphism**: a
region that matches the left-hand side of some known rule. When it finds one, it
rewrites that region into the rule's right-hand side. Do this enough times, in the
right order, and the graph settles into a new spine — the result.

This is done with a VF2-based matcher (the classic algorithm for subgraph
isomorphism) and a library of hand-authored rewrite rules — currently a solid,
validated set for addition, with subtraction under active construction using a
four-phase borrow mechanism.

Nothing about this requires numbers to be small, or the rules to be exhaustive by
hand forever — which is the point of the next layer.

## Why graphs

Encoding arithmetic as graph structure buys something a normal calculator doesn't
have: **rules are objects**. A rule is just a pair of graphs (before/after) plus a
mapping between them. That means rules can be inspected, compared, composed,
mutated, and — crucially — checked for a structural property most calculators never
have to think about: **is this operation reversible?**

Perspective has a reversibility classifier that takes a rule and determines whether
it can be run backwards as a valid rule in its own right, purely from the structure
of what crosses the rule's boundary (which nodes are born, which die, which edges
survive). This isn't a convention bolted on — it falls out of the graph structure
itself. A rule earns "reversible" or it doesn't, and the classifier can prove which.

## Where it's going: rules that write rules

The rule library today is hand-built. The design target is a **genetic algorithm**
that generates new rules on its own — recombining pieces of existing rules,
mutating the connective structure between them, and keeping what survives fitness
checks against a known-correct arithmetic reducer. The GA's search target is solving
equations down to the form `x = number`, treating commutation and rearrangement as
waypoints, not special cases.

The reversibility work matters directly here: legality for a GA-generated move
splits along exactly this line. An *irreversible* (upward, value-changing) move has
to preserve correctness under the reducer. A *reversible* (sideways) move only has
to prove it's invertible — a much cheaper and more local check. Reversibility isn't
a side feature; it's the hinge the whole generative side of the project turns on.

## What's built vs. what's designed

| Area | State |
|---|---|
| Addition (spine graphs, bit rules) | Built and validated — 213 confirmed `bit_add` rules |
| Subtraction | Init-stage rules validated; full bit-level build in progress |
| Reversibility classifier | Designed and implemented; confirmed against a real production rule |
| Genetic algorithm | Architecture designed (five-node model); implementation not started |

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
