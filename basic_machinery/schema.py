"""
schema.py — DRAFT. Compile a read-only transition graph (graph2) into an
execution schema ONCE at rule creation, so the apply pass executes instead of
interpreting.

Design (settled this session):
  - graph2 is READ-ONLY and the single source of truth.
  - A shared FRONT-END derives the binding-independent facts:
        match_view        : input-side relation (markers retranslated), read-only
        delete            : matched input nodes consumed (no output correspondent)
        inherit           : output node -> input node whose identity it takes
        born              : output nodes with no inherited identity (fresh)
        internal_edges    : output structural edges, both endpoints in the output
                            (op edges decoded from graph2 marker chains -> direct)
        boundary_survivors: (output_node, type, direction) crossings to nodes
                            OUTSIDE the match — pre-FILTERED at creation by the
                            output placeholder preserve set. The outside endpoint
                            is the only thing read live at apply time.
  - Two BACK-END views off the shared core:
        edits    : a delta for rebuild (in-place, layer 0, max id preservation)
        fragment : a standalone output graph for layer apply (clone-and-fuse)

  NO markers are inserted into any live graph. NO runtime interpretation.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from basic_machinery.graph import PerspectiveGraph, Node, Edge, EdgeType


# ---- direction key ----
# (EdgeType, 'out' | 'in')  from the matched/output node's perspective.
DegreeKey = tuple


@dataclass
class SchemaCore:
    """Binding-independent compiled facts derived once from graph2."""
    # input-side
    input_nodes: set[Node] = field(default_factory=set)
    placeholders: set[Node] = field(default_factory=set)
    markers: set[Node] = field(default_factory=set)
    # output-side
    output_nodes: set[Node] = field(default_factory=set)
    # dispositions
    delete: set[Node] = field(default_factory=set)            # input nodes consumed
    inherit: dict[Node, Node] = field(default_factory=dict)   # out_node -> in_node
    born: set[Node] = field(default_factory=set)              # out_nodes, no inherit
    # input->output mapping (which inputs map to each output). Needed for MERGED
    # provenance: a non-inheriting input that maps to an output folds into it.
    mapping_in: dict = field(default_factory=dict)            # out_node -> set[in_node]
    # output structure (both endpoints are output nodes)
    internal_edges: set[tuple] = field(default_factory=set)   # (out_src, out_tgt, EdgeType)
    # boundary grab: per output node, the (input_node, type, direction) external
    # crossings it draws. The ONLY link is the input->output mapping (already in
    # graph2). An output node grabs externals from the input node(s) that map to
    # it, filtered by its own placeholder preserve schema (which (type,dir) it
    # declares preservable). Inherited and born nodes use the identical rule —
    # born nodes have a mapping input even without an identity correspondent.
    # The match supplies the live outside endpoints for those input nodes.
    boundary_grab: dict[Node, set] = field(default_factory=dict)


def _self_loops(n: Node, g: PerspectiveGraph) -> tuple[bool, bool]:
    return (Edge(n, n, EdgeType.STRUCTURAL) in g,
            Edge(n, n, EdgeType.OPERATIONAL) in g)


def _classify(graph2: PerspectiveGraph):
    """Step-2 classification, lifted verbatim from _apply_pass."""
    placeholders: set[Node] = set()
    markers: set[Node] = set()
    for n in graph2.nodes:
        has_s, has_o = _self_loops(n, graph2)
        if has_s and has_o:
            placeholders.add(n)
        elif has_o:
            markers.add(n)

    has_outgoing: set[Node] = set()
    has_incoming: set[Node] = set()
    for e in graph2.edges:
        if e.edge_type == EdgeType.OPERATIONAL and e.source != e.target:
            has_outgoing.add(e.source)
            has_incoming.add(e.target)
    output_only = has_incoming - has_outgoing
    excluded = markers | placeholders
    input_nodes = set(graph2.nodes) - output_only - excluded
    output_nodes = output_only
    return input_nodes, output_nodes, placeholders, markers, has_outgoing


def _decode_op_chain_targets(graph2, src, markers):
    """Output op edges from src, decoded from marker chains:
    src ->S-> m ->S-> tgt  (m an op-marker)  ==>  op relation src->tgt.
    Returns list of tgt."""
    out = []
    for e in graph2.edges_from(src, EdgeType.STRUCTURAL):
        m = e.target
        if m in markers:
            for e2 in graph2.edges_from(m, EdgeType.STRUCTURAL):
                if e2.target != m:
                    out.append(e2.target)
    return out


def compile_core(graph2: PerspectiveGraph) -> SchemaCore:
    input_nodes, output_nodes, placeholders, markers, has_outgoing = _classify(graph2)
    core = SchemaCore(
        input_nodes=set(input_nodes), placeholders=set(placeholders),
        markers=set(markers), output_nodes=set(output_nodes),
    )

    # --- input->output mapping (the single link) ---
    # mapping_in[out_node] = set of input nodes that map to it (direct op edge
    # input -> output in graph2). Used for BOTH identity (inherit) and boundary
    # grab. No "first grab": every output node uses its full mapping set.
    mapping_in: dict[Node, set] = {n: set() for n in output_nodes}
    for inp in input_nodes:
        for e in graph2.edges_from(inp, EdgeType.OPERATIONAL):
            if e.target != inp and e.target in output_nodes:
                mapping_in[e.target].add(inp)

    # delete = input nodes that map to NO output node (consumed).
    mapped_inputs = set().union(*mapping_in.values()) if mapping_in else set()
    core.delete = set(input_nodes) - mapped_inputs

    # inherit = output node takes an input node's identity. INJECTIVE: each input
    # may be inherited by AT MOST ONE output (a real node cannot become two
    # outputs). When several outputs map from the same input, ONE inherits its
    # identity and the REST are BORN (fresh real nodes) — the shared mapping still
    # drives their boundary grab, but not identity. Consistent-per-rule choice:
    # process outputs in id order, each claims the min-id unclaimed input it maps
    # from; an output whose every mapped input is already claimed is BORN.
    inherit: dict[Node, Node] = {}
    claimed_inputs: set = set()
    for out_node in sorted(output_nodes, key=lambda n: n.id):
        srcs = [s for s in mapping_in[out_node] if s not in claimed_inputs]
        if srcs:
            src = min(srcs, key=lambda n: n.id)
            inherit[out_node] = src
            claimed_inputs.add(src)
    core.inherit = inherit
    core.born = set(output_nodes) - set(inherit.keys())
    core.mapping_in = {o: set(s) for o, s in mapping_in.items()}

    # Non-survivor fan-in sources: input nodes that mapped to an output but were
    # not chosen as the identity inheritor (claimed_inputs excludes them, yet they
    # are in mapped_inputs so they escaped core.delete above). They have no output
    # correspondent and must be consumed — otherwise they persist as live orphans
    # carrying pre-fire edges. (KB: compile_core_fanin_orphan)
    non_survivor_fanin = mapped_inputs - claimed_inputs
    core.delete |= non_survivor_fanin

    # --- internal edges (both endpoints output nodes) ---
    # A self-loop (src==tgt, both output nodes) IS an internal edge — e.g. a
    # structural self-loop encoding bit value 1 on a result leaf. Do NOT exclude
    # src==tgt; that exclusion was dropping built bit values.
    internal: set[tuple] = set()
    for e in graph2.edges:
        if e.edge_type == EdgeType.STRUCTURAL:
            if e.source in output_nodes and e.target in output_nodes:
                internal.add((e.source, e.target, EdgeType.STRUCTURAL))
    for src in output_nodes:
        for tgt in _decode_op_chain_targets(graph2, src, markers):
            if tgt in output_nodes:
                internal.add((src, tgt, EdgeType.OPERATIONAL))
    core.internal_edges = internal

    # --- boundary grab = (input->output mapping) x (output node preserve set) ---
    preserve = _preserve_sets(graph2, output_nodes, placeholders, markers)
    grab: dict[Node, set] = {}
    for out_node in output_nodes:
        cases = preserve.get(out_node, set())
        if not cases:
            continue
        srcs = mapping_in[out_node]
        g = set()
        for inp in srcs:
            for (et, direction) in cases:
                g.add((inp, et, direction))
        if g:
            grab[out_node] = g
    core.boundary_grab = grab
    return core


def _preserve_sets(graph2, output_nodes, placeholders, markers):
    """Per output node, the (EdgeType, 'out'|'in') cases it declares preservable
    via placeholder connections. struct = direct edge to/from placeholder;
    op = marker chain out_node -S-> m -S-> placeholder (and reverse)."""
    preserve: dict[Node, set] = {n: set() for n in output_nodes}
    for n in output_nodes:
        # direct structural to/from placeholder
        for e in graph2.edges:
            if e.edge_type != EdgeType.STRUCTURAL or e.source == e.target:
                continue
            if e.source == n and e.target in placeholders:
                preserve[n].add((EdgeType.STRUCTURAL, 'out'))
            elif e.target == n and e.source in placeholders:
                preserve[n].add((EdgeType.STRUCTURAL, 'in'))
        # op via marker chain
        for m in markers:
            sp = {e.source for e in graph2.edges
                  if e.target == m and e.source != m and e.edge_type == EdgeType.STRUCTURAL}
            ss = {e.target for e in graph2.edges
                  if e.source == m and e.target != m and e.edge_type == EdgeType.STRUCTURAL}
            if n in sp and (ss & placeholders):
                preserve[n].add((EdgeType.OPERATIONAL, 'out'))
            if n in ss and (sp & placeholders):
                preserve[n].add((EdgeType.OPERATIONAL, 'in'))
    return preserve


# ===========================================================================
# BACK-END ARTIFACTS — precompiled ONCE from the core. Executors consume these;
# they do NOT recompute the output. The only per-fire work is binding-dependent:
# reading live boundary endpoints and fusing identities.
# ===========================================================================


@dataclass
class FragmentArtifact:
    """Precompiled standalone output graph (for the layer-apply executor).

    `graph` is the constant result fragment: born nodes + inherited-node
    placeholders + internal edges, built once. It does NOT depend on the binding.

    `frag_of_output` maps each schema output Node -> the Node inside `graph`
    (so the executor can resolve inherit/boundary against the fragment's nodes).

    `inherit` (output Node -> input Node) and `boundary_grab` are carried through
    so the executor knows which fragment nodes fuse onto a matched real identity
    and which external crossings to read+rebuild. Born = fragment nodes with no
    inherit entry.
    """
    graph: PerspectiveGraph
    frag_of_output: dict           # schema output Node -> fragment Node
    inherit: dict                  # schema output Node -> schema input Node
    boundary_grab: dict            # schema output Node -> set[(input Node, EdgeType, dir)]
    born: set                      # schema output Nodes with no inherit


@dataclass
class EditsArtifact:
    """Precompiled delta plan (for the in-place rebuild executor).

    Expressed over SCHEMA nodes (input/output), resolved against the live
    binding at apply time. Max id preservation: inherited outputs reuse the
    matched real node's identity; only born outputs mint fresh.

    delete        : input nodes whose real node is removed.
    inherit       : output node -> input node whose real identity it takes.
    born          : output nodes that mint a fresh real node.
    internal_edges: (out_src, out_tgt, EdgeType) to build over resolved outputs.
    boundary_grab : out_node -> set[(input node, EdgeType, dir)] external crossings
                    to read live (from the input node's real node) and rebuild on
                    the resolved output node.
    """
    delete: set
    inherit: dict
    born: set
    internal_edges: set
    boundary_grab: dict


def compile_fragment(core: SchemaCore) -> FragmentArtifact:
    """Build the constant output fragment ONCE. Clone every output node into a
    fresh PerspectiveGraph and lay down the internal edges among them. Inherited
    vs born is recorded (not baked into node identity — the executor fuses
    inherited fragment nodes onto matched real ids at apply time)."""
    g = PerspectiveGraph()
    frag_of_output: dict = {}
    for o in core.output_nodes:
        frag_of_output[o] = g.add_node()
    for (src, tgt, et) in core.internal_edges:
        fs, ft = frag_of_output.get(src), frag_of_output.get(tgt)
        if fs is not None and ft is not None:
            if Edge(fs, ft, et) not in g:
                g.add_edge(fs, ft, et)
    return FragmentArtifact(
        graph=g,
        frag_of_output=frag_of_output,
        inherit=dict(core.inherit),
        boundary_grab={o: set(s) for o, s in core.boundary_grab.items()},
        born=set(core.born),
    )


def compile_edits(core: SchemaCore) -> EditsArtifact:
    """Project the core into an in-place delta plan. (For now this is a thin
    re-expression of the core fields; it exists as a separate artifact so the
    rebuild executor never touches the core or graph2 — and so the two output
    forms stay independently precompiled.)"""
    return EditsArtifact(
        delete=set(core.delete),
        inherit=dict(core.inherit),
        born=set(core.born),
        internal_edges=set(core.internal_edges),
        boundary_grab={o: set(s) for o, s in core.boundary_grab.items()},
    )


@dataclass
class Schema:
    """The compiled execution schema stored on an OperationDefinition.
    core     : shared derived facts (and the match view source).
    edits    : precompiled in-place delta plan (rebuild executor).
    fragment : precompiled standalone output graph (layer-apply executor).
    """
    core: SchemaCore
    edits: EditsArtifact
    fragment: FragmentArtifact


def compile_schema(graph2: PerspectiveGraph) -> Schema:
    core = compile_core(graph2)
    return Schema(core=core, edits=compile_edits(core), fragment=compile_fragment(core))


# ===========================================================================
# EXECUTORS — consume a precompiled artifact + a binding. No interpretation.
# ===========================================================================
# binding : dict[schema input Node -> real Node] from the cut-at-edge match.
# real_region : the matched real nodes (binding.values()); "external" = a real
#               node NOT in real_region (the boundary's outside endpoint).
# ===========================================================================


def _read_boundary_externals(edits: EditsArtifact, binding: dict, graph: PerspectiveGraph):
    """For each output node's boundary_grab, read (live, before teardown) the
    external edges of its mapped input node's real node, of the recorded
    (type, direction), to nodes OUTSIDE the matched region. Returns
    out_node -> list[(EdgeType, direction, outside_real_node)]."""
    real_region = set(binding.values())
    saved: dict = {}
    for out_node, grabs in edits.boundary_grab.items():
        collected = []
        for (in_node, et, direction) in grabs:
            real = binding.get(in_node)
            if real is None:
                continue
            if direction == 'out':
                for e in graph.edges_from(real, et):
                    if e.target != real and e.target not in real_region:
                        collected.append((et, 'out', e.target))
            else:  # 'in'
                for e in graph.edges_to(real, et):
                    if e.source != real and e.source not in real_region:
                        collected.append((et, 'in', e.source))
        if collected:
            saved[out_node] = collected
    return saved


def rebuild(graph: PerspectiveGraph, edits: EditsArtifact, binding: dict) -> dict:
    """In-place execution (layer 0 construction / backwards-compatible apply).
    Max id preservation: inherited outputs reuse the matched real node; only
    born outputs mint fresh. Returns output_map: schema output Node -> real Node.
    """
    real_region = set(binding.values())

    # 1. read boundary externals LIVE, before any teardown
    saved_externals = _read_boundary_externals(edits, binding, graph)

    # 2. resolve output identities
    output_map: dict = {}
    for out_node, in_node in edits.inherit.items():
        output_map[out_node] = binding[in_node]      # inherit matched real id
    for out_node in edits.born:
        output_map[out_node] = graph.add_node()        # born: fresh id

    surviving = set(output_map.values())

    # 3. delete consumed input real nodes (that no output inherited)
    for in_node in edits.delete:
        real = binding.get(in_node)
        if real is not None and real not in surviving and real in graph:
            graph.remove_node(real)

    # 4. strip ALL edges off surviving real nodes (edges are rebuilt, never kept)
    for real in surviving:
        for e in list(graph.edges):
            if e.source == real or e.target == real:
                graph.remove_edge(e)

    # 5. build internal edges over resolved outputs
    for (src, tgt, et) in edits.internal_edges:
        rs, rt = output_map.get(src), output_map.get(tgt)
        if rs is not None and rt is not None and Edge(rs, rt, et) not in graph:
            graph.add_edge(rs, rt, et)

    # 6. rebuild boundary edges to the saved live outside endpoints
    for out_node, crossings in saved_externals.items():
        rnode = output_map.get(out_node)
        if rnode is None:
            continue
        for (et, direction, outside) in crossings:
            if outside not in graph:   # outside endpoint may have been deleted
                continue
            if direction == 'out':
                if Edge(rnode, outside, et) not in graph:
                    graph.add_edge(rnode, outside, et)
            else:
                if Edge(outside, rnode, et) not in graph:
                    graph.add_edge(outside, rnode, et)

    return output_map


# ===========================================================================
# PROVENANCE — written DIRECTLY from compiled dispositions + binding + output_map.
# No identity-diff reconstruction: the schema already knows MAPPED/MERGED/
# CONSUMED/BORN. This is what apply_to_layer persists on an UPWARD LayerRecord.
# ===========================================================================

def provenance_from_schema(core: SchemaCore, binding: dict, output_map: dict):
    """Build a layers.Provenance from the compiled schema and a firing.

    binding    : schema input Node -> real Node (from the match)
    output_map : schema output Node -> real Node (from rebuild)

    MAPPED   : an inherited output — its identity-source input's real node maps
               1:1 to the output's real node (same real node).
    MERGED   : an input that maps to an output but is NOT that output's identity
               source — it folds into the output's real node.
    CONSUMED : a delete-set input — destroyed, no result.
    BORN     : a born output — created, no source.
    """
    from basic_machinery.layers import Provenance, Disposition
    prov = Provenance()

    # MAPPED — inherited outputs
    for out_node, in_node in core.inherit.items():
        prov.add(source=binding[in_node], result=output_map[out_node],
                 disposition=Disposition.MAPPED)

    # MERGED — inputs mapping to an output that they do NOT inherit. Each folds
    # into that output's real node. (An input could map to several outputs; it
    # merges into each it is not the identity source of.)
    for out_node, srcs in core.mapping_in.items():
        identity_src = core.inherit.get(out_node)
        for in_node in srcs:
            if in_node is identity_src:
                continue
            if in_node in core.delete:
                continue  # consumed elsewhere; not a merge
            prov.add(source=binding[in_node], result=output_map[out_node],
                     disposition=Disposition.INHERITED)

    # CONSUMED — delete-set inputs
    for in_node in core.delete:
        prov.add(source=binding[in_node], result=None,
                 disposition=Disposition.CONSUMED)

    # BORN — born outputs
    for out_node in core.born:
        prov.add(source=None, result=output_map[out_node],
                 disposition=Disposition.BORN)

    return prov


# ===========================================================================
# LAYER-APPLY EXECUTOR — fragment-based (clone-and-fuse), emits a delta layer.
#
# Unlike the in-place rebuild, this never mutates the base. It computes the
# result node-set by:
#   - inherited outputs  -> REUSE the matched base real node (identity kept)
#   - born outputs       -> MINT a fresh node (genuinely new id; makes the
#                           identity-diff born=result-base sound)
#   - consumed inputs    -> absent from the result roster
# Then it writes the new layer's edges (internal + boundary) as a sparse delta
# for born+changed nodes, and provenance DIRECTLY from the schema.
#
# The precompiled fragment graph is used as the STRUCTURE source: its internal
# edges (incl. self-loops) are the output structure, already built once.
# ===========================================================================


def layer_apply_schema(lg, registry, base_layer, new_layer, operation):
    """Fire `operation` (which must carry a compiled `.schema`) on the graph
    materialized at base_layer, writing new_layer as a sparse delta. Provenance
    is written directly from the schema. Returns a LayerApplyResult-shaped object
    via the caller (operations.apply_to_layer wraps this)."""
    from basic_machinery.match_view import derive_match_view, match_cut_at_edge
    from basic_machinery.layers import LayerRecord, TravelType

    schema = operation.schema
    core = schema.core
    edits = schema.edits

    base = lg.materialize(base_layer)
    base_nodes = set(base.nodes)

    # firing decision
    view = derive_match_view(operation.graph2)
    binding = match_cut_at_edge(operation.graph2, base, list(base.nodes), view=view)
    if binding is None:
        return None  # caller maps None -> fired=False

    # read boundary externals from the materialized base (read-only)
    saved_externals = _read_boundary_externals(edits, binding, base)

    # resolve output identities WITHOUT mutating base
    output_map = {}
    used_ids = {n.id for n in base_nodes}
    next_id = (max(used_ids) + 1) if used_ids else 0
    for out_node, in_node in core.inherit.items():
        output_map[out_node] = binding[in_node]          # reuse base id (inherit)
    for out_node in core.born:
        output_map[out_node] = Node(id=next_id); next_id += 1   # mint fresh

    # dispositions by schema (not identity diff)
    consumed = {binding[i] for i in core.delete}
    born = {output_map[o] for o in core.born}
    survived = {output_map[o] for o in core.inherit}      # reused base nodes

    # build the result graph's edge set for surviving+born nodes:
    #  - internal edges (from fragment / core.internal_edges) over output_map
    #  - boundary edges (saved externals) on the resolving output node
    result_incident = {n: set() for n in (survived | born)}
    def _add(src, tgt, et):
        e = Edge(src, tgt, et)
        if src in result_incident: result_incident[src].add(e)
        if tgt in result_incident: result_incident[tgt].add(e)

    for (s, t, et) in core.internal_edges:
        rs, rt = output_map.get(s), output_map.get(t)
        if rs is not None and rt is not None:
            _add(rs, rt, et)

    # Boundary crossings. A crossing is double-recorded: it must land in BOTH the
    # inside output node's entry AND the outside endpoint's entry, and the outside
    # endpoint must get its own fresh per-layer entry at new_layer (decision
    # placeholder_designates_layer_entry). Without the outside entry the edge is
    # present from the inside and absent from the outside under fallback
    # resolution — the double-recording invariant (layers.validate) is violated.
    # We collect each outside node's new crossings here, then write its entry
    # below (after the roster includes it) as: base-resolved incident, minus the
    # crossings the rewrite replaced (into consumed nodes), plus the new crossings.
    outside_new_crossings: dict = {}   # outside Node -> set[Edge] at new_layer
    for out_node, crossings in saved_externals.items():
        r = output_map.get(out_node)
        if r is None: continue
        for (et, direction, outside) in crossings:
            if outside not in base_nodes:  # outside endpoint must still exist
                continue
            e = Edge(r, outside, et) if direction == 'out' else Edge(outside, r, et)
            if direction == 'out': _add(r, outside, et)
            else:                  _add(outside, r, et)
            outside_new_crossings.setdefault(outside, set()).add(e)

    # child roster: parent - consumed + born, PLUS the outside endpoints of any
    # new crossing (they now carry a changed edge at this layer, so they must be
    # roster-present for both the entry write and the present-filter below).
    child_roster = lg.derive_roster(parent=base_layer, consumed=consumed, born=born)
    child_roster = set(child_roster) | set(outside_new_crossings.keys())
    lg.set_roster(new_layer, child_roster)
    present = set(child_roster)

    # changed = surviving base nodes whose incident set differs from base
    base_incident = {n: {e for e in base.edges if e.source == n or e.target == n}
                     for n in survived}
    changed = {n for n in survived
               if base_incident.get(n, set()) !=
                  {e for e in result_incident.get(n, set())
                   if e.source in present and e.target in present}}

    # MERGE-NEIGHBOUR / BYSTANDER fix. A roster-present node that the rule did
    # NOT touch (not survived, not born, not an outside-crossing endpoint) keeps
    # its base entry by fallback. If that entry contains an edge to a node that is
    # consumed (or otherwise not present at new_layer), the bystander silently
    # retains a stale edge to a node that no longer exists at this layer — the
    # merge-neighbour double-recording defect (KB open_boundary_double_recording).
    # validate() does not catch it because it skips edges to non-present
    # endpoints, but the edge is real in the bystander's resolved entry and would
    # surface on materialize/traversal. Fix: any roster node whose base-resolved
    # incident set contains an edge to a non-present endpoint gets a rewritten
    # entry at new_layer with those dead edges dropped (roster-present filtered).
    bystanders: set = set()
    already = survived | born | set(outside_new_crossings.keys())
    for n in present:
        if n in already:
            continue
        base_inc = {e for e in lg.edges_of(n, base_layer)
                    if e.source == n or e.target == n}
        if any((e.source not in present) or (e.target not in present)
               for e in base_inc):
            bystanders.add(n)

    # write sparse edge entries for born + changed (roster-present endpoints only)
    for n in (born | changed):
        incident = {e for e in result_incident.get(n, set())
                    if e.source in present and e.target in present}
        lg.set_edges(n, new_layer, incident)
        if n not in lg.nodes:
            lg.adopt_node(n)

    # write trimmed entries for bystanders: their base incidence minus edges to
    # non-present endpoints. This drops the stale edge to the consumed node while
    # preserving every still-valid edge (agreement holds: the surviving partner
    # keeps the same edge, since it too is roster-present and unchanged).
    for n in bystanders:
        base_inc = {e for e in lg.edges_of(n, base_layer)
                    if e.source == n or e.target == n}
        trimmed = {e for e in base_inc
                   if e.source in present and e.target in present}
        lg.set_edges(n, new_layer, trimmed)
        if n not in lg.nodes:
            lg.adopt_node(n)
    changed = changed | bystanders

    # write the outside endpoints' fresh entries. set_edges overwrites, so the
    # entry must be COMPLETE: the union of (a) the new crossings built this fire
    # and (b) the outside node's OTHER base edges that still hold — plus a
    # roster-present filter. "Still hold" is decided by AGREEMENT with the other
    # endpoint: a base edge survives into outside's new entry iff the other
    # endpoint's NEW-LAYER resolved entry also contains it. This is stricter than
    # "other endpoint not consumed" — a survivor whose entry was rebuilt may have
    # DROPPED a crossing (e.g. an inherited node whose pre-fire boundary edge the
    # rule did not re-grab); keeping it on outside alone would leave outside
    # holding an edge its partner no longer has, which is exactly the
    # double-recording violation this fix exists to prevent. The born/changed
    # entries were written just above, so edges_of(other, new_layer) already
    # reflects the rewrite for touched nodes and falls back correctly for
    # untouched ones.
    for outside, new_edges in outside_new_crossings.items():
        base_edges = {e for e in lg.edges_of(outside, base_layer)
                      if e.source == outside or e.target == outside}
        surviving_old = set()
        for e in base_edges:
            other = e.target if e.source == outside else e.source
            if other == outside:           # self-loop: no partner to disagree with
                surviving_old.add(e); continue
            if other in consumed:           # partner gone
                continue
            if e in lg.edges_of(other, new_layer):
                surviving_old.add(e)
        entry = {e for e in (surviving_old | new_edges)
                 if e.source in present and e.target in present}
        lg.set_edges(outside, new_layer, entry)
        if outside not in lg.nodes:
            lg.adopt_node(outside)

    # provenance DIRECTLY from schema
    prov = provenance_from_schema(core, binding, output_map)

    registry.add(LayerRecord(
        key=new_layer, travel_type=TravelType.UPWARD,
        ruleset=frozenset({operation.name}), provenance=prov,
        parents=(base_layer,),
    ))

    return {
        'layer_key': new_layer, 'provenance': prov,
        'born': born, 'consumed': consumed, 'changed': changed,
    }


# ===========================================================================
# COMPOUND MATCH RESOLUTION — detection (collect step 2 of 2; step 1 is
# collecting the raw match list itself via match_all/find_all_cores).
#
# Per the ERS-committed decision (decision_schema_reuse): precompiled per-rule
# SchemaCore/EditsArtifact/FragmentArtifact are REUSED unmodified here. This
# function authors no new graph2 -- it only reads, via the existing
# _read_boundary_externals, which real nodes a match's boundary crossings
# touch, and cross-references that against every other match's own matched
# region (binding.values()). Nothing is torn down; base_graph is read-only.
# ===========================================================================

def detect_overlaps(matches: list, base_graph: PerspectiveGraph) -> dict:
    """
    Given the full collected match list for a firing pass, find every real
    node touched by more than one match, classified into the two cases the
    Compound Match Resolution framework distinguishes:

      overlapping_nodes  : a real node that is itself matched (as an input)
                            by two or more matches' own regions.
      boundary_crossings : a real node that one match (i) reads as a live
                            boundary-crossing target, while another match (j)
                            has that SAME node inside its own matched region
                            (the boundary_of_one_inside_other case) -- keyed
                            (i, j) -> set of such nodes.

    matches   : list of (operation, binding). operation carries .schema
                (Schema: core/edits/fragment); binding: schema input Node ->
                real Node, from match_all/match_cut_at_edge.
    base_graph: the graph this pass fires against, materialized once,
                read-only (detection never mutates or tears down).

    Returns a dict with region_of, boundary_touches, overlapping_nodes,
    boundary_crossings, and degree (real_node -> count of distinct matches
    touching it via region OR boundary) -- degree is what step 2 (resolution)
    ranks on to decide which overlap to resolve first.
    """
    region_of: dict = {}
    for i, (_, binding) in enumerate(matches):
        for real in set(binding.values()):
            region_of.setdefault(real, set()).add(i)

    externals: dict = {}
    boundary_touches: dict = {}
    for i, (operation, binding) in enumerate(matches):
        edits = operation.schema.edits
        ext = _read_boundary_externals(edits, binding, base_graph)
        externals[i] = ext
        boundary_touches[i] = {
            outside for crossings in ext.values()
            for (_et, _direction, outside) in crossings
        }

    overlapping_nodes = {n: set(idxs) for n, idxs in region_of.items()
                          if len(idxs) > 1}

    boundary_crossings: dict = {}
    for i, touched in boundary_touches.items():
        for n in touched:
            owners = region_of.get(n, set()) - {i}
            for j in owners:
                boundary_crossings.setdefault((i, j), set()).add(n)

    degree: dict = {n: set(idxs) for n, idxs in region_of.items()}
    for i, touched in boundary_touches.items():
        for n in touched:
            degree.setdefault(n, set()).add(i)
    degree = {n: len(idxs) for n, idxs in degree.items()}

    return {
        "region_of": region_of,
        "boundary_touches": boundary_touches,
        "externals": externals,
        "overlapping_nodes": overlapping_nodes,
        "boundary_crossings": boundary_crossings,
        "degree": degree,
    }


def resolve_compound(matches: list, overlap_info: dict) -> dict:
    """
    Compound Match Resolution step 2: rank the overlaps detect_overlaps found
    by degree (highest first) and resolve each.

      overlapping_nodes case: two+ matches claim the same real node as their
      own input. One match keeps inherit rights (deterministic: lowest match
      index -- the ranking only affects processing order here since each
      node's resolution doesn't currently depend on another node's outcome;
      see the carried limitation below). Every other match on that node is
      forced to mint a fresh (born) identity for its own output instead of
      inheriting -- this is a per-firing override, the underlying compiled
      EditsArtifact.inherit is untouched.

      boundary_crossings case: match i's crossing reads real node n live, but
      n is inside match j's own region. i's crossing must be redirected to
      resolve through j's eventual output identity for n at apply time (via
      j's own output_map, computed the normal way -- see decision_schema_reuse)
      instead of n's stale pre-fire identity.

    Carried limitation: resolution of one overlap node is currently
    independent of another's outcome. The framework's cascade ("resolved
    outputs become stable anchors for remaining matches") is not exercised
    here because neither test scenario had one match's own region overlap
    with two DIFFERENT other matches' resolved nodes simultaneously -- true
    transitive cascade (chained overlaps) is unverified past 2 matches.

    Returns:
      forced_born    : match_index -> set of that match's own schema INPUT
                        nodes whose output must mint fresh instead of inherit.
      redirects      : (i, out_node_i) -> owner match index j.
      resolved_owner : real_node -> winning/owning match index.
    """
    ranked_nodes = sorted(
        set(overlap_info["overlapping_nodes"])
        | {n for nodes in overlap_info["boundary_crossings"].values() for n in nodes},
        key=lambda n: -overlap_info["degree"][n],
    )

    forced_born: dict = {}
    resolved_owner: dict = {}

    for n in ranked_nodes:
        if n in overlap_info["overlapping_nodes"]:
            idxs = sorted(overlap_info["overlapping_nodes"][n])
            winner = idxs[0]
            resolved_owner[n] = winner
            for loser in idxs[1:]:
                _op, binding = matches[loser]
                in_node = next(k for k, v in binding.items() if v == n)
                forced_born.setdefault(loser, set()).add(in_node)

    redirects: dict = {}
    for (i, j), nodes in overlap_info["boundary_crossings"].items():
        for n in nodes:
            owner = resolved_owner.get(n, j)
            for out_node, crossings in overlap_info["externals"][i].items():
                if any(outside == n for (_et, _direction, outside) in crossings):
                    redirects[(i, out_node)] = owner

    return {
        "forced_born": forced_born,
        "redirects": redirects,
        "resolved_owner": resolved_owner,
    }


# ===========================================================================
# COMPOUND MATCH RESOLUTION — orchestrator (apply). Per decision_schema_reuse,
# every per-rule SchemaCore/EditsArtifact is reused unmodified; this function
# is the new apply-time layer that fires ALL matches in one pass as a single
# combined write, using detect_overlaps + resolve_compound's decisions.
# Per decision_orchestrator_order: resolution order is a topological sort of
# the redirect dependency graph (owner before crosser); a redirect cycle
# raises rather than guessing. A redirect whose owner has no surviving
# inherit claim on the shared node is dropped, not reattached to the stale
# pre-fire identity.
# ===========================================================================

def _compound_provenance(operation, binding: dict, output_map: dict, forced_inputs: set):
    """Like provenance_from_schema, but any inherit input in `forced_inputs`
    (this firing's forced-born override) is recorded as BORN, not MAPPED --
    its fresh identity has no source; the original real id's provenance
    continues through whichever match actually won it."""
    from basic_machinery.layers import Provenance, Disposition
    core = operation.schema.core
    prov = Provenance()

    for out_node, in_node in core.inherit.items():
        if in_node in forced_inputs:
            prov.add(source=None, result=output_map[out_node], disposition=Disposition.BORN)
        else:
            prov.add(source=binding[in_node], result=output_map[out_node],
                     disposition=Disposition.MAPPED)

    for out_node, srcs in core.mapping_in.items():
        identity_src = core.inherit.get(out_node)
        for in_node in srcs:
            if in_node is identity_src:
                continue
            if in_node in core.delete:
                continue
            prov.add(source=binding[in_node], result=output_map[out_node],
                     disposition=Disposition.INHERITED)

    for in_node in core.delete:
        prov.add(source=binding[in_node], result=None, disposition=Disposition.CONSUMED)

    for out_node in core.born:
        prov.add(source=None, result=output_map[out_node], disposition=Disposition.BORN)

    return prov


def apply_compound(lg, registry, base_layer, new_layer, matches: list) -> dict:
    """Fire every match in `matches` together as ONE combined firing pass,
    writing a single new_layer. Generalizes layer_apply_schema across the
    whole firing set instead of one operation.

    matches: list of (operation, binding) already collected for this pass
             (e.g. via match_all/find_all_cores per rule). Every operation
             must carry a compiled .schema.
    """
    from basic_machinery.layers import LayerRecord, TravelType, Provenance

    base = lg.materialize(base_layer)
    base_nodes = set(base.nodes)

    overlap_info = detect_overlaps(matches, base)
    resolution = resolve_compound(matches, overlap_info)
    forced_born = resolution["forced_born"]
    redirects = resolution["redirects"]

    # ---- resolution order: topo sort of the owner-dependency graph ----
    n = len(matches)
    deps = {i: set() for i in range(n)}
    for (i, _out_node), owner in redirects.items():
        if owner != i:
            deps[i].add(owner)

    order: list = []
    temp_mark, perm_mark = set(), set()

    def visit(k):
        if k in perm_mark:
            return
        if k in temp_mark:
            raise ValueError(f"compound redirect cycle detected involving match {k}")
        temp_mark.add(k)
        for d in deps[k]:
            visit(d)
        temp_mark.discard(k)
        perm_mark.add(k)
        order.append(k)

    for k in range(n):
        visit(k)

    # ---- per-match output_map, honoring forced_born ----
    used_ids = {node.id for node in base_nodes}
    next_id = (max(used_ids) + 1) if used_ids else 0
    output_maps: dict = {}
    for i in order:
        operation, binding = matches[i]
        core = operation.schema.core
        overridden = forced_born.get(i, set())
        om = {}
        for out_node, in_node in core.inherit.items():
            if in_node in overridden:
                om[out_node] = Node(id=next_id); next_id += 1
            else:
                om[out_node] = binding[in_node]
        for out_node in core.born:
            om[out_node] = Node(id=next_id); next_id += 1
        output_maps[i] = om

    # ---- dispositions across the whole firing set ----
    consumed: set = set()
    born: set = set()
    survived: set = set()
    for i, (operation, binding) in enumerate(matches):
        core = operation.schema.core
        om = output_maps[i]
        overridden = forced_born.get(i, set())
        for in_node in core.delete:
            consumed.add(binding[in_node])
        for out_node in core.born:
            born.add(om[out_node])
        for out_node, in_node in core.inherit.items():
            if in_node in overridden:
                born.add(om[out_node])
            else:
                survived.add(om[out_node])

    result_incident: dict = {node: set() for node in (survived | born)}

    def _add(src, tgt, et):
        e = Edge(src, tgt, et)
        if src in result_incident: result_incident[src].add(e)
        if tgt in result_incident: result_incident[tgt].add(e)

    for i, (operation, _binding) in enumerate(matches):
        core = operation.schema.core
        om = output_maps[i]
        for (s, t, et) in core.internal_edges:
            rs, rt = om.get(s), om.get(t)
            if rs is not None and rt is not None:
                _add(rs, rt, et)

    # boundary crossings, resolving redirects through the owner's output_map
    outside_new_crossings: dict = {}
    for i, (operation, _binding) in enumerate(matches):
        om = output_maps[i]
        saved_externals = overlap_info["externals"][i]
        for out_node, crossings in saved_externals.items():
            r = om.get(out_node)
            if r is None:
                continue
            for (et, direction, outside) in crossings:
                target = outside
                if (i, out_node) in redirects:
                    owner = redirects[(i, out_node)]
                    owner_op, owner_binding = matches[owner]
                    owner_core = owner_op.schema.core
                    owner_in = next((k for k, v in owner_binding.items() if v == outside), None)
                    if owner_in is None:
                        continue  # fail safe: no known owner input, drop
                    # owner_in is either the inherit source of exactly one output
                    # (survives with that identity) or in owner_core.delete (gone
                    # -- this holds even if owner_in also appears in some
                    # mapping_in[out] as a non-identity fan-in input: compile_core
                    # puts every non-identity fan-in loser into core.delete too,
                    # confirmed by construction -- inherit-values and delete
                    # exhaustively partition all inputs with no third "merged but
                    # alive elsewhere" state. Checking mapping_in as a fallback
                    # here would incorrectly resurrect a genuinely-deleted input.
                    owner_out = next(
                        (o for o, inp in owner_core.inherit.items() if inp == owner_in),
                        None)
                    if owner_out is None:
                        continue  # owner consumed it (in core.delete): drop
                    target = output_maps[owner][owner_out]
                if target not in base_nodes and target not in born and target not in survived:
                    continue
                e = Edge(r, target, et) if direction == 'out' else Edge(target, r, et)
                if direction == 'out': _add(r, target, et)
                else:                  _add(target, r, et)
                outside_new_crossings.setdefault(target, set()).add(e)

    child_roster = lg.derive_roster(parent=base_layer, consumed=consumed, born=born)
    child_roster = set(child_roster) | set(outside_new_crossings.keys())
    lg.set_roster(new_layer, child_roster)
    present = set(child_roster)

    base_incident = {node: {e for e in base.edges if e.source == node or e.target == node}
                      for node in survived}
    changed = {node for node in survived
               if base_incident.get(node, set()) !=
                  {e for e in result_incident.get(node, set())
                   if e.source in present and e.target in present}}

    bystanders: set = set()
    already = survived | born | set(outside_new_crossings.keys())
    for node in present:
        if node in already:
            continue
        base_inc = {e for e in lg.edges_of(node, base_layer)
                    if e.source == node or e.target == node}
        if any((e.source not in present) or (e.target not in present) for e in base_inc):
            bystanders.add(node)

    for node in (born | changed):
        incident = {e for e in result_incident.get(node, set())
                    if e.source in present and e.target in present}
        lg.set_edges(node, new_layer, incident)
        if node not in lg.nodes:
            lg.adopt_node(node)

    for node in bystanders:
        base_inc = {e for e in lg.edges_of(node, base_layer)
                    if e.source == node or e.target == node}
        trimmed = {e for e in base_inc if e.source in present and e.target in present}
        lg.set_edges(node, new_layer, trimmed)
        if node not in lg.nodes:
            lg.adopt_node(node)
    changed = changed | bystanders

    for outside, new_edges in outside_new_crossings.items():
        base_edges = {e for e in lg.edges_of(outside, base_layer)
                      if e.source == outside or e.target == outside}
        surviving_old = set()
        for e in base_edges:
            other = e.target if e.source == outside else e.source
            if other == outside:
                surviving_old.add(e); continue
            if other in consumed:
                continue
            if e in lg.edges_of(other, new_layer):
                surviving_old.add(e)
        entry = {e for e in (surviving_old | new_edges)
                 if e.source in present and e.target in present}
        lg.set_edges(outside, new_layer, entry)
        if outside not in lg.nodes:
            lg.adopt_node(outside)

    prov = Provenance()
    for i, (operation, binding) in enumerate(matches):
        piece = _compound_provenance(operation, binding, output_maps[i], forced_born.get(i, set()))
        prov.entries.extend(piece.entries)

    registry.add(LayerRecord(
        key=new_layer, travel_type=TravelType.UPWARD,
        ruleset=frozenset({operation.name for operation, _ in matches}),
        provenance=prov,
        parents=(base_layer,),
    ))

    return {
        'layer_key': new_layer, 'provenance': prov,
        'born': born, 'consumed': consumed, 'changed': changed,
        'output_maps': output_maps,
    }
