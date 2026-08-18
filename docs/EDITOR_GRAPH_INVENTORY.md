# Editor Graph Inventory — Supabase project `cswxrijpyporhejaovuy`

Live graphs in the graph-editor project (tables: graphs / nodes / edges; reverse-load
via channel_loader.load_graph -> PerspectiveGraph). Snapshot taken end of session.

| name | id | rev | nodes | edges | what it is |
|------|----|-----|-------|-------|------------|
| `spine_addinit_01ss_FAULTY_radial` | cccccccc-0000-0000-0000-00000000a101 | 5 | 21 | 41 | add_init(0,1,single,single) emitted for VISUAL inspection. Collapsed (marker chains -> direct `op` edges), mapping edges typed `mapping`, radial layout centered on the operand, rs<->placeholder boundary removed (rev 5). The FAULTY variant kept verbatim so the construction can be eyeballed. NOTE: the "+2 loose nodes" it appears to show is the DECODER ILLUSION (LSB pointer), not bad construction — see KB rebuild_oracle_decoder. |
| `finalise_multibit` | 22222222-2222-2222-2222-222222222222 | 10 | 14 | 28 | The 3-OR-MORE-bit finalise variant. MSB and LSB both matched; interior spine between them is BOUNDARIED (MSB<->LSB via cross/boundary, no inside edge). |
| `finalise_multibit_2bit` | dddddddd-0000-0000-0000-00000000b201 | 1 | 14 | 28 | The 2-bit finalise variant. MSB adjacent to LSB -> direct INSIDE struct edge between them. Inserted this session from the saved snapshot so both variants are live simultaneously. |
| `finalise_single` | 11111111-1111-1111-1111-111111111111 | 11 | 12 | 20 | Single-result-bit, no-carry terminal finalise (the verified 1-bit rule, where LSB==MSB coincide). |
| `addinit_flat_0p1` | aaaaaaaa-0000-0000-0000-0000000000f1 | 1 | 22 | 24 | OLD placeholder stub from a previous session. Not iterated this session. |
| `addinit_schema_0p1` | bbbbbbbb-0000-0000-0000-0000000000f2 | 1 | 22 | 23 | OLD placeholder stub. Not iterated this session. |

## Reading these back
- Node `metadata.g2id` holds the graph2 node id (the rule-space id). Editor row `id` is
  a separate DB identity (GENERATED ALWAYS — inserts need `overriding system value`).
- Edge `kind` vocabulary: struct, op, mapping, cross, boundary, selfS, selfO.
  `mapping` = input->output rewrite instruction (NOT a real operational edge);
  `cross`/`boundary` carry a `metadata.type` of struct|op.
- A placeholder node = both a selfS and a selfO self-loop (the boundary signature).

## The two finalise variants — why two (not over-specification)
Both match a FIXED node set: handle, buffer, cyc0/1, anchor, the two operand-zero
spines+leaves, MSB spine, LSB spine. MSB is matched to CHECK FOR CARRY; LSB is matched
because the PARENT EDGE RE-ATTACHES to it. The only width-sensitive difference is the
MSB<->LSB relation: INSIDE edge (2-bit, adjacent) vs CROSS/BOUNDARY (3+, interior
spine preserved). 3+ is width-invariant (interior is boundary, uncounted), so exactly
two variants close the case.

## Caveat
Neither finalise variant matches REAL post-bit_add output yet — blocked by the buffer
edge-direction divergence (bit_add emits a source-buffer; all specs incl. finalise expect
a sink-buffer). See KB multibit_finalise_built_matches_rewrite_bug. The variants were
authored against the CORRECT (sink-buffer) shape and will be testable once bit_add is fixed.
