"""
Diff two writable-memory snapshots (from snapshot_writable.py) and list
addresses whose byte value changed by exactly `delta` (default +1) -
narrows a generic "what changed" diff down to changes consistent with a
menu cursor moving one step.
"""
import pickle
import sys


def main():
    path1, path2 = sys.argv[1], sys.argv[2]
    delta = int(sys.argv[3]) if len(sys.argv) > 3 else 1

    with open(path1, "rb") as f:
        regions1 = {base: data for base, data in pickle.load(f)}
    with open(path2, "rb") as f:
        regions2 = {base: data for base, data in pickle.load(f)}

    common_bases = set(regions1) & set(regions2)
    print(f"snap1 regions={len(regions1)} snap2 regions={len(regions2)} common={len(common_bases)}")

    hits = []
    for base in common_bases:
        a, b = regions1[base], regions2[base]
        if len(a) != len(b):
            continue
        for i in range(len(a)):
            if (b[i] - a[i]) % 256 == delta % 256 and a[i] != b[i]:
                hits.append((base + i, a[i], b[i]))

    print(f"\n{len(hits)} byte(s) changed by exactly {delta} (mod 256):")
    for addr, old, new in hits[:2000]:
        print(f"  0x{addr:012x}  {old} -> {new}")
    if len(hits) > 2000:
        print(f"  ... and {len(hits) - 2000} more")


if __name__ == "__main__":
    main()
