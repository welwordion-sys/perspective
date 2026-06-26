"""Spine add_init v4 — pattern uses PLAIN edges only (the verified-builder principle).
_typed_input_graph encodes input-side markers ONCE. Output side uses _add_op_marker_chain.
No hand _marker on the pattern.
"""
from basic_machinery.graph import PerspectiveGraph, Node, EdgeType, Edge
from basic_machinery.operations import OperationDefinition
from basic_machinery import encoding as E
from basic_machinery import transition_helpers as S

def _ocm(g,src,tgt):   # output-side operational edge as marker chain
    return S._marker(g,src,tgt)

def _ph_both(g, node, ph):
    """MIGRATED to four-case: declares all four (type,direction) preserve cases
    (struct both directions direct; op both directions as marker chains) so the
    four-case step-4c preserves every external crossing of this boundary node.
    Op is always a marker chain — never a direct op edge (would corrupt the
    output node's input/output classification)."""
    from boundary_decl import ph_all_four
    ph_all_four(g, node, ph)

# Per-side operand state for add_init's match window:
#   'single' : 1-bit operand. LSB is the whole number, no successor.
#   'term'   : exactly-2-bit operand. LSB has a successor, and that successor is
#              the MSB -> successor degree {(OP,out):bit, (S,in):1}, NO deeper chain.
#   'cont'   : >=3-bit operand. LSB's successor is a MID spine -> successor degree
#              {(OP,out):bit, (S,out):1, (S,in):1}, HAS a deeper chain crossing.
# The LSB's own degree is identical for 'term' and 'cont' (both {(OP,out),(S,out)});
# the distinction lives ENTIRELY on the successor node, which is in the window.
# Hence the 3-way split per side: 2(left_bit) x 2(right_bit) x 3 x 3 = 36 variants.
# The successor's BIT VALUE never enters (its leaf is not modelled) -> no value axis.

