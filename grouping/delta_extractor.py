"""
delta_extractor.py — structural delta from core to variant.

Given:
  core_edges  : set of Edge in core (expressed in A's node IDs)
  node_map    : dict a_node -> variant_node  (from find_core subgraph)
  variant_edges: full edge set of the variant

The delta is the set of edges in the variant that have no correspondent
in the core. Each delta edge is expressed using core node labels
(not variant node IDs) — making it ID-agnostic and transferable to
any instance of the core.

For variants that introduce NEW nodes (not in the core mapping),
those nodes are given delta-local labels (d0, d1, ...) and their
attachment to core nodes is recorded.

Usage:
    r = find_core(A_edges, B_edges)
    _, node_map = r['subgraphs'][0]
    delta = extract_delta(r['safe_core'], node_map, variant_edges)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from collections import defaultdict

Edge = tuple  # (src, tgt, kind, type)


@dataclass(frozen=True)
class DeltaEdge:
    """
    An edge in the delta, with endpoints expressed as labels:
      core:N   — node N in the core (using core's node ID)
      delta:N  — new node N introduced by this variant's delta
    """
    src_label:    Any    # core node ID or delta int
    src_is_delta: bool
    tgt_label:    Any    # core node ID or delta int
    tgt_is_delta: bool
    kind:         str
    typ:          Any

    def __str__(self):
        sl = f"delta:{self.src_label}" if self.src_is_delta else f"core:{self.src_label}"
        tl = f"delta:{self.tgt_label}" if self.tgt_is_delta else f"core:{self.tgt_label}"
        return f"{sl} -[{self.kind},{self.typ}]-> {tl}"


@dataclass
class Delta:
    """
    Structural delta from core to variant.
    All edges expressed using core node labels or delta-local labels.
    """
    new_nodes:  list[tuple[int, DeltaEdge]] = field(default_factory=list)
    # (delta_id, first_attachment_edge) — the edge that introduces the new node

    new_edges:  list[DeltaEdge] = field(default_factory=list)
    # edges between already-placed nodes (core or earlier delta nodes)

    attachment_points: set[Any] = field(default_factory=set)
    # core node labels that delta edges attach to

    def total_steps(self) -> int:
        return len(self.new_nodes) + len(self.new_edges)

    def describe(self) -> None:
        print(f"Delta: {len(self.new_nodes)} new nodes, "
              f"{len(self.new_edges)} new edges")
        print(f"Attachment points (core nodes): {sorted(self.attachment_points)}")
        if self.new_nodes:
            print("New nodes:")
            for did, edge in self.new_nodes:
                print(f"  delta:{did}  via  {edge}")
        if self.new_edges:
            print("New edges:")
            for e in self.new_edges:
                print(f"  {e}")


def extract_delta(
    core_edges:    set[Edge],
    node_map:      dict[Any, Any],   # core_node -> variant_node
    variant_edges: list[Edge],
) -> Delta:
    """
    Extract the structural delta from core to variant.

    core_edges:    edges confirmed as core (in core node ID space)
    node_map:      maps core node IDs to their variant node IDs
    variant_edges: full edge set of the variant (in variant node IDs)
    """
    # Reverse map: variant_node -> core_node label
    var_to_core: dict[Any, Any] = {v: c for c, v in node_map.items()}

    # Translate core edges into variant ID space for comparison
    core_in_variant: set[Edge] = set()
    for e in core_edges:
        vs = node_map.get(e[0])
        vt = node_map.get(e[1])
        if vs is not None and vt is not None:
            core_in_variant.add((vs, vt, e[2], e[3]))

    v_set = set(variant_edges)
    delta = Delta()
    delta.attachment_points = {
        var_to_core[v] for v in var_to_core
    }

    # Nodes in variant not in core mapping
    variant_nodes = {n for e in variant_edges for n in (e[0], e[1])}
    unplaced_var  = variant_nodes - set(var_to_core.keys())

    # Assign delta labels to unplaced nodes, in attachment order
    delta_labels: dict[Any, int] = {}
    next_id = [0]
    placed = set(var_to_core.keys())

    # Process unplaced nodes in BFS order from placed nodes
    from collections import deque
    idx = defaultdict(list)
    for e in variant_edges:
        idx[e[0]].append(e)
        if e[1] != e[0]:
            idx[e[1]].append(e)

    queue = deque(placed)
    seen  = set(placed)
    while queue:
        node = queue.popleft()
        for e in idx[node]:
            other = e[1] if e[0] == node else e[0]
            if other in seen:
                continue
            seen.add(other)
            if other in unplaced_var:
                did = next_id[0]; next_id[0] += 1
                delta_labels[other] = did
                # Record the attachment edge
                direction = 'out' if e[0] == node else 'in'
                if node in var_to_core:
                    att_label, att_is_delta = var_to_core[node], False
                else:
                    att_label, att_is_delta = delta_labels[node], True
                if direction == 'out':
                    attach_edge = DeltaEdge(
                        src_label=att_label, src_is_delta=att_is_delta,
                        tgt_label=did, tgt_is_delta=True,
                        kind=e[2], typ=e[3])
                else:
                    attach_edge = DeltaEdge(
                        src_label=did, src_is_delta=True,
                        tgt_label=att_label, tgt_is_delta=att_is_delta,
                        kind=e[2], typ=e[3])
                delta.new_nodes.append((did, attach_edge))
                placed.add(other)
            queue.append(other)

    def label(var_node):
        if var_node in var_to_core:
            return var_to_core[var_node], False
        return delta_labels[var_node], True

    # New edges: in variant but not in core, both endpoints placed
    emitted = set()
    for e in variant_edges:
        if e in core_in_variant:
            continue
        vs, vt, kind, typ = e
        if vs not in placed or vt not in placed:
            continue
        sl, sd = label(vs)
        tl, td = label(vt)
        de = DeltaEdge(sl, sd, tl, td, kind, typ)
        if de not in emitted:
            delta.new_edges.append(de)
            emitted.add(de)
            # Track attachment points
            if not sd:
                delta.attachment_points.add(sl)
            if not td:
                delta.attachment_points.add(tl)

    return delta
