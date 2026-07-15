"""
core_tree.py — incremental core tree with fingerprint gating and transitivity pruning.

Structure:
    Rules are LEAVES. Internal CoreNodes represent shared cores.
    A CoreNode's core_edges = edges shared by ALL rules in its subtree.
    Children are either rules (leaves) or CoreNodes (subgroups with larger cores).

    CoreNode (core=X)
    ├── CoreNode (core=X+extra, subgroup)
    │   ├── rule_A  (leaf)
    │   └── rule_B  (leaf)
    └── rule_C  (leaf)

Insertion:
    1. Fingerprint gate: cheap upper-bound on possible core size before find_core.
    2. Transitivity bounds: use known pairwise results to tighten upper bound / warm seed.
    3. Walk top-down to find insertion point.
    4. If new rule shares larger core with a subset of existing leaves -> new CoreNode.
    5. Propagate upward surprises to strongly transitive neighbours.

Fingerprint:
    Per core node: (min_out_S, min_in_S, min_out_O, min_in_O, has_self_loop).
    A candidate node matches if it meets ALL minimums.
    Excess edges averaged across candidates -> predicted delta -> predicted c.

Transitivity:
    core(D,X) <= core(D,A) & core(A,X)  [subset property, sound upper bound]
    Exclusion: if upper bound < min_ratio -> skip find_core.
    Discovery: if find_core returns larger than predicted -> propagate to
               rules strongly transitive to X.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from collections import defaultdict
from core_finder import find_core, _grow_from, _node_edges
from delta_extractor import extract_delta, DeltaEdge

Edge = tuple  # (src, tgt, kind, type)
Fingerprint = tuple  # (min_out_S, min_in_S, min_out_O, min_in_O, has_self_loop)


# ---------------------------------------------------------------------------
# Fingerprint helpers
# ---------------------------------------------------------------------------

def _compute_fingerprints(edges: list[Edge]) -> dict[Any, Fingerprint]:
    """
    Compute minimum connectivity fingerprint for each node in an edge set.
    Used on cores (where edges ARE the minimum connectivity by definition).
    """
    out_s  = defaultdict(int)
    in_s   = defaultdict(int)
    out_o  = defaultdict(int)
    in_o   = defaultdict(int)
    self_l = defaultdict(bool)
    nodes  = set()

    for s, t, kind, _ in edges:
        nodes.add(s); nodes.add(t)
        if s == t:
            self_l[s] = True
            continue
        if kind == 'STRUCTURAL':
            out_s[s] += 1; in_s[t] += 1
        else:
            out_o[s] += 1; in_o[t] += 1

    return {
        n: (out_s[n], in_s[n], out_o[n], in_o[n], self_l[n])
        for n in nodes
    }


def _node_profile(edges: list[Edge]) -> dict[Any, Fingerprint]:
    """
    Compute actual connectivity profile for each node in a rule graph.
    Same structure as fingerprint but represents actual (not minimum) counts.
    """
    return _compute_fingerprints(edges)  # same computation, different semantics


def _fingerprint_gate(
    core_fps: dict[Any, Fingerprint],
    candidate_edges: list[Edge],
    min_ratio: float,
) -> tuple[bool, float]:
    """
    Cheap upper-bound check before running find_core.

    For each core node, find compatible candidates in the candidate graph
    (nodes meeting all fingerprint minimums). Average excess edges across
    candidates. Compute predicted c.

    Returns (should_try, predicted_c).
    should_try=False means predicted c < min_ratio — skip find_core.
    """
    if not core_fps:
        return True, 1.0

    cand_profiles = _node_profile(candidate_edges)
    total_core_nodes = len(core_fps)
    matchable = 0
    total_avg_excess = 0.0

    for core_node, cfp in core_fps.items():
        min_os, min_is, min_oo, min_io, need_sl = cfp
        # Find candidates that meet all minimums
        candidates = [
            n for n, (os, is_, oo, io, sl) in cand_profiles.items()
            if os >= min_os and is_ >= min_is
            and oo >= min_oo and io >= min_io
            and (not need_sl or sl)
        ]
        if not candidates:
            continue  # this core node has no compatible candidate
        matchable += 1
        # Average excess across candidates (excess = total degree - minimum degree)
        min_total = min_os + min_is + min_oo + min_io
        avg_excess = sum(
            (cand_profiles[c][0] + cand_profiles[c][1] +
             cand_profiles[c][2] + cand_profiles[c][3]) - min_total
            for c in candidates
        ) / len(candidates)
        total_avg_excess += avg_excess

    predicted_c = matchable / total_core_nodes if total_core_nodes else 0.0
    return predicted_c >= min_ratio, predicted_c


def _compute_delta_info(
    rule_edges: list[Edge],
    core_node_set: set,  # rule-space nodes that are in the core match
) -> tuple[dict, float]:
    """
    Compute delta fingerprint and delta ratio for a rule given its core match.

    delta_fingerprint: fingerprint over nodes NOT in core_node_set
    delta_ratio: fraction of rule edges where BOTH endpoints are outside core_node_set

    Used for cross-reference candidate filtering:
    - delta_ratio < cross_ref_min_delta -> skip (not enough delta for secondary core)
    - delta fingerprints incompatible -> skip (no structural basis for match)
    """
    delta_edges = [
        e for e in rule_edges
        if e[0] not in core_node_set and e[1] not in core_node_set
    ]
    delta_ratio = len(delta_edges) / len(rule_edges) if rule_edges else 0.0
    delta_fp = _compute_fingerprints(delta_edges)
    return delta_fp, delta_ratio


# ---------------------------------------------------------------------------
# CoreNode
# ---------------------------------------------------------------------------

@dataclass
class CoreNode:
    """
    Internal node = shared core of all rules in subtree.
    children = list of (CoreNode | str) — sub-CoreNodes or rule name leaves.
    """
    core_edges:   set[Edge]
    fingerprints: dict[Any, Fingerprint]   # core node -> fingerprint
    children:     list                      # list of CoreNode | str (rule name)
    parent:       CoreNode | None = field(default=None, repr=False)

    @property
    def size(self) -> int:
        return len(self.core_edges)

    @property
    def members(self) -> frozenset:
        """All rule names (leaves) in this subtree."""
        result = set()
        for child in self.children:
            if isinstance(child, str):
                result.add(child)
            else:
                result |= child.members
        return frozenset(result)

    def __repr__(self):
        return f"CoreNode(core={self.size}, children={len(self.children)}, members={set(self.members)})"


def _make_node(core_edges: set[Edge], parent: CoreNode | None = None) -> CoreNode:
    fps = _compute_fingerprints(list(core_edges))
    return CoreNode(core_edges=core_edges, fingerprints=fps, children=[], parent=parent)


# ---------------------------------------------------------------------------
# CoreTree
# ---------------------------------------------------------------------------

class CoreTree:
    """
    Live incremental core tree. Rules are leaves, CoreNodes are shared cores.

    Usage:
        tree = CoreTree()
        for name, edges in rules.items():
            tree.insert(name, edges)
    """

    def __init__(self, min_ratio: float = 0.3, cross_ref_min_delta: float = 0.2):
        self.min_ratio = min_ratio
        self.cross_ref_min_delta = cross_ref_min_delta  # min delta fraction for cross-ref
        self.root: CoreNode | None = None
        #: coreless rules seen before any root existed (see insert)
        self._pending_leaves: list[str] = []
        # Pairwise cache: frozenset({a, b}) -> (core_edges_in_a_space, node_map_a_to_b)
        self._pairwise: dict[frozenset, tuple[set[Edge], dict]] = {}
        # Rule edges cache
        self._rule_edges: dict[str, list[Edge]] = {}
        # Delta info per rule (computed at insert time, updated if core shrinks)
        # name -> (delta_fingerprint, delta_ratio, core_node_set_in_rule_space)
        self._rule_delta: dict[str, tuple[dict, float, set]] = {}
        # Per-rule map: core_node -> rule_node, built level by level as rule descends tree.
        # Each rule carries the full correspondence from root to its leaf node.
        # CoreNode IDs are the reference space — stable, path-independent.
        self._rule_map: dict[str, dict] = {}
        # Anchored-delta cache: (id(node), rule_name) -> canonical frozenset.
        # Invalidated implicitly per node identity — a node whose core_edges
        # changes (shrink/lift) is a structurally different node going forward;
        # stale entries keyed on its old id() simply stop being looked up since
        # we always pass the live node object.
        self._delta_cache: dict[tuple[int, str], frozenset] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def insert(self, name: str, edges: list[Edge]) -> None:
        """Insert a new rule into the tree."""
        self._rule_edges[name] = edges

        # A rule with no edges in its match view cannot carry a core: the MCS
        # of an empty edge set with anything is empty. If such a rule lands at
        # the root (insert order decides this — the registry's first rule is
        # add_zero_collapse, which binds a single node and therefore yields
        # zero relations), the root core is empty and NOTHING can group
        # beneath it. Measured: full registry 257 rules -> 1 core node, all
        # flat; the same 257 with these rules held out -> 55 core nodes.
        # Such rules belong at a leaf, not at the root. This mirrors the
        # existing "fingerprint excluded everywhere -> add as leaf at root"
        # path below; the only reason it did not apply was that the FIRST
        # insert bypassed every check.
        if not edges:
            self._rule_delta[name] = ({}, 0.0, set())
            self._rule_map[name] = {}
            if self.root is None:
                self._pending_leaves.append(name)
            else:
                self.root.children.append(name)
            return

        if self.root is None:
            # First rule — create root with trivial core (the rule itself)
            node = _make_node(set(edges))
            node.children.append(name)
            self.root = node
            self._rule_delta[name] = ({}, 0.0, set())
            self._rule_map[name] = {}
            # Rules parked before any root existed now attach as leaves.
            for parked in self._pending_leaves:
                node.children.append(parked)
            self._pending_leaves = []
            return

        # General case: walk tree to find insertion point (also handles the
        # second rule — root already exists as a 1-leaf node with core = the
        # first rule's FULL edges, so this naturally shrinks root via a
        # size-asymmetric subgraph-embedding test rather than jumping straight
        # to a same-size pairwise core, which risks a spurious total-graph
        # isomorphism on structurally symmetric rule families).
        placed = self._insert_into(self.root, name, edges)
        if not placed:
            # Fingerprint excluded everywhere — add as leaf at root with empty map
            self.root.children.append(name)
            self._rule_map[name] = {}

        # Compute and store delta info for cross-reference pass
        self._update_delta_info(name, edges)

    def all_rules(self) -> frozenset:
        return self.root.members if self.root else frozenset()

    def _update_delta_info(self, name: str, edges: list[Edge]) -> None:
        """
        Compute delta info for a rule based on its current core match.
        Finds the rule's position in the tree to get the core_node_set.
        """
        core_node_set = self._get_core_node_set(name)
        delta_fp, delta_ratio = _compute_delta_info(edges, core_node_set)
        self._rule_delta[name] = (delta_fp, delta_ratio, core_node_set)

    def _get_core_node_set(self, name: str) -> set:
        """
        Rule-space nodes covered by the core, from the rule's own map.
        _rule_map[name] maps core_node -> rule_node built level by level.
        Values are the rule-space nodes that correspond to core nodes.
        """
        return set(self._rule_map.get(name, {}).values())

    def cross_reference(self) -> int:
        """
        Cross-reference pass: find delta-only secondary cores between rules
        in different branches. These are shared structures entirely outside
        any existing core — not discoverable by stepwise growth.

        Returns number of new subgroups discovered.
        """
        # Refresh delta info — core may have shrunk since rules were inserted
        for name in self.all_rules():
            self._update_delta_info(name, self._rule_edges[name])

        rules = list(self.all_rules())
        new_subgroups = 0

        # Collect rules with sufficient delta for a secondary core
        candidates = [
            name for name in rules
            if name in self._rule_delta
            and self._rule_delta[name][1] >= self.cross_ref_min_delta
        ]

        for i, a in enumerate(candidates):
            for b in candidates[i+1:]:
                key = frozenset({a, b})
                if key in self._pairwise:
                    continue  # already compared

                fp_a, ratio_a, core_nodes_a = self._rule_delta[a]
                fp_b, ratio_b, core_nodes_b = self._rule_delta[b]

                # Delta fingerprint compatibility check
                should_try, _ = _fingerprint_gate(fp_a, self._rule_edges[b], self.min_ratio)
                if not should_try:
                    continue

                # Extract delta edges for both rules
                delta_a = [e for e in self._rule_edges[a]
                          if e[0] not in core_nodes_a and e[1] not in core_nodes_a]
                delta_b = [e for e in self._rule_edges[b]
                          if e[0] not in core_nodes_b and e[1] not in core_nodes_b]

                if not delta_a or not delta_b:
                    continue

                # find_core on delta regions only
                r = find_core(delta_a, delta_b)
                if r['ratio'] < self.min_ratio:
                    continue

                # Found a secondary core — insert new subgroup into tree
                # This is a new intermediate node connecting a and b
                # For now: record in pairwise cache and trigger re-insertion
                node_map = r['subgraphs'][0][1] if r['subgraphs'] else {}
                self._pairwise[key] = (r['safe_core'], node_map)
                new_subgroups += 1
                # TODO: restructure tree to reflect new subgroup

        return new_subgroups

    def print_tree(self, node: CoreNode | None = None, indent: int = 0) -> None:
        if node is None:
            node = self.root
        if node is None:
            print("<empty tree>")
            return
        prefix = '  ' * indent
        print(f"{prefix}CoreNode(core={node.size}, members={set(node.members)})")
        for child in node.children:
            if isinstance(child, str):
                print(f"{prefix}  [{child}]")
            else:
                self.print_tree(child, indent + 1)

    # ------------------------------------------------------------------
    # Pairwise cache
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Anchored delta (fragment identity)
    # ------------------------------------------------------------------
    #
    # Raw pairwise find_core(rule_A, rule_B) finds the BEST matching subgraph
    # under ANY valid node correspondence between A and B. Two rules carrying
    # structurally distinct, unrelated deltas can still score a spuriously
    # large pairwise core if an alternate (symmetric/coincidental) correspondence
    # happens to align that many edges — e.g. a "left operand" delta and a
    # "right operand" delta can align under a left<->right relabeling even
    # though they are not the same fragment. This is what causes order-
    # dependent / incorrect fusion: comparing rules directly to each other.
    #
    # Fix: never compare two rules to each other. Compare both to the SAME
    # third thing — this node's own core_edges — and compare the resulting
    # deltas as canonical, ID-agnostic DeltaEdge sets. Two rules that
    # genuinely carry the same fragment get IDENTICAL canonical deltas;
    # rules with different fragments do not coincide, regardless of any
    # alternate correspondence that might align them pairwise.

    def _anchored_delta(self, node: "CoreNode", name: str) -> frozenset:
        """
        Canonical delta of rule `name` beyond node.core_edges, expressed as a
        frozenset of normalized (src_label, src_is_delta, tgt_label, tgt_is_delta,
        kind, typ) tuples. Delta-local node ids are renumbered deterministically
        so that two rules introducing structurally-equivalent new nodes compare
        equal regardless of extraction order. Cached per (node, name).
        """
        key = (id(node), len(node.core_edges), name)
        cached = self._delta_cache.get(key)
        if cached is not None:
            return cached

        edges = self._rule_edges[name]
        r = find_core(list(node.core_edges), edges)
        core_edges = r['safe_core']
        node_map = r['subgraphs'][0][1] if r['subgraphs'] else {}
        delta = extract_delta(core_edges, node_map, edges)
        canon = self._canonicalize_delta(delta)
        self._delta_cache[key] = canon
        return canon

    @staticmethod
    def _canonicalize_delta(delta) -> frozenset:
        """
        Renumber delta-local node ids deterministically (sorted by their
        attachment-edge signature) and return a frozenset of plain tuples —
        comparable across independently-extracted Delta objects.
        """
        def attach_key(item):
            did, e = item
            return (e.src_is_delta, str(e.src_label), e.tgt_is_delta,
                    str(e.tgt_label), e.kind, str(e.typ))

        ordered = sorted(delta.new_nodes, key=attach_key)
        remap = {old_did: new_id for new_id, (old_did, _) in enumerate(ordered)}

        def relabel(label, is_delta):
            return remap[label] if is_delta else label

        out = set()
        for old_did, e in ordered:
            out.add((relabel(e.src_label, e.src_is_delta), e.src_is_delta,
                      relabel(e.tgt_label, e.tgt_is_delta), e.tgt_is_delta,
                      e.kind, e.typ))
        for e in delta.new_edges:
            out.add((relabel(e.src_label, e.src_is_delta), e.src_is_delta,
                      relabel(e.tgt_label, e.tgt_is_delta), e.tgt_is_delta,
                      e.kind, e.typ))
        return frozenset(out)

    def _anchored_delta_for_edges(self, outer_node: "CoreNode", edges: set, edges_id) -> frozenset:
        """
        Like _anchored_delta, but for an arbitrary edge-set rather than a stored
        rule (used to compare a CHILD's own core_edges against its parent's core —
        not a deep member's full edges, which could carry fragments the child's
        core itself doesn't require).
        """
        key = (id(outer_node), len(outer_node.core_edges), edges_id, len(edges))
        cached = self._delta_cache.get(key)
        if cached is not None:
            return cached

        edges_list = list(edges)
        r = find_core(list(outer_node.core_edges), edges_list)
        core_edges = r['safe_core']
        node_map = r['subgraphs'][0][1] if r['subgraphs'] else {}
        delta = extract_delta(core_edges, node_map, edges_list)
        canon = self._canonicalize_delta(delta)
        self._delta_cache[key] = canon
        return canon

    @staticmethod
    def _materialize_fragment_core(node: "CoreNode", frag: frozenset) -> set:
        """
        Translate a canonical delta fragment (frozenset of normalized tuples)
        back into a real edge-set in node.core_edges' own template space,
        allocating fresh symbolic ids for the fragment's delta-local nodes.
        The matcher is structural/id-agnostic, so these ids only need to be
        internally consistent — not meaningful in any other space.
        """
        existing_ids = set()
        for (s, t, _k, _ty) in node.core_edges:
            existing_ids.add(s)
            existing_ids.add(t)
        next_id = (max(existing_ids) + 1) if existing_ids else 0

        delta_id_map: dict = {}
        new_edges = set(node.core_edges)
        for (src_label, src_is_delta, tgt_label, tgt_is_delta, kind, typ) in frag:
            if src_is_delta:
                if src_label not in delta_id_map:
                    delta_id_map[src_label] = next_id
                    next_id += 1
                s = delta_id_map[src_label]
            else:
                s = src_label
            if tgt_is_delta:
                if tgt_label not in delta_id_map:
                    delta_id_map[tgt_label] = next_id
                    next_id += 1
                t = delta_id_map[tgt_label]
            else:
                t = tgt_label
            new_edges.add((s, t, kind, typ))
        return new_edges

    def _get_pairwise(
        self,
        a: str,
        b: str,
        warm_map: dict | None = None,
    ) -> tuple[set[Edge], dict]:
        """
        Get or compute pairwise core between rules a and b.
        Returns (core_edges_in_a_space, node_map_a_to_b).
        Uses warm_map as seed for _grow_from if provided.
        """
        key = frozenset({a, b})
        if key in self._pairwise:
            return self._pairwise[key]

        a_edges = self._rule_edges[a]
        b_edges = self._rule_edges[b]

        if warm_map:
            # Seeded grow from composed map
            seed_a = next(iter(warm_map))
            seed_b = warm_map[seed_a]
            matched, node_map = _grow_from(a_edges, b_edges, seed_a, seed_b)
            result = (matched, node_map)
        else:
            r = find_core(a_edges, b_edges)
            node_map = r['subgraphs'][0][1] if r['subgraphs'] else {}
            result = (r['safe_core'], node_map)

        self._pairwise[key] = result
        return result

    def _transitivity_bound(
        self,
        d: str,
        x: str,
    ) -> tuple[set[Edge] | None, dict | None]:
        """
        Upper bound on core(d, x) via transitivity through any known intermediary A.
        Returns (upper_bound_edges, warm_seed_map) or (None, None) if no bound available.
        Upper bound = core(d,A) & core(A,x) for best intermediary A.
        """
        best_bound: set[Edge] | None = None
        best_map: dict | None = None

        for key, (core_da, map_da) in self._pairwise.items():
            if d not in key:
                continue
            others = key - {d}
            if not others:
                continue
            a = next(iter(others))
            key_ax = frozenset({a, x})
            if key_ax not in self._pairwise:
                continue
            core_ax, map_ax = self._pairwise[key_ax]

            # Intersect in a's node ID space
            bound = core_da & core_ax  # both in a's space... actually core_da is in d's space
            # We need both in same space — use the size as proxy
            bound_size = min(len(core_da), len(core_ax))
            if best_bound is None or bound_size > len(best_bound):
                best_bound = bound  # approximate
                # Compose d->a->x map as warm seed
                inv_map_da = {v: k for k, v in map_da.items()}  # a->d
                composed: dict = {}
                for a_node, x_node in map_ax.items():
                    if a_node in inv_map_da:
                        composed[inv_map_da[a_node]] = x_node
                best_map = composed if composed else None

        return best_bound, best_map

    # ------------------------------------------------------------------
    # Tree insertion
    # ------------------------------------------------------------------

    def _match_against_core(
        self,
        name: str,
        edges: list[Edge],
        core_edges: set[Edge],
        fingerprints: dict,
        ref_member: str | None = None,
        parent_map: dict | None = None,
    ) -> tuple[bool, set[Edge], dict]:
        """
        Try to match rule `name` against a core edge set.

        parent_map: node correspondence already established at the parent level.
            Used as warm seed — we only need to grow into the delta beyond
            what the parent level already matched. This is the key reuse principle:
            level k+1 continues from level k's result, not from scratch.

        Returns (matched, core_in_rule_space, node_map_core_to_rule).
        matched=False means ratio < min_ratio.
        """
        # Fingerprint gate
        should_try, _ = _fingerprint_gate(fingerprints, edges, self.min_ratio)
        if not should_try:
            return False, set(), {}

        # Determine warm seed: parent_map takes priority (direct reuse of found work),
        # then transitivity bound for additional pruning.
        warm_map: dict | None = parent_map

        if ref_member is not None and warm_map is None:
            tb_core, tb_map = self._transitivity_bound(name, ref_member)
            if tb_core is not None:
                tb_ratio = len(tb_core) / len(core_edges) if core_edges else 0
                if tb_ratio < self.min_ratio:
                    return False, set(), {}
                warm_map = tb_map

        # Always use find_core for the node-level match. A warm seed via _grow_from
        # routinely undersizes matched_edges (single arbitrary seed pair), which then
        # poisons node.core_edges through the intersection lines in _insert_into and
        # lowers the fusion bar. warm_map is still used above as a transitivity early
        # exit (sound size check); it is not a substitute matcher here.
        r = find_core(list(core_edges), edges)
        matched_edges = r['safe_core']
        node_map = r['subgraphs'][0][1] if r['subgraphs'] else {}
        ratio = r['ratio']

        if ratio < self.min_ratio:
            return False, set(), {}

        return True, matched_edges, node_map

    def _insert_into(
        self,
        node: CoreNode,
        name: str,
        edges: list[Edge],
        parent_map: dict | None = None,
        accumulated_map: dict | None = None,
    ) -> bool:
        """
        Recursively insert rule `name` into the subtree rooted at `node`.
        Returns True if rule was placed somewhere in this subtree.
        Rule goes into exactly ONE place.

        parent_map: node_map from level k-1, used as warm seed for level k.
        accumulated_map: growing core_node->rule_node map built level by level.
            Each level extends it with new delta correspondences.
            When the rule is finally placed as a leaf, this map is stored
            as _rule_map[name] — the complete correspondence from root to leaf.
        """
        if accumulated_map is None:
            accumulated_map = {}

        ref_member = next(iter(node.members)) if node.members else None

        # Level k match — seeded from parent_map (reuses work from level k-1)
        matched, matched_core, node_map = self._match_against_core(
            name, edges, node.core_edges, node.fingerprints, ref_member,
            parent_map=parent_map
        )
        if not matched:
            return False

        # Extend accumulated map with new correspondences found at this level
        accumulated_map.update(node_map)

        # newN_core = what this node's core becomes after admitting `name`.
        # A node core is the intersection of all member graphs, so it can only
        # shrink or stay — never grow.
        newN_core = node.core_edges & matched_core
        shrank = len(newN_core) < len(node.core_edges)

        # CASE 2 (shrink): `name` lacks some of this node's core. Every PRIOR
        # member shared the old (larger) core by definition, so the prior members
        # are lifted into one child preserving the old core, and this node's core
        # drops to newN_core. `name` shares only newN_core with them, so it is
        # placed as a plain leaf here (it cannot also descend — the descend match
        # below would re-derive the same shrink). We handle the shrink first so the
        # tree is well-formed before placing `name`.
        if shrank:
            self._lift_prior_into_subgroup(node, newN_core)
            self._rule_map[name] = dict(accumulated_map)
            node.children.append(name)
            return True

        # CASE 1 (no shrink): `name` has everything this node requires.
        # Try to place deeper first (most-specific subgroup wins) — but only into
        # children whose ENTIRE core `name` contains. Coverage is tested by
        # comparing both `name` and the child's representative to THIS node's
        # core (anchored delta), never to each other directly — a direct
        # pairwise comparison can find a spuriously large match under an
        # unrelated alternate correspondence (e.g. a left-operand delta
        # aligning with a right-operand delta under relabeling). `name` covers
        # the child iff the representative's anchored delta is a SUBSET of
        # name's anchored delta (the child's extra structure is fully present
        # in name).
        delta_name = self._anchored_delta(node, name)
        for child in node.children:
            if isinstance(child, CoreNode):
                delta_child = self._anchored_delta_for_edges(
                    node, child.core_edges, id(child))
                if not delta_child <= delta_name:
                    continue  # `name` does not cover this subgroup's core — skip
                if self._insert_into(child, name, edges,
                                     parent_map=node_map,
                                     accumulated_map=accumulated_map):
                    return True

        # Could not descend — place here. Fusion: group existing leaves by their
        # EXACT anchored delta (their true fragment identity relative to this
        # node). A leaf qualifies to fuse with `name` only on EXACT equality —
        # not "shares more than node core" by raw size, which previously
        # conflated structurally-distinct same-size fragments (e.g. a left-
        # operand delta and a right-operand delta can score the same pairwise
        # size under an unrelated correspondence). Exact equality is what
        # correctly partitions e.g. left-only vs right-only deltas into
        # separate subgroups instead of merging them.
        leaf_members = [c for c in node.children if isinstance(c, str)]

        if delta_name:  # only attempt fusion when name actually has extra structure
            matching_leaves = [
                leaf for leaf in leaf_members
                if self._anchored_delta(node, leaf) == delta_name
            ]
        else:
            matching_leaves = []

        self._rule_map[name] = dict(accumulated_map)

        if matching_leaves:
            sub_core = self._materialize_fragment_core(node, delta_name)
            sub_node = _make_node(sub_core, parent=node)
            sub_node.children.extend(matching_leaves)
            sub_node.children.append(name)
            for leaf in matching_leaves:
                node.children.remove(leaf)
            node.children.append(sub_node)
            self._propagate_discovery(node, sub_node, sub_core)
        else:
            node.children.append(name)

        return True

    def _lift_prior_into_subgroup(
        self,
        node: CoreNode,
        new_core: set[Edge],
    ) -> None:
        """
        Core-shrink event (spec step4). The node core is dropping to `new_core`,
        which is strictly smaller than its current core. Every existing child
        shared the OLD larger core, so they are lifted into a single child
        CoreNode that preserves the old core; the node core then drops to
        `new_core`. No propagation (the lifted group has strictly fewer members).

        Guards:
          - strictly-larger: the lifted subgroup's core (old core) is strictly
            larger than `new_core` by construction (we only enter on a real
            shrink), so it is a valid subgroup, never an equal-core chain link.
          - no-redundant-wrapper: if the node already holds exactly one child and
            it is a CoreNode, that child already preserves a larger core — do not
            wrap it again; just shrink this node's core.
        """
        old_core = node.core_edges
        prior = list(node.children)

        if len(prior) == 1 and isinstance(prior[0], CoreNode):
            # Single existing subgroup already preserves the larger core.
            node.core_edges = new_core
            node.fingerprints = _compute_fingerprints(list(new_core))
            return

        if prior:
            sub_node = _make_node(old_core, parent=node)
            sub_node.children.extend(prior)
            for c in prior:
                if isinstance(c, CoreNode):
                    c.parent = sub_node
            node.children = [sub_node]

        node.core_edges = new_core
        node.fingerprints = _compute_fingerprints(list(new_core))

    def _propagate_discovery(
        self,
        parent: CoreNode,
        new_subgroup: CoreNode,
        new_core: set[Edge],
    ) -> None:
        """
        A larger core was discovered (new_subgroup). Check remaining leaves of parent
        for strong transitivity — if their known core with a subgroup member covers
        the new core region, they may belong in the subgroup too.
        """
        subgroup_members = list(new_subgroup.members)
        remaining_leaves = [c for c in parent.children
                           if isinstance(c, str) and c not in new_subgroup.members]

        for leaf in remaining_leaves:
            # Check if leaf is strongly transitive to any subgroup member
            for sm in subgroup_members:
                key = frozenset({leaf, sm})
                if key not in self._pairwise:
                    continue
                leaf_sm_core, _ = self._pairwise[key]
                # Strongly transitive = their core covers the new_core region
                # Proxy: core size >= new_core size
                if len(leaf_sm_core) >= len(new_core):
                    # Worth checking leaf against the new subgroup
                    leaf_edges = self._rule_edges[leaf]
                    r = find_core(list(new_core), leaf_edges)
                    if len(r['safe_core']) >= len(new_core) * self.min_ratio:
                        # Leaf belongs in subgroup
                        parent.children.remove(leaf)
                        new_subgroup.children.append(leaf)
                    break
