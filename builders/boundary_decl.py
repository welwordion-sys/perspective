"""
boundary_decl.py — four-case output boundary declaration for spine builders.

Declares a surviving output boundary node's preserve directives in ALL FOUR
(edge_type, direction) cases, as placeholder connections the four-case step-4c
reads and discards (never real edges):

    out-struct : node -S-> ph          (direct structural edge)
    in-struct  : ph -S-> node          (direct structural edge)
    out-op     : node -S-> m -S-> ph   (marker chain; op is ALWAYS a marker chain)
    in-op      : ph -S-> m -S-> node   (marker chain)

A direct operational edge is NEVER used: a real op edge on an output node would
corrupt its input/output classification (output_only = has_incoming - has_outgoing
over operational edges). Operational boundary directives must ride on a marker's
self-loop, off the output node's direct edges — same encoding as every other
operational crossing.

"All four declared" = "preserve every external crossing of this node, whatever
its type/direction." Declaring a case the node has no real edge for is harmless:
the directive is a keep-filter (set membership), not a degree count.
"""
from basic_machinery.graph import PerspectiveGraph, Node, EdgeType, Edge
from basic_machinery.transition_helpers import _marker


def ph_all_four(g: PerspectiveGraph, node: Node, ph: Node) -> None:
    """Declare all four (type, direction) preserve cases for `node` against
    placeholder `ph`."""
    # structural, both directions (direct)
    if Edge(node, ph, EdgeType.STRUCTURAL) not in g:
        g.add_edge(node, ph, EdgeType.STRUCTURAL)
    if Edge(ph, node, EdgeType.STRUCTURAL) not in g:
        g.add_edge(ph, node, EdgeType.STRUCTURAL)
    # operational, both directions (marker chains)
    _marker(g, node, ph)   # out-op
    _marker(g, ph, node)   # in-op
