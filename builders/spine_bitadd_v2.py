"""Spine bit_add v1 — middle addition step, 1-RESULT-BIT variant.

Fires on the state add_init leaves (one result bit, MSB==LSB coincident):
  PATTERN (plain edges; _typed_input_graph encodes input markers once):
    finished operator: ring(cyc) + anchor, no tail
    handle -S-> buffer
    result_spine -OP-> result_leaf        (existing LSB bit; result_leaf is a
                                           value-bearing BOUNDARY node, OUT of the
                                           window -> value-agnostic, preserved)
    result_spine -S->  buffer             (MSB-growth)
    result_spine -OP-> buffer             (coincident LSB-readback anchor; INTERNAL)
    [carry_in] carry_a -S-> result_spine ; carry_a<->carry_b   (carry on SPINE,
                                           STRUCTURAL incoming; +1 (S,in) discriminates.
                                           Spine OP-out is reserved for the bit pointer,
                                           so carry uses the empty (S,in) channel. See
                                           spine_carry_attaches_leaf_structural rev 2026-06-16.)
    per side: cyc[port] -OP-> operand_spine -OP-> operand_leaf (current bit),
              operand state single/term/cont as in add_init.

  REWRITE: insert born (new_spine,new_leaf) between result_spine and buffer:
    result_spine -S-> new_spine           (redirect of result_spine -S-> buffer)
    new_spine    -S-> buffer
    new_spine    -OP-> new_leaf           (new MSB bit = this step's result_bit)
    drop result_spine -OP-> buffer        (coincident anchor consumed)
    result_spine -OP-> result_leaf        (preserved; result_leaf rides outside match)
    operand ports advance to successors (single -> implicit zero spine+leaf)
    [carry_out] carry_a -S-> new_spine ; carry_a<->carry_b   (STRUCTURAL incoming, same convention)
"""
from basic_machinery.graph import PerspectiveGraph, Node, EdgeType, Edge
from basic_machinery.operations import OperationDefinition
from basic_machinery import encoding as E
from basic_machinery import transition_helpers as S

OUT, IN = 'out', 'in'

def _ocm(g, src, tgt):
    return S._marker(g, src, tgt)

def _ph_both(g, node, ph):
    # MIGRATED to four-case: all four (type,direction) preserve cases.
    from boundary_decl import ph_all_four
    ph_all_four(g, node, ph)


