"""
travel_loop.py — der GA-Pfad: ruleset -> matches -> layer -> reversibility.

DIE LUECKE, DIE DAS SCHLIESST:
apply_compound's docstring sagt "matches: list of (operation, binding) already
collected for this pass (e.g. via match_all/find_all_cores per rule)". Dieser
Produzent existierte nicht. apply_compound, reverse_fire und
reclassify_after_firing sind alle gebaut und getestet — aber matches wurde
ihnen immer von Hand hereingereicht. Es gab keinen Aufrufer, der aus einem
Ruleset + Graph die matches erzeugt. Genau das ist der Schritt, den ein GA
braucht: neue Regeln -> anwenden -> Layer -> reversibel?

WAS HIER NEU IST: nur fire_layer(). Alles andere ist bestehende Maschinerie
(Matcher.collect_all, reclassify_after_firing). Kein Eingriff in
basic_machinery.

SEMANTIK — collect_all, NICHT dispatch:
  dispatch()    = erste feuernde Regel, dann Stopp (forward drive)
  collect_all() = jede Regel, jede Bindung (compound firing)
Compound Match Resolution muss ALLE matches sehen, bevor sie entscheidet,
welche ueberlappen. Ein first-match-wins-Loop kann das nicht liefern.

GROUPING TRAEGT HIER — ABER NUR BEI GETEILTER STRUKTUR:
  Additionsregeln (252):  254x, 1 statt 252 invocations, 4 core-misses
                          erschlagen 248 regeln. Baum: 4 kinder-cores.
  Volle Registry (257):   KEIN gewinn. Der Baum ist FLACH (0 kinder-cores,
                          alle 257 direkt an der wurzel) — add/sub/mul/div
                          teilen kaum struktur, es gibt nichts zu gruppieren.
Fuer den GA heisst das: pro Operator-Familie ein Matcher, nicht einer ueber
die ganze Registry.
"""
from __future__ import annotations
import os
import sys

_R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in ['', 'grouping', 'builders', 'basic_machinery']:
    _q = os.path.join(_R, _p)
    if _q not in sys.path:
        sys.path.insert(0, _q)

from basic_machinery.reverse_compound import reclassify_after_firing


def fire_layer(lg, registry, base_layer, new_layer, matcher):
    """EIN GA-schritt: matches sammeln, layer feuern, reversibilitaet pruefen.

    Args:
        lg, registry: LayeredGraph + LayerRegistry
        base_layer, new_layer: layer keys
        matcher: grouping.matcher.Matcher ueber dem ruleset

    Returns:
        (fired, fwd_result, verdict)
        fired=False wenn keine regel matcht (nichts wird geschrieben).
        verdict ist reverse_fire's dict: reversible True/False/unverifiable.
        Bei True hat reclassify_after_firing den LayerRecord bereits von
        UPWARD auf SIDEWAYS gehoben — das ist der 'proven otherwise'-schritt,
        den laut reverse_compound.py's docstring "nothing anywhere ever calls".

    reclassify_after_firing ruft apply_compound INTERN. Deshalb wird hier NICHT
    selbst gefeuert — sonst liefe der pass doppelt.
    """
    base = lg.materialize(base_layer)
    matches = matcher.collect_all(base)
    if not matches:
        return False, None, None
    fwd, verdict = reclassify_after_firing(lg, registry, base_layer,
                                           new_layer, matches)
    return True, fwd, verdict


def travel(lg, registry, matcher, start_layer=0, max_steps=40):
    """Der travel path: wiederholt fire_layer bis nichts mehr matcht.

    Returns (final_layer, trail) — trail ist eine liste von
    (layer_key, reversible) pro schritt. reversible ist True (SIDEWAYS,
    bewiesen umkehrbar) / False / None (unverifiable oder nicht geprueft).
    """
    current = start_layer
    trail = []
    for _ in range(max_steps):
        nxt = current + 1
        fired, _fwd, verdict = fire_layer(lg, registry, current, nxt, matcher)
        if not fired:
            break
        rev = verdict.get("reversible") if verdict else None
        trail.append((nxt, rev))
        current = nxt
    return current, trail
