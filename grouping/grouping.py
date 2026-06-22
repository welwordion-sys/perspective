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


def _canon_etype(e):
    """Canonical string form of an edge type. _input_relations returns EdgeType
    enums for registered rules; clean-table carrier adapters use bare strings
    ('struct'/'op'). Normalizing to a canonical string at the relation boundary
    makes every downstream `==` comparison compare like with like, so a mixed
    group (registered + clean-table) cannot silently fail with zero candidates.

    EdgeType.STRUCTURAL/'struct'/'STRUCTURAL' -> 'struct';
    EdgeType.OPERATIONAL/'op'/'OPERATIONAL'   -> 'op'."""
    s = str(e).split('.')[-1].lower()  # 'EdgeType.STRUCTURAL' -> 'structural'
    if s.startswith('struct'):
        return 'struct'
    if s.startswith('op'):  # 'operational' or 'op'
        return 'op'
    return s


def _profile(op):
    """Per-rule: view, typed-out relations among bind targets, variant-indep feature.
    Relation edge types are CANONICALIZED to strings (see _canon_etype) so etype
    equality downstream is source-agnostic."""
    v = derive_match_view(op.graph2)
    raw_rel = _input_relations(op.graph2, v)         # src -> [(tgt, etype)]
    rel = {src: [(t, _canon_etype(e)) for (t, e) in lst]
           for src, lst in raw_rel.items()}
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


def _pick_group_anchor(prof, names):
    """Group-stable, hub-based anchor selection (KB grouping_anchor_picks_the_delta).

    The old per-rule max-degree picker chose the highest-degree unique node, which
    for bit_add carriers lands in the result-buffer region — exactly where the
    result-width delta lives — so it anchored ON the delta and raised a false
    mismatch.

    The fix (corrected against the real carriers): the anchor must be the OP/cyc
    hub (feature (1,0,2,1) for these carriers), but that node is NOT necessarily
    unique-by-feature in every member — the multibit-result delta gives node 19 a
    placeholder crossing that bumps its struct_out to match the hub's, so a
    strict per-member-uniqueness gate wrongly discards the hub and falls back to a
    degenerate leaf. So the gate is RESOLVABILITY, not uniqueness:

      1. A feature is a CANDIDATE iff present in every member and is a hub in canon
         (>=1 out-relation). Bit-value self-loops are already excluded from the
         feature, so a feature shared across members marks shared skeleton.
      2. For each member, resolve the feature to ONE node by neighbour-signature:
         among nodes of that feature, the anchor is the one whose multiset of
         (out-relation edge-type, neighbour-feature) matches canon's anchor. This
         disambiguates feature-twins structurally (same mechanism the growth uses),
         instead of requiring there be no twin at all.
      3. Pick the candidate feature that is the best canon hub (most out-relations).

    Returns {name: anchor_node} or raises GroupCoreError if no feature resolves
    uniquely in every member.
    """
    canon = names[0]

    def feat_nodes(nm, f):
        v, rel, feat = prof[nm]
        return [n for n in v.bind_targets if feat[n] == f]

    def out_sig(nm, n):
        # multiset of (edge_type, neighbour_feature) over out-relations.
        # Sort by string keys: edge types may be EdgeType enums (registered rules)
        # which are not orderable, or strings (clean-table carriers).
        v, rel, feat = prof[nm]
        return tuple(sorted(((str(e), feat[t]) for (t, e) in rel.get(n, [])),
                            key=lambda x: (x[0], x[1])))

    # canon features that are hubs (have out-relations)
    _, canon_rel, canon_feat = prof[canon]
    canon_by_feat = collections.defaultdict(list)
    for n in prof[canon][0].bind_targets:
        canon_by_feat[canon_feat[n]].append(n)
    # candidate features: present in every member, hub in canon
    candidate_feats = []
    for f, ns in canon_by_feat.items():
        if not any(len(prof[canon][2].get(n, [])) > 0 for n in ns):
            continue
        if all(feat_nodes(nm, f) for nm in names):
            candidate_feats.append(f)
    if not candidate_feats:
        raise GroupCoreError("no shared hub feature present in every member")

    def resolve(nm, f, canon_node):
        """Resolve feature f in member nm to the node matching canon_node's
        out-signature. Returns the node or None if 0 or >1 match."""
        target = out_sig(canon, canon_node)
        matches = [n for n in feat_nodes(nm, f) if out_sig(nm, n) == target]
        return matches[0] if len(matches) == 1 else None

    # prefer the candidate feature that is the best canon hub
    def canon_hub(f):
        return max(len(prof[canon][2].get(n, [])) for n in canon_by_feat[f])
    for f in sorted(candidate_feats, key=lambda f: (canon_hub(f), f), reverse=True):
        # canon anchor node = the hub-est node of this feature in canon
        canon_node = max(canon_by_feat[f], key=lambda n: len(prof[canon][2].get(n, [])))
        resolved = {canon: canon_node}
        ok = True
        for nm in names[1:]:
            r = resolve(nm, f, canon_node)
            if r is None:
                ok = False
                break
            resolved[nm] = r
        if ok:
            return resolved

    raise GroupCoreError(
        "no shared hub feature resolves to a unique corresponding node in every member"
    )


