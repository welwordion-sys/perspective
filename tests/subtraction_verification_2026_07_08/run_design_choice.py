import json
from reason_setter import ReasonSetter

s = ReasonSetter([
    "Which subtraction design (current 4-phase, translated Arm A, translated Arm B, or a hybrid) "
    "should Perspective adopt for the negative-path subtraction, given its actual architecture "
    "constraints (independent per-operand spines, two reserved EdgeTypes, 0-n terminal frame)?",
])

def show(cb, label):
    print(f"--- {label} ---")
    print("ok:", cb.ok)
    if not cb.ok:
        print("reason:", cb.reason)
        print("repair:", cb.repair)
    if cb.warnings:
        print("warnings:", cb.warnings)
    if cb.queue:
        print("queue:", cb.queue)
    print()

# ---- ground: architecture facts ----
cb = s.ground([
    {"id":"s_arch_spines","status":"given","statement":
     "Each operand is its own independent variable-length spine chain, joined to the operator "
     "only via port edges; there is no single shared/padded array spanning both operands."},
    {"id":"s_channels","status":"given","statement":
     "Only two EdgeTypes exist, STRUCTURAL and OPERATIONAL, with specific channels already "
     "reserved per node; no generic token-edge type exists."},
    {"id":"s_negenc","status":"given","statement":
     "A negative result is encoded as a finished 0-n structural subtree, not a sign-tag "
     "attached to a value."},
    {"id":"s_marker_channels","status":"given","statement":
     "The marker-edge mechanism uses only the two channels already free on existing node "
     "types, leaf OP-out and spine OP-in, deliberately avoiding any new EdgeType."},
    {"id":"s_4phase_refmodel","status":"given","statement":
     "The current 4-phase arithmetic was checked clean as a Python reference model over a,b "
     "in 1..127 for both positive and negative results."},
    {"id":"s_4phase_reachability","status":"given","statement":
     "Empirical sweep over a,b in 1..63 with a less than b found only 6 of the 8 possible "
     "frontier-table keys are ever reached; the other 2 are asserted, not proven, unreachable."},
    {"id":"s_frontier_history","status":"given","statement":
     "An earlier attempt to negate only the phase-1 low-bit results in place failed on many "
     "cases across the a less than b sweep 0..31, because the low bits are coupled to the "
     "overhang region through the standing borrow."},
    {"id":"s_armA_false","status":"given","statement":
     "Arm A's core determinism claim, that at most one active token/label state exists in the "
     "graph at any time, has been empirically refuted: grade_armA.py found 21844/65025 inputs "
     "where sign-delivery and trim run as concurrent processes."},
    {"id":"s_armB_verified","status":"given","statement":
     "Arm B passed grade_armB.py over a full sweep a,b in 1..255 plus 4000 random 16-bit "
     "pairs, on its own toy graph model."},
])
show(cb, "ground: architecture + KB facts")

# ---- ground: standalone advantages of the current 4-phase design, each individually cited ----
cb = s.ground([
    {"id":"adv_native_arch","status":"derived","statement":
     "The 4-phase mechanism's rules were authored directly against Perspective's actual "
     "primitives, spine-per-operand, two-EdgeType channel model, 0-n frame output, so adopting "
     "it needs no additional encoding or translation layer.",
     "derived_from":[{"parents":["s_arch_spines","s_channels","s_negenc"],
                      "rule":"the design's own construction history in the KB shows it was "
                             "iterated directly against these three constraints"}]},
    {"id":"adv_no_new_edge_type","status":"derived","statement":
     "The marker mechanism fits inside the existing two-EdgeType model with no new edge kind "
     "requested, unlike Arm B's generic token-edge.",
     "derived_from":[{"parents":["s_channels","s_marker_channels"],
                      "rule":"direct structural fact: marker uses only already-free channels"}]},
    {"id":"adv_sign_native","status":"derived","statement":
     "Output is produced directly as the canonical 0-n structural frame, with no separate "
     "sign-tag node needing a later reframing step.",
     "derived_from":[{"parents":["s_negenc"],
                      "rule":"the mechanism's output convention matches the negative_encoding "
                             "decision by construction, not by translation"}]},
    {"id":"adv_reachability_narrowed","status":"derived","statement":
     "An empirical sweep has already narrowed the frontier table to 6 of 8 keys, reducing the "
     "number of graph rules that must be authored for Part 2.",
     "derived_from":[{"parents":["s_4phase_reachability"],
                      "rule":"direct restatement of the sweep result as a design advantage"}]},
    {"id":"adv_refmodel_validated","status":"derived","statement":
     "The arithmetic has already been checked clean as a Python reference model across the "
     "full sign range, a stronger empirical base than either Arm had before its own falsifier "
     "was run.",
     "derived_from":[{"parents":["s_4phase_refmodel"],
                      "rule":"direct restatement of the reference-model sweep result"}]},
])
show(cb, "ground: current-design ADVANTAGES (standalone)")

