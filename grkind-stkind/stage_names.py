#!/usr/bin/env python3
"""Where do melee's stage-kind names come from?

Audits the claim that the decomp's ALL-CAPS stage enum members are invented, by
pulling every name the shipped DOL actually contains:

1. the develop-mode stage list -- 12-byte fixed-width strings at 0x803FAB04 plus
   a pointer array at 0x803FAF0C, 86 entries indexed 0x00..0x55. It lines up
   index-for-index with the stkind space, so it names every stkind, including
   the ones the decomp still calls Unk;
2. the original per-stage module names, recovered from the `gr*.c` __FILE__
   strings the asserts embed. There is one per grkind, so this -- not the stage
   list above -- is the grkind-space source;
3. a literal search for the decomp's current member spellings, to see whether
   any of them appear in the binary at all.

Usage: python3 stage_names.py [--dol path/to/main.dol] [--forward path/to/gr/forward.h]
"""
from __future__ import annotations

import argparse
import re
import struct
from pathlib import Path

NAME_PTRS = 0x803FAF0C     # char*[86], indexed by stkind
NAME_PTRS_LEN = 86


class Dol:
    def __init__(self, data: bytes):
        self.d = data
        offs = struct.unpack(">18I", data[0x00:0x48])
        addrs = struct.unpack(">18I", data[0x48:0x90])
        sizes = struct.unpack(">18I", data[0x90:0xD8])
        self.segs = [(o, a, s) for o, a, s in zip(offs, addrs, sizes) if s]

    def off(self, addr: int):
        for o, a, s in self.segs:
            if a <= addr < a + s:
                return o + (addr - a)
        return None

    def u32(self, addr: int) -> int:
        o = self.off(addr)
        return struct.unpack(">I", self.d[o:o + 4])[0]

    def cstr(self, addr: int) -> str | None:
        o = self.off(addr)
        if o is None:
            return None
        return self.d[o:self.d.index(b"\0", o)].decode("ascii", "replace")


def stkind_names(dol: Dol) -> list[str]:
    out = []
    for i in range(NAME_PTRS_LEN):
        p = dol.u32(NAME_PTRS + i * 4)
        s = dol.cstr(p)
        out.append((s or "").rstrip())
    return out


def gr_modules(dol: Dol) -> set[str]:
    return {m.group().decode()[:-2]
            for m in re.finditer(rb"gr[a-z0-9_]{2,20}\.c", dol.d)}


def grkind_members(forward_h: Path) -> list[str]:
    src = forward_h.read_text()
    body = src[src.index("typedef enum GrKind {"):src.index("} GrKind;")]
    out = []
    for line in body.splitlines():
        line = line.strip().rstrip(",")
        if re.fullmatch(r"[A-Za-z0-9_]+", line) and line != "typedef":
            out.append(line)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dol", type=Path,
                    default=Path.home() / "etc/melee/orig/GALE01/sys/main.dol")
    ap.add_argument("--forward", type=Path,
                    default=Path.home() / "etc/melee/src/melee/gr/forward.h")
    args = ap.parse_args()
    dol = Dol(args.dol.read_bytes())

    print("== 1. develop-mode stage list (stkind-indexed) ==")
    names = stkind_names(dol)
    for i, n in enumerate(names):
        print(f"   0x{i:02X} {i:>3}  {n!r}")

    print("\n== 2. original gr module names (one per grkind) ==")
    mods = gr_modules(dol)
    print(f"   {len(mods)} found: " + ", ".join(sorted(mods)))

    if args.forward.exists():
        print("\n== 3. current GrKind members vs those modules ==")
        members = grkind_members(args.forward)
        misses = []
        for i, m in enumerate(members):
            if m.startswith("GrKind_Unk"):
                continue
            if "gr" + m.lower() not in mods:
                misses.append((i, m))
        print(f"   {len(members)} members; "
              f"{len(members) - len(misses)} match a gr<name>.c module exactly")
        for i, m in misses:
            near = sorted(x for x in mods if x[2:5] == m.lower()[:3])
            print(f"   MISMATCH 0x{i:02X} {m}  (closest module: {near})")

    print("\n== 4. do the decomp's spellings appear in the DOL at all? ==")
    probe = ["TEST", "CASTLE", "RCRUISE", "KONGO", "GARDEN", "GREATBAY",
             "SHRINE", "ZEBES", "KRAID", "STORY", "YORSTER", "IZUMI", "GREENS",
             "CORNERIA", "VENOM", "PSTADIUM", "PURA", "MUTECITY", "BIGBLUE",
             "ONETT", "FOURSIDE", "ICEMTN", "INISHIE1", "INISHIE2", "FLATZONE",
             "OLDPUPUPU", "OLDYOSHI", "OLDKONGO", "KINOKOROUTE", "SHRINEROUTE",
             "ZEBESROUTE", "BIGBLUEROUTE", "BATTLE", "LAST", "FIGUREGET",
             "PUSHON", "HEAL", "HOMERUN", "FIGURE1", "TMARIO", "TSEAK"]
    hits = 0
    for n in probe:
        where = [m.start() for m in re.finditer(re.escape(n.encode()), dol.d)]
        if not where:
            continue
        hits += 1
        s = where[0]
        a = s
        while a > 0 and 32 <= dol.d[a - 1] < 127:
            a -= 1
        b = s
        while b < len(dol.d) and 32 <= dol.d[b] < 127:
            b += 1
        print(f"   {n:<12} x{len(where):<3} e.g. {dol.d[a:b].decode()[:60]!r}")
    print(f"   -> {hits}/{len(probe)} appear anywhere in the DOL")

    print("\n== 5. original identifier style in this code (from asserts) ==")
    for pat in (rb"\bGr_[A-Za-z0-9_]{2,30}", rb"\bSt_[A-Za-z0-9_]{2,30}"):
        found = sorted({m.group().decode() for m in re.finditer(pat, dol.d)})
        print("   " + ", ".join(found))
    print("   ALL-CAPS exception: BATTLE_BG_MAX (assert in grbattle.c)")


if __name__ == "__main__":
    main()
