from __future__ import annotations
from dataclasses import dataclass, field
from typing import Iterator
from basic_machinery.graph import PerspectiveGraph, Node, Edge, EdgeType


@dataclass
class MatchResult:
    success: bool
    node_map: dict[Node, Node] = field(default_factory=dict)


@dataclass
class OperationDefinition:
    name: str
    pattern: PerspectiveGraph
    graph2s: PerspectiveGraph
    graph2o: PerspectiveGraph


_registry: dict[str, OperationDefinition] = {}


def register(operation: OperationDefinition) -> None:
    if operation.name in _registry:
        raise ValueError(f"Operation '{operation.name}' is already registered.")
    _registry[operation.name] = operation


def lookup(name: str) -> OperationDefinition:
    if name not in _registry:
        raise KeyError(f"No operation registered under '{name}'.")
    return _registry[name]


def _candidate_mappings(
    pattern_nodes: list[Node],
    graph_nodes: list[Node]
) -> Iterator[dict[Node, Node]]:
    from itertools import permutations
    for perm in permutations(graph_nodes, len(pattern_nodes)):
        yield dict(zip(pattern_nodes, perm))


def _mapping_is_valid(
    mapping: dict[Node, Node],
    pattern: PerspectiveGraph,
    graph: PerspectiveGraph
) -> bool:
    for edge in pattern.edges:
        mapped_source = mapping[edge.source]
        mapped_target = mapping[edge.target]
        expected = Edge(source=mapped_source, target=mapped_target, edge_type=edge.edge_type)
        if expected not in graph:
            return False
    return True


def match(
    pattern: PerspectiveGraph,
    graph: PerspectiveGraph,
    candidates: list[Node] | None = None,
) -> MatchResult:
    pattern_nodes = list(pattern.nodes)
    graph_nodes = candidates if candidates is not None else list(graph.nodes)
    if len(pattern_nodes) > len(graph_nodes):
        return MatchResult(success=False)
    for mapping in _candidate_mappings(pattern_nodes, graph_nodes):
        if _mapping_is_valid(mapping, pattern, graph):
            return MatchResult(success=True, node_map=mapping)
    return MatchResult(success=False)


def match_all(
    pattern: PerspectiveGraph,
    graph: PerspectiveGraph,
) -> list[MatchResult]:
    pattern_nodes = list(pattern.nodes)
    graph_nodes = list(graph.nodes)
    results = []
    for mapping in _candidate_mappings(pattern_nodes, graph_nodes):
        if _mapping_is_valid(mapping, pattern, graph):
            results.append(MatchResult(success=True, node_map=dict(mapping)))
    return results


def snapshot(graph: PerspectiveGraph) -> PerspectiveGraph:
    return graph.copy()


def revert(graph: PerspectiveGraph, snap: PerspectiveGraph) -> None:
    graph.restore(snap)