# ---- ground: current-design disadvantages, for an honest ledger ----
cb = s.ground([
    {"id":"dis_frontier_complexity","status":"derived","statement":
     "The frontier table was only reached after an earlier simpler attempt failed, and 2 of 8 "
     "keys remain asserted, not proven, unreachable.",
     "derived_from":[{"parents":["s_frontier_history","s_4phase_reachability"],
                      "rule":"restate the design's own correction history and open reachability gap"}]},
    {"id":"dis_no_engine_validation","status":"derived","statement":
     "\"Validated\" here means only the Python reference model; the actual VF2-based rule "
     "engine has not run this mechanism.",
     "derived_from":[{"parents":["s_4phase_refmodel"],
                      "rule":"restate the reference-model-only scope as a limitation"}]},
])
show(cb, "ground: current-design DISADVANTAGES")

# ---- ground: Arm A / Arm B derived findings, and the hybrid, and assumed recurrences ----
cb = s.ground([
    {"id":"a_subdef","status":"assumed","statement":
     "diff_i = a_i XOR b_i XOR borrow_in; borrow_out = (NOT a_i AND b_i) OR (NOT a_i AND "
     "borrow_in) OR (b_i AND borrow_in)."},
    {"id":"a_negdef","status":"assumed","statement":
     "new_bit = NOT(old_bit) XOR carry_in; carry_out = NOT(old_bit) AND carry_in."},
    {"id":"d_armB_translation_cost","status":"derived","statement":
     "Arm B assumes one shared or padded spine with a generic token-edge type, both conflicting "
     "with Perspective's independent-spine model and fixed two-EdgeType channel reservation.",
     "derived_from":[{"parents":["s_arch_spines","s_channels"],
                      "rule":"structural comparison of Arm B's alphabet against Perspective's primitives"}]},
    {"id":"d_armB_sign_conflict","status":"derived","statement":
     "Arm B's SIGN-EDGE tag conflicts with encoding negativity as a graph shape; adopting its "
     "output as-is needs an extra step to reframe the tagged result into a 0-n frame.",
     "derived_from":[{"parents":["s_negenc"],
                      "rule":"comparison of Arm B's sign-node convention against the negative_encoding decision"}]},
    {"id":"d_armA_contribution","status":"derived","statement":
     "Independent of its refuted determinism claim, Arm A's mechanism of carrying phase state "
     "as compound labels via in-place relabeling, rather than separate token nodes, is a "
     "salvageable idea that does not itself depend on the token-uniqueness argument shown false.",
     "derived_from":[{"parents":["s_armA_false"],
                      "rule":"separating Arm A's labeling mechanism from its refuted uniqueness argument"}]},
    {"id":"cand_hybrid_claim","status":"derived","statement":
     "Adopt a hybrid: keep Perspective's actual architecture in full and replace the current "
     "design's Phase-2/Phase-3/frontier-table machinery with one uniform two's-complement "
     "negate pass applied to the entire raw phase-1 result, extended through the subtrahend's "
     "overhang via the existing a-absent implicit-zero rule, eliminating the frontier table.",
     "derived_from":[{"parents":["adv_native_arch","adv_no_new_edge_type","adv_sign_native",
                                 "d_armA_contribution","d_armB_translation_cost",
                                 "a_subdef","a_negdef"],
                      "rule":"retain every current-design advantage (native arch, no new edge "
                             "type, native sign encoding) while dropping dis_frontier_complexity "
                             "via a whole-result negate built from the standard recurrences, "
                             "borrowing Arm A's relabel-only representation instead of Arm B's "
                             "token edges"}]},
    {"id":"cand_4phase_claim","status":"derived","statement":
     "Adopt the current validated 4-phase mechanism unchanged, including its known frontier-table "
     "limitations.",
     "derived_from":[{"parents":["adv_native_arch","adv_no_new_edge_type","adv_sign_native",
                                 "adv_reachability_narrowed","adv_refmodel_validated",
                                 "dis_frontier_complexity","dis_no_engine_validation"],
                      "rule":"restate the mechanism as currently specified, citing its full "
                             "honest advantage/disadvantage ledger"}]},
    {"id":"cand_armA_claim","status":"given","statement":
     "Adopt Arm A's design, compound spine labels with no separate token edges, as documented, "
     "including its refuted single-active-token determinism claim."},
    {"id":"cand_armB_claim","status":"derived","statement":
     "Adopt Arm B's design, translated onto Perspective's actual encoding primitives.",
     "derived_from":[{"parents":["s_armB_verified","d_armB_translation_cost","d_armB_sign_conflict"],
                      "rule":"the candidate is the translated-for-adoption version, which "
                             "inherits the translation and sign-encoding costs even though the "
                             "untranslated design verified clean on its own toy model"}]},
])
show(cb, "ground: Arm A/B findings + 4 candidate claims")

