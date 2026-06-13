"""
arithmetic.py — consolidated spine-topology arithmetic rules (WORKING BASELINE).

This file is the single entry point for the spine-encoded addition rules, assembled
from the working prototype modules so a new session starts from the verified state
rather than reconstructing it. It is the NON-prototype baseline: the engine
(basic_machinery.operations._apply_pass) is the committed one, NOT the strict
four-case-4c prototype (which is mid-migration — see STATUS below).

============================================================================
STATUS (as of 2026-06-13) — read this before building on top.
============================================================================

TOPOLOGY (live, ratified): operator IS the anchored directed cycle; the op node
as a separate handle is eliminated. handle = cycle[-1]; left port = cycle[0]
(carries the anchor, the left landmark); right port = cycle[1]. Numbers are spine
encoded: a spine node -OP-> its bit-leaf (leaf structural self-loop = bit 1),
spines chained structurally LSB->MSB. The GitHub main `encoding.py` implements
this; older project-attached copies were stale.

RULES AND THEIR VERIFIED STATUS:

  add_init  (spine_addinit_v4.build_labeled):
      FIRES and is correct on the post-encode state. For no-carry single-bit
      operands it leaves the state finalise consumes. VERIFIED.

  add_finalise / 1-bit  (spine_finalise_v1.build_finalise):
      The single-result-bit, no-carry terminal rule. Fires when BOTH operands
      are exhausted to ZERO and there is NO carry, result spine length 1.
      VERIFIED end-to-end: add_init -> finalise rewrites 0+1 and 1+0 to result 1
      (decodes identically to a hand-checked reference). Correctly does NOT fire
      on the carry path. This rule was additionally round-tripped through the
      graph-editing channel (Supabase project 'Graph editing and exchange
      system') and reconstructed/re-verified — see KB graph_channel_built.

  bit_add  (spine_bitadd_v1.build_labeled):
      Middle step, 1-result-bit variant. FIRES on the post-add_init carry state
      (e.g. 1+1 -> bit_add(0,0,carry_in=1,single,single)) and computes the
      CORRECT 2-bit result spine (1+1 -> value 2, well-formed: LSB bit 0, MSB
      bit 1, no stray carry edges). VERIFIED to compute correctly. It leaves
      orphaned scaffold (born-without-consume at the node level) but the RESULT
      is correct.
      GENERATION GUARD REQUIRED: bit_add must NOT generate the (left_bit=0,
      right_bit=0, carry_in=0) variant for any operand state — that terminal
      both-operands-zero-no-carry state belongs exclusively to finalise. The
      single/single case is degree-identical to finalise (confirmed collision);
      the term/cont (0,0,c0) cases describe unreachable configurations (a zero
      operand is structurally terminal, cannot carry a successor). Skip all
      (0,0,c0) in the registration loop.

  add_finalise / multibit:  UNBUILT. This is the blocker to closing the carry
      path. 1+1 stalls after bit_add because no rule terminates a multi-bit
      result spine. The 1-bit and multibit finalise are SEPARATE rules
      (distinct match shapes): in the 1-bit case the result LSB's operational
      edge is INTERNAL to the match; in the multibit case it crosses to a
      placeholder (the rest of the spine rides outside the window).

  drain:  not consolidated here / not yet verified under spine topology.

BOUNDARY / PLACEHOLDER MODEL — DESIGN DIRECTION (intended, not yet implemented):
      We INTEND to move to CASE-SENSITIVE boundary preservation. Today the
      output-side boundary (step-4c preserve) is effectively structural-only and
      direction-coarse, which is why operational external edges were historically
      dropped (the bit_add parent-pointer / result-leaf bug). The intended model
      is four independent preserve-cases per output boundary node, keyed by
      (type, direction): in-op, in-struct, out-op, out-struct. All four present
      => preserve every crossing.

      CRITICAL CONSTRAINT discovered while prototyping this: preserve-directives
      MUST be construction-time signals that step-4c consumes and DISCARDS — they
      must NOT persist as real edges. A prototype that materialized the four
      crossings as real marker-chain edges inflated the boundary node's real
      degree, which the DOWNSTREAM rule's input matcher counts (output of rule N
      is matched as input of rule N+1), breaking the chain (add_init fired but
      finalise/bit_add then NO-MATCHed). So: input `cross` stays precise and
      matcher-counted; output `boundary` becomes case-sensitive but its
      directives are signals, removed after preservation, leaving real degree
      unchanged. The placeholder/marker machinery already does exactly this
      consume-and-discard for markers — the four preserve-cases should follow it.
      See KB cross_boundary_convention + apply_pass_4c_directional_cleanup.

CROSS vs BOUNDARY convention:
      cross   = INPUT-side placeholder crossing. Typed (struct/op) and
                direction-aware; counted by the matcher toward expected degree.
                Leave precise — never over-provision (breaks matching).
      boundary= OUTPUT-side preserve mark. Direction-aware. Moving to
                case-sensitive (type-aware) per the design direction above.

KNOWN TOOLING:
      g2dump v2 fixes the role/mapping classifier bug (it had emitted internal
      operational edges as `mapping`, cascading into role misclassification).
      Classify side by label prefix (in_/out_), reserve `mapping` for true
      input->output instructions only.

============================================================================
"""
from __future__ import annotations

# The working rule builders live in their prototype modules; this file assembles
# and registers them. Import paths assume the spine_* modules and scratch_add_init2
# are importable alongside basic_machinery.
from basic_machinery.operations import register

import spine_addinit_v4 as _addinit
import spine_bitadd_v1 as _bitadd
import spine_finalise_v1 as _finalise


_STATES = ('single', 'term', 'cont')


def _named(rule, name):
    """Builders hardcode a fixed name; give each variant a unique one so they
    can coexist in the registry."""
    rule.name = name
    return rule


def register_add_init():
    """add_init: every (left_bit, right_bit) x (left_state, right_state)."""
    for lb in (0, 1):
        for rb in (0, 1):
            for ls in _STATES:
                for rs in _STATES:
                    rule, _labels = _addinit.build_labeled(lb, rb, ls, rs)
                    register(_named(rule, f'add_init_{lb}{rb}_{ls}_{rs}'))


def register_bit_add():
    """bit_add middle step, WITH the finalise-exclusion guard.

    Skips every (0,0,carry_in=0) variant: both operands terminal-zero with no
    carry is finalise's exclusive terminal state (single/single is degree-
    identical to finalise; term/cont (0,0,c0) are unreachable). See STATUS.
    """
    for lb in (0, 1):
        for rb in (0, 1):
            for ci in (0, 1):
                for ls in _STATES:
                    for rs in _STATES:
                        if lb == 0 and rb == 0 and ci == 0:
                            continue  # finalise owns the both-zero-no-carry state
                        rule, _labels = _bitadd.build_labeled(lb, rb, ci, ls, rs)
                        register(_named(rule, f'bit_add_{lb}{rb}_c{ci}_{ls}_{rs}'))


def register_finalise_1bit():
    """The verified single-result-bit, no-carry terminal rule."""
    rule, _labels = _finalise.build_finalise()
    register(_named(rule, 'add_finalise_1bit'))


def register_all():
    register_add_init()
    register_bit_add()
    register_finalise_1bit()
    # multibit finalise: UNBUILT — the carry path does not terminate yet.


if __name__ == '__main__':
    register_all()
    from basic_machinery.operations import _registry
    print(f"registered {len(_registry)} rules")
