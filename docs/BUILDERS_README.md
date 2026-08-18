# Builders — the rule-generating source (exact versions this session ran against)

These are the spine_* builders that `arithmetic.py` imports. They are NOT in the
GitHub repo — the repo's arithmetic.py imports them but they live only here / in
Sven's zips. The repo does not run standalone without them. These copies are the
EXACT versions all of this session's analysis was run against (md5s below).

## md5 (provenance)
  spine_addinit_v4.py        fe02f8cca7c87a1821d71583e77d3a74
  spine_bitadd_v1.py         c01824659b717ac173742a0fd6740e1e
  spine_finalise_v1.py       d39114c7f3af47a74a600c3121a5d202
  spine_finalise_multibit.py 7de78b5ee98628ebba05011beb6d59f5
  scratch_add_init2.py       7678a3b628aa937e0a19e6146964a824
  boundary_decl.py           5bdab3d2dcad5db2716db1b258843760

## What each is
  - spine_addinit_v4.build_labeled(lb,rb,ls,rs) -> (OperationDefinition, labels):
    the add_init family (operator unfinished -> finished, first result bit). 36
    variants over (bit,bit,state,state); state in (single,term,cont).
  - spine_bitadd_v1.build_labeled(lb,rb,ci,ls,rs): the middle step (consume a carry,
    grow the result spine by one bit). (0,0,c0) is the termination condition and is
    excluded at registration.
  - spine_finalise_v1.build_finalise(): the 1-bit (LSB==MSB) terminal rule. VERIFIED.
  - spine_finalise_multibit.py: an EARLIER python attempt at multibit finalise. NOTE:
    its comments/orientation are the SUPERSEDED LSB-invisible hypothesis (see KB
    multibit_finalise_built_matches_rewrite_bug). The CURRENT multibit finalise design
    is the two EDITOR graphs (finalise_multibit_2bit / finalise_multibit), not this
    file. Kept for reference only; do not assume it is correct.
  - boundary_decl.py: helper for declaring per-node boundary crossing specs
    (ph_all_four etc.). scratch_add_init2.py: scratch helpers.

## THE BUFFER-DIRECTION BUG — precise localization (read with KB node)
The multibit blocker is: bit_add's REALIZED (fired) output has the buffer as a
SOURCE, but every rule SPEC (incl. bit_add's own output side) wants the buffer as a
SINK. Important nuance found at handoff time:

  - In spine_bitadd_v1.py the OUTPUT-side structure is ALREADY sink-correct:
      out_handle    -S-> out_buffer      (buffer receives)
      out_new_spine -S-> out_buffer      (buffer receives)
    There is NO out_buffer -S-> X edge in the spec. So the builder's output spec is
    NOT the obvious culprit — the buffer is specified as a sink here.
  - Therefore the source-vs-sink REVERSAL is most likely introduced at REBUILD time
    (schema.rebuild), e.g. via the `in_buffer -OP-> out_buffer` survive-mapping
    interacting with identity reuse / boundary grab, NOT a wrong add_edge in the
    builder. The earlier handoff phrasing "bit_add doesn't realize its own spec" is
    correct as a SYMPTOM; this note refines WHERE: compare bit_add's compiled
    internal_edges for the buffer (should be sink) against the buffer's edges in the
    FIRED graph (came out source) and find which rebuild step flips them.

## How they were assembled this session
All placed in /home/claude/gate_run/ alongside basic_machinery/ (which held the
schema-based operations.py + schema.py). arithmetic.py register_all() then builds
and registers every variant. encoding.py was the GitHub version (md5 a89dd3d...).
