"""Lockstep-Kern (final): vollstaendiges, wandfreies Paar-Verfahren.

EINSICHT (Sven, bestaetigt 2026-07-20): ein zusammenhaengender Match wird
Kante fuer Kante gebaut. Ein Knoten dockt nur an NACHBARN seines gebundenen
Bildes an — Verzweigung ~Nachbarschaft, nicht |B|. Die fruehere alle-B-Regel
zaehlte injektive Teilabbildungen auf ganz B (fakultaer) und war die
eigentliche Ursache der Skalierungswand.

KANDIDATEN fuer Frontier-Knoten a: B-Knoten b, wo eine Kante von a an b
JETZT realisiert wird —
  - Self-Loop a->a(k,y): b braucht b->b(k,y)
  - Kante a->x(k,y), x GEBUNDEN an bx: b braucht b->bx(k,y)  (bzw. eingehend)
KEINE Kante zu ungebundenen Nachbarn (die alle-B-Klausel) — deren Cores
liefert ihr eigener Seed, das Zusammensetzen dockt sie an.

VOLLSTAENDIGKEIT gilt auf CORE-Ebene (mit reassemble), nicht per Seed:
verlustfrei gegen Brute-Force-Referenz 500/500 (bis 5x5, 3 kinds) + 4/4
Haertefaelle + Teilkomponenten-Konstruktion. ERS neighbor_lockstep.json.
"""
from collections import defaultdict


def _matched(A, nm, bs):
    out = set()
    for s, t, k, y in A:
        bs_, bt_ = nm.get(s), nm.get(t)
        if bs_ is not None and bt_ is not None and (bs_, bt_, k, y) in bs:
            out.add((s, t, k, y))
    return frozenset(out)


def _seed_comp_leaf(A, nm, seed_a, bs):
    m = _matched(A, nm, bs)
    used = {seed_a}
    for e in m:
        used.add(e[0]); used.add(e[1])
    nmu = {k: v for k, v in nm.items() if k in used}
    comp = {seed_a}; ch = True
    while ch:
        ch = False
        for e in A:
            es, et = e[0], e[1]
            if es in nmu and et in nmu and (es in comp) != (et in comp):
                comp.add(es); comp.add(et); ch = True
    m = frozenset(e for e in m if e[0] in comp and e[1] in comp)
    nmu = {k: v for k, v in nmu.items() if k in comp}
    return m, nmu


def seed_components(A, B, seed_a, seed_b, aedges, bs, bn):
    comps = {}

    def cands(a, nm, nmr):
        cs = set()
        for e in aedges[a]:
            s, t, k, y = e
            if s == t == a:
                for b in bn:
                    if b not in nmr and (b, b, k, y) in bs:
                        cs.add(b)
                continue
            other = t if s == a else s
            a_src = (s == a)
            if other in nm:
                bo = nm[other]
                for b in bn:
                    if b in nmr:
                        continue
                    if a_src and (b, bo, k, y) in bs:
                        cs.add(b)
                    if (not a_src) and (bo, b, k, y) in bs:
                        cs.add(b)
        return cs

    def expand(nm, nmr, ex):
        fr = []
        for a in nm:
            for e in aedges[a]:
                o = e[1] if e[0] == a else e[0]
                if o != a and o not in nm and o not in ex and o not in fr:
                    fr.append(o)
        if not fr:
            m, nmu = _seed_comp_leaf(A, nm, seed_a, bs)
            if m:
                comps[(m, tuple(sorted(nmu.items())))] = (m, nmu)
            return
        a = min(fr)
        for c in sorted(cands(a, nm, nmr)):
            n2 = dict(nm); n2[a] = c
            r2 = dict(nmr); r2[c] = a
            expand(n2, r2, ex)
        expand(nm, nmr, ex | {a})

    expand({seed_a: seed_b}, {seed_b: seed_a}, frozenset())
    return list(comps.values())


