"""Spine add_finalise multibit — terminal collapse for N-bit (N>=3) result spine.

Scope: 3+-bit results only (the 2-bit case is add_finalise_2bit; the 1-bit case
is add_finalise_1bit). Fires when both operands are exhausted to ZERO and the
result spine has at least 3 nodes (lsb ... chain ... msb-frontier ... buffer).

Design source: graph-channel graph `finalise_multibit` (id 22222222…, Sven-
authored). Key mechanic differs from the earlier (buggy) three-node passthrough:

  MERGE: the operator handle AND the result LSB spine node map to the SAME
  output node (out_lsb). The handle carries the parent/'=' operational pointer;
  merging it into the LSB rewires that pointer onto the surviving result LSB.

  r_lsb (result LSB):
    - op -> buffer  : the buffer readback. CONSUMED (no mapping, no crossing).
    - leaf          : preserved as an external (OPERATIONAL, out) crossing.
    - chain         : preserved as an external (STRUCTURAL, out) crossing —
                      spine grows LSB->MSB, so the LSB's chain edge is OUTBOUND
                      toward the higher bits (the middle bits live outside the
                      window and survive on this crossing).

  r_msb (MSB-frontier):
    - leaf matched INSIDE the window as a 1-bit (structural self-loop = value 1).
    - msb -S-> buffer, with (S,in) from the external chain.
    - maps to out_msb, preserved with full boundary crossings.
"""
from basic_machinery.graph import PerspectiveGraph, Node, EdgeType, Edge
from basic_machinery.operations import OperationDefinition
from basic_machinery import encoding as E
from basic_machinery import transition_helpers as S
from boundary_decl import ph_all_four


def build_finalise_multibit():
    labels = {}
    p = PerspectiveGraph()

    handle, tag = E.build_operator(p, '+', finished=True)
    cyc = tag.cycle_nodes
    for i, c in enumerate(cyc):
        labels[c.id] = f'in_cyc{i}' + ('(handle)' if c is handle else '')
    labels[tag.anchor.id] = 'in_anchor'

    buffer = p.add_node(); labels[buffer.id] = 'in_buffer'
    p.add_edge(handle, buffer, EdgeType.STRUCTURAL)

    lz_spine = p.add_node(); lz_leaf = p.add_node()
    rz_spine = p.add_node(); rz_leaf = p.add_node()
    labels[lz_spine.id] = 'in_left_zero_spine'; labels[lz_leaf.id] = 'in_left_zero_leaf'
    labels[rz_spine.id] = 'in_right_zero_spine'; labels[rz_leaf.id] = 'in_right_zero_leaf'
    p.add_edge(lz_spine, lz_leaf, EdgeType.OPERATIONAL)
    p.add_edge(rz_spine, rz_leaf, EdgeType.OPERATIONAL)
    p.add_edge(cyc[0], lz_spine, EdgeType.OPERATIONAL)
    p.add_edge(cyc[1], rz_spine, EdgeType.OPERATIONAL)

    # Two result spine nodes — NOT connected to each other in the pattern; the
    # middle chain between them is external.
    r_lsb = p.add_node(); labels[r_lsb.id] = 'in_result_spine(lsb)'
    r_msb = p.add_node(); labels[r_msb.id] = 'in_result_spine(msb)'
    p.add_edge(r_lsb, buffer, EdgeType.OPERATIONAL)   # lsb -OP-> buffer (readback; consumed)
    p.add_edge(r_msb, buffer, EdgeType.STRUCTURAL)    # msb -S-> buffer
    # MSB leaf is NOT in the pattern; its (OP,out) to its own leaf is an external
    # crossing, so the real leaf survives the rewrite untouched (same shape as the
    # verified F2 fix). This preserves the MSB bit value without consuming it.

    specs = {
        handle: [(EdgeType.OPERATIONAL, 'in')],          # parent/'=' pointer
        r_lsb:  [(EdgeType.OPERATIONAL, 'out'),          # LSB leaf — preserved
                 (EdgeType.STRUCTURAL, 'out')],          # LSB chain (outbound to MSB) — preserved
        r_msb:  [(EdgeType.STRUCTURAL, 'in'),            # chain entering MSB from outside
                 (EdgeType.OPERATIONAL, 'out')],         # MSB leaf — preserved via crossing
        # r_lsb op->buffer readback is consumed (not crossed).
    }
    g2, nm, ph = S._typed_input_graph(p, specs)

    _patlabels = dict(labels)
    labels = {}
    for old in p.nodes:
        if old.id in _patlabels and old in nm:
            labels[nm[old].id] = _patlabels[old.id]
    if ph is not None:
        labels[ph.id] = 'placeholder'

    in_handle = nm[handle]
    in_r_lsb  = nm[r_lsb]
    in_r_msb  = nm[r_msb]

    out_lsb = g2.add_node(); labels[out_lsb.id] = 'out_result_spine(lsb)'
    out_msb = g2.add_node(); labels[out_msb.id] = 'out_result_spine(msb)'

    # MERGE: handle AND r_lsb both map to out_lsb. The handle's parent pointer is
    # inherited by the surviving LSB result node; the LSB's leaf and chain are
    # carried by its boundary crossings.
    g2.add_edge(in_handle, out_lsb, EdgeType.OPERATIONAL)
    g2.add_edge(in_r_lsb,  out_lsb, EdgeType.OPERATIONAL)
    g2.add_edge(in_r_msb,  out_msb, EdgeType.OPERATIONAL)

    # Both survivors keep all four boundary crossings (the LSB's op-out leaf and
    # struct-out chain, the MSB's frontier crossings).
    ph_all_four(g2, out_lsb, ph)
    ph_all_four(g2, out_msb, ph)

    return OperationDefinition(name='add_finalise_multibit', pattern=p, graph2=g2), labels
