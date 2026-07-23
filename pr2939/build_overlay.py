"""Build the on-screen stage-id audit overlay for GALE01 rev2 (NTSC 1.02).

The overlay uses the game's own develop-mode text console (DevText_*) to
render, every frame, on any scene where the HUD text pipeline exists:

    ext=07 CORNERIA map=0E
    live=0E GrCn.dat OK
    next=16                      (kiosk build, while a change is pending)

  - ext   = selected_stage.external_id (what Stage_802251E8 was given)
  - name  = the PR's ExternalStageId enum name for that value
  - map   = stage_id_map[ext].internal_id (the PR's table claim)
  - live  = stage_info.internal_stage_id (what the engine actually loaded)
  - GrXx.dat = Ground_803DFEDC[live]->data1 (the game's own archive name)
  - OK/MISMATCH = map == live

Two Gecko artifacts are produced:

  overlay.gecko.ini -- passive: just the overlay, safe in any scene.
  kiosk.gecko.ini   -- audit kiosk: boots straight into a CPU-vs-CPU match and
                       P1 D-pad Right/Left cycles through every VS external
                       stage id (0x02..0x20, skipping deleted 0x15), reloading
                       the match each press. Extra hooks: the three scene-flow
                       setters are pinned to VS/match, fn_8016E730 writes the
                       pending external id into StartMeleeRules::xE, and the
                       memory-card prompt is disabled.

All payload code/data lives in db_AnimationInfo + db_CameraInfoDisplay_buf +
db_SoundInfoText_buf (0x8049FE18..0x804A04F0): contiguous develop-mode-only
DevText buffers that retail play never touches. The overlay hook is
DevText_DrawAll (0x80302608), gated on draw pass 2 like the function itself.

Outputs (committed so auditors do not need binutils):
  overlay.s / matchhook.s   -- generated assembly (review these)
  overlay_code.bin          -- code linked at CODE_BASE, ends `b DrawAll+4`
  overlay_data.bin          -- constants/strings blob, loads at DATA_BASE
  overlay.gecko.ini / kiosk.gecko.ini
  overlay_meta.json         -- addresses/offsets for the injecting script

Rebuilding requires powerpc-eabi binutils (melee repo: build/binutils) and
orig/GALE01/sys/main.dol (for the displaced instructions of hooked functions).
"""
import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import addresses as A  # noqa: E402

MELEE = Path.home() / "etc/melee"
BINUTILS = MELEE / "build/binutils"
MAIN_DOL = MELEE / "orig/GALE01/sys/main.dol"

PAD_COPY_STATUS = 0x804C20BC  # HSD_PadCopyStatus[4]; ::trigger at +8
PAD_STRIDE = 0x44

# ---- payload region: contiguous develop-mode-only debug buffers ----
# db_CpuHandicapInfo (0x8049FAC8, 0x350) directly precedes db_AnimationInfo
# (0x8049FE18, 0x5A8), which is followed by db_CameraInfoDisplay_buf (0xC0)
# and db_SoundInfoText_buf (0x70): 0x8049FAC8..0x804A04F0, all only ever
# touched by develop-mode debug menus that retail play cannot reach.
STATE = A.STATE  # 0x8049FE18 db_AnimationInfo
REGION_LO = STATE - 0x350
REGION_HI = STATE + 0x6D8

# ---- data blob layout (offsets from STATE) ----
OFF_PENDING = 0x00  # mutable: kiosk pending external id (0 = none yet)
OFF_CACHED_TEXT = 0x04  # mutable: our DevText*
OFF_BG = 0x08  # blob written by gecko 06 starts here
OFF_FG = 0x0C
OFF_SCALE_X = 0x10
OFF_SCALE_Y = 0x14
OFF_FMT1 = 0x18
OFF_FMT2 = 0x40
OFF_FMT3 = 0x50
OFF_STR_OK = 0x60
OFF_STR_UNK = 0x64
OFF_STR_BAD = 0x68
OFF_MODE = 0x74  # 0 = passive overlay, 1 = buttons, 2 = buttons + autosweep
OFF_NAMES = 0x80
NAME_SLOT = 12
OFF_BLOB_END = 0x210
# Mutable autosweep state and the glyph buffer live BELOW STATE, inside
# db_CpuHandicapInfo, outside the every-frame gecko 06 data write:
OFF_RES_N = -0x350  # number of recorded result rows
OFF_RES_DONE = -0x34C  # autosweep-finished flag
OFF_RES_STABLE = -0x348  # frames the current stage has been stable
OFF_RES_ROWS = -0x340  # rows of {ext, map_internal, live_internal}
RES_MAX = 40
OFF_BUF = -0x150  # DevText glyph buffer: w*h*2+4 = 32*3*2+4 = 0xC4
BUF_W, BUF_H = 32, 3
assert OFF_RES_ROWS + RES_MAX * 12 <= OFF_BUF
assert OFF_BUF + BUF_W * BUF_H * 2 + 4 <= 0
OFF_CODE = 0x210
CODE_BASE = STATE + OFF_CODE
DATA_BASE = STATE + OFF_BG

