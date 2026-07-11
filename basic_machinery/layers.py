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
    INHERITED = auto()  # source's crossings inherited by a result via a non-identity
                        # mapping (NOT identity-inheritance, which is MAPPED). Covers
                        # both one-input->many-results (split: each result inherits the
                        # shared source's accepted crossings) and many-inputs->one-result
                        # (fusion: the result inherits from every mapping source). It is
                        # NOT a fold-in/merge — the old name MERGED was misleading.
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

    def reclassify(self, key: LayerKey, record: LayerRecord) -> None:
        """Replace an EXISTING record for `key` (unlike add(), which forbids
        overwriting) -- for the reversibility checker (reverse_compound.py:
        reclassify_after_firing) to upgrade a poisoned-apple UPWARD default
        to SIDEWAYS once reverse_fire proves reversibility for that layer.
        record.key must equal key; LayerRecord's own __post_init__ still
        enforces the travel_type/provenance invariant (SIDEWAYS forbids
        provenance, UPWARD requires it) -- this method does not bypass that.
        """
        if key not in self._records:
            raise ValueError(f"Layer {key!r} not registered -- nothing to reclassify.")
        if record.key != key:
            raise ValueError(f"record.key {record.key!r} does not match {key!r}.")
        self._records[key] = record

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
        # --- per-layer node roster (membership) -------------------------------
        # layer_key -> frozenset[Node] present at that layer. AUTHORITATIVE for
        # presence (see KB layer_membership_roster): materialize and presence
        # tests read the roster, NOT self._nodes (which is all-nodes-ever and
        # grows unbounded as fresh born nodes are minted per no_recycle_in_layers).
        # frozenset enforces committed-layer immutability — a layer's roster does
        # not change after creation; a new layer clones the parent's and mutates
        # the COPY (parent - consumed/merged + born). The two stores are
        # orthogonal (delta_representation): _roster answers "who is present at L",
        # _edges_at answers "what each present node looks like".
        self._roster: dict[LayerKey, frozenset[Node]] = {}

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

    # --- per-layer roster (membership) ---

    def set_roster(self, layer: LayerKey, nodes: Iterable[Node]) -> None:
        """Store the node membership of `layer` (authoritative for presence).
        Frozen so a committed layer's roster cannot be mutated in place."""
        self._roster[layer] = frozenset(nodes)

    def roster(self, layer: LayerKey) -> frozenset[Node]:
        """The set of real nodes present at `layer`. Empty frozenset if the
        layer has no recorded roster (e.g. queried before creation)."""
        return self._roster.get(layer, frozenset())

    def present(self, node: Node, layer: LayerKey) -> bool:
        """O(1) presence test: is `node` in `layer`'s roster?"""
        return node in self._roster.get(layer, frozenset())

    def derive_roster(self, parent: LayerKey | None,
                      consumed: Iterable[Node] = (),
                      born: Iterable[Node] = ()) -> frozenset[Node]:
        """Compute a child layer's roster by CLONING the parent's and mutating
        the copy: (parent_roster - consumed) | born. The parent roster is never
        touched (it is frozen). `parent=None` means base layer: roster = born
        (the initially committed node set). This is the membership delta from
        KB layer_membership_roster; `consumed` covers both CONSUMED and INHERITED
        dispositions (both leave the roster), `born` covers freshly minted nodes
        (no recycling — see no_recycle_in_layers)."""
        base = self._roster.get(parent, frozenset()) if parent is not None else frozenset()
        return frozenset((set(base) - set(consumed)) | set(born))

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
        Reconstruct the full flat graph at `layer` by resolving the edges of
        every node PRESENT at that layer. Presence is read from the layer roster
        (authoritative; see KB layer_membership_roster), NOT from self._nodes —
        self._nodes is all-nodes-ever and grows unbounded as fresh born nodes are
        minted (no_recycle_in_layers), so iterating it would be both wrong
        (includes nodes not present at L, e.g. consumed ones whose edges would
        resurrect via fallback) and increasingly expensive. The roster excludes
        consumed/merged nodes by omission, which is exactly why no explicit empty
        edge-entry is needed for deleted nodes.

        Fallback: if no roster is recorded for `layer`, fall back to the legacy
        all-nodes scan so older call sites keep working.
        """
        g = PerspectiveGraph()
        if layer in self._roster:
            present = list(self._roster[layer])
        else:
            present = list(self._nodes)
        g._nodes = set(present)
        g._next_id = self._next_id
        edges: set[Edge] = set()
        for n in present:
            edges |= self.edges_of(n, layer)
        # only keep edges whose BOTH endpoints are present at this layer — a
        # resolved edge to a node absent from the roster (e.g. a consumed
        # neighbour) must not appear in the materialized graph.
        present_set = set(present)
        g._edges = {e for e in edges if e.source in present_set and e.target in present_set}
        return g

    # --- invariant check ---

    def validate(self, layer: LayerKey) -> list[str]:
        """
        Return a list of double-recording violations at `layer`: every edge
        present in one endpoint's resolved set must be present in the other's.
        Empty list = consistent.
        """
        problems: list[str] = []
        # Presence is the roster (authoritative; see materialize). A node absent
        # from the layer (consumed/merged) must NOT be checked: with no entry at
        # `layer` its edges resolve via fallback to an earlier layer and would
        # resurrect stale edges (e.g. a consumed node's old crossing), producing
        # phantom violations. Mirror materialize: only roster-present nodes, and
        # only edges whose BOTH endpoints are present.
        if layer in self._roster:
            present = set(self._roster[layer])
        else:
            present = set(self._nodes)
        for n in present:
            for e in self.edges_of(n, layer):
                if e.source not in present or e.target not in present:
                    continue
                other = e.target if e.source == n else e.source
                if e not in self.edges_of(other, layer):
                    problems.append(
                        f"edge {e} present at {n} but missing at endpoint {other} (layer {layer!r})"
                    )
        return problems
