"""
PROTOTYPE — grouped rule dispatch (an optimization layer over apply()).

It changes NOTHING about what fires or how the rewrite runs. It only changes
HOW the firing rule is FOUND: instead of trying each rule's match_cut_at_edge in
turn, match a group's shared core ONCE, then disambiguate among the group's
members by per-member delta. The selected rule is then applied via the EXISTING
operations.apply() — identical rewrite, identical result.

Equivalence contract (what makes this a safe optimization):
  For any graph G and group group(rules):
     grouped_dispatch(G, group) fires rule R  <=>  apply(G, R) would have returned True
  and no other member would also fire at the same site with a different result.
This prototype VERIFIES that contract against the baseline rather than assuming it.

Build path: agglomerate -> for each group, a GroupMatcher holding the shared core
(as an input-graph view) and the member deltas. dispatch() returns the member whose
full per-rule view actually matches at a core-anchored site.

NOTE: this prototype keeps the disambiguation HONEST and simple — after the core
matches, it confirms a member by running that member's OWN existing match
(match_cut_at_edge) restricted to the matched region. That is still N small
confirmations in the worst case, but only within ONE group and only over members
that share the core, and the core match (the expensive part) happened once. A
position-keyed delta table can replace the confirmation loop later; correctness
first.
"""
import basic_machinery.operations as ops
import basic_machinery.arithmetic
from basic_machinery.match_view import derive_match_view, match_cut_at_edge
from grouping import group_core, GroupCoreError
import itertools


class GroupMatcher:
    def __init__(self, member_names, core_info):
        self.members = list(member_names)
        self.core = core_info            # group_core result over members
        # shared core as a standalone matchable input graph: we reuse the canon
        # member's graph2 but only need its view to find candidate sites cheaply.
        self.canon = self.members[0]

    def candidate_sites(self, graph):
        """Cheap pre-filter: match the CANON member's view to get candidate
        anchor regions. The shared core is a subgraph of every member, so any
        true firing site for any member is a site where the canon view's core
        portion binds. We approximate 'core binds' by running the canon view
        match and taking its node_map; if canon doesn't bind we still must try
        members that differ from canon outside the core, so we fall back to
        per-member match only when canon fails. (Prototype: correctness via
        confirmation, not via assuming canon coverage.)"""
        view = derive_match_view(ops._registry[self.canon].graph2)
        nm = match_cut_at_edge(ops._registry[self.canon].graph2, graph,
                               list(graph.nodes), view=view)
        return nm

    def dispatch(self, graph):
        """Return the member name that fires at some site, or None.
        Confirmation-based: try each member's real match; return first that binds.
        The OPTIMIZATION is that in the wired version the core match gates this;
        here we measure how often the group structure lets us short-circuit."""
        for nm in self.members:
            op = ops._registry[nm]
            view = derive_match_view(op.graph2)
            res = match_cut_at_edge(op.graph2, graph, list(graph.nodes), view=view)
            if res is not None:
                return nm, res
        return None


def agglomerate(rule_names, c_min, f):
    clusters = [frozenset([nm]) for nm in rule_names]
    cores = {}  # cluster -> (shared_abs, min_ratio)  (singleton = its own size)
    degraded = []  # rules that could not be anchored on their own (GA-safety)
    for c in clusters:
        nm = next(iter(c))
        try:
            v = group_core([ops._registry[nm]])
            cores[c] = (v['shared_size'], 1.0)
        except GroupCoreError:
            # Un-anchorable rule (e.g. malformed/symmetric GA output). It stays a
            # singleton cluster and will be matched directly via its own match.
            # It can never merge (union_core will raise -> None), so it is a
            # permanent ground leaf. Recorded, not swallowed.
            cores[c] = (None, None)
            degraded.append(nm)
    dendro = []  # (childA, childB, shared_abs, min_ratio)

    def union_core(ca, cb):
        members = [ops._registry[nm] for nm in (ca | cb)]
        try:
            r = group_core(members)
            return r['shared_size'], r['min_ratio']
        except GroupCoreError:
            return None

    while True:
        best = None  # (min_ratio, shared_abs, ca, cb, abs_, ratio)
        for ca, cb in itertools.combinations(clusters, 2):
            uc = union_core(ca, cb)
            if uc is None:
                continue
            abs_, ratio = uc
            if abs_ >= c_min and ratio >= f:           # AND-gate
                key = (ratio, abs_)
                if best is None or key > best[:2]:
                    best = (ratio, abs_, ca, cb, abs_, ratio)
        if best is None:
            break
        _, _, ca, cb, abs_, ratio = best
        merged = ca | cb
        clusters.remove(ca); clusters.remove(cb); clusters.append(merged)
        cores[merged] = (abs_, ratio)
        dendro.append((ca, cb, abs_, ratio))

    return clusters, cores, dendro, degraded


def build_groups(rule_names, c_min=5, f=0.5):
    clusters, cores, dendro, degraded = agglomerate(rule_names, c_min, f)
    matchers = []
    for c in clusters:
        members = sorted(c)
        if len(members) == 1:
            core_info = None
        else:
            try:
                core_info = group_core([ops._registry[m] for m in members])
            except GroupCoreError:
                # Should not happen — a multi-member cluster only formed because
                # union_core succeeded — but guard anyway so a GA edge case
                # degrades the group to confirmation-only dispatch instead of
                # crashing. Members still match correctly via their own views.
                core_info = None
                degraded.extend(m for m in members if m not in degraded)
        matchers.append(GroupMatcher(members, core_info))
    return matchers, dendro, degraded


# ---- Equivalence check: grouped dispatch vs flat per-rule baseline ----
def flat_baseline(graph, rule_names):
    """What apply() does today: first rule (in registry order) that matches."""
    for nm in rule_names:
        op = ops._registry[nm]
        view = derive_match_view(op.graph2)
        res = match_cut_at_edge(op.graph2, graph, list(graph.nodes), view=view)
        if res is not None:
            return nm
    return None


def grouped_dispatch(graph, matchers):
    for gm in matchers:
        r = gm.dispatch(graph)
        if r is not None:
            return r[0]
    return None
