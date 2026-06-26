"""Spine add_finalise v1 — terminal collapse.

Fires when both operands are exhausted to ZERO and there is NO carry.
Matches: finished operator (ring+anchor) + buffer + two zero-spines each with a
bit-0 leaf (value-matched zero) + result LSB spine (spine ONLY, not its leaf) +
parent-port crossing (parent points operationally at the operator handle).

Transformation: parent port -> result LSB spine. Everything else (operator ring,
anchor, buffer, both zero-spines, both zero-leaves) is consumed. The result spine
survives; its leaf rides along outside the match (result LSB bit is UNREAD).

Result spine is a BOUNDARY node: its (OP,out) to its own leaf leaves the matched
region, so it carries a placeholder crossing to balance its degree.
"""
from basic_machinery.graph import PerspectiveGraph, Node, EdgeType, Edge
from basic_machinery.operations import OperationDefinition
from basic_machinery import encoding as E
from basic_machinery import transition_helpers as S

def _ocm(g, src, tgt):
    return S._marker(g, src, tgt)

def build_finalise():
    labels = {}
    p = PerspectiveGraph()
    # finished operator: ring (size 3 for '+') + anchor, no tail
    handle, tag = E.build_operator(p, '+', finished=True)
    cyc = tag.cycle_nodes
    for i, c in enumerate(cyc): labels[c.id] = f'in_cyc{i}' + ('(handle)' if c is handle else '')
    labels[tag.anchor.id] = 'in_anchor'

    # buffer hangs off the handle (add_init/drain output: handle -S-> buffer)
    buffer = p.add_node(); labels[buffer.id] = 'in_buffer'
    p.add_edge(handle, buffer, EdgeType.STRUCTURAL)

    # two zero operands: zero-spine -OP-> zero-leaf, leaf bit 0 (NO self-loop)
    lz_spine = p.add_node(); lz_leaf = p.add_node()
    rz_spine = p.add_node(); rz_leaf = p.add_node()
    labels[lz_spine.id]='in_left_zero_spine';  labels[lz_leaf.id]='in_left_zero_leaf'
    labels[rz_spine.id]='in_right_zero_spine'; labels[rz_leaf.id]='in_right_zero_leaf'
    p.add_edge(lz_spine, lz_leaf, EdgeType.OPERATIONAL)
    p.add_edge(rz_spine, rz_leaf, EdgeType.OPERATIONAL)
    # operator ports point at the two zero spines
    p.add_edge(cyc[0], lz_spine, EdgeType.OPERATIONAL)
    p.add_edge(cyc[1], rz_spine, EdgeType.OPERATIONAL)

    # result LSB spine (spine ONLY; its leaf is NOT in the pattern).
    r_spine = p.add_node(); labels[r_spine.id] = 'in_result_spine'
    # result spine connects to operator via the buffer (add_init: rspine -S-> buffer)
    p.add_edge(r_spine, buffer, EdgeType.STRUCTURAL)
    # At add_init's firing LSB==MSB (one result bit so far), so the LSB-readback
    # anchor (OP, "I am the LSB, here's the MSB") and the MSB-growth anchor
    # (S, "I am the MSB, here's where to grow") both point at the SAME buffer from
    # the SAME node. Without this OP edge, r_spine's real degree (OP,out:2 — to
    # buffer AND to its own leaf) doesn't match the pattern's (OP,out:1).
    p.add_edge(r_spine, buffer, EdgeType.OPERATIONAL)

    # --- input side via typed crossings ---
    # boundary crossings:
    #   handle: parent points operationally at it -> (OPERATIONAL, in)
    #   result spine: its (OP,out) to its own (unmatched) leaf -> (OPERATIONAL, out)
    specs = {
        handle:  [(EdgeType.OPERATIONAL, 'in')],
        r_spine: [(EdgeType.OPERATIONAL, 'out')],
    }
    g2, nm, ph = S._typed_input_graph(p, specs)

    # Relabel through nm: the labels above are keyed by PATTERN node id, but g2
    # nodes have DIFFERENT ids. Carry each pattern label to its g2 node id and
    # DROP the stale pattern-id keys, so `labels` is uniformly graph2-keyed.
    # (Mixed keyspaces caused phantom mis-identification — never identify nodes
    #  by label alone; labels are display only, keyed to g2 ids.)
    _patlabels = dict(labels)
    labels = {}
    for old in p.nodes:
        if old.id in _patlabels and old in nm:
            labels[nm[old].id] = _patlabels[old.id]
    if ph is not None:
        labels[ph.id] = 'placeholder'

    in_handle  = nm[handle]
    in_rspine  = nm[r_spine]

    # --- output side ---
    # The result spine SURVIVES IN PLACE; the operator handle MERGES INTO IT, so the
    # parent's operational pointer (parent -OP-> handle) gets rewired by the merge
    # logic onto the result spine (parent -OP-> result spine). That IS the
    # finalise behaviour: result attaches to the PARENT (finalise_two_methods),
    # achieved by redirecting the parent's existing pointer onto the surviving result.
    out_rspine = g2.add_node(); labels[out_rspine.id] = 'out_result_spine'
    # result spine maps to the (single) output node -> survives, keeps its identity.
    g2.add_edge(in_rspine, out_rspine, EdgeType.OPERATIONAL)
    # handle maps to the SAME output node -> follow_mapping records a merge
    # (handle's real node merges into the result spine's real node); the merge
    # rewires handle's incoming parent operational edge onto the result spine.
    g2.add_edge(in_handle, out_rspine, EdgeType.OPERATIONAL)
    # surviving result spine keeps its boundary placeholder in ALL FOUR cases so
    # four-case-4c preserves every external crossing — crucially its OPERATIONAL
    # external to its (unmatched) result-bit leaf, which struct-only declaration
    # would drop (that was the dropped-result-bit bug).
    from boundary_decl import ph_all_four
    ph_all_four(g2, out_rspine, ph)

    # Everything else (operator ring, anchor, buffer, both zero spines/leaves) has
    # NO outgoing mapping edge -> consumed/deleted by _apply_pass. Their stale
    # structural crossings into the survivor are removed by symmetric step-4c.

    return OperationDefinition(name='add_finalise', pattern=p, graph2=g2), labels
