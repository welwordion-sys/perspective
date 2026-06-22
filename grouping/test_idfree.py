"""Adversarial test: does pop_core recover the core between a graph and a
RELABELED copy (same structure, disjoint node IDs)? This is the id-free case
the method exists for. Honest check: it should work; if it returns ~0, the
matching step secretly depends on node IDs."""
import sys; # run from package dir
from carriers import CARRIERS
from pop_core import find_core

def norm(e):
    s,t,k,ty=e; return (s,t,k,ty)

base = set(map(norm, CARRIERS['core_tt_2bit']))

# relabel: shift every node id by +1000 (disjoint from original)
def relabel(edges, off=1000):
    return {(s+off, t+off, k, ty) for (s,t,k,ty) in edges}
relabeled = relabel(base)

print("base edges:", len(base), " relabeled edges:", len(relabeled))
print("raw edge-tuple overlap (should be 0 — disjoint ids):", len(base & relabeled))

# Run pop_core: match base against relabeled
core, tally, n = find_core(list(base), relabeled, n_sequences=200)
print(f"\npop_core core (base vs relabeled): {len(core)} edges")
print("VERDICT:", "id-DEPENDENT (found ~nothing)" if len(core)==0
      else f"recovered {len(core)} — but check if meaningful")
