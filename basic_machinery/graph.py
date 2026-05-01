from enum import Enum, auto
from dataclasses import dataclass, field


class EdgeType(Enum):
    STRUCTURAL = auto()
    OPERATIONAL = auto()


@dataclass(frozen=True)
class Node:
    id: int


@dataclass(frozen=True)
class Edge:
    source: Node
    target: Node
    edge_type: EdgeType


class PerspectiveGraph:
    def __init__(self):
        self._nodes: set[Node] = set()
        self._edges: set[Edge] = set()
        self._next_id: int = 0

    # --- Node management ---

    def add_node(self) -> Node:
        node = Node(id=self._next_id)
        self._next_id += 1
        self._nodes.add(node)
        return node

    def remove_node(self, node: Node) -> None:
        if node not in self._nodes:
            raise ValueError(f"Node {node} not in graph.")
        self._edges = {e for e in self._edges if e.source != node and e.target != node}
        self._nodes.discard(node)

    # --- Edge management ---

    def add_edge(self, source: Node, target: Node, edge_type: EdgeType) -> Edge:
        if source not in self._nodes or target not in self._nodes:
            raise ValueError("Both nodes must exist in the graph before adding an edge.")
        edge = Edge(source=source, target=target, edge_type=edge_type)
        if edge in self._edges:
            raise ValueError(f"Edge {edge} already exists.")
        self._edges.add(edge)
        return edge

    def remove_edge(self, edge: Edge) -> None:
        if edge not in self._edges:
            raise ValueError(f"Edge {edge} not in graph.")
        self._edges.discard(edge)

    # --- Queries ---

    @property
    def nodes(self) -> frozenset[Node]:
        return frozenset(self._nodes)

    @property
    def edges(self) -> frozenset[Edge]:
        return frozenset(self._edges)

    def edges_from(self, node: Node, edge_type: EdgeType | None = None) -> list[Edge]:
        return [
            e for e in self._edges
            if e.source == node and (edge_type is None or e.edge_type == edge_type)
        ]

    def edges_to(self, node: Node, edge_type: EdgeType | None = None) -> list[Edge]:
        return [
            e for e in self._edges
            if e.target == node and (edge_type is None or e.edge_type == edge_type)
        ]

    def neighbors(self, node: Node, edge_type: EdgeType | None = None) -> list[Node]:
        return [e.target for e in self.edges_from(node, edge_type)]

    def copy(self) -> "PerspectiveGraph":
        g = PerspectiveGraph()
        g._nodes = set(self._nodes)
        g._edges = set(self._edges)
        g._next_id = self._next_id
        return g

    def __contains__(self, item) -> bool:
        if isinstance(item, Node):
            return item in self._nodes
        if isinstance(item, Edge):
            return item in self._edges
        return False

    def __repr__(self) -> str:
        return f"PerspectiveGraph(nodes={len(self._nodes)}, edges={len(self._edges)})"
