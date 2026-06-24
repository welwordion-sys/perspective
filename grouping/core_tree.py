"""
core_tree.py — subgroup core tree for rule family hierarchy.

Data structure:
    CoreNode
        members     : frozenset of graph labels in this subgroup
        core_edges  : set of Edge — edges shared by all members
        delta_in    : edges in parent's core NOT in this core
                      (structure the parent subgroup shares but this one doesn't)
        children    : list[CoreNode] — sub-subgroups

The root is the full family core (intersection of all members).
Each child is a subgroup whose core is a superset of the parent's core.
Moving DOWN the tree = more members = smaller core = more delta_in.
Moving UP the tree = fewer members = larger core = richer subgroup.

Build strategy:
    1. Compute all pairwise cores.
    2. Start from the full family (most members), work down by similarity.
       At each step, the member whose removal GROWS the core the most
       forms a branch — that branch's core is the subgroup without it.
    3. Recurse on each branch.
    4. Keep all branch cores alive — they are valid subgroup rules.

Delta data:
    core(parent) - core(child) = edges that are shared within the child
    subgroup but NOT shared across the full parent group.
    These are candidate rule conditions that distinguish the subgroup.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from core_finder7 import find_core, _grow_from, _node_edges

Edge = tuple


@dataclass
class CoreNode:
    members:    frozenset           # graph labels in this subgroup
    core_edges: set[Edge]           # edges shared by all members
    delta_in:   set[Edge]           # parent.core - self.core (what this level lost)
    children:   list[CoreNode] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.core_edges)

    def __repr__(self):
        return (f"CoreNode(members={set(self.members)}, "
                f"core={self.size}, delta_in={len(self.delta_in)})")


def _pairwise_core(graphs: dict[str, list[Edge]]) -> dict[frozenset, set[Edge]]:
    """Compute core for every pair of graphs. Returns {frozenset({a,b}): core_edges}."""
    labels = list(graphs.keys())
    result = {}
    for i, la in enumerate(labels):
        for lb in labels[i+1:]:
            r = find_core(graphs[la], graphs[lb])
            result[frozenset({la, lb})] = r['safe_core']
    return result


def _group_core(
    members: frozenset,
    graphs: dict[str, list[Edge]],
    pairwise: dict[frozenset, set[Edge]],
) -> set[Edge]:
    """
    Find the core of a subgroup by sequential pairwise merge.
    Uses the member whose pairwise core with the current core is largest
    at each step (greedy similarity ordering).
    """
    if len(members) == 1:
        label = next(iter(members))
        return set(graphs[label])

    if len(members) == 2:
        key = frozenset(members)
        if key in pairwise:
            return set(pairwise[key])
        la, lb = list(members)
        r = find_core(graphs[la], graphs[lb])
        pairwise[key] = r['safe_core']
        return set(r['safe_core'])

    # Start with pairwise core of the two most similar members
    labels = list(members)
    best_pair = max(
        [(la, lb) for i,la in enumerate(labels) for lb in labels[i+1:]],
        key=lambda p: len(pairwise.get(frozenset(p),
            _group_core(frozenset(p), graphs, pairwise)))
    )
    current_core = set(pairwise.get(frozenset(best_pair),
        _group_core(frozenset(best_pair), graphs, pairwise)))
    remaining = set(members) - set(best_pair)

    # Greedily add members that reduce core the least
    while remaining:
        best_member = max(remaining,
            key=lambda m: len(_intersect_with(current_core, graphs[m])))
        current_core = _intersect_with(current_core, graphs[best_member])
        remaining.remove(best_member)

    return current_core


def _intersect_with(core_edges: set[Edge], B_edges: list[Edge]) -> set[Edge]:
    """
    Find edges in core_edges that have a correspondent in B_edges.
    Uses find_core treating core_edges as graph A.
    """
    if not core_edges:
        return set()
    r = find_core(list(core_edges), B_edges)
    return r['safe_core']


def build_tree(
    graphs: dict[str, list[Edge]],
    parent_core: set[Edge] | None = None,
    members: frozenset | None = None,
    pairwise: dict | None = None,
    min_members: int = 2,
) -> CoreNode:
    """
    Recursively build the core tree.

    graphs:  label -> edge list for each rule variant
    parent_core: core of the parent node (None for root)
    members: labels in this subgroup (None = all)
    pairwise: cache of pairwise cores
    min_members: stop branching below this subgroup size
    """
    if members is None:
        members = frozenset(graphs.keys())
    if pairwise is None:
        pairwise = _pairwise_core(graphs)

    # Core of this subgroup
    this_core = _group_core(members, graphs, pairwise)
    delta_in  = (parent_core - this_core) if parent_core is not None else set()

    node = CoreNode(
        members=members,
        core_edges=this_core,
        delta_in=delta_in,
    )

    if len(members) <= min_members:
        return node

    # Find branches: for each member, compute core without it
    # A branch is formed when removing a member GROWS the core significantly
    branch_cores = {}
    for label in members:
        sub = members - {label}
        sub_core = _group_core(sub, graphs, pairwise)
        growth = len(sub_core) - len(this_core)
        branch_cores[label] = (sub, sub_core, growth)

    # Form branches for members whose removal causes significant growth
    # Threshold: any growth > 0 is a meaningful branch
    branched = set()
    for label, (sub, sub_core, growth) in sorted(
            branch_cores.items(), key=lambda x: x[1][2], reverse=True):
        if growth > 0 and label not in branched:
            child = build_tree(
                graphs=graphs,
                parent_core=this_core,
                members=sub,
                pairwise=pairwise,
                min_members=min_members,
            )
            node.children.append(child)
            branched.add(label)

    return node


def print_tree(node: CoreNode, indent: int = 0) -> None:
    prefix = '  ' * indent
    print(f"{prefix}members={set(node.members)}  core={node.size}  delta_in={len(node.delta_in)}")
    for child in node.children:
        print_tree(child, indent+1)


def all_subgroup_cores(node: CoreNode) -> list[CoreNode]:
    """Return all nodes in the tree — every subgroup core."""
    result = [node]
    for child in node.children:
        result.extend(all_subgroup_cores(child))
    return result
