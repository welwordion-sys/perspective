"""Add prototype: encode(a+b=...) -> apply spine add_init -> apply spine
add_finalise -> decode the result spine. Targets the simplest complete chain:
both operands single-bit, no carry (e.g. 0+1)."""
import scratch_add_init2 as S
import spine_addinit_v4 as AI
import spine_finalise_v1 as F
import basic_machinery.encoding as E
import basic_machinery.operations as O
from basic_machinery.graph import PerspectiveGraph, EdgeType, Edge
from basic_machinery.match_view import derive_match_view, match_cut_at_edge

def st(v):
    n = v.bit_length()
    return 'single' if n <= 1 else ('term' if n == 2 else 'cont')

def lb(v):
    return v & 1

def decode_spine(g, lsb):
    val = 0; w = 1; cur = lsb; seen = set()
    while cur is not None:
        if cur in seen: raise ValueError('cycle in spine')
        seen.add(cur)
        bit = [e.target for e in g.edges_from(cur, EdgeType.OPERATIONAL) if e.target != cur]
        b = 1 if (bit and Edge(bit[0], bit[0], EdgeType.STRUCTURAL) in g) else 0
        val += b * w; w <<= 1
        nxt = [e.target for e in g.edges_from(cur, EdgeType.STRUCTURAL) if e.target != cur]
        cur = nxt[0] if nxt else None
    return val

def add_prototype(a: int, b: int, verbose=True):
    expected = a + b
    g = PerspectiveGraph()
    E.encode(g, f"{a}+{b}={expected}")
    if verbose: print(f"encode({a}+{b}={expected}): {g}")

    # --- Step 1: add_init ---
    rule, labels = AI.build_labeled(lb(a), lb(b), st(a), st(b))
    view = derive_match_view(rule.graph2)
    nm = match_cut_at_edge(rule.graph2, g, list(g.nodes), view=view)
    if nm is None:
        return None, "add_init: NO MATCH"
    O._apply_pass(g, nm, rule.graph2)
    if verbose: print(f"after add_init:  {g}")

    carry = (a + b) >= 2  # only valid for single-bit a,b
    if carry:
        return None, "carry case: bit_add/drain not yet built, stopping after add_init"

    # --- Step 2: add_finalise (no-carry path) ---
    frule, flabels = F.build_finalise()
    fview = derive_match_view(frule.graph2)
    fnm = match_cut_at_edge(frule.graph2, g, list(g.nodes), view=fview)
    if fnm is None:
        return None, "add_finalise: NO MATCH"
    O._apply_pass(g, fnm, frule.graph2)
    if verbose: print(f"after finalise:  {g}")

    # --- Decode: find the '=' equality's left operand's target ---
    # parent (=) port -> survivor node (result spine)
    # locate the = node: it's the only finished/unfinished tag whose op-edges
    # now point at small surviving fragments. Simplify: after finalise, the
    # surviving result spine is whatever the '=' left port points at.
    # Find '=' by looking for the unfinished equality tag (size-7 cycle + tail).
    # Cheaper: the left port of '=' is an operational edge from a node with
    # >=2 operational out-edges in a 7/8-node tag region. For this prototype,
    # just decode from EVERY remaining node as lsb and report consistent ones,
    # since only the true result spine will decode without raising.
    candidates = {}
    for n in g.nodes:
        try:
            candidates[n.id] = decode_spine(g, n)
        except Exception:
            pass
    if verbose: print("decode candidates (node_id -> value):", candidates)
    return candidates, None

if __name__ == "__main__":
    for (a, b) in [(0, 1), (1, 0), (0, 0)]:
        print(f"\n=== {a} + {b} ===")
        cands, err = add_prototype(a, b)
        if err:
            print("  ", err)
