"""Reads float_parse.gd output on stdin and checks each "MM" line against Python's correctly
rounded parser: was the printed text right (Python reads it back as the original double), and
how many ulps off was Godot's parse?

    godot --headless --path repros -s float_parse.gd | python check_mismatches.py
"""
import struct
import sys


def from_hex_le(h):
    return struct.unpack("<d", bytes.fromhex(h))[0]


def bits(x):
    return struct.unpack("<q", struct.pack("<d", x))[0]


printed_ok = parse_wrong = 0
ulps = []
for line in sys.stdin:
    if not line.startswith("MM "):
        continue
    _, xh, s, yh = line.split()
    x, y = from_hex_le(xh), from_hex_le(yh)
    if float(s) == x:
        printed_ok += 1
    if float(s) != y:
        parse_wrong += 1
        ulps.append(abs(bits(float(s)) - bits(y)))
print(f"mismatches checked: {printed_ok + 0} of them printed exactly (Python reads the text back "
      f"as the original); {parse_wrong} Godot parses differ from Python's")
if ulps:
    print(f"Godot parse error in ulps: min {min(ulps)}, max {max(ulps)}")