def build_labeled(left_bit, right_bit, left_state, right_state):
    result_bit=(left_bit+right_bit)%2; carry=(left_bit+right_bit)>=2
    labels={}
    p=PerspectiveGraph()
    handle,tag=E.build_operator(p,'+',finished=False); cyc=tag.cycle_nodes

    succ_specs={}   # successor pattern node -> list of typed crossings to placeholder

    def operand(bit,state,side):
        spine=p.add_node(); leaf=p.add_node()
        p.add_edge(spine,leaf,EdgeType.OPERATIONAL)        # PLAIN op edge (bit pointer)
        if bit==1: p.add_edge(leaf,leaf,EdgeType.STRUCTURAL)
        labels[spine.id]=f'in_{side}_spine'; labels[leaf.id]=f'in_{side}_leaf'
        succ=None
        if state!='single':
            succ=p.add_node(); p.add_edge(spine,succ,EdgeType.STRUCTURAL)   # PLAIN struct chain (in-window)
            labels[succ.id]=f'in_{side}_succ'
            # Successor's REAL crossings out of the window:
            #   its own bit pointer (OPERATIONAL,out) -- ALWAYS present on a spine vertex
            #   its deeper chain    (STRUCTURAL,out)  -- ONLY if it is a MID spine ('cont')
            cross=[(EdgeType.OPERATIONAL,'out')]
            if state=='cont':
                cross.append((EdgeType.STRUCTURAL,'out'))
            succ_specs[succ]=cross
        return spine,leaf,succ

    lspine,ll,lsucc=operand(left_bit,left_state,'left')
    rspine,rl,rsucc=operand(right_bit,right_state,'right')
    p.add_edge(cyc[0],lspine,EdgeType.OPERATIONAL)         # PLAIN port->spine
    p.add_edge(cyc[1],rspine,EdgeType.OPERATIONAL)

    left_single=(left_state=='single'); right_single=(right_state=='single')

    specs={handle:[(EdgeType.OPERATIONAL,'in')]}
    specs.update(succ_specs)
    g2,nm,ph=S._typed_input_graph(p,specs)

    # labels carry through nm for REAL pattern nodes only (markers are created fresh by
    # _typed_input_graph and are intentionally left unlabeled).
    for old in p.nodes:
        if old.id in labels and old in nm:
            labels[nm[old].id]=labels[old.id]
    # NOTE: pattern node ids and g2 ids differ; assign via nm only, never raw id reuse.
    # Clear any label that accidentally points at a marker/placeholder in g2.
    for nid in list(labels):
        n=[x for x in g2.nodes if x.id==nid]
        if not n: continue
        nn=n[0]
        is_marker=Edge(nn,nn,EdgeType.OPERATIONAL) in g2 and Edge(nn,nn,EdgeType.STRUCTURAL) not in g2
        is_ph=Edge(nn,nn,EdgeType.OPERATIONAL) in g2 and Edge(nn,nn,EdgeType.STRUCTURAL) in g2
        if is_marker or is_ph: del labels[nid]
    for i,c in enumerate(cyc): labels[nm[c].id]=f'in_cyc{i}'
    labels[nm[handle].id]='in_handle'; labels[nm[tag.anchor].id]='in_anchor'; labels[nm[tag.tail].id]='in_tail'
    if ph is not None: labels[ph.id]='placeholder'

    in_cyc=[nm[c] for c in cyc]; in_anchor=nm[tag.anchor]; in_tail=nm[tag.tail]
    in_lsucc=nm[lsucc] if not left_single else None
    in_rsucc=nm[rsucc] if not right_single else None
    in_left_spine=nm[lspine]; in_left_leaf=nm[ll]
    in_right_spine=nm[rspine]; in_right_leaf=nm[rl]

    sz=len(cyc)
    out_cyc=[g2.add_node() for _ in range(sz-1)]; out_handle=g2.add_node(); out_cyc.append(out_handle)
    for i,o in enumerate(out_cyc): labels[o.id]=f'out_cyc{i}'
    labels[out_handle.id]='out_handle'
    out_anchor=g2.add_node(); labels[out_anchor.id]='out_anchor'
    out_rspine=g2.add_node(); labels[out_rspine.id]='out_result_spine'
    out_rleaf=g2.add_node(); labels[out_rleaf.id]='out_result_leaf'
    out_buffer=g2.add_node(); labels[out_buffer.id]='out_buffer'
    out_lsucc=g2.add_node() if not left_single else None
    out_rsucc=g2.add_node() if not right_single else None
    if out_lsucc is not None: labels[out_lsucc.id]='out_left_succ'
    if out_rsucc is not None: labels[out_rsucc.id]='out_right_succ'

    # Implicit-zero read-head for SINGLE operands (KB add_init_redesign_with_buffer.implicit_zero
    # + pointer_structure): a consumed single-bit operand does NOT leave the port dangling; the
    # port advances onto a FRESH zero spine vertex placed at the operand's next level, so a later
    # drain/bit_add has a zero to read on the exhausted side. Spine shape: zero-spine -OP-> zero-leaf
    # (leaf has NO structural self-loop => bit 0), uniform with every real spine vertex so bit_add
    # reads spine->OP->bit identically. Born nodes (no input correspondent) -> mapping edge from
    # in_tail, the conservative result-line source (conservative_mapping), so step-2 classifies
    # them as output not input.
    out_lzero_spine = g2.add_node() if left_single else None
    out_lzero_leaf  = g2.add_node() if left_single else None
    out_rzero_spine = g2.add_node() if right_single else None
    out_rzero_leaf  = g2.add_node() if right_single else None
    if out_lzero_spine is not None:
        labels[out_lzero_spine.id]='out_left_zero_spine'; labels[out_lzero_leaf.id]='out_left_zero_leaf'
    if out_rzero_spine is not None:
        labels[out_rzero_spine.id]='out_right_zero_spine'; labels[out_rzero_leaf.id]='out_right_zero_leaf'

    # mapping (in->out, plain operational — these are mapping instructions, not real edges)
    for ic,oc in zip(in_cyc,out_cyc): g2.add_edge(ic,oc,EdgeType.OPERATIONAL)
    g2.add_edge(in_anchor,out_anchor,EdgeType.OPERATIONAL)
    g2.add_edge(in_tail,out_rspine,EdgeType.OPERATIONAL)
    g2.add_edge(in_tail,out_buffer,EdgeType.OPERATIONAL)
    g2.add_edge(in_tail,out_rleaf,EdgeType.OPERATIONAL)
    if not left_single:  g2.add_edge(in_lsucc,out_lsucc,EdgeType.OPERATIONAL)
    if not right_single: g2.add_edge(in_rsucc,out_rsucc,EdgeType.OPERATIONAL)
    # Implicit zero = the single operand TRANSFORMED in place, not a born node.
    # Map operand spine -> zero spine and operand leaf -> zero leaf, so each zero
    # node has its real correspondent (disposition MAPPED, invertible/local per
    # conservative_mapping) instead of all sourcing from in_tail. The output leaf
    # simply lacks the structural self-loop => the former bit becomes 0.
    if left_single:
        g2.add_edge(in_left_spine, out_lzero_spine, EdgeType.OPERATIONAL)
        g2.add_edge(in_left_leaf,  out_lzero_leaf,  EdgeType.OPERATIONAL)
    if right_single:
        g2.add_edge(in_right_spine, out_rzero_spine, EdgeType.OPERATIONAL)
        g2.add_edge(in_right_leaf,  out_rzero_leaf,  EdgeType.OPERATIONAL)

    # operator ring + anchor + tail attachment (output structural)
    for i in range(sz): g2.add_edge(out_cyc[i],out_cyc[(i+1)%sz],EdgeType.STRUCTURAL)
    g2.add_edge(out_cyc[0],out_anchor,EdgeType.STRUCTURAL)
    g2.add_edge(out_handle,out_buffer,EdgeType.STRUCTURAL)
    # The handle is a SURVIVING boundary node: the parent (or equality port for a
    # root operator) points operationally INTO it (parent -OP-> handle), an edge
    # OUTSIDE add_init's match. Declare the handle's boundary (all four cases) so
    # the schema rebuild preserves that incoming pointer — without it the parent/
    # equality pointer is stripped and the operator detaches from its context.
    _ph_both(g2,out_handle,ph)

    # result: spine + bit pointer (OUTPUT marker chain) + buffer
    _ocm(g2,out_rspine,out_rleaf)                          # output op edge = marker chain
    if result_bit==1: g2.add_edge(out_rleaf,out_rleaf,EdgeType.STRUCTURAL)
    g2.add_edge(out_rspine,out_buffer,EdgeType.STRUCTURAL)
    _ocm(g2,out_rspine,out_buffer)
    # The result spine is a SURVIVING boundary node: after this rule, an external
    # operational pointer reaches it (e.g. the equality LHS port -OP-> result
    # spine once the operator collapses, or the parent operator's pointer). That
    # in-op external is OUTSIDE add_init's window, so four-case 4c strips it
    # unless declared. Declare all four cases so every external crossing of the
    # result spine is preserved (the in-op case is the load-bearing one — without
    # it the equality loses its pointer to the LHS value).
    _ph_both(g2,out_rspine,ph)

    # new read-head: port -> successor spine (OUTPUT marker chain) + boundary
    if not left_single:
        _ocm(g2,out_cyc[0],out_lsucc); _ph_both(g2,out_lsucc,ph)
    if not right_single:
        _ocm(g2,out_cyc[1],out_rsucc); _ph_both(g2,out_rsucc,ph)
    # single operand: port advances onto the implicit-zero spine vertex (OUTPUT marker chain),
    # which carries its own zero-leaf (spine -OP-> leaf, leaf has NO self-loop => bit 0).
    # No placeholder/boundary edge: the implicit zero is freshly created and terminal (it has no
    # deeper chain), so it has no external crossing to preserve.
    if left_single:
        _ocm(g2,out_cyc[0],out_lzero_spine)        # port -> zero spine (read-head)
        _ocm(g2,out_lzero_spine,out_lzero_leaf)    # zero spine -OP-> zero leaf (bit 0)
    if right_single:
        _ocm(g2,out_cyc[1],out_rzero_spine)
        _ocm(g2,out_rzero_spine,out_rzero_leaf)

    if carry:
        ca,cb=g2.add_node(),g2.add_node(); labels[ca.id]='out_carry_a'; labels[cb.id]='out_carry_b'
        g2.add_edge(ca,cb,EdgeType.STRUCTURAL); g2.add_edge(cb,ca,EdgeType.STRUCTURAL)
        # REVISED 2026-06-16 (supersedes the 2026-06-12 operational-on-spine note):
        # carry attaches to the result SPINE via a SINGLE STRUCTURAL edge INTO the
        # spine (ca -S-> out_rspine), NOT operationally. Reason (least edge-type
        # confusion): the spine's (OPERATIONAL,out) is its BIT POINTER; a second
        # operational-out for the carry collides with the bit pointer and is what
        # blocked bit_add from matching (result spine showed OP-out=3, no variant
        # expected it). The spine's (STRUCTURAL,out) means the chain (-> next spine,
        # -> buffer); the spine's (STRUCTURAL,in) is empty on the result line, so an
        # incoming structural edge is an unused, unambiguous signature. Carry
        # presence = +1 (STRUCTURAL,in) on the spine. Leaf stays out of the window
        # (carry is on the spine, not the leaf); spine OP-out stays exactly = 1.
        g2.add_edge(ca,out_rspine,EdgeType.STRUCTURAL)
        # born carry nodes (no input correspondent): conservative mapping source
        # = in_tail (result-line); per cut_at_edge_matching.id_preservation the
        # source is not a correctness property.
        g2.add_edge(in_tail,ca,EdgeType.OPERATIONAL); g2.add_edge(in_tail,cb,EdgeType.OPERATIONAL)

    return OperationDefinition(name='sp',pattern=p,graph2=g2), labels
