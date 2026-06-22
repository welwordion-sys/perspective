"""Regression test for pop_core: validates the two measured properties on the
shared-id carriers (the only available ground truth).
  1. Union-coverage recovers the full intersection-by-id core (incl. island {0,1}).
  2. Feedback reaches full coverage in fewer sequences than blind.
"""
from carriers import CARRIERS
from pop_core import find_core, core_and_deltas

def norm(e):
    s,t,k,ty = e; return (s,t,k,ty)

sets = {nm: set(map(norm, CARRIERS[nm])) for nm in CARRIERS}
true_core = set.intersection(*sets.values())

# 1. union-coverage recovers the full core, including the carry island 0<->1
core, deltas = core_and_deltas(sets)
assert true_core <= core, f"union core missing {len(true_core-core)} edges: {sorted(true_core-core)[:5]}"
assert (0,1,'struct',None) in core and (1,0,'struct',None) in core, \
    "carry island {0,1} not recovered (the case single-path growth missed)"
print(f"union-coverage core: {len(core & true_core)}/{len(true_core)} (incl. carry island) OK")

# 2. feedback beats blind on sequences-to-full-coverage (hardest case: mres)
def seqs_to_full(src, target, use_fb, seed):
    # binary search-ish: grow incrementally, find first N reaching full core
    from pop_core import build_sequence, agreement
    import random, collections
    rng = random.Random(seed)
    tally={'match':collections.Counter(),'stop':collections.Counter()}
    seen=set(); union=set(); made=0; tries=0
    while made<300 and tries<15000:
        tries+=1
        seq=build_sequence(list(src),tally,use_fb,rng)
        if seq in seen: continue
        seen.add(seq); made+=1
        m=agreement(seq,target); union|=set(m)
        for e in m: tally['match'][e]+=1
        for e in seq:
            if e not in target: tally['stop'][e]+=1; break
        if (true_core & union)==true_core:
            return made
    return 999

src='core_mres_multibit'
others=[n for n in sets if n!=src]
target=set.intersection(*(sets[o] for o in others))
blind=sum(seqs_to_full(sets[src],target,False,s) for s in range(5))/5
fb   =sum(seqs_to_full(sets[src],target,True, s) for s in range(5))/5
print(f"mres seqs-to-full: blind {blind:.1f}  feedback {fb:.1f}  ({blind/fb:.1f}x)")
assert fb < blind, "feedback did not beat blind"
assert fb < blind * 0.6, f"feedback gain weaker than expected ({blind/fb:.1f}x)"
print("PASS")