def all_components(A, B):
    an = sorted({n for e in A for n in (e[0], e[1])})
    bn = sorted({n for e in B for n in (e[0], e[1])})
    bs = set(B)
    aedges = defaultdict(list)
    for e in A:
        aedges[e[0]].append(e)
        if e[1] != e[0]:
            aedges[e[1]].append(e)
    comps = {}
    for a in an:
        for b in bn:
            for m, nmu in seed_components(A, B, a, b, aedges, bs, bn):
                comps[(m, tuple(sorted(nmu.items())))] = (m, nmu)
    return list(comps.values())


def _global_dominance(components):
    """GLOBALER Dominanzfilter ueber ALLE Seeds. Der per-Seed-Filter laesst
    Teilstuecke stehen, die von EINEM anderen Seed maximal, aber global in
    einer groesseren Struktur enthalten sind. Hier gestrichen, BEVOR
    reassemble laeuft — sonst baut reassemble knotendisjunkte Vereinigungen
    aus tausenden ineinander verschachtelten Fragmenten (kombinatorisch).

    Dominanz zweiseitig wie im per-Seed-Filter: (m1,map1) dominiert von
    (m2,map2) wenn m1<m2 und map1 konsistent fortgesetzt in map2, ODER m1==m2
    und map1 echte Teilmenge von map2.
    """
    out = list(components)
    keep = []
    for i, (m1, p1) in enumerate(out):
        dom = False
        for j, (m2, p2) in enumerate(out):
            if i == j:
                continue
            if (m1 < m2 and all(p2.get(k) == v for k, v in p1.items())) or \
               (m1 == m2 and set(p1.items()) < set(p2.items())):
                dom = True
                break
        if not dom:
            keep.append((m1, p1))
    return keep


def _match_essential(components):
    """Reduziere jede Komponente auf die fuer den MATCH noetigen Knoten.
    Ertraglose Zwischenbindungen (Knoten, die an keiner gematchten Kante
    haengen) werden aus der Map geworfen. Sie sind fuer den Core irrelevant,
    machen aber sonst zwei Komponenten faelschlich knoten-UNdisjunkt (eine
    ertraglose a1->b3-Bindung blockiert b3 fuer eine andere Komponente).
    Danach nach (m, essenzielle map) dedupliziert."""
    out = {}
    for m, nmu in components:
        used = set()
        for e in m:
            used.add(e[0]); used.add(e[1])
        ess = {k: v for k, v in nmu.items() if k in used}
        out[(m, tuple(sorted(ess.items())))] = (m, ess)
    return list(out.values())


def reassemble(components):
    # 1) Ertraglose Zwischenbindungen raus (sonst falsche Konkurrenz).
    components = _match_essential(components)
    # 2) GLOBALE Dominanz: enthaltene Fragmente raus (deine Diagnose:
    #    972/973 Strukturen waren Teilmengen EINER maximalen).
    components = _global_dominance(components)
    comps = []
    for m, nmu in components:
        comps.append((frozenset(m), frozenset(nmu.keys()), frozenset(nmu.values())))
    n = len(comps)
    unions = set()

    def grow(chosen, acc_a, acc_b, start):
        extended = False
        for i in range(start, n):
            c = comps[i]
            if not (c[1] & acc_a) and not (c[2] & acc_b):
                extended = True
                grow(chosen + [i], acc_a | c[1], acc_b | c[2], i + 1)
        if not extended and chosen:
            unions.add(frozenset().union(*(comps[i][0] for i in chosen)))

    grow([], frozenset(), frozenset(), 0)
    ul = list(unions)
    return [m1 for i, m1 in enumerate(ul)
            if not any(i != j and m1 < m2 for j, m2 in enumerate(ul))]


def pair_cores(A, B):
    """Alle maximalen Cores (matched-Kantenmengen) des Paares."""
    return reassemble(all_components(A, B))


# ==========================================================================
# RAND-OBJEKT + ZONENVERGLEICH  (ERS border_object.json, verifiziert)
# ==========================================================================
# Atomare Cores fuer Zonenarbeit = zusammenhaengende Komponenten nach
# match-essential + globaler Dominanz (VOR reassemble). Vereinigungen
# unzusammenhaengender Teile sind Konsumenten-Ableitung (positive Monotonie).

