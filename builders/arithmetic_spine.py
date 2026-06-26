"""
arithmetic_spine.py — rule registration for the spine-encoded addition pipeline.

Rule families and registration order (order matters: finalise before bit_add
before add_init, so the most specific rules get first-match priority):

  F1  add_finalise_1bit       — 1-node result, both operands single-zero
  F2  add_finalise_2bit       — 2-node result (lsb directly adjacent to msb)
  FM  add_finalise_multibit   — 3+-node result (lsb..msb-frontier via external chain)
  AI  add_init (36 variants)  — first step: finished op + both operand LSBs
  BA  bit_add (189 variants)  — middle steps: advance through operand bits
                                 coincident / 2bit / multibit result width
                                 single / term / cont operand state
                                 carry_in 0/1

Guard: skip BA(0,0,c0,single,single,*) — finalise's exclusive state.

Battery status: 0..7 + 0..7, all 64 pass.
"""
from basic_machinery.graph import PerspectiveGraph, EdgeType
from basic_machinery.operations import OperationDefinition, register
from basic_machinery import encoding as E
import scratch_add_init2 as SM
from boundary_decl import ph_all_four
import spine_addinit_v4 as _ai
import spine_bitadd_v2 as _ba
import spine_finalise_v1 as _f1
import spine_finalise_multibit as _fmb

_STATES = ('single', 'term', 'cont')
_RW     = ('coincident', '2bit', 'multibit')


def _build_finalise_2bit() -> OperationDefinition:
    """
    2-node result finalise: r_lsb -S-> r_msb -S-> buffer (both in-window).
    Distinct from finalise_multibit: lsb and msb are directly S-adjacent,
    so the pattern includes that internal edge and uniquely matches 2-node spines.
    """
    p = PerspectiveGraph()
    handle, tag = E.build_operator(p, '+', finished=True)
    cyc = tag.cycle_nodes
    buffer = p.add_node()
    p.add_edge(handle, buffer, EdgeType.STRUCTURAL)
    lzs = p.add_node(); lzl = p.add_node()
    rzs = p.add_node(); rzl = p.add_node()
    p.add_edge(lzs, lzl, EdgeType.OPERATIONAL)
    p.add_edge(rzs, rzl, EdgeType.OPERATIONAL)
    p.add_edge(cyc[0], lzs, EdgeType.OPERATIONAL)
    p.add_edge(cyc[1], rzs, EdgeType.OPERATIONAL)
    r_lsb = p.add_node(); r_msb = p.add_node()
    p.add_edge(r_lsb, r_msb, EdgeType.STRUCTURAL)   # direct adjacency — 2-node discriminator
    p.add_edge(r_msb, buffer, EdgeType.STRUCTURAL)
    p.add_edge(r_lsb, buffer, EdgeType.OPERATIONAL)
    specs = {
        handle: [(EdgeType.OPERATIONAL, 'in')],
        r_lsb:  [(EdgeType.OPERATIONAL, 'out')],
        r_msb:  [(EdgeType.OPERATIONAL, 'out')],
    }
    g2, nm, ph = SM._typed_input_graph(p, specs)
    in_handle = nm[handle]; in_r_lsb = nm[r_lsb]; in_r_msb = nm[r_msb]
    out_lsb = g2.add_node(); out_msb = g2.add_node()
    g2.add_edge(in_handle, out_lsb, EdgeType.OPERATIONAL)
    g2.add_edge(in_r_lsb,  out_lsb, EdgeType.OPERATIONAL)
    g2.add_edge(in_r_msb,  out_msb, EdgeType.OPERATIONAL)
    g2.add_edge(out_lsb, out_msb, EdgeType.STRUCTURAL)
    ph_all_four(g2, out_lsb, ph)
    ph_all_four(g2, out_msb, ph)
    return OperationDefinition(name='add_finalise_2bit', pattern=p, graph2=g2)


def register_all() -> None:
    # Finalise — most specific first
    r, _ = _f1.build_finalise()
    r.name = 'add_finalise_1bit'
    register(r)

    r = _build_finalise_2bit()
    register(r)

    r, _ = _fmb.build_finalise_multibit()
    r.name = 'add_finalise_multibit'
    register(r)

    # add_init (36 variants: 2 lb x 2 rb x 3 ls x 3 rs)
    for lb in (0, 1):
        for rb in (0, 1):
            for ls in _STATES:
                for rs in _STATES:
                    r, _ = _ai.build_labeled(lb, rb, ls, rs)
                    r.name = f'add_init_{lb}{rb}_{ls}_{rs}'
                    register(r)

    # bit_add (189 variants: 7 non-zero combos x 3 ls x 3 rs x 3 rw,
    #          minus the (0,0,c0,ss,*) finalise-exclusive state)
    for lb in (0, 1):
        for rb in (0, 1):
            for ci in (0, 1):
                for ls in _STATES:
                    for rs in _STATES:
                        if lb == 0 and rb == 0 and ci == 0 and ls == 'single' and rs == 'single':
                            continue  # finalise's exclusive state
                        for rw in _RW:
                            r, _ = _ba.build_labeled(lb, rb, ci, ls, rs, rw)
                            r.name = f'bit_add_{lb}{rb}_c{ci}_{ls}_{rs}_{rw}'
                            register(r)


if __name__ == '__main__':
    register_all()
    from basic_machinery.operations import _registry
    print(f"Registered {len(_registry)} rules")
