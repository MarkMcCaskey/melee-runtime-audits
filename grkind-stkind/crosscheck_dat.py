#!/usr/bin/env python3
"""Offline proof that the game's "stkind" is the EXTERNAL stage id.

`Ground_801C28CC` searches `stage_info.param->xB0` for a caller-supplied id and,
on failure, OSReports

    "%s:%d: not found stage param in DAT(grkind=%d stkind=%d,num=%d)\n"

with `stage_info.internal_stage_id` in the grkind slot and its own parameter in
the stkind slot (GALE01 rev2, 0x801C2A48..0x801C2A6C).

`stage_info.param` is the stage archive's public symbol `grGroundParam`
(grdatfiles.c), so the searched keys live on the disc and the question "which id
space are they in?" can be answered with no emulator at all:

    for every stage_id_map entry:            (external id -> internal id)
        file = Ground_803DFEDC[internal]->data1        ("GrNBa.dat", ...)
        assert external in grGroundParam(file) keys

Usage:
    python3 crosscheck_dat.py --iso ssbm_rev2.iso [--dol main.dol] [--jsonl out]

Needs only the retail ISO; the DOL defaults to the copy inside it.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

# --- GALE01 rev2 addresses (doldecomp/melee config/GALE01/symbols.txt) -------
STAGE_ID_MAP = 0x803E9960       # stage_id_map[286], {internal, unk1, unk2}
STAGE_ID_MAP_LEN = 0xD68 // 12
STAGE_DATA_TABLE = 0x803DFEDC   # Ground_803DFEDC: StageData* per internal id
STAGE_DATA_TABLE_LEN = 0x1BC // 4
STAGE_DATA_NAME_OFF = 0x8       # StageData::data1 -> "/GrNBa.dat"
PARAM_LIST_OFF = 0xB0           # grGroundParam.xB0 -> entry array
PARAM_COUNT_OFF = 0xB4          # grGroundParam.xB4 -> entry count
PARAM_ENTRY_SIZE = 0x64         # UnkBgmStruct; +0 is the id ("stageid=%d")


class Dol:
    def __init__(self, data: bytes):
        self.data = data
        offs = struct.unpack(">18I", data[0x00:0x48])
        addrs = struct.unpack(">18I", data[0x48:0x90])
        sizes = struct.unpack(">18I", data[0x90:0xD8])
        self.segs = [(o, a, s) for o, a, s in zip(offs, addrs, sizes) if s]

    def _off(self, addr: int) -> int:
        for o, a, s in self.segs:
            if a <= addr < a + s:
                return o + (addr - a)
        raise KeyError(f"{addr:#x} not in any DOL segment")

    def u32(self, addr: int) -> int:
        o = self._off(addr)
        return struct.unpack(">I", self.data[o:o + 4])[0]

    def cstr(self, addr: int) -> str:
        o = self._off(addr)
        return self.data[o:self.data.index(b"\0", o)].decode("ascii", "replace")


class Disc:
    """Minimal GameCube disc reader (FST walk, root-level files)."""

    def __init__(self, path: Path):
        self.fh = path.open("rb")
        fst_off, fst_size = struct.unpack(">II", self._read(0x424, 8))
        fst = self._read(fst_off, fst_size)
        count = struct.unpack(">I", fst[8:12])[0]
        strtab = count * 12
        self.files = {}
        for i in range(count):
            kind = fst[i * 12]
            name_off = struct.unpack(">I", b"\0" + fst[i * 12 + 1:i * 12 + 4])[0]
            off, length = struct.unpack(">II", fst[i * 12 + 4:i * 12 + 12])
            if kind == 0:
                end = fst.index(b"\0", strtab + name_off)
                name = fst[strtab + name_off:end].decode("shift_jis", "replace")
                self.files[name] = (off, length)
        self.dol_offset = struct.unpack(">I", self._read(0x420, 4))[0]

    def _read(self, off: int, size: int) -> bytes:
        self.fh.seek(off)
        return self.fh.read(size)

    def file(self, name: str) -> bytes | None:
        if name not in self.files:
            return None
        off, length = self.files[name]
        return self._read(off, length)

    def dol(self) -> bytes:
        # main.dol has no FST entry; its size is the max section end.
        head = self._read(self.dol_offset, 0x100)
        offs = struct.unpack(">18I", head[0x00:0x48])
        sizes = struct.unpack(">18I", head[0x90:0xD8])
        size = max((o + s for o, s in zip(offs, sizes) if s), default=0x100)
        return self._read(self.dol_offset, size)


def ground_param_keys(dat: bytes) -> list[int] | None:
    """Entry ids of the DAT's `grGroundParam` list, or None if absent."""
    _fsize, dsize, nreloc, npub, nextern = struct.unpack(">5I", dat[0:20])
    data = 0x20
    public = data + dsize + nreloc * 4
    strings = public + npub * 8 + nextern * 8

    def name(off: int) -> str:
        return dat[strings + off:dat.index(b"\0", strings + off)].decode(
            "ascii", "replace")

    for i in range(npub):
        off, name_off = struct.unpack(">II", dat[public + i * 8:public + i * 8 + 8])
        if name(name_off) != "grGroundParam":
            continue
        base = data + off
        lst, count = struct.unpack(
            ">II", dat[base + PARAM_LIST_OFF:base + PARAM_COUNT_OFF + 4])
        entries = data + lst
        return [struct.unpack(">i", dat[entries + j * PARAM_ENTRY_SIZE:
                                        entries + j * PARAM_ENTRY_SIZE + 4])[0]
                for j in range(count)]
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--iso", required=True, type=Path)
    ap.add_argument("--dol", type=Path, help="main.dol (default: from the ISO)")
    ap.add_argument("--jsonl", type=Path, help="write one row per external id")
    args = ap.parse_args()

    disc = Disc(args.iso)
    dol = Dol(args.dol.read_bytes() if args.dol else disc.dol())

    cache: dict[str, list[int] | None] = {}
    rows = []
    for ext in range(STAGE_ID_MAP_LEN):
        internal = dol.u32(STAGE_ID_MAP + ext * 12)
        fname, keys = None, None
        if internal < STAGE_DATA_TABLE_LEN:
            sd = dol.u32(STAGE_DATA_TABLE + internal * 4)
            name_ptr = dol.u32(sd + STAGE_DATA_NAME_OFF) if sd else 0
            if name_ptr:
                fname = dol.cstr(name_ptr).lstrip("/")
                if not fname.endswith(".dat"):
                    fname += ".dat"          # a few entries drop the suffix
                if fname not in cache:
                    blob = disc.file(fname)
                    cache[fname] = ground_param_keys(blob) if blob else None
                keys = cache[fname]
        rows.append({
            "external": ext, "internal": internal, "file": fname,
            "num": len(keys) if keys is not None else None,
            "keys": keys,
            "external_in_keys": bool(keys) and ext in keys,
            "internal_in_keys": bool(keys) and internal in keys,
            "distinguishable": ext != internal,
        })

    if args.jsonl:
        with args.jsonl.open("w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")

    have = [r for r in rows if r["keys"] is not None]
    disc_rows = [r for r in have if r["distinguishable"]]
    ext_only = [r for r in disc_rows
                if r["external_in_keys"] and not r["internal_in_keys"]]
    int_only = [r for r in disc_rows
                if r["internal_in_keys"] and not r["external_in_keys"]]
    both = [r for r in disc_rows
            if r["external_in_keys"] and r["internal_in_keys"]]
    neither = [r for r in disc_rows if not r["external_in_keys"]
               and not r["internal_in_keys"]]

    print(f"stage_id_map entries          : {len(rows)}")
    print(f"  with a stage file + params  : {len(have)}")
    print(f"  external id in its DAT list : "
          f"{sum(1 for r in have if r['external_in_keys'])}")
    print()
    print("Entries where external != internal (only these can tell the two "
          f"spaces apart): {len(disc_rows)}")
    print(f"  external id in the list, internal absent : {len(ext_only)}")
    print(f"  internal id in the list, external absent : {len(int_only)}")
    print(f"  both present (the internal number is also some other stage's"
          f" external id in the same file) : {len(both)}")
    print(f"  neither                                  : {len(neither)}  "
          + (", ".join(f"0x{r['external']:02X}->int {r['internal']} "
                       f"({r['file']})" for r in neither) if neither else ""))
    print()
    print("Sample (external != internal, so exactly one reading survives):")
    print(f"  {'file':<12} {'internal':>8}  {'external':>8}  grGroundParam keys")
    shown = set()
    for r in have:
        if r["file"] in ("GrCs.dat", "GrSt.dat", "GrNBa.dat", "GrIm.dat") \
                and r["external_in_keys"] and r["distinguishable"] \
                and r["file"] not in shown:
            shown.add(r["file"])
            ks = " ".join(f"0x{k:X}" for k in r["keys"][:8])
            print(f"  {r['file']:<12} {r['internal']:>8}  0x{r['external']:02X}"
                  f"{'':>6}  {ks}{' ...' if r['num'] > 8 else ''}")

    verdict = len(int_only) == 0 and len(ext_only) > 0
    print()
    print("VERDICT: the searched key ('stkind') is the EXTERNAL stage id; "
          "'grkind' is the internal one."
          if verdict else "VERDICT: inconclusive -- see rows above.")
    return 0 if verdict else 1


if __name__ == "__main__":
    sys.exit(main())
