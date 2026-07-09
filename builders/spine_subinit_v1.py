"""Spine sub_init v1 — 33 variants across four families (ERS coding_guard session
2026-07-09; see d_family_shapes for the pre-code derivation).

Families over the init column of an unfinished '-' operator (ring size 4,
disjoint from '+' size 3, so no cross-matching with add rules):

  PLAIN (24): left term/cont x right single/term/cont x both bit values.
      add_init topology with the recurrence flipped:
        result_bit = (l - r) mod 2 ; borrow_out = (l - r) < 0
      borrow encodes exactly like add's carry: 2-cycle ba<->bb with
      ba -S-> result_spine (signature +1 (S,in); channel free on '-' spines).

  BOTH-SINGLE (2): left single-1 x right single-{0,1}. Positive by
      construction (1-0, 1-1); Config2 needs borrow_in, impossible at init.
      Both ports advance onto implicit-zero spines.

  MARKER (4): left single-1 x right term/cont x right bit. The init column IS
      the frontier with vacuous phases 1-2 (b1=b2=0 => borrow_in = NOT(b1) AND
      b2 = 0), so init computes the derived frontier formula directly, in b-a
      direction: result_bit = (r - 1) mod 2 ; borrow_out = (r - 1) < 0.
      Plants the marker: output op chain right_successor_spine -> result_spine
      (anchor = current-lowest REMAINING right bit per the 2026-07-09 ruling;
      spine anchor, not leaf — the operand bit is undetermined in phase-2
      windows). The successor spine's OP-out degree becomes 2 (bit pointer +
      marker), structurally excluding every Part-1 window (regime by degree).

  A0-FINALISE (3): left single-0 (minuend zero — the input already IS the
      negative frame modulo the tail; negative_encoding decision):
        'zero'  (right single-0): 0-0=0. Collapse-to-zero: ring, anchor, tail,
                and right operand deleted; the left zero spine+leaf survive as
                the value; the HANDLE MAPS ONTO the left spine so the parent
                pointer is redirected onto the result (redirects rewrite both
                endpoints).
        'one'   (right single-1): finished -1 frame: ONLY the tail is deleted
                (matched, no output correspondent); ring, anchor, both
                operands, and port pointers survive.
        'multi' (right term AND cont, collapsed): finished frame; the right
                successor is NOT modelled (declared (S,out) crossing on the
                right spine suffices — b>=2>0 entailed, leaf also external),
                which is why term/cont fuse into one rule here: no port
                advance means the successor never needs to be in-window.
"""
from basic_machinery.graph import PerspectiveGraph, Node, EdgeType, Edge
from basic_machinery.operations import OperationDefinition
from basic_machinery import encoding as E
from basic_machinery import transition_helpers as S


def _ocm(g, src, tgt):
    return S._marker(g, src, tgt)


def _ph_both(g, node, ph):
    from boundary_decl import ph_all_four
    ph_all_four(g, node, ph)


def _label_transfer(p, g2, nm, labels, cyc, handle, tag, ph):
    """Carry labels through nm for real pattern nodes; scrub marker/placeholder ids."""
    for old in p.nodes:
        if old.id in labels and old in nm:
            labels[nm[old].id] = labels[old.id]
    for nid in list(labels):
        n = [x for x in g2.nodes if x.id == nid]
        if not n:
            continue
        nn = n[0]
        is_marker = Edge(nn, nn, EdgeType.OPERATIONAL) in g2 and Edge(nn, nn, EdgeType.STRUCTURAL) not in g2
        is_ph = Edge(nn, nn, EdgeType.OPERATIONAL) in g2 and Edge(nn, nn, EdgeType.STRUCTURAL) in g2
        if is_marker or is_ph:
            del labels[nid]
    for i, c in enumerate(cyc):
        labels[nm[c].id] = f'in_cyc{i}'
    labels[nm[handle].id] = 'in_handle'
    labels[nm[tag.anchor].id] = 'in_anchor'
    if tag.tail is not None:
        labels[nm[tag.tail].id] = 'in_tail'
    if ph is not None:
        labels[ph.id] = 'placeholder'