def _apply_pass(
    graph: PerspectiveGraph,
    node_map: dict[Node, Node],
    transition: PerspectiveGraph,
) -> dict[Node, Node]:
    """
    Apply one transformation pass using the transition graph.

    The transition graph encodes:
      - Input side: mirrors the real matched subgraph topology, with operational
        edges represented as marker chains (A->[S]->m->[S]->B, m->[OP]->m).
      - Output side: describes the desired final state of surviving nodes.
        STRUCTURAL edges are written as STRUCTURAL. Marker chains in the output
        side are written as OPERATIONAL edges into the real graph.
      - OPERATIONAL edges in the transition (non-self-loop): input->output mapping.

    Steps:
      1. Insert marker nodes for operational edges in real matched subgraph.
      2. Classify transition nodes (input vs output, excluding transition markers).
      3. Match transition input subgraph against real matched subgraph.
         Candidate pool excludes marker nodes.
      4. Follow OPERATIONAL edges in transition to build output_map.
         Collect nodes_to_delete and nodes_to_merge.
      4b. Delete merged nodes (rewriting edges to survivor).
          Delete nodes with no output.
          Remove all marker nodes.
      5. Write edges from transition output side into real graph.
         Plain STRUCTURAL edges -> STRUCTURAL.
         Marker chains -> OPERATIONAL.
    """
    matched_target_nodes = set(node_map.values())

    # ------------------------------------------------------------------
    # Step 1: Insert marker nodes for OPERATIONAL edges in matched subgraph.
    # A->[OP]->B becomes A->[S]->m, m->[S]->B, m->[OP]->m
    # Self-loops (e.g. tombstone) are left unchanged.
    # ------------------------------------------------------------------
    marker_nodes: set[Node] = set()
    for edge in list(graph.edges):
        if (
            edge.edge_type == EdgeType.OPERATIONAL
            and edge.source != edge.target
            and edge.source in matched_target_nodes
            and edge.target in matched_target_nodes
        ):
            graph.remove_edge(edge)
            m = graph.add_node()
            marker_nodes.add(m)
            graph.add_edge(edge.source, m, EdgeType.STRUCTURAL)
            graph.add_edge(m, edge.target, EdgeType.STRUCTURAL)
            graph.add_edge(m, m, EdgeType.OPERATIONAL)

    # ------------------------------------------------------------------
    # Step 2: Classify transition nodes.
    # OPERATIONAL non-self-loop edges define input (has_outgoing) and
    # output (has_incoming) sets. Transition nodes with operational
    # self-loops are markers — excluded from input/output classification.
    # ------------------------------------------------------------------
    has_outgoing: set[Node] = set()
    has_incoming: set[Node] = set()
    for edge in transition.edges:
        if edge.edge_type == EdgeType.OPERATIONAL and edge.source != edge.target:
            has_outgoing.add(edge.source)
            has_incoming.add(edge.target)
    output_only = has_incoming - has_outgoing
    transition_markers: set[Node] = {
        n for n in transition.nodes
        if Edge(source=n, target=n, edge_type=EdgeType.OPERATIONAL) in transition
    }
    input_nodes = set(transition.nodes) - output_only - transition_markers

    # ------------------------------------------------------------------
    # Step 3: Match transition input subgraph against real matched subgraph.
    # Marker nodes excluded from candidate pool.
    # ------------------------------------------------------------------
    input_subgraph = transition.subgraph(input_nodes)
    matched_subgraph = graph.subgraph(matched_target_nodes | marker_nodes)
    non_marker_candidates = list(matched_target_nodes)
    input_match = match(input_subgraph, matched_subgraph, candidates=non_marker_candidates)

    if not input_match.success:
        # Revert step 1: restore original operational edges, remove markers
        for m in list(marker_nodes):
            incoming = [e for e in graph.edges if e.target == m and e.source != m]
            outgoing = [e for e in graph.edges if e.source == m and e.target != m]
            for edge in list(graph.edges):
                if edge.source == m or edge.target == m:
                    graph.remove_edge(edge)
            if incoming and outgoing:
                graph.add_edge(incoming[0].source, outgoing[0].target, EdgeType.OPERATIONAL)
            graph.remove_node(m)
        return node_map
    print(f"input_match: { {k.id: v.id for k, v in input_match.node_map.items()} }")
    print(f"has_outgoing: {sorted(n.id for n in has_outgoing)}")

    # ------------------------------------------------------------------
    # Step 4: Follow OPERATIONAL edges in transition to build output_map.
    # output_map: transition output node -> real node
    # nodes_to_delete: input nodes with no outgoing OPERATIONAL edge (consumed)
    # nodes_to_merge: real node -> survivor
    # ------------------------------------------------------------------
    output_map: dict[Node, Node] = {}
    nodes_to_delete: set[Node] = set()
    nodes_to_merge: dict[Node, Node] = {}

    def follow_mapping(t_input: Node, real: Node) -> None:
        current_real = real
        # Only non-self-loop OPERATIONAL edges are mapping edges
        edges_from = [
            e for e in transition.edges_from(t_input, EdgeType.OPERATIONAL)
            if e.target != t_input
        ]
        print(f"follow_mapping t_input={t_input.id} real={real.id} edges_from={[e.target.id for e in edges_from]}")
        for i, edge in enumerate(edges_from):
            t_out = edge.target
            if t_out not in output_map:
                output_map[t_out] = current_real
                if i < len(edges_from) - 1:
                    current_real = graph.add_node()
            else:
                existing_real = output_map[t_out]
                if current_real != existing_real:
                    nodes_to_merge[current_real] = existing_real

    for t_input, real in input_match.node_map.items():
        if t_input in has_outgoing:
            follow_mapping(t_input, real)
        else:
            nodes_to_delete.add(real)
    print(f"nodes_to_delete: {sorted(n.id for n in nodes_to_delete)}")
    print(f"output_map after step 4: { {k.id: v.id for k, v in output_map.items()} }")
    # ------------------------------------------------------------------
    # Step 4b: Merge, delete, clean up markers.
    # ------------------------------------------------------------------

    # Merge: rewrite edges to survivor, remove merged node
    for real_node, survivor in nodes_to_merge.items():
        for edge in list(graph.edges):
            if edge.source == real_node or edge.target == real_node:
                graph.remove_edge(edge)
                new_src = survivor if edge.source == real_node else edge.source
                new_tgt = survivor if edge.target == real_node else edge.target
                candidate = Edge(source=new_src, target=new_tgt, edge_type=edge.edge_type)
                if candidate not in graph:
                    graph.add_edge(new_src, new_tgt, edge.edge_type)
        if real_node in graph:
            graph.remove_node(real_node)

    # Delete: remove all edges then remove node
    for real_node in nodes_to_delete:
        if real_node not in graph:
            continue
        for edge in list(graph.edges):
            if edge.source == real_node or edge.target == real_node:
                graph.remove_edge(edge)
        graph.remove_node(real_node)

    # Remove marker nodes (always temporary)
    for m in marker_nodes:
        if m not in graph:
            continue
        for edge in list(graph.edges):
            if edge.source == m or edge.target == m:
                graph.remove_edge(edge)
        graph.remove_node(m)

    # ------------------------------------------------------------------
    # Step 5: Write edges from transition output side into real graph.
    # Plain STRUCTURAL edges -> STRUCTURAL in real graph.
    # Marker chains (A->[S]->m->[S]->B, m->[OP]->m) -> OPERATIONAL in real graph.
    # ------------------------------------------------------------------
    # Identify transition marker nodes and collect nodes involved in marker chains
    marker_chain_nodes: set[Node] = set()
    for t_marker in transition_markers:
        incoming = [
            e for e in transition.edges
            if e.target == t_marker
            and e.source != t_marker
            and e.edge_type == EdgeType.STRUCTURAL
        ]
        outgoing = [
            e for e in transition.edges
            if e.source == t_marker
            and e.target != t_marker
            and e.edge_type == EdgeType.STRUCTURAL
        ]
        for inc in incoming:
            for out in outgoing:
                src_real = output_map.get(inc.source)
                tgt_real = output_map.get(out.target)
                if src_real is not None and tgt_real is not None:
                    candidate = Edge(source=src_real, target=tgt_real, edge_type=EdgeType.OPERATIONAL)
                    if candidate not in graph:
                        graph.add_edge(src_real, tgt_real, EdgeType.OPERATIONAL)
        marker_chain_nodes.add(t_marker)
        for inc in incoming:
            marker_chain_nodes.add(inc.source)
        for out in outgoing:
            marker_chain_nodes.add(out.target)

    # Write remaining STRUCTURAL edges (not part of marker chains)
    print(f"transition total edges: {len(list(transition.edges))}")
    print(f"transition structural edges total: {len([e for e in transition.edges if e.edge_type == EdgeType.STRUCTURAL])}")
    print(f"transition_markers: {[n.id for n in transition_markers]}")
    print(f"output_map keys: {sorted(k.id for k in output_map)}")

    for edge in transition.edges:
        if edge.edge_type != EdgeType.STRUCTURAL:
            continue
        print(f"  t:{edge.source.id}→t:{edge.target.id}  src_in_map={edge.source in output_map}  tgt_in_map={edge.target in output_map}  marker_skip={edge.source in transition_markers or edge.target in transition_markers}")
        if edge.source in transition_markers or edge.target in transition_markers:
            continue
        source = output_map.get(edge.source)
        target = output_map.get(edge.target)
        if source is None or target is None:
            continue
        candidate = Edge(source=source, target=target, edge_type=EdgeType.STRUCTURAL)
        if candidate not in graph:
            graph.add_edge(source, target, EdgeType.STRUCTURAL)
    return output_map


def apply(
    graph: PerspectiveGraph,
    operation: OperationDefinition,
) -> bool:
    result = match(operation.pattern, graph)
    if not result.success:
        return False

    # Pass 1: graph2s — structural rewrite
    updated_map = _apply_pass(
        graph,
        result.node_map,
        operation.graph2s,
    )

    # Pass 2: graph2o — operational rewrite
    _apply_pass(
        graph,
        updated_map,
        operation.graph2o,
    )

    return True


def restore(
    graph: PerspectiveGraph,
    operation: OperationDefinition,
) -> bool:
    snap = snapshot(graph)
    success = apply(graph, operation)
    if not success:
        revert(graph, snap)
    return success
