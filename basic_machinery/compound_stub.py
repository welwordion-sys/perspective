"""compound_stub.py -- minimal LayeredGraph-compatible adapter (Sven, this
session: correcting an earlier mischaracterization that apply_compound
needed real unbuilt integration work; a fuller read shows every touchpoint
is a trivial operation against a single base layer). Reuses the REAL
apply_compound(schema.py) unchanged against a plain PerspectiveGraph,
instead of the hand-rolled reverse_footprint_lightweight/reconstruction
logic duplicating part of what apply_compound already does correctly.
"""
from __future__ import annotations
from basic_machinery.graph import PerspectiveGraph, Node, Edge


class PlainGraphLayeredStub:
    """Implements exactly the methods apply_compound calls, against a single
    supplied base layer materialized from a plain PerspectiveGraph. Not a
    general LayeredGraph replacement -- scoped to one throwaway compound
    resolution/reconstruction, not persistent multi-layer storage.
    """
    def __init__(self, base_graph: PerspectiveGraph, base_layer_key="base"):
        self._base_graph = base_graph
        self._base_layer_key = base_layer_key
        self._roster = {base_layer_key: frozenset(base_graph.nodes)}
        self._nodes = set(base_graph.nodes)
        self._edges_at = {}  # node -> {layer_key: set[Edge]}

    def materialize(self, layer) -> PerspectiveGraph:
        if layer == self._base_layer_key:
            return self._base_graph
        # a "new" layer requested before being written -- return the base
        # graph as a starting point (matches materialize's own fallback
        # semantics: an unwritten node falls back to its origin layer).
        return self._base_graph

    def roster(self, layer) -> frozenset:
        return self._roster.get(layer, frozenset())

    def set_roster(self, layer, nodes) -> None:
        self._roster[layer] = frozenset(nodes)

    def present(self, node, layer) -> bool:
        return node in self._roster.get(layer, frozenset())

    def derive_roster(self, parent, consumed=(), born=()) -> frozenset:
        base = self._roster.get(parent, frozenset()) if parent is not None else frozenset()
        return frozenset((set(base) - set(consumed)) | set(born))

    @property
    def nodes(self) -> frozenset:
        return frozenset(self._nodes)

    def edges_of(self, node, layer):
        if layer == self._base_layer_key:
            return {e for e in self._base_graph.edges if e.source == node or e.target == node}
        return self._edges_at.get(node, {}).get(layer, set())

    def set_edges(self, node, layer, edges) -> None:
        self._edges_at.setdefault(node, {})[layer] = set(edges)

    def adopt_node(self, node) -> None:
        self._nodes.add(node)
        self._edges_at.setdefault(node, {})

    def materialize_result(self, layer) -> PerspectiveGraph:
        """NOT part of the LayeredGraph interface apply_compound expects --
        a convenience for OUR purposes: build a plain PerspectiveGraph from
        the written new_layer edge entries, falling back to base_graph for
        anything not explicitly written (matches the delta-representation
        convention: unchanged = no new entry = structural reference to origin).
        """
        present = self._roster.get(layer, frozenset())
        result = PerspectiveGraph()
        for node in present:
            result._nodes.add(node)  # Node is a plain frozen dataclass; no
                                      # "adopt with existing id" method exists
                                      # on PerspectiveGraph (add_node() always
                                      # mints a fresh id) -- insert directly.
        if present:
            # BUG FOUND AND FIXED this session (Sven's substrate/failure-level
            # question led directly to finding this): result._next_id was
            # never synced with the actual ids inserted above, staying at its
            # default (0) even when the graph holds nodes up to a much higher
            # id -- latent, would collide the moment anything downstream
            # calls result.add_node() to mint a genuinely fresh node.
            result._next_id = max(n.id for n in present) + 1
        for node in present:
            written = self._edges_at.get(node, {}).get(layer)
            edge_set = written if written is not None else self.edges_of(node, self._base_layer_key)
            for e in edge_set:
                if e.source in present and e.target in present:
                    if e not in result._edges:
                        result._edges.add(e)
        return result


class SimpleRegistry:
    """Stub for apply_compound's `registry` parameter -- it only calls
    registry.add(LayerRecord(...)); LayerRecord's own __post_init__ already
    validates travel_type/provenance consistency, nothing more is needed."""
    def __init__(self):
        self.records = []

    def add(self, record) -> None:
        self.records.append(record)
