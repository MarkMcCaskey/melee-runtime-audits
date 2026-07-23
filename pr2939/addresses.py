"""GALE01 rev2 addresses used by the PR #2939 runtime audit.

Every address is taken from doldecomp/melee config/GALE01/symbols.txt (or the
struct layouts in src/melee/...) so a reviewer can cross-check each one.
"""

# --- DevText (develop-mode text console), src/melee/if/text{lib,draw}.c ---
DEVTEXT_GET_GOBJ = 0x80301FB4  # DevText_GetGObj
DEVTEXT_SETUP = 0x80302708  # DevText_Setup(classifier, p_link, prio, gx_link, render_prio, cam_prio)
DEVTEXT_DRAW_ALL = 0x80302608  # DevText_DrawAll(gobj, pass) -- overlay hook point
DEVTEXT_CREATE = 0x80302834  # DevText_Create(id, x, y, w, h, buf)
DEVTEXT_SHOW = 0x80302810  # DevText_Show(gobj, text)
DEVTEXT_HIDE_CURSOR = 0x80302AB0  # DevText_HideCursor(text)
DEVTEXT_SET_BG_COLOR = 0x80302B90  # DevText_SetBGColor(text, GXColor* by ref)
DEVTEXT_SET_TEXT_COLOR = 0x80302B64  # DevText_SetTextColor(text, GXColor* by ref)
DEVTEXT_SET_SCALE = 0x80302B10  # DevText_SetScale(text, f32 x, f32 y)
DEVTEXT_ERASE = 0x80302BB0  # DevText_Erase(text)
DEVTEXT_SET_CURSOR_XY = 0x80302A3C  # DevText_SetCursorXY(text, x, y)
DEVTEXT_PRINTF = 0x80302D4C  # DevText_Printf(text, fmt, ...)
DEVTEXT_DRAWLIST = 0x804D6E18  # devtext_drawlist (head of visible DevText list)
DEVTEXT_NEXT_OFF = 0x30  # struct DevText::next (src/melee/if/types.h)

# --- stage id state (the PR's subject matter) ---
SELECTED_STAGE = 0x804D49E8  # selected_stage.external_id (PR renames unk_struct_804D49E8)
STAGE_ID_MAP = 0x803E9960  # stage_id_map[286] (PR renames unk_arr_803E9960)
STAGE_ID_MAP_LEN = 0xD68 // 12  # 286 entries of {internal, unk1, unk2}
STAGE_INFO = 0x8049E6C8  # stage_info
STAGE_INFO_INTERNAL_ID = STAGE_INFO + 0x88  # stage_info.internal_stage_id
STAGE_DATA_TABLE = 0x803DFEDC  # Ground_803DFEDC: StageData* per internal id
STAGE_DATA_TABLE_LEN = 0x1BC // 4  # 111 entries
STAGE_DATA_NAME_OFF = 0x8  # StageData::data1 (archive file name, e.g. "GrCn.dat")

# --- free space used by the overlay payload ---
# db_AnimationInfo (.bss, 0x5A8 bytes): the develop-mode "animation info"
# DevText buffer. Only written by fn_SetupAnimationInfo/fn_UpdateAnimationInfo,
# which are unreachable in retail play (debug menu only), so it is safe scratch.
STATE = 0x8049FE18
STATE_SIZE = 0x5A8

# --- scene machinery (headless boot-to-match; see examples/melee/README) ---
SET_PENDING_MODE = 0x801A42E8
CHANGE_MODE = 0x801A42F8
SET_PENDING_SCENE = 0x801A42A0
MATCH_START = 0x8016E730  # fn_8016E730(StartMeleeData*)
STAGE_LOAD = 0x802251E8  # Stage_802251E8(external_id, s32*)
MEMCARD_PROMPT = 0x8001CE78  # lb_8001CE78
VI_RETRACE = 0x8034F314
VS_DATA = 0x8045AC58
GS_VS_DATA = 0x80480530
ROUTING = 0x80479D30
PENDING_SCENE_IDX = 0x80479D35
ADVANCE_NOW = 0x80479D64
GM_VS = 2