FMT1 = "ext=%02X %s map=%02X\n"
FMT2 = "live=%02X %s %s"
FMT3 = "\nnext=%02X"

EXT_MIN, EXT_MAX, EXT_SKIP = 0x02, 0x20, 0x15


# ---------------------------------------------------------------------------
def read_dol_word(addr: int) -> int:
    dol = MAIN_DOL.read_bytes()
    offs = struct.unpack(">18I", dol[0x00:0x48])
    addrs = struct.unpack(">18I", dol[0x48:0x90])
    sizes = struct.unpack(">18I", dol[0x90:0xD8])
    for o, a, s in zip(offs, addrs, sizes):
        if s and a <= addr < a + s:
            return struct.unpack(">I", dol[o + addr - a:o + addr - a + 4])[0]
    raise SystemExit(f"{addr:#x} not in any DOL section")


def build_data(external_names: dict, mode: int) -> bytes:
    """Blob covering [STATE+0x08, STATE+0x210)."""
    blob = bytearray(OFF_BLOB_END - OFF_BG)

    def put(off, data):
        off -= OFF_BG
        blob[off:off + len(data)] = data

    put(OFF_BG, struct.pack(">I", 0x000000C0))  # GXColor black, a=0xC0
    put(OFF_FG, struct.pack(">I", 0xFFFFFFFF))  # GXColor white
    put(OFF_SCALE_X, struct.pack(">f", 9.0))
    put(OFF_SCALE_Y, struct.pack(">f", 12.0))
    put(OFF_FMT1, FMT1.encode() + b"\0")
    put(OFF_FMT2, FMT2.encode() + b"\0")
    put(OFF_FMT3, FMT3.encode() + b"\0")
    put(OFF_STR_OK, b"OK\0")
    put(OFF_STR_UNK, b"?\0")
    put(OFF_STR_BAD, b"MISMATCH\0")
    put(OFF_MODE, struct.pack(">I", mode))
    by_value = {}
    for name, value in external_names.items():
        short = name.replace("ExternalStageID_", "")
        if value <= 0x20 and value not in by_value:
            by_value[value] = short
    for value in range(0x21):
        s = by_value.get(value, "?").encode()[:NAME_SLOT - 1] + b"\0"
        put(OFF_NAMES + value * NAME_SLOT, s)
    return bytes(blob)


