#!/usr/bin/env python3
"""Boot external stage 0x1A and read back what the game reports as grkind/stkind."""
import json, shutil, struct, subprocess, sys, tempfile, time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(Path.home() / "etc/melee-runtime-audits/pr2939"))
import audit_pr2939 as A  # noqa: E402

SCRATCH = 0x8049FA50
MAGIC = 0x53544B44
SELECTED_STAGE = 0x804D49E8
INTERNAL_ID = 0x8049E750
PORT = 55603
DOLPHIN = str(Path.home() / "etc/dolphin-dap/build/Binaries/dolphin-emu-nogui")
ISO = "/Users/mark/etc/melee/ssbm_rev2.iso"


def log(*a):
    print(*a, flush=True)


def main():
    user_dir = tempfile.mkdtemp(prefix="icetop2-dolphin-")
    gs = Path(user_dir) / "GameSettings"
    gs.mkdir(parents=True)
    shutil.copy(HERE / "icetop.gecko.ini", gs / "GALE01.ini")
    cmd = [DOLPHIN, "-u", user_dir,
           "-C", f"Dolphin.General.GDBPort={PORT}",
           "-C", "Dolphin.Core.CPUThread=False",
           "-C", "Dolphin.Core.EmulationSpeed=0.0",
           "-C", "Dolphin.Core.EnableCheats=True",
           "--platform", "headless", "-v", "Null", "--exec", ISO]
    log("launch:", " ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    g = None
    try:
        g = A.Gdb("127.0.0.1", PORT)
        g.cont()
        log("connected; waiting for the 0x1A load to miss its stage param...")
        deadline = time.time() + 420
        while time.time() < deadline:
            time.sleep(0.3)
            try:
                if g.r32(SCRATCH) != MAGIC:
                    continue
                grkind = g.r32(SCRATCH + 4)
                stkind = g.r32(SCRATCH + 8)
                num = g.r32(SCRATCH + 12)
                ext = g.r32(SELECTED_STAGE)
                internal = g.r32(INTERNAL_ID)
            except Exception:
                continue
            log("")
            log("the game reached ground.c's failure path and would print:")
            log(f'  "not found stage param in DAT(grkind={grkind} '
                f'stkind={stkind},num={num})"')
            log("")
            log(f"  selected external id (0x804D49E8) = {ext} (0x{ext:02X})")
            log(f"  live internal id (0x8049E750)     = {internal}")
            log(f"  -> grkind {grkind} == internal id : {grkind == internal}")
            log(f"  -> stkind {stkind} == external id : {stkind == ext}")
            (HERE / "icetop_marker.json").write_text(json.dumps(
                {"grkind": grkind, "stkind": stkind, "num": num,
                 "external": ext, "internal": internal,
                 "grkind_is_internal": grkind == internal,
                 "stkind_is_external": stkind == ext}, indent=1))
            return
        log("timed out without hitting the failure path")
    finally:
        if g:
            g.close()
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    main()
