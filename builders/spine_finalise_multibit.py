"""Spine add_finalise multibit — terminal collapse for N-bit (N>=3) result spine.

Fires when both operands are exhausted to ZERO and the result spine has at least
3 nodes (lsb ... msb-frontier ... buffer). The two spine nodes in-window are:
  r_lsb: the result LSB — holds the OP readback anchor to buffer, and has a
         structural successor OUTSIDE the window (chain continues toward MSB).
  r_msb: the MSB-frontier — the last spine node before buffer, reached from
         below via a structural chain that enters from outside the window.

Neither r_lsb nor r_msb is directly connected to each other in the pattern —
the chain between them is entirely outside the match window.

Transformation:
  - handle merges into out_lsb (= operator pointer rewired onto lsb)
  - in_r_lsb real node preserved as out_r_lsb_pass (its S-out chain is external
    and must survive; ph_all_four declares the (S,out) crossing)
  - out_lsb -S-> out_pass: handle now leads into the existing spine chain
  - out_pass -S-> [external chain] -S-> msb-frontier (preserved externally)
  - out_msb survives with all four crossings
"""
from basic_machinery.graph import PerspectiveGraph, Node, EdgeType, Edge
from basic_machinery.operations import OperationDefinition
from basic_machinery import encoding as E
import scratch_add_init2 as S
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

    # Two result spine nodes — NOT connected to each other in the pattern.
    # r_lsb: anchored to buffer via OP (readback). S-out exits the window.
    # r_msb: anchored to buffer via S. S-in enters from the chain outside.
    r_lsb = p.add_node(); labels[r_lsb.id] = 'in_result_spine(lsb)'
    r_msb = p.add_node(); labels[r_msb.id] = 'in_result_spine(msb)'
    p.add_edge(r_lsb, buffer, EdgeType.OPERATIONAL)   # lsb -OP-> buffer (readback)
    p.add_edge(r_msb, buffer, EdgeType.STRUCTURAL)    # msb -S-> buffer

    specs = {
        handle: [(EdgeType.OPERATIONAL, 'in')],
        r_lsb:  [(EdgeType.OPERATIONAL, 'out'), (EdgeType.STRUCTURAL, 'out')],
        r_msb:  [(EdgeType.OPERATIONAL, 'out'), (EdgeType.STRUCTURAL, 'in')],
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

    out_lsb  = g2.add_node(); labels[out_lsb.id]  = 'out_result_spine(lsb)'
    out_msb  = g2.add_node(); labels[out_msb.id]  = 'out_result_spine(msb)'
    out_pass = g2.add_node(); labels[out_pass.id] = 'out_r_lsb_pass'

    # handle merges into out_lsb (= operator's OP-in is preserved via handle's boundary grab)
    # in_r_lsb maps to out_pass (preserves the lsb real node and its S-out chain)
    # in_r_msb maps to out_msb
    g2.add_edge(in_handle,  out_lsb,  EdgeType.OPERATIONAL)
    g2.add_edge(in_r_lsb,  out_pass, EdgeType.OPERATIONAL)
    g2.add_edge(in_r_msb,  out_msb,  EdgeType.OPERATIONAL)

    # out_lsb -S-> out_pass: connect handle to the lsb position
    # out_pass's boundary grab will preserve its (S,out) to the first external chain node
    g2.add_edge(out_lsb, out_pass, EdgeType.STRUCTURAL)

    # No direct out_pass->out_msb edge: the external chain connects them.
    # Both survivors keep all four boundary crossings.
    ph_all_four(g2, out_lsb, ph)
    ph_all_four(g2, out_pass, ph)  # preserves out_pass's S-out to the external chain
    ph_all_four(g2, out_msb, ph)

    return OperationDefinition(name='add_finalise_multibit', pattern=p, graph2=g2), labels
