#!/usr/bin/env python3
"""Live check: is the DAT stage-param list keyed by the EXTERNAL stage id?

Boots the PR #2939 autosweep kiosk (the game walks every VS stage itself) and,
for each loaded stage, reads stage_info.param->{xB0,xB4} -- the very list that
Ground_801C28CC searches with the value the game's own OSReport calls "stkind"
-- and dumps each entry's x0 ("stageid" per the message's own second string).

Streams one JSON row per stage to stkind_live.jsonl as it goes.
"""
import json, struct, sys, time, signal
from pathlib import Path

HERE = Path.home() / "etc/melee-runtime-audits/pr2939"
sys.path.insert(0, str(HERE))
from audit_pr2939 import Gdb, launch_dolphin  # noqa: E402

STAGE_INFO = 0x8049E6C8
INTERNAL_ID = STAGE_INFO + 0x88
PARAM_PTR = STAGE_INFO + 0x6B0
SELECTED_STAGE = 0x804D49E8
STAGE_ID_MAP = 0x803E9960
STAGE_DATA_TABLE = 0x803DFEDC
OUT = Path(__file__).with_name("stkind_live2.jsonl")

DOLPHIN = str(Path.home() / "etc/dolphin-dap/build/Binaries/dolphin-emu-nogui")
ISO = "/Users/mark/etc/melee/ssbm_rev2.iso"


def log(*a):
    print(*a, flush=True)


def main():
    seen = {}
    proc, user_dir = launch_dolphin(DOLPHIN, ISO, 55599,
                                    ["--platform", "headless", "-v", "Null"],
                                    log)
    g = None
    deadline = time.time() + 900
    cur_ext = None
    pending = None
    try:
        g = Gdb("127.0.0.1", 55599)
        g.cont()
        log("connected; sweeping (settled sample per stage)...")
        fh = OUT.open("a")

        def flush():
            nonlocal pending
            if pending and pending["ext"] not in seen:
                seen[pending["ext"]] = pending
                fh.write(json.dumps(pending) + "\n")
                fh.flush()
                r = pending
                log(f"ext 0x{r['ext']:02X} int {r['internal']:>3} "
                    f"{r['file']:<12} num={r['num']:>2} "
                    f"keys={[hex(k) for k in r['keys'][:6]]}"
                    f"{'...' if r['num'] > 6 else ''}  "
                    f"ext_in_list={r['ext_in_keys']} "
                    f"int_in_list={r['internal_in_keys']}")
            pending = None

        while time.time() < deadline:
            time.sleep(0.15)
            try:
                ext = g.r32(SELECTED_STAGE)
                internal = g.r32(INTERNAL_ID)
                param = g.r32(PARAM_PTR)
            except Exception as e:
                log("read error:", e)
                continue
            if not (0 < ext < 0x200) or internal >= 111:
                continue
            if ext != cur_ext:
                flush()
                cur_ext = ext
            if not (0x80000000 <= param < 0x81800000):
                continue
            if g.r32(STAGE_ID_MAP + ext * 12) != internal:
                continue
            try:
                lst = g.r32(param + 0xB0)
                cnt = g.r32(param + 0xB4)
                if not (0x80000000 <= lst < 0x81800000) or not (0 < cnt < 64):
                    continue
                raw = g.read(lst, cnt * 0x64)
                keys = [struct.unpack(">i", raw[i * 0x64:i * 0x64 + 4])[0]
                        for i in range(cnt)]
                sd = g.r32(STAGE_DATA_TABLE + internal * 4)
                nameptr = g.r32(sd + 8) if sd else 0
                fname = ""
                if 0x80000000 <= nameptr < 0x81800000:
                    fname = g.read(nameptr, 24).split(b"\0")[0].decode(
                        "ascii", "replace")
            except Exception:
                continue        # transient pointer mid-load; resample
            pending = {"ext": ext, "internal": internal, "file": fname,
                       "num": cnt, "keys": keys, "ext_in_keys": ext in keys,
                       "internal_in_keys": internal in keys}
            if len(seen) >= 29:
                break
        flush()
    finally:
        if g:
            g.close()
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:
            proc.kill()
    log(f"recorded {len(seen)} stages -> {OUT}")


if __name__ == "__main__":
    main()