def build_labeled(left_bit, right_bit, carry_in, left_state, right_state, in_result_width='coincident'):
    total = left_bit + right_bit + carry_in
    result_bit = total % 2
    carry_out = total >= 2
    labels = {}
    left_single = (left_state == 'single'); right_single = (right_state == 'single')

    # ---------------- PATTERN ----------------
    p = PerspectiveGraph()
    handle, tag = E.build_operator(p, '+', finished=True)
    cyc = tag.cycle_nodes

    succ_specs = {}
    def operand(bit, state, side):
        spine = p.add_node(); leaf = p.add_node()
        p.add_edge(spine, leaf, EdgeType.OPERATIONAL)
        if bit == 1: p.add_edge(leaf, leaf, EdgeType.STRUCTURAL)
        labels[spine.id] = f'in_{side}_spine'; labels[leaf.id] = f'in_{side}_leaf'
        succ = None
        if state != 'single':
            succ = p.add_node(); p.add_edge(spine, succ, EdgeType.STRUCTURAL)
            labels[succ.id] = f'in_{side}_succ'
            cross = [(EdgeType.OPERATIONAL, OUT)]
            if state == 'cont':
                cross.append((EdgeType.STRUCTURAL, OUT))
            succ_specs[succ] = cross
        return spine, leaf, succ

    lspine, ll, lsucc = operand(left_bit, left_state, 'left')
    rspine, rl, rsucc = operand(right_bit, right_state, 'right')
    p.add_edge(cyc[0], lspine, EdgeType.OPERATIONAL)
    p.add_edge(cyc[1], rspine, EdgeType.OPERATIONAL)

    # result side. Three input-result shapes (in_result_width):
    #   'coincident' = add_init output: 1-bit result, MSB==LSB, r_spine -OP-> buffer
    #                  coincident anchor. carry attaches to r_spine.
    #   '2bit'       = prior bit_add output: result spine is r_spine(LSB) -S-> msb(frontier)
    #                  -S-> buffer; msb -OP-> its leaf (out of window); r_spine -OP-> buffer
    #                  is the RETAINED LSB-readback anchor; carry attaches to msb (frontier).
    #                  Terminates in-window (no continuation crossing).
    #   'multibit'   = like 2bit but lsb is NOT directly adjacent to msb; chain between
    #                  them is external. lsb has (S,out) crossing, msb has (S,in) crossing.
    r_spine = p.add_node(); buffer = p.add_node()
    labels[r_spine.id] = 'in_result_spine'; labels[buffer.id] = 'in_buffer'
    p.add_edge(handle, buffer, EdgeType.STRUCTURAL)         # operator holds buffer

    if in_result_width == 'coincident':
        p.add_edge(r_spine, buffer, EdgeType.STRUCTURAL)    # MSB-growth (internal)
        p.add_edge(r_spine, buffer, EdgeType.OPERATIONAL)   # coincident anchor (internal)
        rspine_cross = [(EdgeType.OPERATIONAL, OUT)]        # -> result_leaf (out of window)
        carry_target = r_spine                              # carry on the (sole) spine vertex
        msb = None
    else:
        # 2bit / multibit: distinct MSB frontier vertex between r_spine(LSB) and buffer.
        # 2bit: lsb directly adjacent to msb (internal S-edge).
        # multibit: lsb connected to msb via external chain (no internal S-edge; S-out crossing on lsb).
        msb = p.add_node(); labels[msb.id] = 'in_result_msb'
        if in_result_width == '2bit':
            p.add_edge(r_spine, msb, EdgeType.STRUCTURAL)   # LSB -S-> MSB frontier (internal, direct)
        # else multibit: lsb's S-out goes to external chain, no direct lsb->msb edge
        p.add_edge(msb, buffer, EdgeType.STRUCTURAL)        # MSB -S-> buffer
        p.add_edge(r_spine, buffer, EdgeType.OPERATIONAL)   # retained LSB-readback anchor (internal)
        if in_result_width == '2bit':
            rspine_cross = [(EdgeType.OPERATIONAL, OUT)]        # r_spine -OP-> its leaf (out of window)
        else:
            # multibit: lsb has S-out crossing (chain to msb exits window) + OP-out crossing (bit ptr)
            rspine_cross = [(EdgeType.OPERATIONAL, OUT), (EdgeType.STRUCTURAL, OUT)]
        msb_cross = [(EdgeType.OPERATIONAL, OUT)]           # msb -OP-> its leaf (out of window)
        if in_result_width == 'multibit':
            msb_cross.append((EdgeType.STRUCTURAL, IN))     # chain enters msb from below (crossing)
        carry_target = msb                                  # carry attaches to the MSB frontier

    if carry_in:
        ca = p.add_node(); cb = p.add_node()
        labels[ca.id] = 'in_carry_a'; labels[cb.id] = 'in_carry_b'
        p.add_edge(ca, cb, EdgeType.STRUCTURAL); p.add_edge(cb, ca, EdgeType.STRUCTURAL)
        p.add_edge(ca, carry_target, EdgeType.STRUCTURAL)   # carry STRUCTURAL INCOMING onto frontier

    # ---------------- boundary specs ----------------
    specs = {handle: [(EdgeType.OPERATIONAL, IN)],          # parent points at handle
             r_spine: rspine_cross}                          # result_spine -> its leaf (out)
    if msb is not None:
        specs[msb] = msb_cross                               # MSB frontier -> its leaf (+continuation if multibit)
    specs.update(succ_specs)
    g2, nm, ph = S._typed_input_graph(p, specs)

    # relabel through nm; strip labels that landed on markers/placeholder
    for old in p.nodes:
        if old.id in labels and old in nm:
            labels[nm[old].id] = labels[old.id]
    for nid in list(labels):
        n = [x for x in g2.nodes if x.id == nid]
        if not n: continue
        nn = n[0]
        is_marker = Edge(nn, nn, EdgeType.OPERATIONAL) in g2 and Edge(nn, nn, EdgeType.STRUCTURAL) not in g2
        is_ph = Edge(nn, nn, EdgeType.OPERATIONAL) in g2 and Edge(nn, nn, EdgeType.STRUCTURAL) in g2
        if is_marker or is_ph: del labels[nid]
    for i, c in enumerate(cyc): labels[nm[c].id] = f'in_cyc{i}'
    labels[nm[handle].id] = 'in_handle'; labels[nm[tag.anchor].id] = 'in_anchor'
    if ph is not None: labels[ph.id] = 'placeholder'

    in_cyc = [nm[c] for c in cyc]; in_anchor = nm[tag.anchor]; in_handle = nm[handle]
    in_r_spine = nm[r_spine]; in_buffer = nm[buffer]
    in_msb = nm[msb] if msb is not None else None
    in_lspine = nm[lspine]; in_ll = nm[ll]; in_rspine = nm[rspine]; in_rl = nm[rl]
    in_lsucc = nm[lsucc] if not left_single else None
    in_rsucc = nm[rsucc] if not right_single else None
    if carry_in: in_ca = nm[ca]; in_cb = nm[cb]

    # ---------------- OUTPUT side ----------------
    sz = len(cyc)
    out_cyc = [g2.add_node() for _ in range(sz - 1)]; out_handle = g2.add_node(); out_cyc.append(out_handle)
    for i, o in enumerate(out_cyc): labels[o.id] = f'out_cyc{i}'
    labels[out_handle.id] = 'out_handle'
    out_anchor = g2.add_node(); labels[out_anchor.id] = 'out_anchor'

    out_r_spine = g2.add_node(); labels[out_r_spine.id] = 'out_result_spine'
    out_buffer = g2.add_node(); labels[out_buffer.id] = 'out_buffer'
    out_new_spine = g2.add_node(); labels[out_new_spine.id] = 'out_new_spine'
    out_new_leaf = g2.add_node(); labels[out_new_leaf.id] = 'out_new_leaf'
    # surviving prior MSB frontier (only when input already had a 2bit/multibit result)
    out_msb = g2.add_node() if in_msb is not None else None
    if out_msb is not None: labels[out_msb.id] = 'out_result_msb'

    out_lsucc = g2.add_node() if not left_single else None
    out_rsucc = g2.add_node() if not right_single else None
    if out_lsucc is not None: labels[out_lsucc.id] = 'out_left_succ'
    if out_rsucc is not None: labels[out_rsucc.id] = 'out_right_succ'
    out_lz_spine = g2.add_node() if left_single else None
    out_lz_leaf = g2.add_node() if left_single else None
    out_rz_spine = g2.add_node() if right_single else None
    out_rz_leaf = g2.add_node() if right_single else None
    if out_lz_spine is not None:
        labels[out_lz_spine.id] = 'out_left_zero_spine'; labels[out_lz_leaf.id] = 'out_left_zero_leaf'
    if out_rz_spine is not None:
        labels[out_rz_spine.id] = 'out_right_zero_spine'; labels[out_rz_leaf.id] = 'out_right_zero_leaf'

    # ---------------- mapping (in->out) ----------------
    for ic, oc in zip(in_cyc, out_cyc): g2.add_edge(ic, oc, EdgeType.OPERATIONAL)
    g2.add_edge(in_anchor, out_anchor, EdgeType.OPERATIONAL)
    g2.add_edge(in_r_spine, out_r_spine, EdgeType.OPERATIONAL)   # spine survives
    g2.add_edge(in_buffer, out_buffer, EdgeType.OPERATIONAL)     # buffer survives, pushed back
    if in_msb is not None:
        g2.add_edge(in_msb, out_msb, EdgeType.OPERATIONAL)       # prior MSB frontier survives
    # born new spine/leaf: conservative source = in_r_spine (result line)
    g2.add_edge(in_r_spine, out_new_spine, EdgeType.OPERATIONAL)
    g2.add_edge(in_r_spine, out_new_leaf, EdgeType.OPERATIONAL)
    if not left_single: g2.add_edge(in_lsucc, out_lsucc, EdgeType.OPERATIONAL)
    if not right_single: g2.add_edge(in_rsucc, out_rsucc, EdgeType.OPERATIONAL)
    if left_single:
        g2.add_edge(in_lspine, out_lz_spine, EdgeType.OPERATIONAL)
        g2.add_edge(in_ll, out_lz_leaf, EdgeType.OPERATIONAL)
    if right_single:
        g2.add_edge(in_rspine, out_rz_spine, EdgeType.OPERATIONAL)
        g2.add_edge(in_rl, out_rz_leaf, EdgeType.OPERATIONAL)

    # ---------------- output structure ----------------
    for i in range(sz): g2.add_edge(out_cyc[i], out_cyc[(i + 1) % sz], EdgeType.STRUCTURAL)
    g2.add_edge(out_cyc[0], out_anchor, EdgeType.STRUCTURAL)
    g2.add_edge(out_handle, out_buffer, EdgeType.STRUCTURAL)
    _ocm(g2, ph, out_handle)   # operational crossing preserves parent -OP-> handle

    frontier = out_msb if out_msb is not None else out_r_spine
    if out_msb is not None:
        # 2bit: rsp and msb are directly adjacent (internal S-edge).
        # multibit: rsp's S-out goes to external chain via (S,out) boundary crossing.
        if in_result_width == '2bit':
            g2.add_edge(out_r_spine, out_msb, EdgeType.STRUCTURAL)  # LSB -S-> prior MSB (internal, direct)
        else:
            g2.add_edge(out_r_spine, ph, EdgeType.STRUCTURAL)       # declares (S,out) crossing on lsb
        _ocm(g2, out_r_spine, ph)                                 # r_spine -OP-> its leaf (retained, out)
        _ocm(g2, out_r_spine, out_buffer)                         # r_spine LSB-readback anchor (retained)
    g2.add_edge(frontier, out_new_spine, EdgeType.STRUCTURAL)     # redirect frontier -S-> new
    g2.add_edge(out_new_spine, out_buffer, EdgeType.STRUCTURAL)   # new -S-> buffer
    _ocm(g2, out_new_spine, out_new_leaf)                         # new MSB bit pointer
    if out_msb is None:
        _ocm(g2, out_r_spine, out_buffer)                         # LSB readback anchor (coincident)
    if out_msb is not None:
        _ocm(g2, out_msb, ph)                                     # out_msb -OP-> its leaf (retained, out)
        if in_result_width == 'multibit':
            g2.add_edge(ph, out_msb, EdgeType.STRUCTURAL)         # declares (S,in) crossing on msb
    if result_bit == 1: g2.add_edge(out_new_leaf, out_new_leaf, EdgeType.STRUCTURAL)
    _ocm(g2, out_r_spine, ph)   # operational crossing preserves result_spine -OP-> leaf

    # operand ports advance
    if not left_single:
        _ocm(g2, out_cyc[0], out_lsucc); _ph_both(g2, out_lsucc, ph)
    if not right_single:
        _ocm(g2, out_cyc[1], out_rsucc); _ph_both(g2, out_rsucc, ph)
    if left_single:
        _ocm(g2, out_cyc[0], out_lz_spine)
        _ocm(g2, out_lz_spine, out_lz_leaf)
    if right_single:
        _ocm(g2, out_cyc[1], out_rz_spine)
        _ocm(g2, out_rz_spine, out_rz_leaf)

    # carry-out on new spine (STRUCTURAL, incoming)
    if carry_out:
        oca = g2.add_node(); ocb = g2.add_node()
        labels[oca.id] = 'out_carry_a'; labels[ocb.id] = 'out_carry_b'
        g2.add_edge(oca, ocb, EdgeType.STRUCTURAL); g2.add_edge(ocb, oca, EdgeType.STRUCTURAL)
        g2.add_edge(oca, out_new_spine, EdgeType.STRUCTURAL)
        g2.add_edge(in_r_spine, oca, EdgeType.OPERATIONAL)
        g2.add_edge(in_r_spine, ocb, EdgeType.OPERATIONAL)

    return OperationDefinition(name='sp_bitadd', pattern=p, graph2=g2), labels
