"""
layers.py — multi-layer graph structure (skeleton).

Implements the two orthogonal structures decided in the KB
(see decision `delta_representation`, framework `layer_model`):

  1. LayeredGraph: a per-node dictionary keyed by layer storing EDGES.
     A node IS its edges (no node typing; identity is structural). Keying
     edges by layer keys the node's whole meaning by layer. Delta is achieved
     by sparse layer keys: an unchanged node has NO entry at the new layer and
     resolves (with fallback) to its most recent earlier entry.

     Edges must be queryable from BOTH endpoints, so an edge is recorded in
     both its source's and target's per-layer edge sets (double-recorded;
     both copies agree per layer). Dedup / single-owner is a deferred
     optimization, NOT done here.

  2. LayerRegistry: one LayerRecord per layer holding how layers relate and
     which moves were lossy:
        travel_type : SIDEWAYS | UPWARD   (poisoned-apple: any irreversible
                                            rule in the pass => whole layer UPWARD)
        ruleset     : frozenset[rule-id]  (the compound pass that fired;
                                            ids for now, navigable rule-tree later)
        provenance  : Provenance | None   (provenance IS the source->result
                                            mapping with disposition; None for
                                            sideways since the ruleset is its own
                                            inverse; REQUIRED for upward.)

These are deliberately agnostic to whether layer keys are a linear integer
sequence or positions in a branching traversal DAG — topology lives in the
registry's provenance, not in the edge dictionary. A layer key is therefore an
opaque hashable token (here: int, but not assumed contiguous or ordered beyond
the resolver's `key_order`).

NOT in this skeleton (it is the P3 work, the apply-pass->layer seam):
  - the firing pass that produces a new layer from a ruleset
  - the provenance-gap classifier (inverse-match via match_all) that decides
    sideways vs upward
  - materialize-to-ground-layer, GC of unreachable layers, changed-set index
    (all deferred optimizations, named in `delta_representation`)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Hashable, Iterable, Callable

from basic_machinery.graph import Node, Edge, EdgeType, PerspectiveGraph


# A layer key is any hashable token. Linear numbering uses int; a branching
# traversal graph would use a layer-id. The edge dictionary does not care.
LayerKey = Hashable

# A rule reference is an id (string) for now. Becomes a rule-tree handle once
# the GA learns to navigate rule space (see rule_collapse_self_similarity).
RuleId = str


class TravelType(Enum):
    SIDEWAYS = auto()   # reversible: ruleset is its own inverse; no provenance needed
    UPWARD = auto()     # irreversible: provenance (the mapping) is the only way back


class Disposition(Enum):
    """What happened to a source node under an upward firing."""
    MAPPED = auto()     # source corresponds 1:1 to a result node
    MERGED = auto()     # source folded into another result node
    CONSUMED = auto()   # source destroyed, no result correspondent
    BORN = auto()       # result node with no source (domain entry is the result side)


@dataclass(frozen=True)
class ProvenanceEntry:
    """One source->result correspondence with its disposition."""
    source: Node | None      # None only for BORN results
    result: Node | None      # None for CONSUMED sources
    disposition: Disposition


@dataclass
class Provenance:
    """
    Provenance IS the source->result mapping (KB correction: not a separate
    pointer + mapping). The source REGION is the domain of the mapping —
    implied by the set of `source` nodes across entries, not stored separately.

    This is exactly the information `_apply_pass` already computes (output_map,
    nodes_to_merge, nodes_to_delete, born/recycled nodes) and currently
    DISCARDS. Persisting it on an upward firing IS persisting provenance.

    Maps naturally onto a hyperedge over the source region (named upgrade path).
    """
    entries: list[ProvenanceEntry] = field(default_factory=list)

    def source_region(self) -> set[Node]:
        return {e.source for e in self.entries if e.source is not None}

    def result_nodes(self) -> set[Node]:
        return {e.result for e in self.entries if e.result is not None}

    def add(self, source: Node | None, result: Node | None, disposition: Disposition) -> None:
        self.entries.append(ProvenanceEntry(source, result, disposition))


@dataclass
class LayerRecord:
    """
    One record per layer. Describes how the layer was produced, not its content
    (content lives in LayeredGraph's per-node edge dictionaries).
    """
    key: LayerKey
    travel_type: TravelType
    ruleset: frozenset[RuleId]
    provenance: Provenance | None = None       # required iff travel_type is UPWARD
    parents: tuple[LayerKey, ...] = ()          # source layer(s); enables branching DAG

    def __post_init__(self) -> None:
        if self.travel_type is TravelType.UPWARD and self.provenance is None:
            raise ValueError(
                f"Layer {self.key!r} is UPWARD but has no provenance — "
                f"an irreversible layer's mapping is the only way back."
            )
        if self.travel_type is TravelType.SIDEWAYS and self.provenance is not None:
            # Not fatal, but a sideways layer's source is recoverable via the
            # ruleset's inverse; storing a mapping is redundant. Flag loudly.
            raise ValueError(
                f"Layer {self.key!r} is SIDEWAYS but carries provenance — "
                f"sideways layers recover their source from the ruleset inverse; "
                f"the mapping should be None."
            )


class LayerRegistry:
    """dict[LayerKey -> LayerRecord]. The 'how layers relate' structure."""

    def __init__(self) -> None:
        self._records: dict[LayerKey, LayerRecord] = {}

    def add(self, record: LayerRecord) -> None:
        if record.key in self._records:
            raise ValueError(f"Layer {record.key!r} already registered.")
        self._records[record.key] = record

    def get(self, key: LayerKey) -> LayerRecord:
        return self._records[key]

    def __contains__(self, key: LayerKey) -> bool:
        return key in self._records

    @property
    def keys(self) -> frozenset[LayerKey]:
        return frozenset(self._records)

    def is_upward(self, key: LayerKey) -> bool:
        return self._records[key].travel_type is TravelType.UPWARD


class LayeredGraph:
    """
    Per-node, per-layer edge dictionary.

    Storage: _edges_at[node][layer_key] -> set[Edge]
    Each edge is stored under BOTH endpoints at the layer it exists
    (double-recorded; agreement is an invariant, checked by validate()).

    Resolution: a node's edges at layer L = its explicit entry at L, or — if it
    has none — its entry at the most recent earlier layer per `key_order`.
    `key_order` is supplied by the caller because layer keys are topology-agnostic
    (linear int order, or a DAG walk). Default assumes orderable keys (ints).
    """

    def __init__(self, key_order: Callable[[Iterable[LayerKey]], list[LayerKey]] | None = None):
        # node -> {layer_key -> set[Edge]}
        self._edges_at: dict[Node, dict[LayerKey, set[Edge]]] = {}
        self._nodes: set[Node] = set()
        self._next_id: int = 0
        # orders a set of layer keys oldest->newest; override for DAG topologies
        self._key_order = key_order or (lambda keys: sorted(keys))

    # --- node management ---

    def add_node(self) -> Node:
        node = Node(id=self._next_id)
        self._next_id += 1
        self._nodes.add(node)
        self._edges_at[node] = {}
        return node

    def adopt_node(self, node: Node) -> None:
        """Register a pre-existing Node (e.g. from layer-0 encoding) by identity."""
        self._nodes.add(node)
        self._edges_at.setdefault(node, {})
        self._next_id = max(self._next_id, node.id + 1)

    @property
    def nodes(self) -> frozenset[Node]:
        return frozenset(self._nodes)

    # --- writing a layer ---

    def set_edges(self, node: Node, layer: LayerKey, edges: Iterable[Edge]) -> None:
        """
        Write `node`'s explicit edge set at `layer`. Only changed nodes get an
        entry (sparse = delta). Does NOT auto-mirror to the other endpoint;
        callers writing a layer should call set_edges for every node that
        changed, including both endpoints of any changed edge. mirror_layer()
        is the helper that enforces double-recording from an edge list.
        """
        self._edges_at.setdefault(node, {})[layer] = set(edges)

    def mirror_layer(self, layer: LayerKey, edges: Iterable[Edge],
                     changed_nodes: Iterable[Node]) -> None:
        """
        Convenience writer enforcing the double-recording invariant. Given the
        full edge set that exists at `layer` and the set of nodes whose
        incident edges changed, write each changed node's incident edge set
        (both incoming and outgoing) into its layer entry.
        """
        edges = list(edges)
        changed = set(changed_nodes)
        for node in changed:
            incident = {e for e in edges if e.source == node or e.target == node}
            self.set_edges(node, layer, incident)

    # --- resolving a layer (read with fallback) ---

    def _resolve_key(self, node: Node, layer: LayerKey) -> LayerKey | None:
        """The layer key whose entry applies to `node` at `layer`: `layer` itself
        if present, else the latest earlier key in order, else None."""
        entries = self._edges_at.get(node, {})
        if layer in entries:
            return layer
        ordered = self._key_order(set(entries) | {layer})
        # walk backward from `layer` to find the nearest present earlier key
        if layer not in ordered:
            return None
        idx = ordered.index(layer)
        for k in reversed(ordered[:idx]):
            if k in entries:
                return k
        return None

    def edges_of(self, node: Node, layer: LayerKey) -> set[Edge]:
        """Resolved incident edge set for `node` at `layer` (with fallback)."""
        key = self._resolve_key(node, layer)
        if key is None:
            return set()
        return set(self._edges_at[node][key])

    def edges_from(self, node: Node, layer: LayerKey,
                   edge_type: EdgeType | None = None) -> list[Edge]:
        return [e for e in self.edges_of(node, layer)
                if e.source == node and (edge_type is None or e.edge_type == edge_type)]

    def edges_to(self, node: Node, layer: LayerKey,
                 edge_type: EdgeType | None = None) -> list[Edge]:
        return [e for e in self.edges_of(node, layer)
                if e.target == node and (edge_type is None or e.edge_type == edge_type)]

    # --- materialize a layer into a flat PerspectiveGraph ---

    def materialize(self, layer: LayerKey) -> PerspectiveGraph:
        """
        Reconstruct the full flat graph at `layer` by resolving every node's
        edges. This is the read path the matcher/decoder consume, and the basis
        for the deferred 'ground layer' operation (materialize -> use as new
        explicit delta base).
        """
        g = PerspectiveGraph()
        # register nodes that exist at this layer (have a resolvable entry OR
        # are layer-0 origins with an empty entry)
        present = [n for n in self._nodes if self._resolve_key(n, layer) is not None
                   or n in self._edges_at and self._edges_at[n]]
        # fall back: include every known node (a node with no edges is still a node)
        present = list(self._nodes)
        g._nodes = set(present)
        g._next_id = self._next_id
        edges: set[Edge] = set()
        for n in present:
            edges |= self.edges_of(n, layer)
        g._edges = edges
        return g

    # --- invariant check ---

    def validate(self, layer: LayerKey) -> list[str]:
        """
        Return a list of double-recording violations at `layer`: every edge
        present in one endpoint's resolved set must be present in the other's.
        Empty list = consistent.
        """
        problems: list[str] = []
        for n in self._nodes:
            for e in self.edges_of(n, layer):
                other = e.target if e.source == n else e.source
                if e not in self.edges_of(other, layer):
                    problems.append(
                        f"edge {e} present at {n} but missing at endpoint {other} (layer {layer!r})"
                    )
        return problems