def _matched_components(matched, amap):
    """Zerlege eine matched-Kantenmenge in ueber GEMATCHTE Kanten
    zusammenhaengende Teile. Der Vertrag buendelt ueber ungematchte A-Kanten
    (a0-a2 zieht getrennte Self-Loops zusammen); fuer Zone/Rand/Cut-Zeuge ist
    aber die matched-zusammenhaengende Struktur die atomare Einheit."""
    adj = defaultdict(set)
    for s, t, k, y in matched:
        adj[s].add(t); adj[t].add(s)
    seen = set()
    out = []
    for start in set(adj):
        if start in seen:
            continue
        comp = {start}; stack = [start]; seen.add(start)
        while stack:
            x = stack.pop()
            for nb in adj[x]:
                if nb not in seen:
                    seen.add(nb); comp.add(nb); stack.append(nb)
        m_c = frozenset(e for e in matched if e[0] in comp and e[1] in comp)
        amap_c = {k: v for k, v in amap.items() if k in comp}
        out.append((m_c, amap_c))
    return out


def connected_cores(A, B):
    """Ueber GEMATCHTE Kanten zusammenhaengende Cores mit Map: (matched, amap).
    Atomare Einheit fuer Zone/Rand/Cut-Zeuge und Zonen-Transitivitaet."""
    raw = _global_dominance(_match_essential(all_components(A, B)))
    out = {}
    for m, amap in raw:
        for m_c, amap_c in _matched_components(m, amap):
            if m_c:
                out[(m_c, tuple(sorted(amap_c.items())))] = (m_c, amap_c)
    vals = list(out.values())
    return [vals[i] for i, (m1, _) in enumerate(vals)
            if not any(i != j and m1 < m2 for j, (m2, _) in enumerate(vals))]


def _bimg(e, amap):
    s, t, k, y = e
    return (amap[s], amap[t], k, y)


def core_zone(matched, amap):
    """Belegte B-Kantenregion des Cores."""
    return frozenset(_bimg(e, amap) for e in matched)


def core_border(matched, amap, B):
    """Rand = B-Kanten an belegten B-Knoten, ausserhalb der Zone (Cut-Kanten)."""
    R = core_zone(matched, amap)
    Vb = set(amap.values())
    return frozenset((s, t, k, y) for (s, t, k, y) in B
                     if (s, t, k, y) not in R and (s in Vb or t in Vb))


def cut_witness(matched, amap, B):
    """Zahl voller Einbettungen der A-Struktur des Cores in Zone∪Rand.
    ==1: eindeutiger Cut (Ausschluss positiv fortpflanzbar).
    >1 : Verschiebungssymmetrie (Ausschluss braucht echte Suche)."""
    sub = list(core_zone(matched, amap) | core_border(matched, amap, B))
    A = list(matched)
    comps = _global_dominance(_match_essential(all_components(A, sub)))
    return sum(1 for m, _ in comps if frozenset(m) == frozenset(A))


def zone_transitivity(cores_AB, cores_BC):
    """Positive Transitivitaet ohne A-C-Suche: untere Schranke der Cores von
    (A,C), vermittelt ueber die geteilte B-Region.

    cores_AB: (matched_A, amap A->B).  cores_BC: (matched_B, bmap B->C).
    Rueckgabe: Liste (a_edges, acmap A->C) — verlustfrei sound (<= echtem
    core(A,C)), NICHT vollstaendig (nur B-vermittelte Cores)."""
    out = {}
    for m1, amap in cores_AB:
        inv1 = {}                      # B-Kante -> A-Kante
        bnode_of = {v: k for k, v in amap.items()}   # B-Knoten -> A-Knoten
        for e in m1:
            inv1[_bimg(e, amap)] = e
        R1 = set(inv1.keys())
        for m2, bmap in cores_BC:
            shared = R1 & set(m2)      # geteilte B-Kanten
            if not shared:
                continue
            a_edges = frozenset(inv1[be] for be in shared)
            # komponierte Map A->C ueber die geteilten B-Knoten
            acmap = {}
            ok = True
            for be in shared:
                s, t, k, y = be
                for bn in (s, t):
                    an = bnode_of.get(bn)
                    if an is None or bn not in bmap:
                        ok = False; break
                    cn = bmap[bn]
                    if an in acmap and acmap[an] != cn:
                        ok = False; break
                    acmap[an] = cn
                if not ok:
                    break
            if not ok or len(set(acmap.values())) != len(acmap):
                continue               # nicht injektiv -> verwerfen
            out[(a_edges, tuple(sorted(acmap.items())))] = (a_edges, acmap)
    # Dominanz: nur maximale a_edges-Mengen
    vals = list(out.values())
    keep = []
    for i, (m1, _) in enumerate(vals):
        if not any(i != j and m1 < m2 for j, (m2, _) in enumerate(vals)):
            keep.append(vals[i])
    return keep