OVERLAY_ASM = f"""
# Auto-generated by build_overlay.py -- edit that script, not this file.
.set STATE,      {STATE:#x}
.set GETGOBJ,    {A.DEVTEXT_GET_GOBJ:#x}
.set CREATE,     {A.DEVTEXT_CREATE:#x}
.set SHOW,       {A.DEVTEXT_SHOW:#x}
.set HIDECURSOR, {A.DEVTEXT_HIDE_CURSOR:#x}
.set SETBG,      {A.DEVTEXT_SET_BG_COLOR:#x}
.set SETFG,      {A.DEVTEXT_SET_TEXT_COLOR:#x}
.set SETSCALE,   {A.DEVTEXT_SET_SCALE:#x}
.set ERASE,      {A.DEVTEXT_ERASE:#x}
.set SETXY,      {A.DEVTEXT_SET_CURSOR_XY:#x}
.set PRINTF,     {A.DEVTEXT_PRINTF:#x}
.set DRAWLIST,   {A.DEVTEXT_DRAWLIST:#x}
.set SELECTED,   {A.SELECTED_STAGE:#x}
.set MAP,        {A.STAGE_ID_MAP:#x}
.set LIVEID,     {A.STAGE_INFO_INTERNAL_ID:#x}
.set SDTBL,      {A.STAGE_DATA_TABLE:#x}
.set PAD,        {PAD_COPY_STATUS:#x}
.set PENDSC,     {A.PENDING_SCENE_IDX:#x}
.set ADVNOW,     {A.ADVANCE_NOW:#x}

.macro CALL addr
    lis 12, \\addr@h
    ori 12, 12, \\addr@l
    mtctr 12
    bctrl
.endm

.text
.global hook_entry
hook_entry:
    # DevText_DrawAll(gobj r3, pass r4); only act on the draw pass, like it does
    cmplwi 4, 2
    bne orig_tail
    mflr 0
    stw 0, 4(1)
    stwu 1, -0x40(1)
    stw 3, 0x08(1)
    stw 4, 0x0C(1)
    stw 23, 0x14(1)
    stw 24, 0x18(1)
    stw 25, 0x1C(1)
    stw 26, 0x20(1)
    stw 27, 0x24(1)
    stw 28, 0x28(1)
    stw 29, 0x2C(1)
    stw 30, 0x30(1)
    stw 31, 0x34(1)
    bl main
    lwz 23, 0x14(1)
    lwz 24, 0x18(1)
    lwz 25, 0x1C(1)
    lwz 26, 0x20(1)
    lwz 27, 0x24(1)
    lwz 28, 0x28(1)
    lwz 29, 0x2C(1)
    lwz 30, 0x30(1)
    lwz 31, 0x34(1)
    lwz 3, 0x08(1)
    lwz 4, 0x0C(1)
    addi 1, 1, 0x40
    lwz 0, 4(1)
    mtlr 0
    b orig_tail

main:
    mflr 0
    stw 0, 4(1)
    stwu 1, -0x10(1)
    lis 31, STATE@h
    ori 31, 31, STATE@l
    CALL GETGOBJ                # devtext gobj for this scene
    cmplwi 3, 0
    beq done
    mr 30, 3
    # our DevText survives only until the next scene reset: trust it only if
    # it is still linked on devtext_drawlist
    lwz 29, {OFF_CACHED_TEXT}(31)
    cmplwi 29, 0
    beq create
    lis 5, DRAWLIST@h
    ori 5, 5, DRAWLIST@l
    lwz 5, 0(5)
walk:
    cmplwi 5, 0
    beq create
    cmpw 5, 29
    beq have_text
    lwz 5, {A.DEVTEXT_NEXT_OFF}(5)
    b walk
create:
    li 3, 9                     # id (game debug uses 1/7/8)
    li 4, 20                    # x
    li 5, 420                   # y
    li 6, {BUF_W}
    li 7, {BUF_H}
    addi 8, 31, {OFF_BUF}
    CALL CREATE
    cmplwi 3, 0
    bne created
    li 0, 0
    stw 0, {OFF_CACHED_TEXT}(31)
    b done
created:
    mr 29, 3
    stw 29, {OFF_CACHED_TEXT}(31)
    mr 3, 30
    mr 4, 29
    CALL SHOW
    mr 3, 29
    CALL HIDECURSOR
    mr 3, 29
    addi 4, 31, {OFF_BG}
    CALL SETBG
    mr 3, 29
    addi 4, 31, {OFF_FG}
    CALL SETFG
    mr 3, 29
    lfs 1, {OFF_SCALE_X}(31)
    lfs 2, {OFF_SCALE_Y}(31)
    CALL SETSCALE
have_text:
    mr 3, 29
    CALL ERASE
    mr 3, 29
    li 4, 0
    li 5, 0
    CALL SETXY
    # ext = selected_stage.external_id
    lis 5, SELECTED@h
    ori 5, 5, SELECTED@l
    lwz 28, 0(5)
    # map = stage_id_map[ext].internal_id, -1 if out of range
    li 27, -1
    cmplwi 28, {A.STAGE_ID_MAP_LEN - 1:#x}
    bgt got_map
    mulli 0, 28, 12
    lis 5, MAP@h
    ori 5, 5, MAP@l
    lwzx 27, 5, 0
got_map:
    # live = stage_info.internal_stage_id
    lis 5, LIVEID@h
    ori 5, 5, LIVEID@l
    lwz 26, 0(5)
    # live stage archive name via Ground_803DFEDC[live]->data1
    addi 25, 31, {OFF_STR_UNK}
    cmplwi 26, {A.STAGE_DATA_TABLE_LEN - 1:#x}
    bgt got_name
    lis 5, SDTBL@h
    ori 5, 5, SDTBL@l
    slwi 0, 26, 2
    lwzx 5, 5, 0
    cmplwi 5, 0
    beq got_name
    lwz 5, {A.STAGE_DATA_NAME_OFF}(5)
    cmplwi 5, 0
    beq got_name
    mr 25, 5
got_name:
    # ext enum name (0x00..0x20 only)
    addi 24, 31, {OFF_STR_UNK}
    cmplwi 28, 0x20
    bgt got_ext
    mulli 0, 28, {NAME_SLOT}
    addi 24, 31, {OFF_NAMES}
    add 24, 24, 0
got_ext:
    addi 23, 31, {OFF_STR_OK}
    cmpw 27, 26
    beq judged
    addi 23, 31, {OFF_STR_BAD}
judged:
    mr 3, 29
    addi 4, 31, {OFF_FMT1}
    mr 5, 28
    mr 6, 24
    mr 7, 27
    CALL PRINTF
    mr 3, 29
    addi 4, 31, {OFF_FMT2}
    mr 5, 26
    mr 6, 25
    mr 7, 23
    CALL PRINTF
    # third line: pending kiosk target, while it differs from current
    lwz 8, {OFF_PENDING}(31)
    cmplwi 8, 0
    beq no_line3
    cmpw 8, 28
    beq no_line3
    mr 3, 29
    addi 4, 31, {OFF_FMT3}
    mr 5, 8
    CALL PRINTF
no_line3:
    # buttons (mode >= 1): P1 D-pad Right/Left cycles the external stage id
    lwz 5, {OFF_MODE}(31)
    cmplwi 5, 0
    beq done
    lis 5, PAD@h
    ori 5, 5, PAD@l
    lwz 6, 8(5)                 # HSD_PadCopyStatus[0].trigger
    andi. 7, 6, 2               # D-pad Right: next
    bne adv_next
    andi. 7, 6, 1               # D-pad Left: prev
    bne adv_prev
    # autosweep (mode 2): walk external ids without input, record results
    lwz 5, {OFF_MODE}(31)
    cmplwi 5, 2
    bne done
    lwz 5, {OFF_RES_DONE}(31)
    cmplwi 5, 0
    bne done
    lwz 8, {OFF_PENDING}(31)
    cmplwi 8, 0
    bne sweep_check
    mr 8, 28                    # adopt the current stage as first target
    stw 8, {OFF_PENDING}(31)
sweep_check:
    cmpw 8, 28                  # still waiting for a pending reload?
    beq sweep_stable
    li 0, 0
    stw 0, {OFF_RES_STABLE}(31)
    b done
sweep_stable:
    lwz 9, {OFF_RES_STABLE}(31)
    addi 9, 9, 1
    stw 9, {OFF_RES_STABLE}(31)
    cmpwi 9, 90                 # ~1.5s on this stage: record and move on
    bne done
    lwz 10, {OFF_RES_N}(31)
    cmplwi 10, {RES_MAX - 1}
    bgt done
    mulli 0, 10, 12
    addi 11, 31, {OFF_RES_ROWS}
    add 11, 11, 0
    stw 28, 0(11)               # external id
    stw 27, 4(11)               # stage_id_map internal id
    stw 26, 8(11)               # live internal id
    addi 10, 10, 1
    stw 10, {OFF_RES_N}(31)
    li 0, 0
    stw 0, {OFF_RES_STABLE}(31)
    cmplwi 28, {EXT_MAX}        # single pass ends at the last VS external
    blt adv_next
    li 0, 1
    stw 0, {OFF_RES_DONE}(31)
    b done
adv_next:
    lwz 8, {OFF_PENDING}(31)
    cmplwi 8, 0
    bne 1f
    mr 8, 28
1:  addi 8, 8, 1
    cmplwi 8, {EXT_SKIP}
    bne 2f
    addi 8, 8, 1
2:  cmplwi 8, {EXT_MAX}
    ble commit
    li 8, {EXT_MIN}
    b commit
adv_prev:
    lwz 8, {OFF_PENDING}(31)
    cmplwi 8, 0
    bne 1f
    mr 8, 28
1:  addi 8, 8, -1
    cmplwi 8, {EXT_SKIP}
    bne 2f
    addi 8, 8, -1
2:  cmplwi 8, {EXT_MIN}
    bge commit
    li 8, {EXT_MAX}
commit:
    stw 8, {OFF_PENDING}(31)
    li 6, 3                     # force current minor scene to exit,
    lis 5, PENDSC@h             # fn_8016E730 will apply the pending id
    ori 5, 5, PENDSC@l
    stb 6, 0(5)
    li 6, 1
    lis 5, ADVNOW@h
    ori 5, 5, ADVNOW@l
    stw 6, 0(5)
done:
    addi 1, 1, 0x10
    lwz 0, 4(1)
    mtlr 0
    blr

orig_tail:
    mflr 0                      # displaced DevText_DrawAll first instruction
    b DRAWALL_RET               # resolved by ld (stripped for the Gecko C2 variant)
"""

