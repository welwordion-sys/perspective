"""transition_helpers.py — input-side graph construction helpers for spine rule builders.

Two primitives used by every spine rule builder:

  _marker(g, src, tgt)
      Encode an OPERATIONAL edge src->tgt as a structural marker chain:
          src -S-> m, m -S-> tgt, m -O-> m
      (marker_chain_is_encoded_edge_not_scaffold: a real operational edge lives
       as a structural marker chain; the bare operational channel is reserved
       for in_X -> out_X mapping instructions.)

  _typed_input_graph(p, specs) -> (g2, node_map, placeholder)
      Clone pattern p's nodes/edges into g2 (input side), translating the
      pattern's own OPERATIONAL relations into marker chains, then attach each
      boundary node in `specs` to a single shared placeholder using the TYPED
      crossing encoding from KB pitfall operational_crossing_needs_marker_chain:

          (STRUCTURAL, out): B  -S-> ph
          (STRUCTURAL, in):  ph -S-> B
          (OPERATIONAL, out): marker chain  B  -S-> m -S-> ph,  m -O-> m
          (OPERATIONAL, in):  marker chain  ph -S-> m -S-> B,   m -O-> m

      specs: dict[Node, list[(EdgeType, 'in'|'out')]]  keyed by PATTERN nodes.
      A single tuple (etype, direction) is also accepted for backwards compat.
      Returns the placeholder node (or None if specs empty).
"""
from basic_machinery.graph import PerspectiveGraph, Node, EdgeType, Edge

OUT, IN = 'out', 'in'


def _marker(g: PerspectiveGraph, src: Node, tgt: Node) -> Node:
    """Add a structural marker chain encoding an OPERATIONAL edge src->tgt."""
    m = g.add_node()
    g.add_edge(src, m, EdgeType.STRUCTURAL)
    g.add_edge(m, tgt, EdgeType.STRUCTURAL)
    g.add_edge(m, m, EdgeType.OPERATIONAL)
    return m


def _typed_input_graph(p: PerspectiveGraph, specs: dict):
    """
    Clone p into a fresh input-side graph g2.

    STRUCTURAL edges copied unchanged.
    OPERATIONAL self-loops -> STRUCTURAL self-loops (bit-value / tag carry).
    OPERATIONAL A->B (non-self-loop) -> marker chain A -S-> m -S-> B, m -O-> m.
    Boundary nodes in `specs` get typed crossings to one shared placeholder.
    """
    g = PerspectiveGraph()
    nm: dict[Node, Node] = {}
    for node in p.nodes:
        nm[node] = g.add_node()

    for e in p.edges:
        s, t = nm[e.source], nm[e.target]
        if e.edge_type == EdgeType.STRUCTURAL:
            g.add_edge(s, t, EdgeType.STRUCTURAL)
        elif e.source == e.target:
            # operational self-loop -> structural self-loop
            g.add_edge(s, t, EdgeType.STRUCTURAL)
        else:
            _marker(g, s, t)

    ph = None
    if specs:
        ph = g.add_node()
        g.add_edge(ph, ph, EdgeType.STRUCTURAL)
        g.add_edge(ph, ph, EdgeType.OPERATIONAL)
        for bn, crossings in specs.items():
            B = nm[bn]
            # Accept a single (etype, direction) tuple or a list of them.
            # A spine successor needs multiple typed crossings of different types;
            # the match view folds each into a distinct (type,direction) degree key,
            # so one shared placeholder carries them distinctly (verified).
            if isinstance(crossings, tuple) and len(crossings) == 2 \
                    and not isinstance(crossings[0], (tuple, list)):
                crossings = [crossings]
            for (etype, direction) in crossings:
                if etype == EdgeType.STRUCTURAL and direction == OUT:
                    g.add_edge(B, ph, EdgeType.STRUCTURAL)
                elif etype == EdgeType.STRUCTURAL and direction == IN:
                    g.add_edge(ph, B, EdgeType.STRUCTURAL)
                elif etype == EdgeType.OPERATIONAL and direction == OUT:
                    _marker(g, B, ph)
                elif etype == EdgeType.OPERATIONAL and direction == IN:
                    _marker(g, ph, B)
                else:
                    raise ValueError(f"bad spec for {bn}: {(etype, direction)}")
    return g, nm, ph