# ==========================================================================
# TRANSITIVITAET: Such-Lenkung (positiv) + Skip-Entscheidung (negativ)
# ERS neg_transitivity.json. Sound unter Hub(B) + eindeutigem Cut.
# ==========================================================================

def _covered_nodes(covered):
    cov = set()
    for cset in covered:
        cov |= set(cset)
    return cov


def transitive_zone(cores_AB, cores_BC):
    """Positiv: bekannt-geteilte A-Regionen (untere Schranke, ueber B vermittelt).
    Rueckgabe: Liste (a_edges, acmap A->C) — die Seed-Regionen fuer A-C."""
    return zone_transitivity(cores_AB, cores_BC)


def _B_is_hub_for(qcores_AC_structs, B):
    """Exakt (ueber connected_cores, nicht ref-Naeherung): enthaelt B jede der
    gegebenen A-C-Kernstrukturen als eigene matched-Struktur?"""
    for q in qcores_AC_structs:
        found = any(frozenset(m) == frozenset(q)
                    for m, _ in connected_cores(list(q), B))
        if not found:
            return False
    return True


def skip_decision(A, B, cores_AB, cores_BC, n_min=3, min_ratio=0.3,
                  known_AC_structs=None):
    """Negative Transitivitaet: darf die A-C-Suche uebersprungen werden?

    SOUND nur unter zwei Bedingungen (ERS neg_transitivity):
      (1) B ist Hub fuer die (bekannten) A-C-Strukturen  -> kein Typ-1-Eindringen
      (2) jede die Zone stellende A-B-Kernzone ist eindeutig geschnitten
          (cut_witness==1)                               -> keine Verschiebung

    known_AC_structs: falls die A-C-Kerne aus einem Vorfahr-Kontext bekannt sind
    (DAG), pruefe Hub exakt gegen sie. Ohne sie ist Hub nicht zertifizierbar
    -> kein Skip (konservativ False).

    Rueckgabe: (skip: bool, seeds: Liste der Seed-Regionen fuer die Rest-Suche).
    skip=True  -> A-C-Suche entfaellt, cores(A,C) == transitive Zone.
    skip=False -> gelenkte Suche noetig, seeds = transitive Zonen als Startpunkte.
    """
    trans = transitive_zone(cores_AB, cores_BC)
    covered = [a for a, _ in trans if a]
    seeds = covered
    if not covered:
        return False, seeds
    # Bedingung 2: Eindeutigkeit der die Zone stellenden A-B-Zonen
    unambiguous = all(
        cut_witness(m, amap, B) == 1
        for m, amap in cores_AB
        if any(frozenset(m) >= c for c in covered)
    )
    if not unambiguous:
        return False, seeds
    # Bedingung 1: Hub. Ohne bekannte A-C-Strukturen nicht zertifizierbar.
    if known_AC_structs is None:
        return False, seeds
    if not _B_is_hub_for(known_AC_structs, B):
        return False, seeds
    return True, seeds