# Hook at fn_8016E730(StartMeleeData* r3): apply the kiosk's pending external
# id to rules.xE; first time through, adopt the game's own value instead.
MATCHHOOK_ASM = f"""
.set STATE, {STATE:#x}
.text
.global match_hook
match_hook:
    lis 12, STATE@h
    ori 12, 12, STATE@l
    lwz 11, {OFF_PENDING}(12)
    cmplwi 11, 0
    beq init_pending
    sth 11, 0xE(3)
    b tail
init_pending:
    lhz 11, 0xE(3)
    stw 11, {OFF_PENDING}(12)
tail:
"""


def assemble(asm: str, base: int, ret_addr=None) -> bytes:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "in.s").write_text(asm)
        subprocess.run(
            [str(BINUTILS / "powerpc-eabi-as"), "-mgekko",
             "-o", td / "in.o", td / "in.s"], check=True)
        cmd = [str(BINUTILS / "powerpc-eabi-ld"), "-Ttext", hex(base),
               "-o", td / "out.elf", td / "in.o"]
        if ret_addr is not None:
            cmd.insert(1, f"--defsym=DRAWALL_RET={ret_addr:#x}")
        subprocess.run(cmd, check=True)
        subprocess.run(
            [str(BINUTILS / "powerpc-eabi-objcopy"), "-O", "binary",
             "--only-section=.text", td / "out.elf", td / "out.bin"],
            check=True)
        return (td / "out.bin").read_bytes()