def group_core(rules):
    """rules: list[OperationDefinition]. Returns dict with shared subgraph (in
    canon = rules[0] node space), shared edge list, and per-rule delta nodes."""
    if not rules:
        raise GroupCoreError("empty rule list")
    names = [r.name for r in rules]
    prof = {r.name: _profile(r) for r in rules}

    # Group-stable, hub-based anchor (KB grouping_anchor_picks_the_delta).
    # Replaces the per-rule max-degree picker that anchored on the result-width
    # delta and raised false mismatches.
    anchors = _pick_group_anchor(prof, names)

    canon = rules[0].name
    # correspondence: canon_node -> {name: node}
    corr = {}
    start = anchors[canon]
    corr[start] = {nm: anchors[nm] for nm in names}

    q = collections.deque([start])
    visited = {start}

    def typed_out(nm, node):
        return prof[nm][1].get(node, [])

    def typed_in(nm, node):
        # incoming typed relations (src, etype) — rebuilt from rel each call;
        # cheap at these graph sizes.
        res = []
        for s, lst in prof[nm][1].items():
            for (t, e) in lst:
                if t == node:
                    res.append((s, e))
        return res

    def disambiguate(nm, cands, ctgt):
        """Among feature-equal candidates in member `nm`, keep those whose typed
        edges to ALREADY-corresponded nodes match canon ctgt's edges to the
        corresponding canon nodes. Structural disambiguation, not a guess: a true
        correspondent must agree with canon on every edge to a node already placed.
        Returns the filtered candidate list (possibly still >1 if genuinely
        symmetric, in which case the caller bails — fail closed)."""
        # canon ctgt's edges to/from already-placed canon nodes
        canon_out = [(t, e) for (t, e) in typed_out(canon, ctgt) if t in corr]
        canon_in  = [(s, e) for (s, e) in typed_in(canon, ctgt) if s in corr]
        kept = []
        for c in cands:
            ok = True
            # every canon out-edge to a placed node must exist from c to that
            # node's correspondent in nm
            for (t, e) in canon_out:
                want = corr[t][nm]
                if not any(tt == want and ee == e for (tt, ee) in typed_out(nm, c)):
                    ok = False; break
            if ok:
                for (s, e) in canon_in:
                    want = corr[s][nm]
                    if not any(ss == want and ee == e for (ss, ee) in typed_in(nm, c)):
                        ok = False; break
            if ok:
                kept.append(c)
        return kept

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
                if len(cands) > 1:
                    # disambiguate by edges to already-placed correspondents
                    cands = disambiguate(nm, cands, ctgt)
                # fail closed: still not exactly one => not a clean core member
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
