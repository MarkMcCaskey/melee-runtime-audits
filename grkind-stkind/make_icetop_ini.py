#!/usr/bin/env python3
"""Build `icetop.gecko.ini`: boot straight to external stage 0x1A and have the
game record the grkind/stkind values it is about to print.

Two pieces, both built from ../pr2939's generator so every address stays
traceable:

1. the PR #2939 autosweep kiosk with its stage cycle reduced to 0x02 -> 0x1A,
   so the game itself loads the second Icicle Mountain entry;
2. a C2 hook on `Ground_801C28CC`'s "stage param not found" path
   (0x801C2A48) that stores the three varargs of

       "%s:%d: not found stage param in DAT(grkind=%d stkind=%d,num=%d)\n"

   into develop-mode-only debug memory, where a plain memory read can pick
   them up:

       0x8049FA50  "STKD"
       0x8049FA54  stage_info.internal_stage_id   (the grkind vararg)
       0x8049FA58  the function's s32 parameter   (the stkind vararg)
       0x8049FA5C  the entry count                (the num vararg)

   0x8049FA50 is `db_ItemAndPokemonMenuText_buf`, written only by the item /
   Pokemon debug menu, and sits below the overlay's own payload region.
"""
import shutil
import struct
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
PR2939 = HERE.parent / "pr2939"

HOOK = 0x801C2A48          # first instruction of the failure block
DISPLACED = 0x3C60804A     # lis r3, -32694   (stage_info, high half)
SCRATCH = 0x8049FA50       # db_ItemAndPokemonMenuText_buf
INTERNAL_ID = 0x8049E750   # stage_info.internal_stage_id
CYCLE_SRC = """CYCLE = (list(range(0x02, 0x15)) + [0x16, 0x17, 0x18, 0x19]
         + list(range(0x1B, 0x21)))"""
CYCLE_NEW = "CYCLE = [0x02, 0x1A]  # boot to Fountain, then jump to Icetop"

ASM = f"""
    lis   3, 0x{SCRATCH >> 16:04X}
    ori   3, 3, 0x{SCRATCH & 0xFFFF:04X}
    lis   5, 0x5354
    ori   5, 5, 0x4B44          /* "STKD" */
    stw   5, 0(3)
    lis   5, 0x{INTERNAL_ID >> 16:04X}
    ori   5, 5, 0x{INTERNAL_ID & 0xFFFF:04X}
    lwz   5, 0(5)
    stw   5, 4(3)               /* grkind vararg */
    stw   4, 8(3)               /* stkind vararg (the parameter) */
    stw   27, 12(3)             /* num vararg (entry count) */
    .long 0x{DISPLACED:08X}     /* displaced instruction */
"""


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        work = Path(td) / "pr2939"
        shutil.copytree(PR2939, work)
        gen = work / "build_overlay.py"
        src = gen.read_text()
        assert CYCLE_SRC in src, "pr2939/build_overlay.py CYCLE moved"
        gen.write_text(src.replace(CYCLE_SRC, CYCLE_NEW))

        sys.path.insert(0, str(work))
        import build_overlay as B          # noqa: E402  (patched copy)
        B.main()                           # regenerates the .gecko.ini files

        assert B.read_dol_word(HOOK) == DISPLACED, \
            f"instruction at {HOOK:#x} is not the expected {DISPLACED:#010x}"
        code = B.assemble(ASM, HOOK)
        assert struct.unpack(">I", code[-4:])[0] == DISPLACED

        lines = (work / "autosweep.gecko.ini").read_text().rstrip("\n").split("\n")
        lines += B.c2(HOOK, code)
        out = HERE / "icetop.gecko.ini"
        out.write_text("\n".join(lines) + "\n")
        print(f"wrote {out} (cycle 0x02 -> 0x1A, C2 hook at {HOOK:#x})")


if __name__ == "__main__":
    main()