# ---------------------------------------------------------------------------
# Gecko emission
# ---------------------------------------------------------------------------
def c2(addr: int, insns: bytes) -> list:
    """Insert-asm code: body executes in place of the insn at addr."""
    words = [insns[i:i + 4] for i in range(0, len(insns), 4)]
    if len(words) % 2 == 0:
        words += [struct.pack(">I", 0x60000000)]
    words += [b"\0\0\0\0"]
    lines = [f"C2{addr & 0x01FFFFFF:06X} {len(words) // 2:08X}"]
    for i in range(0, len(words), 2):
        lines.append(f"{words[i].hex().upper()} {words[i + 1].hex().upper()}")
    return lines


def w06(addr: int, data: bytes) -> list:
    padded = data + b"\0" * (-len(data) % 8)
    lines = [f"06{addr & 0x01FFFFFF:06X} {len(data):08X}"]
    for i in range(0, len(padded), 8):
        lines.append(
            f"{padded[i:i + 4].hex().upper()} {padded[i + 4:i + 8].hex().upper()}")
    return lines


def w32c(addr: int, value: int) -> list:
    return [f"04{addr & 0x01FFFFFF:06X} {value & 0xFFFFFFFF:08X}"]


def w16c(addr: int, value: int) -> list:
    return [f"02{addr & 0x01FFFFFF:06X} 0000{value & 0xFFFF:04X}"]


def w8c(addr: int, value: int) -> list:
    return [f"00{addr & 0x01FFFFFF:06X} 000000{value & 0xFF:02X}"]


def ini(title: str, lines: list) -> str:
    return "\n".join(["[Gecko]", f"${title}", *lines,
                      "[Gecko_Enabled]", f"${title}", ""])