def build_labeled(left_bit, right_bit, left_state, right_state):
    """PLAIN / BOTH-SINGLE / MARKER families (add_init skeleton, '-' ring)."""
    left_single = (left_state == 'single')
    right_single = (right_state == 'single')

    if left_single:
        assert left_bit == 1, "left single-0 belongs to the a0 family (build_a0)"
        if right_single:
            family = 'both_single'
        else:
            family = 'marker'
    else:
        family = 'plain'

    if family == 'marker':
        # frontier formula, b-a direction, vacuous phases 1-2 => borrow_in 0
        v = right_bit - 1
    else:
        v = left_bit - right_bit
    result_bit = v % 2
    borrow = v < 0

    labels = {}
    p = PerspectiveGraph()
    handle, tag = E.build_operator(p, '-', finished=False)
    cyc = tag.cycle_nodes

    succ_specs = {}

    def operand(bit, state, side):
        spine = p.add_node(); leaf = p.add_node()
        p.add_edge(spine, leaf, EdgeType.OPERATIONAL)
        if bit == 1:
            p.add_edge(leaf, leaf, EdgeType.STRUCTURAL)
        labels[spine.id] = f'in_{side}_spine'; labels[leaf.id] = f'in_{side}_leaf'
        succ = None
        if state != 'single':
            succ = p.add_node()
            p.add_edge(spine, succ, EdgeType.STRUCTURAL)
            labels[succ.id] = f'in_{side}_succ'
            cross = [(EdgeType.OPERATIONAL, 'out')]
            if state == 'cont':
                cross.append((EdgeType.STRUCTURAL, 'out'))
            succ_specs[succ] = cross
        return spine, leaf, succ

    lspine, ll, lsucc = operand(left_bit, left_state, 'left')
    rspine, rl, rsucc = operand(right_bit, right_state, 'right')
    p.add_edge(cyc[0], lspine, EdgeType.OPERATIONAL)
    p.add_edge(cyc[1], rspine, EdgeType.OPERATIONAL)

    specs = {handle: [(EdgeType.OPERATIONAL, 'in')]}
    specs.update(succ_specs)
    g2, nm, ph = S._typed_input_graph(p, specs)
    _label_transfer(p, g2, nm, labels, cyc, handle, tag, ph)

    in_cyc = [nm[c] for c in cyc]; in_anchor = nm[tag.anchor]; in_tail = nm[tag.tail]
    in_lsucc = nm[lsucc] if not left_single else None
    in_rsucc = nm[rsucc] if not right_single else None
    in_left_spine = nm[lspine]; in_left_leaf = nm[ll]
    in_right_spine = nm[rspine]; in_right_leaf = nm[rl]

    sz = len(cyc)
    out_cyc = [g2.add_node() for _ in range(sz - 1)]
    out_handle = g2.add_node(); out_cyc.append(out_handle)
    for i, o in enumerate(out_cyc):
        labels[o.id] = f'out_cyc{i}'
    labels[out_handle.id] = 'out_handle'
    out_anchor = g2.add_node(); labels[out_anchor.id] = 'out_anchor'
    out_rspine = g2.add_node(); labels[out_rspine.id] = 'out_result_spine'
    out_rleaf = g2.add_node(); labels[out_rleaf.id] = 'out_result_leaf'
    out_buffer = g2.add_node(); labels[out_buffer.id] = 'out_buffer'
    out_lsucc = g2.add_node() if not left_single else None
    out_rsucc = g2.add_node() if not right_single else None
    if out_lsucc is not None:
        labels[out_lsucc.id] = 'out_left_succ'
    if out_rsucc is not None:
        labels[out_rsucc.id] = 'out_right_succ'

    out_lzero_spine = g2.add_node() if left_single else None
    out_lzero_leaf = g2.add_node() if left_single else None
    out_rzero_spine = g2.add_node() if right_single else None
    out_rzero_leaf = g2.add_node() if right_single else None
    if out_lzero_spine is not None:
        labels[out_lzero_spine.id] = 'out_left_zero_spine'
        labels[out_lzero_leaf.id] = 'out_left_zero_leaf'
    if out_rzero_spine is not None:
        labels[out_rzero_spine.id] = 'out_right_zero_spine'
        labels[out_rzero_leaf.id] = 'out_right_zero_leaf'

    # mapping (in -> out)
    for ic, oc in zip(in_cyc, out_cyc):
        g2.add_edge(ic, oc, EdgeType.OPERATIONAL)
    g2.add_edge(in_anchor, out_anchor, EdgeType.OPERATIONAL)
    g2.add_edge(in_tail, out_rspine, EdgeType.OPERATIONAL)
    g2.add_edge(in_tail, out_buffer, EdgeType.OPERATIONAL)
    g2.add_edge(in_tail, out_rleaf, EdgeType.OPERATIONAL)
    if not left_single:
        g2.add_edge(in_lsucc, out_lsucc, EdgeType.OPERATIONAL)
    if not right_single:
        g2.add_edge(in_rsucc, out_rsucc, EdgeType.OPERATIONAL)
    if left_single:
        g2.add_edge(in_left_spine, out_lzero_spine, EdgeType.OPERATIONAL)
        g2.add_edge(in_left_leaf, out_lzero_leaf, EdgeType.OPERATIONAL)
    if right_single:
        g2.add_edge(in_right_spine, out_rzero_spine, EdgeType.OPERATIONAL)
        g2.add_edge(in_right_leaf, out_rzero_leaf, EdgeType.OPERATIONAL)

    # output structure
    for i in range(sz):
        g2.add_edge(out_cyc[i], out_cyc[(i + 1) % sz], EdgeType.STRUCTURAL)
    g2.add_edge(out_cyc[0], out_anchor, EdgeType.STRUCTURAL)
    g2.add_edge(out_handle, out_buffer, EdgeType.STRUCTURAL)
    _ph_both(g2, out_handle, ph)

    _ocm(g2, out_rspine, out_rleaf)
    if result_bit == 1:
        g2.add_edge(out_rleaf, out_rleaf, EdgeType.STRUCTURAL)
    g2.add_edge(out_rspine, out_buffer, EdgeType.STRUCTURAL)
    _ocm(g2, out_rspine, out_buffer)
    _ph_both(g2, out_rspine, ph)

    if not left_single:
        _ocm(g2, out_cyc[0], out_lsucc); _ph_both(g2, out_lsucc, ph)
    if not right_single:
        _ocm(g2, out_cyc[1], out_rsucc); _ph_both(g2, out_rsucc, ph)
    if left_single:
        _ocm(g2, out_cyc[0], out_lzero_spine)
        _ocm(g2, out_lzero_spine, out_lzero_leaf)
    if right_single:
        _ocm(g2, out_cyc[1], out_rzero_spine)
        _ocm(g2, out_rzero_spine, out_rzero_leaf)

    # MARKER planting: real operational edge (as output marker chain) from the
    # right SUCCESSOR spine (new current-lowest remaining right bit) to the
    # result spine. Anchor on the SPINE, never the leaf (bit undetermined in
    # phase-2 windows); target result-spine OP-in per the settled channels.
    if family == 'marker':
        _ocm(g2, out_rsucc, out_rspine)

    # borrow-out on the result spine (same 2-cycle + S-in signature as add's carry)
    if borrow:
        ba, bb = g2.add_node(), g2.add_node()
        labels[ba.id] = 'out_borrow_a'; labels[bb.id] = 'out_borrow_b'
        g2.add_edge(ba, bb, EdgeType.STRUCTURAL); g2.add_edge(bb, ba, EdgeType.STRUCTURAL)
        g2.add_edge(ba, out_rspine, EdgeType.STRUCTURAL)
        g2.add_edge(in_tail, ba, EdgeType.OPERATIONAL)
        g2.add_edge(in_tail, bb, EdgeType.OPERATIONAL)

    name = f'sub_init_{family}_L{left_bit}{left_state[0]}_R{right_bit}{right_state[0]}'
    return OperationDefinition(name=name, pattern=p, graph2=g2), labels


