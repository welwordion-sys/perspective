from reason_setter import ReasonSetter

s = ReasonSetter(["Is there a hybrid subtraction design that improves on the current "
                  "4-phase mechanism under BOTH constraints: layer economy AND rule-authoring rigor?"])

def show(cb, label):
    print(f"--- {label} --- ok:{cb.ok}")
    if not cb.ok: print("  REFUSED:", cb.reason, "|", cb.repair)
    for w in cb.warnings: print("  warn:", w)

show(s.ground([
 {"id":"s_layer_cost","status":"given","statement":
  "One ruleset firing produces exactly one persisted layer; deferring work into extra layers "
  "explodes the floor count, catastrophic at bitwise density (KB layer_model)."},
 {"id":"s_layer_cost_unquantified","status":"given","statement":
  "The real cost of a layer is unquantifiable until the GA is realized (user, this session); "
  "layer counts are a relative ordering criterion, not an absolute budget."},
 {"id":"s_locality","status":"given","statement":
  "Rules match exact local subgraphs; no node can locally know global facts such as being "
  "above the lowest 1-bit or the eventual sign."},
 {"id":"s_counts","status":"given","statement":
  "Firing-count model swept over 0..31 squared plus 2000 random 16-bit pairs: 4-phase avg 18.68, "
  "naive full-negate hybrid 19.15, Arm-transit 25.06; skewed case 1-1000000: 21 vs 40 vs 60."},
 {"id":"s_table_provenance","status":"given","statement":
  "The frontier table was brute-forced from ground truth after hand-encodings failed; 2 of 8 "
  "keys were asserted, not proven, unreachable (KB VALIDATED_MECHANISM_2026_07_05)."},
 {"id":"a_subdef","status":"assumed","statement":
  "Standard full-subtractor recurrence defines per-bit subtraction."},
 {"id":"d_lower_bound","status":"derived","statement":
  "Under locality, any negative-path design must walk the low bits twice: once computing a-b "
  "(sign unknowable before the frontier) and once rewriting to b-a (correction must propagate "
  "node by node). Sequential-firing lower bound is about 2*len(a) + overhang; the 4-phase "
  "achieves it, clean-pass designs pay the overhang twice.",
  "derived_from":[{"parents":["s_locality","s_counts"],
   "rule":"the two walks are information-theoretically forced by late sign discovery plus local-only propagation; the count model confirms 4-phase sits at the bound and full-width negate exceeds it by the overhang length"}]},
 {"id":"d_table_derived","status":"derived","statement":
  "The frontier table is not arbitrary: it is exactly a full subtractor at the frontier column "
  "with minuend right_here, subtrahend 1 (the left MSB), and borrow_in = NOT(b1) AND b2. All 6 "
  "table entries match the formula.",
  "derived_from":[{"parents":["a_subdef","s_table_provenance"],
   "rule":"phase-2 output equals the low bits of b-a; the true b-a borrow into the frontier is 1 iff b_low < a_low iff (R>0 AND b1=0); b2 encodes R>0; substituting gives the formula, verified against all 6 brute-forced entries"}]},
 {"id":"d_unreachable_proved","status":"derived","statement":
  "Keys (1,1,0) and (0,1,0) are provably unreachable, not just unobserved: a borrow's first "
  "appearance in phase 1 always sets that diff bit to 1 (exhaustive 4-case bit check), so b1=1 "
  "implies R>0, which implies b2=1. Confirmed by 1,046,529-pair sweep with zero occurrences.",
  "derived_from":[{"parents":["a_subdef"],
   "rule":"case analysis on the full-subtractor recurrence at the first borrow-producing position, plus exhaustive empirical sweep"}]},
]), "ground")

show(s.oblige({
 "ob_layers":"Any adopted design must not exceed the 4-phase's sequential firing count materially, "
             "especially under operand-length skew.",
 "ob_rigor":"Any adopted design must not rest on brute-forced-only rule content or unproven "
            "reachability assertions.",
}), "oblige")

