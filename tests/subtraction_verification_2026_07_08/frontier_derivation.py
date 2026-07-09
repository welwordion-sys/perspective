"""Hypothesis: the brute-forced frontier table is exactly a full-subtractor at
the frontier column with minuend=right_here, subtrahend=1 (left MSB, always 1),
and borrow_in = (NOT b1) AND b2.

Reasoning to verify:
- Phase-2 output = low bits of (0 - R) mod 2^f = low bits of (b - a). 
- The TRUE b-a computation's borrow into the frontier = 1 iff b_low < a_low
  = 1 iff (R > 0 AND b1 = 0). And b2 = 1 iff R > 0 (0 - R borrows iff R nonzero).
  So borrow_in_true = (NOT b1) AND b2.
Also: unreachability proof for (*,1,0): b1=1 requires some low diff bit = 1
(a borrow cannot first appear at a diff=0 position), so R>0, so b2=1.
"""

TABLE = {  # from KB VALIDATED_MECHANISM_2026_07_05.frontier_table
    (0,0,0):(1,1), (0,0,1):(0,1), (0,1,1):(1,1),
    (1,0,0):(0,0), (1,0,1):(1,1), (1,1,1):(0,0),
}

def derived_frontier(r, b1, b2):
    bin_true = (1 - b1) & b2          # borrow_in = NOT(b1) AND b2
    v = r - 1 - bin_true              # full subtractor: r minus left-MSB(=1) minus borrow
    return (v % 2, 1 if v < 0 else 0)

print("== derived formula vs brute-forced table ==")
ok = True
for k, expected in TABLE.items():
    got = derived_frontier(*k)
    match = got == expected
    ok &= match
    print(k, "table:", expected, "formula:", got, "OK" if match else "MISMATCH")
print("all match:", ok)

# ---- unreachability: prove (r,1,0) never occurs, by exhaustive simulation ----
print("\n== unreachability of b1=1,b2=0 (empirical over wide sweep) ==")
def bitlen(x): return max(x.bit_length(), 1)
hits_bad = 0
checked = 0
for a in range(1, 1024):
    for b in range(1, 1024):
        la, lb = bitlen(a), bitlen(b)
        f = la - 1  # frontier index = left MSB
        # phase 1 over positions 0..f-1
        brw = 0
        R = 0
        for i in range(f):
            ai = (a >> i) & 1
            bi = (b >> i) & 1 if i < lb else 0
            d = ai ^ bi ^ brw
            brw = 1 if ((ai == 0 and (bi or brw)) or (bi and brw)) else 0
            R |= d << i
        b1 = brw
        # phase 2: 0 - R over f bits; b2 = borrow out = 1 iff R > 0
        b2 = 1 if R > 0 else 0
        checked += 1
        if b1 == 1 and b2 == 0:
            hits_bad += 1
print(f"checked {checked} (a,b) pairs: b1=1,b2=0 occurrences = {hits_bad}")

# ---- algebraic core of the proof, checked exhaustively at the bit level ----
print("\n== 'borrow cannot first appear at a diff=0 position' (exhaustive bit check) ==")
viol = 0
for ai in (0,1):
    for bi in (0,1):
        d = ai ^ bi ^ 0                      # borrow_in = 0 (first appearance)
        bout = 1 if ((ai == 0 and bi) ) else 0
        if bout == 1 and d == 0:
            viol += 1
print("violations:", viol, "(0 = borrow's first appearance always sets diff=1, so b1=1 => R>0 => b2=1)")