def build_a0(right_kind):
    """A0-FINALISE family: left single-0 (minuend zero). right_kind in
    {'zero','one','multi'}. See module docstring for the three rewrites."""
    assert right_kind in ('zero', 'one', 'multi')
    labels = {}
    p = PerspectiveGraph()
    handle, tag = E.build_operator(p, '-', finished=False)
    cyc = tag.cycle_nodes

    lspine = p.add_node(); lleaf = p.add_node()
    p.add_edge(lspine, lleaf, EdgeType.OPERATIONAL)      # bit 0: no self-loop
    labels[lspine.id] = 'in_left_spine'; labels[lleaf.id] = 'in_left_leaf'

    rspine = p.add_node()
    labels[rspine.id] = 'in_right_spine'
    rleaf = None
    if right_kind in ('zero', 'one'):
        rleaf = p.add_node()
        p.add_edge(rspine, rleaf, EdgeType.OPERATIONAL)
        if right_kind == 'one':
            p.add_edge(rleaf, rleaf, EdgeType.STRUCTURAL)
        labels[rleaf.id] = 'in_right_leaf'
    # 'multi': leaf AND successor both external — declared as crossings below.

    p.add_edge(cyc[0], lspine, EdgeType.OPERATIONAL)
    p.add_edge(cyc[1], rspine, EdgeType.OPERATIONAL)

    specs = {handle: [(EdgeType.OPERATIONAL, 'in')]}
    if right_kind == 'multi':
        specs[rspine] = [(EdgeType.OPERATIONAL, 'out'),   # bit pointer to external leaf
                         (EdgeType.STRUCTURAL, 'out')]    # chain to external successor
    g2, nm, ph = S._typed_input_graph(p, specs)
    _label_transfer(p, g2, nm, labels, cyc, handle, tag, ph)

    in_cyc = [nm[c] for c in cyc]; in_anchor = nm[tag.anchor]; in_tail = nm[tag.tail]
    in_lspine = nm[lspine]; in_lleaf = nm[lleaf]; in_rspine = nm[rspine]
    in_rleaf = nm[rleaf] if rleaf is not None else None

    if right_kind == 'zero':
        # collapse-to-zero: only the left zero spine+leaf survive, as the value.
        out_val_spine = g2.add_node(); out_val_leaf = g2.add_node()
        labels[out_val_spine.id] = 'out_value_spine'; labels[out_val_leaf.id] = 'out_value_leaf'
        g2.add_edge(in_lspine, out_val_spine, EdgeType.OPERATIONAL)
        g2.add_edge(in_lleaf, out_val_leaf, EdgeType.OPERATIONAL)
        # HANDLE MAPS ONTO the surviving value => parent -OP-> handle is
        # redirected onto the zero spine (redirects rewrite both endpoints).
        g2.add_edge(nm[handle], out_val_spine, EdgeType.OPERATIONAL)
        _ocm(g2, out_val_spine, out_val_leaf)             # bit pointer (leaf bit 0)
        _ph_both(g2, out_val_spine, ph)                   # preserve redirected parent pointer
        # everything else — ring, anchor, tail, right spine+leaf — matched, unmapped: DELETED.
        name = 'sub_init_a0_zero'
    else:
        # finished frame: ONLY the tail is deleted (matched, no correspondent).
        sz = len(cyc)
        out_cyc = [g2.add_node() for _ in range(sz - 1)]
        out_handle = g2.add_node(); out_cyc.append(out_handle)
        for i, o in enumerate(out_cyc):
            labels[o.id] = f'out_cyc{i}'
        labels[out_handle.id] = 'out_handle'
        out_anchor = g2.add_node(); labels[out_anchor.id] = 'out_anchor'
        out_lspine = g2.add_node(); out_lleaf = g2.add_node()
        labels[out_lspine.id] = 'out_left_spine'; labels[out_lleaf.id] = 'out_left_leaf'
        out_rspine = g2.add_node(); labels[out_rspine.id] = 'out_right_spine'
        out_rleaf = None
        if in_rleaf is not None:
            out_rleaf = g2.add_node(); labels[out_rleaf.id] = 'out_right_leaf'

        for ic, oc in zip(in_cyc, out_cyc):
            g2.add_edge(ic, oc, EdgeType.OPERATIONAL)
        g2.add_edge(in_anchor, out_anchor, EdgeType.OPERATIONAL)
        g2.add_edge(in_lspine, out_lspine, EdgeType.OPERATIONAL)
        g2.add_edge(in_lleaf, out_lleaf, EdgeType.OPERATIONAL)
        g2.add_edge(in_rspine, out_rspine, EdgeType.OPERATIONAL)
        if in_rleaf is not None:
            g2.add_edge(in_rleaf, out_rleaf, EdgeType.OPERATIONAL)
        # in_tail: NO mapping edge => deleted. That IS the finalise.

        for i in range(sz):
            g2.add_edge(out_cyc[i], out_cyc[(i + 1) % sz], EdgeType.STRUCTURAL)
        g2.add_edge(out_cyc[0], out_anchor, EdgeType.STRUCTURAL)
        _ocm(g2, out_cyc[0], out_lspine)                  # port pointers survive
        _ocm(g2, out_cyc[1], out_rspine)
        _ocm(g2, out_lspine, out_lleaf)                   # left zero bit pointer
        if out_rleaf is not None:
            _ocm(g2, out_rspine, out_rleaf)
            g2.add_edge(out_rleaf, out_rleaf, EdgeType.STRUCTURAL)   # right bit 1 ('one')
        else:
            _ph_both(g2, out_rspine, ph)                  # 'multi': leaf+chain external, preserved
        _ph_both(g2, out_handle, ph)                      # parent -OP-> handle preserved
        name = f'sub_init_a0_{right_kind}'
    return OperationDefinition(name=name, pattern=p, graph2=g2), labels


def build_all():
    """All 33 variants: 24 plain + 2 both-single + 4 marker + 3 a0."""
    out = {}
    for lb in (0, 1):
        for rb in (0, 1):
            for ls in ('single', 'term', 'cont'):
                for rs in ('single', 'term', 'cont'):
                    if ls == 'single' and lb == 0:
                        continue                      # a0 family, below
                    op, lab = build_labeled(lb, rb, ls, rs)
                    out[op.name] = (op, lab)
    for kind in ('zero', 'one', 'multi'):
        op, lab = build_a0(kind)
        out[op.name] = (op, lab)
    return out


if __name__ == '__main__':
    rules = build_all()
    fam = {}
    for name in rules:
        f = name.split('_')[2]
        fam[f] = fam.get(f, 0) + 1
    print(f'total: {len(rules)}  by family: {fam}')