def kiosk_lines(core, data, matchhook, displaced_match) -> list:
    """Overlay + hooks that funnel the game into a self-reloading VS match."""
    lines = []
    lines += c2(A.DEVTEXT_DRAW_ALL, core)
    lines += w06(DATA_BASE, data)
    # memory card prompt -> li r3, 45; blr
    lines += w32c(A.MEMCARD_PROMPT, 0x3860002D)
    lines += w32c(A.MEMCARD_PROMPT + 4, 0x4E800020)
    # pin the scene flow to VS mode / match scene (li r3, 2 ahead of each)
    for addr in (A.SET_PENDING_MODE, A.CHANGE_MODE, A.SET_PENDING_SCENE):
        lines += c2(addr, struct.pack(">II", 0x38600002, read_dol_word(addr)))
    # fn_8016E730: apply pending external id to StartMeleeRules::xE
    lines += c2(A.MATCH_START, matchhook + struct.pack(">I", displaced_match))
    # StartMeleeData defaults in both scene-data blocks: stage + 2 CPU players
    for base in (A.VS_DATA, A.GS_VS_DATA):
        lines += w16c(base + 0x0E, EXT_MIN)
        for i in range(6):
            p = base + 0x60 + i * 0x24
            if i < 2:
                for off, val in ((0, i), (1, 1), (2, 4), (4, i), (0xF, 1)):
                    lines += w8c(p + off, val)
            else:
                lines += w8c(p + 1, 3)
    return lines


def main() -> None:
    expected = json.loads((HERE / "expected.json").read_text())

    displaced_drawall = read_dol_word(A.DEVTEXT_DRAW_ALL)
    assert displaced_drawall == 0x7C0802A6  # mflr r0

    code = assemble(OVERLAY_ASM, CODE_BASE, ret_addr=A.DEVTEXT_DRAW_ALL + 4)
    assert struct.unpack(">I", code[-8:-4])[0] == displaced_drawall
    assert CODE_BASE + len(code) <= REGION_HI, f"code too big: {len(code):#x}"

    matchhook = assemble(MATCHHOOK_ASM, 0)  # position-independent
    displaced_match = read_dol_word(A.MATCH_START)
    assert displaced_match == 0x7C0802A6  # mflr r0

    data = {mode: build_data(expected["external"], mode) for mode in (0, 1, 2)}
    assert len(data[0]) <= OFF_BLOB_END - OFF_BG

    (HERE / "overlay.s").write_text(OVERLAY_ASM)
    (HERE / "matchhook.s").write_text(MATCHHOOK_ASM)
    (HERE / "overlay_code.bin").write_bytes(code)
    (HERE / "overlay_data.bin").write_bytes(data[0])
    meta = {
        "region": [REGION_LO, REGION_HI],
        "code_base": CODE_BASE, "data_base": DATA_BASE,
        "hook": A.DEVTEXT_DRAW_ALL, "displaced": displaced_drawall,
        "buf": STATE + OFF_BUF, "buf_w": BUF_W, "buf_h": BUF_H,
        "pending": STATE + OFF_PENDING,
        "cached_text": STATE + OFF_CACHED_TEXT,
        "mode_flag": STATE + OFF_MODE,
        "res_n": STATE + OFF_RES_N, "res_done": STATE + OFF_RES_DONE,
        "res_rows": STATE + OFF_RES_ROWS, "res_max": RES_MAX,
        "ext_range": [EXT_MIN, EXT_MAX, EXT_SKIP],
        "head_sha": expected["head_sha"],
    }
    (HERE / "overlay_meta.json").write_text(json.dumps(meta, indent=1))

    core = code[:-4]  # strip `b DrawAll+4`: the codehandler branches back
    (HERE / "overlay.gecko.ini").write_text(ini(
        "PR2939 Stage ID Audit Overlay [doldecomp audit]",
        c2(A.DEVTEXT_DRAW_ALL, core) + w06(DATA_BASE, data[0])))
    (HERE / "kiosk.gecko.ini").write_text(ini(
        "PR2939 Stage ID Audit Kiosk [doldecomp audit]",
        kiosk_lines(core, data[1], matchhook, displaced_match)))
    (HERE / "autosweep.gecko.ini").write_text(ini(
        "PR2939 Stage ID Audit Autosweep [doldecomp audit]",
        kiosk_lines(core, data[2], matchhook, displaced_match)))

    print(f"code {len(code):#x} B at {CODE_BASE:#x} (region end {REGION_HI:#x}); "
          f"data {len(data[0]):#x} B at {DATA_BASE:#x}; "
          f"matchhook {len(matchhook):#x} B", flush=True)


if __name__ == "__main__":
    main()
