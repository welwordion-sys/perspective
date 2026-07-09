def bitlen(x):
    return max(x.bit_length(), 1)

def count_4phase(a, b):
    """Current design: phase1 to frontier=left MSB, phase2 renegates ONLY those
    bits, phase3 = frontier column + overhang computed directly (no re-negate),
    phase4 = drain. Positive path: phase1 over full width, then drain."""
    la, lb = bitlen(a), bitlen(b)
    if a >= b:
        n = max(la, lb)  # phase1 alone covers everything
        raw = a - b
        firings = n
    else:
        # negative: phase1 spans la (frontier = left MSB), phase2 re-negates
        # those la bits, phase3 = 1 (frontier) + overhang (lb - la - 1) computed
        # directly, no re-negate needed for overhang
        firings = la + la + 1 + max(lb - la - 1, 0)
        raw = b - a
    # drain: count leading zero strips on the final magnitude vs its own width
    width_used = max(la, lb)
    mag_len = bitlen(raw)
    drain = max(width_used - mag_len, 0)
    return firings + drain

def count_hybrid_full_negate(a, b):
    """Hybrid: phase1 over FULL width n (both low + overhang in one continuous
    pass), then if negative, ONE full-width negate pass, then drain."""
    la, lb = bitlen(a), bitlen(b)
    n = max(la, lb)
    if a >= b:
        raw = a - b
        firings = n
    else:
        raw = b - a
        firings = n + n  # phase1 full width + full-width negate
    mag_len = bitlen(raw)
    drain = max(n - mag_len, 0)
    return firings + drain

def count_armstyle_with_transit(a, b):
    """Arm A/B style: same as hybrid but adds an explicit backward TOK_TRANSIT
    walk (tail->head, n steps) before the negate pass can begin."""
    la, lb = bitlen(a), bitlen(b)
    n = max(la, lb)
    if a >= b:
        raw = a - b
        firings = n
    else:
        raw = b - a
        firings = n + n + n  # phase1 + backward transit + negate
    mag_len = bitlen(raw)
    drain = max(n - mag_len, 0)
    return firings + drain

def count_addition_baseline(a, b):
    """Existing bit_add: one firing per bit position, ripple carry, no drain
    needed on addition's own account."""
    return max(bitlen(a), bitlen(b), bitlen(a+b))

import random
random.seed(1)
cases = [(a, b) for a in range(0, 32) for b in range(0, 32) if not (a == 0 and b == 0)]
cases += [(random.randint(0, 2**16), random.randint(0, 2**16)) for _ in range(2000)]

tot4, toth, totarm, totadd, n_ = 0, 0, 0, 0, 0
max4, maxh, maxarm = 0, 0, 0
for a, b in cases:
    c4 = count_4phase(a, b)
    ch = count_hybrid_full_negate(a, b)
    ca = count_armstyle_with_transit(a, b)
    cadd = count_addition_baseline(a, b)
    tot4 += c4; toth += ch; totarm += ca; totadd += cadd; n_ += 1
    max4 = max(max4, c4); maxh = max(maxh, ch); maxarm = max(maxarm, ca)

print(f"cases: {n_}")
print(f"avg firings  4phase={tot4/n_:.2f}  hybrid={toth/n_:.2f}  arm-transit={totarm/n_:.2f}  add-baseline={totadd/n_:.2f}")
print(f"max  firings  4phase={max4}  hybrid={maxh}  arm-transit={maxarm}")

# specific illuminating cases
for a, b in [(1, 1000000), (1, 6), (2, 3), (100, 65536), (7, 8), (8, 9)]:
    print(a, b, "-> 4phase:", count_4phase(a,b), "hybrid:", count_hybrid_full_negate(a,b),
          "arm-transit:", count_armstyle_with_transit(a,b), "add-baseline:", count_addition_baseline(a,b))
