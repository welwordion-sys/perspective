def full_raw_and_sign(a, b):
    # a = minuend (left), b = subtrahend (right), independent bit-lengths
    la = max(a.bit_length(), 1)
    lb = max(b.bit_length(), 1)
    n = max(la, lb)
    borrow = 0
    raw = []
    for i in range(n):
        ai = (a >> i) & 1 if i < la else 0
        bi = (b >> i) & 1 if i < lb else 0
        d = ai ^ bi ^ borrow
        # standard full-subtractor borrow_out
        borrow_out = 1 if ((ai == 0 and (bi or borrow)) or (bi and borrow)) else 0
        raw.append(d)
        borrow = borrow_out
    sign_neg = (borrow == 1)
    if sign_neg:
        # ONE uniform two's-complement negate over the ENTIRE n-bit raw result
        c = 1
        mag = []
        for d in raw:
            newbit = (1 - d) ^ c
            c = (1 - d) & c
            mag.append(newbit)
        raw = mag
    while len(raw) > 1 and raw[-1] == 0:
        raw.pop()
    val = sum(bit << i for i, bit in enumerate(raw))
    return val, sign_neg

fails = []
N = 200
for a in range(0, N):
    for b in range(0, N):
        if a == 0 and b == 0:
            continue
        val, neg = full_raw_and_sign(a, b)
        if a >= b:
            exp_val, exp_neg = a - b, False
        else:
            exp_val, exp_neg = b - a, True
        if (val, neg) != (exp_val, exp_neg):
            fails.append((a, b, val, neg, exp_val, exp_neg))

print(f"swept a,b in 0..{N-1}: {len(fails)} failures")
for f in fails[:10]:
    print(f)

# explicit edge cases
edge_cases = [(0,0),(1,1),(1,0),(0,1),(0,7),(7,0),(1,2**20),(2**20,1)]
for a,b in edge_cases:
    val, neg = full_raw_and_sign(a,b)
    exp_val = abs(a-b)
    exp_neg = a < b
    ok = (val,neg) == (exp_val, exp_neg)
    print(a,b,'->',val,neg,'expected',exp_val,exp_neg,'OK' if ok else 'MISMATCH')

# wider randomized sweep
import random
random.seed(42)
fails2 = 0
for _ in range(20000):
    a = random.randint(0, 2**24)
    b = random.randint(0, 2**24)
    if a==0 and b==0: continue
    val, neg = full_raw_and_sign(a,b)
    exp_val, exp_neg = (a-b, False) if a>=b else (b-a, True)
    if (val,neg) != (exp_val, exp_neg):
        fails2 += 1
print("random 24-bit sweep failures:", fails2, "/ 20000")