def self_overlaps(G):
    """Selbstueberlappungskarte einer Regel/Struktur G: alle vollen
    Einbettungen von G in G (Automorphismen als Knoten-Maps, inkl. Identitaet).

    Basis fuer (a) den Cut-Zeugen (nichttriviale Selbstueberlappung am Rand =
    Verschiebbarkeit) und (b) die Kompression gespeicherter Schnittmengen:
    eine geteilte Struktur, die an mehreren durch Selbstueberlappung verbundenen
    Positionen sitzt, wird einmal gespeichert; die anderen Positionen erzeugt
    diese Karte. cut_witness==1 (nur Identitaet auf Zone-union-Rand) => nichts
    zu rekonstruieren."""
    Gl = list(G)
    comps = _global_dominance(_match_essential(all_components(Gl, Gl)))
    seen = set()
    out = []
    for m, nm in comps:
        if frozenset(m) == frozenset(Gl):
            key = tuple(sorted(nm.items()))
            if key not in seen:
                seen.add(key)
                out.append(nm)
    return out


def transit_via(cores_AX, cores_XC):
    """A-SEITIGE transitive Ableitung (cut-at-edge exakt) — die Variante, die
    die Ersparnis bringt.

    cores_AX: (m_in_A, amap A->X)  — der gespeicherte Kern A gegen Vermittler X.
    cores_XC: (m_in_X, xmap X->C)  — der gespeicherte Kern X gegen Ziel C.

    Bildet die A-Kanten von cores_AX per amap nach X ab und schneidet CUT-AT-EDGE
    EXAKT (Kantengleichheit, nicht Teilmenge) gegen die X-Kanten von cores_XC.
    Der Schnitt wird nach A zurueckgezogen: eine A-Region, die A sowohl mit X als
    auch (ueber X) mit C teilt — ohne A-C-Suche.

    Unterschied zu zone_transitivity(): jenes rechnet B-vermittelt (Schnitt in B
    zwischen cores(A,B) und cores(B,C)); DIESES rechnet A-seitig ueber einen
    Vermittler X und ist die Form, mit der die Skalierungsmessung 110-146x
    Ersparnis zeigte (direkt vs transitiv, 20-100 Ziele bei 10 Vermittlern,
    Faktor STEIGEND mit der Zielzahl).

    Rueckgabe: Menge von A-Kantenmengen (frozenset). Ueber alle Vermittler
    vereinigen, um die transitive Abdeckung fuer ein Ziel C zu erhalten.

    STATUS: Ersparnis gemessen; die ABDECKUNG bei wenigen Vermittlern ueber viele
    Ziele ist NICHT abschliessend geprueft (10/10 vollstaendig bei 20 Vermittlern
    / 10 Zielen; fuer 10 Vermittler / 100+ Ziele offen). Als Seed-Lenkung sicher
    nutzbar; als Ersatz fuer die Suche erst nach der Abdeckungsmessung.
    """
    out = set()
    for mA, amap in cores_AX:
        # A-Kanten -> X-Kanten (Bild), Rueckabbildung merken
        ximg = {(amap[e[0]], amap[e[1]], e[2], e[3]): e for e in mA}
        keys = set(ximg)
        for mX, _xmap in cores_XC:
            shared = keys & set(mX)          # cut-at-edge exakt: Kantengleichheit
            if shared:
                out.add(frozenset(ximg[xe] for xe in shared))
    return out


def transitive_coverage(cores_A_by_mediator, cores_XC_by_mediator):
    """Vereinigte A-seitige transitive Abdeckung fuer EIN Ziel C ueber alle
    Vermittler.

    cores_A_by_mediator: dict X -> cores(A,X)   (gespeichert)
    cores_XC_by_mediator: dict X -> cores(X,C)  (gespeichert)
    Rueckgabe: Menge von A-Kantenmengen — Seeds fuer die A-C-Suche bzw.
    (nach Abdeckungsnachweis) die abgeleiteten Kerne selbst."""
    union = set()
    for X, cAX in cores_A_by_mediator.items():
        cXC = cores_XC_by_mediator.get(X)
        if not cXC:
            continue
        for r in transit_via(cAX, cXC):
            if r:
                union.add(r)
    return union