# ---- propose candidates (advisory discriminators) ----
cb = s.propose([
    {"id":"cand_4phase_claim","statement":"current 4-phase mechanism, unchanged",
     "discriminator":"Native architecture and already-narrowed/validated arithmetic, at the "
                      "cost of frontier-table complexity and no real-engine validation yet."},
    {"id":"cand_armA_claim","statement":"Arm A, as documented",
     "discriminator":"Only candidate whose core correctness claim is empirically refuted."},
    {"id":"cand_armB_claim","statement":"Arm B, translated",
     "discriminator":"Verified on its own toy model, but carries unpaid architecture-translation "
                      "and sign-encoding costs."},
    {"id":"cand_hybrid_claim","statement":"hybrid: native arch + Arm B/A-style whole-result negate",
     "discriminator":"Keeps every current-design advantage, drops the frontier table, checked "
                      "clean on a large arithmetic sweep, still reference-model only."},
])
show(cb, "propose: 4 candidates")

# ---- checks: falsifiers against each candidate ----
cb = s.check([
    {"id":"f_armA","kind":"falsifier","target":"cand_armA_claim",
     "method":"cite grade_armA.py sweep result",
     "result":"21844/65025 inputs violate the assumed single-active-token invariant",
     "outcome":"failed"},
    {"id":"f_armB","kind":"falsifier","target":"cand_armB_claim",
     "method":"check whether the translation has actually been designed/closed",
     "result":"No — shared/padded spine, token-edge type, and sign-tag node are all still "
              "unresolved gaps against Perspective's actual primitives",
     "outcome":"failed"},
    {"id":"f_4phase","kind":"falsifier","target":"cand_4phase_claim",
     "method":"check engine validation status and frontier-table completeness",
     "result":"reference-model only, not run against the real rule engine; 2 of 8 frontier "
              "keys unproven unreachable",
     "outcome":"survived"},
    {"id":"f_hybrid","kind":"falsifier","target":"cand_hybrid_claim",
     "method":"implemented both recurrences in Python; extended phase-1's borrow computation "
              "through the full max(len(a),len(b)) width; applied one uniform two's-complement "
              "negate over the entire raw result when the final borrow escaped; swept "
              "combinatorially, by edge case, and randomly against ground truth",
     "result":"0 failures across a,b in 0..199 combinatorially (~40000 pairs), 8 explicit edge "
              "cases, and 20000 random pairs up to 24-bit width",
     "outcome":"survived"},
])
show(cb, "check: falsifiers on all 4 candidates")

# ---- carry the two assumed recurrences explicitly (not exploring their negation this round) ----
cb = s.carry("a_subdef", "standard full-subtractor recurrence; would flip if Perspective's own "
             "bit convention differs from LSB-first / this exact borrow formula — unverified "
             "against actual engine source this session")
show(cb, "carry a_subdef")
cb = s.carry("a_negdef", "standard two's-complement negate recurrence; would flip under a "
             "different negation convention — unverified against actual engine source this session")
show(cb, "carry a_negdef")

# ---- commit ----
cb = s.commit("cand_hybrid_claim", "assumed", ["a_subdef", "a_negdef"])
show(cb, "commit")

s.save("design_choice_v0_3.json")
print("saved design_choice_v0_3.json, committed =", s.committed is not None)