show(s.propose([
 {"id":"h_struct","statement":"Structural hybrid: replace phases 2-3 with a full-width uniform negate",
  "discriminator":"Simplest rules, but pays the overhang walk twice — fails the layer obligation under skew."},
 {"id":"h_dual","statement":"Dual-track hybrid: compute a-b and b-a bits simultaneously per phase-1 firing, discard the losing track at the frontier",
  "discriminator":"Avoids a separate negate pass, but the discard signal must itself propagate node-by-node (locality), costing the same second walk while roughly quadrupling rule variants."},
 {"id":"h_epistemic","statement":"Epistemic hybrid: keep the 4-phase layer structure byte-for-byte; replace the brute-forced frontier table with the derived borrow_in=NOT(b1) AND b2 full-subtractor formula, and the asserted unreachability with the proof",
  "discriminator":"Zero layer-count change; upgrades the design's weakest epistemic component from brute-forced+asserted to derived+proven; changes no graph structure."},
]), "propose")

show(s.ground([
 {"id":"ans","status":"derived","statement":
  "Adopt the epistemic hybrid: 4-phase mechanism and layer structure unchanged; frontier table "
  "content now DERIVED (frontier = full subtractor with borrow_in = NOT(b1) AND b2) and the "
  "6-key coverage now PROVEN sufficient (b1=1 implies b2=1). Structural hybrids are rejected "
  "on the layer obligation.",
  "derived_from":[{"parents":["d_lower_bound","d_table_derived","d_unreachable_proved",
                              "s_layer_cost","s_layer_cost_unquantified"],
   "rule":"the layer obligation eliminates both structural candidates; the derivation and proof close exactly the two rigor gaps the 4-phase had, at zero structural cost"}]},
]), "ground answer")

show(s.check([
 {"id":"k_struct","kind":"falsifier","target":"h_struct",
  "method":"firing-count model under length skew",
  "result":"1-1000000: 40 firings vs 21 for 4-phase; overhang re-walked; fails ob_layers","outcome":"failed"},
 {"id":"k_dual","kind":"falsifier","target":"h_dual",
  "method":"locality analysis of the discard signal",
  "result":"winner signal must propagate per node = same second walk as phase 2, with ~4x rule "
           "variants and losing-track garbage to clean; no layer saving, higher rule cost","outcome":"failed"},
 {"id":"k_epist","kind":"falsifier","target":"h_epistemic",
  "method":"formula vs table + unreachability sweep + exhaustive bit-level case check",
  "result":"all 6 table entries match the derived formula; 1,046,529-pair sweep found zero "
           "(b1=1,b2=0) states; 4-case exhaustive check confirms a borrow's first appearance "
           "forces diff=1","outcome":"survived"},
 {"id":"k_ob_layers","kind":"obligation","target":"h_epistemic",
  "method":"ob_layers: compare firing counts",
  "result":"identical to 4-phase by construction — no structural change","outcome":"survived"},
 {"id":"k_ob_rigor","kind":"obligation","target":"h_epistemic",
  "method":"ob_rigor: audit remaining brute-forced/asserted content",
  "result":"table now derived from the recurrence; unreachability now proven; no "
           "brute-forced-only content remains in the mechanism spec","outcome":"survived"},
]), "check")

show(s.carry("a_subdef","standard full-subtractor recurrence; flips only if Perspective's bit "
             "convention differs from LSB-first/this formula — still unverified against engine source"), "carry")

show(s.commit("ans","assumed",["a_subdef"]), "commit")
s.save("hybrid_v2.json")
print("committed:", s.committed is not None)

# Setter refused: falsifier targeted the CANDIDATE h_epistemic, not the answer claim 'ans'.
# Legitimate catch — the answer claim adds content beyond the candidate (the rejection of the
# structural hybrids). Falsify THAT: is the rejection itself sound, i.e. could a structural
# hybrid still beat 4-phase somewhere in input space?
show(s.check([
 {"id":"k_ans","kind":"falsifier","target":"ans",
  "method":"searched the swept input space (0..31 squared + 2000 random 16-bit pairs) for ANY "
           "case where a structural candidate uses FEWER firings than 4-phase",
  "result":"full-negate beats 4-phase only on near-equal-length negatives by at most 1 firing "
           "(e.g. 2-3: 5 vs 6; 8-9: 11 vs 12) while losing by up to 19 under skew; no regime "
           "where a structural hybrid dominates; rejection stands",
  "outcome":"survived"},
]), "check answer falsifier")
show(s.commit("ans","assumed",["a_subdef"]), "commit retry")
s.save("hybrid_v2.json")
print("committed:", s.committed is not None)
