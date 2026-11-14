"""Compares format_6f.gd output from two platforms against Python's correctly rounded "%.6f"
(exact decimal expansion, ties to even), and reports which platform is wrong and on what.

    python check_format.py out-windows.txt out-linux.txt
"""
import struct
import sys
from decimal import Decimal


def load(path):
    rows = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.split()
            if len(parts) == 2 and len(parts[0]) == 16:
                rows[parts[0]] = parts[1]
    return rows


a_path, b_path = sys.argv[1], sys.argv[2]
a, b = load(a_path), load(b_path)
diff = [h for h in a if h in b and a[h] != b[h]]
wrong = {a_path: 0, b_path: 0}
ties = 0
for h in diff:
    x = struct.unpack("<d", bytes.fromhex(h))[0]
    exact = Decimal(x)
    exp = exact.as_tuple().exponent
    if isinstance(exp, int) and exp >= -7 and str(exact).endswith("5"):
        ties += 1
    right = "%.6f" % x
    for path, rows in ((a_path, a), (b_path, b)):
        if rows[h] != right:
            wrong[path] += 1
print(f"{len(a)} values; {len(diff)} print differently; {ties} of those are exact ties at the 7th place")
for path, n in wrong.items():
    print(f"{path}: {n} of the differing values are not correctly rounded")
