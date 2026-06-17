"""
Rule grouping procedure (start version, f=0.5).

group_core(rules): anchored shared-subgraph growth with FORCED-UNIQUE
correspondence. Returns (shared_canon_nodes, shared_edges, delta_per_rule).
Raises GroupCoreError if correspondence is ambiguous or the grown subgraph is
not identical across all members.

Variant-independent node feature: (op_out, op_in, struct_out, struct_in) over
bind targets. Structural self-loop (bit value) is deliberately EXCLUDED — it is
delta, read at dispatch time off the bound position.
"""
from __future__ import annotations
import collections
from basic_machinery.match_view import derive_match_view, _input_relations
from basic_machinery.graph import EdgeType, Edge


class GroupCoreError(Exception):
    pass


def _profile(op):
    """Per-rule: view, typed-out relations among bind targets, variant-indep feature."""
    v = derive_match_view(op.graph2)
    rel = _input_relations(op.graph2, v)            # src -> [(tgt, etype)]
    feat = {}
    for n in v.bind_targets:
        d = v.expected_degree[n]
        feat[n] = (
            d.get((EdgeType.OPERATIONAL, 'out'), 0),
            d.get((EdgeType.OPERATIONAL, 'in'), 0),
            d.get((EdgeType.STRUCTURAL, 'out'), 0),
            d.get((EdgeType.STRUCTURAL, 'in'), 0),
        )
    return v, rel, feat


def _pick_anchor(v, feat):
    """Deterministic unique anchor: the feature that occurs exactly once, chosen
    by max op_out then lexicographic feature. Returns (node, feature).
    Raises if no unique-feature node exists (rule needs multi-anchor; out of scope
    for the start version)."""
    by_feat = collections.defaultdict(list)
    for n in v.bind_targets:
        by_feat[feat[n]].append(n)
    uniques = [(f, ns[0]) for f, ns in by_feat.items() if len(ns) == 1]
    if not uniques:
        raise GroupCoreError("no unique-feature anchor; multi-anchor seeding not in start version")
    # max op_out, then max struct_out, then lexicographic feature
    uniques.sort(key=lambda fn: (fn[0][0], fn[0][2], fn[0]), reverse=True)
    f, n = uniques[0]
    return n, f


def group_core(rules):
    """rules: list[OperationDefinition]. Returns dict with shared subgraph (in
    canon = rules[0] node space), shared edge list, and per-rule delta nodes."""
    if not rules:
        raise GroupCoreError("empty rule list")
    names = [r.name for r in rules]
    prof = {r.name: _profile(r) for r in rules}

    # Anchor in each rule, by feature. All anchors must share the SAME feature.
    anchors = {}
    anchor_feat = None
    for r in rules:
        v, rel, feat = prof[r.name]
        node, f = _pick_anchor(v, feat)
        if anchor_feat is None:
            anchor_feat = f
        elif f != anchor_feat:
            raise GroupCoreError(f"anchor feature mismatch: {r.name} has {f}, expected {anchor_feat}")
        anchors[r.name] = node

    canon = rules[0].name
    # correspondence: canon_node -> {name: node}
    corr = {}
    start = anchors[canon]
    corr[start] = {nm: anchors[nm] for nm in names}

    q = collections.deque([start])
    visited = {start}

    def typed_out(nm, node):
        return prof[nm][1].get(node, [])

    while q:
        cnode = q.popleft()
        for (ctgt, et) in typed_out(canon, cnode):
            cfeat = prof[canon][2][ctgt]
            per = {}
            ok = True
            for nm in names:
                src_nm = corr[cnode][nm]
                cands = [t for (t, e) in typed_out(nm, src_nm)
                         if e == et and prof[nm][2][t] == cfeat]
                # FORCED-UNIQUE: ambiguity at a growth step => not a clean core member
                if len(cands) != 1:
                    ok = False
                    break
                if ctgt in corr:
                    if corr[ctgt][nm] != cands[0]:
                        ok = False
                        break
                per[nm] = cands[0]
            if not ok:
                continue
            if ctgt not in corr:
                corr[ctgt] = per
            if ctgt not in visited:
                visited.add(ctgt)
                q.append(ctgt)

    # Strict identity check: the shared EDGE set must be present in every member
    # between corresponding endpoints (both directions of typed_out already cover it).
    shared_edges = []
    for cnode in corr:
        for (ctgt, et) in typed_out(canon, cnode):
            if ctgt not in corr:
                continue
            present_all = all(
                any(t == corr[ctgt][nm] and e == et for (t, e) in typed_out(nm, corr[cnode][nm]))
                for nm in names
            )
            if present_all:
                shared_edges.append((cnode, ctgt, et))
            else:
                raise GroupCoreError(
                    f"edge {cnode}->{ctgt} ({et}) in correspondence but not present in all members"
                )

    # delta per rule = bind targets not in the shared correspondence image
    delta = {}
    for nm in names:
        img = {corr[c][nm] for c in corr}
        delta[nm] = [n for n in prof[nm][0].bind_targets if n not in img]

    # ratio against the SMALLEST member (worst case): shared / total bind targets
    ratios = {nm: len(corr) / len(prof[nm][0].bind_targets) for nm in names}

    return {
        "names": names,
        "shared_size": len(corr),
        "shared_edges": shared_edges,
        "corr": corr,
        "delta": delta,
        "ratios": ratios,
        "min_ratio": min(ratios.values()),
    }
