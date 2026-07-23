#!/usr/bin/env python3
"""Runtime audit of doldecomp/melee PR #2939 (external vs internal stage IDs).

Standalone: Python 3 stdlib only, plus any stock Dolphin recent enough to
have the built-in GDB stub (mainline since ~2022) -- no forks, no plugins.

How it works: the game audits itself. The script launches Dolphin with
cheats enabled and autosweep.gecko.ini (built by build_overlay.py), whose
hooks boot straight into a CPU-vs-CPU VS match and then walk every VS
external stage id (0x02..0x20, skipping the deleted 0x15). For each id the
game reloads the match through its own scene flow -- StartMeleeRules::xE ->
fn_8016E730 -> Stage_802251E8 -- waits 90 stable frames, and records
{external, stage_id_map[external].internal_id, stage_info.internal_stage_id}
into a results array (in develop-mode-only debug memory). The on-screen
overlay shows the same values live.

The script only *reads*: it polls the results array over the GDB remote
protocol (no breakpoints, no interrupts), enriches each row with the loaded
stage's archive name (StageData::data1, e.g. "GrCn.dat") and the overlay's
rendered text, checks rows against expected.json (extracted from the PR head
by extract_expected.py), and also diffs the full 286-entry stage_id_map in
RAM against the PR's table. Everything streams to audit.jsonl; --report
renders REPORT.md.

Usage:
  python3 audit_pr2939.py --dolphin /path/to/dolphin-emu-nogui \
      --iso /path/to/ssbm_rev2.iso
  python3 audit_pr2939.py --report

A human can run the same audit with no tooling at all: add
autosweep.gecko.ini (or kiosk.gecko.ini for D-pad-driven browsing) to
GALE01's gecko codes in any Dolphin and watch the overlay.
"""
import argparse
import binascii
import json
import select
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# GALE01 rev2 addresses (annotated in addresses.py; all from doldecomp/melee
# config/GALE01/symbols.txt or struct layouts in src/).
# ---------------------------------------------------------------------------
STAGE_ID_MAP = 0x803E9960  # stage_id_map[286] of {internal, unk1, unk2}
STAGE_ID_MAP_BYTES = 0xD68
STAGE_DATA_TABLE = 0x803DFEDC  # Ground_803DFEDC: StageData* per internal id
STAGE_DATA_TABLE_LEN = 0x1BC // 4
STAGE_DATA_NAME_OFF = 0x8  # StageData::data1 ("GrCn.dat", ...)


class GdbError(Exception):
    pass


class GdbTimeout(GdbError):
    pass


class Gdb:
    """Minimal GDB Remote Serial Protocol client (read-only use)."""

    def __init__(self, host: str, port: int, connect_timeout: float = 90.0):
        deadline = time.time() + connect_timeout
        last = None
        while time.time() < deadline:
            try:
                self.sock = socket.create_connection((host, port), timeout=5)
                break
            except OSError as e:
                last = e
                time.sleep(0.3)
        else:
            raise GdbError(f"could not connect to gdb stub: {last}")
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.buf = b""
        self.cmd(b"qSupported:")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def _send_frame(self, payload: bytes):
        csum = sum(payload) & 0xFF
        self.sock.sendall(b"$" + payload + b"#" + f"{csum:02x}".encode())

    def _read_byte(self, timeout: float) -> bytes:
        if self.buf:
            b, self.buf = self.buf[:1], self.buf[1:]
            return b
        r, _, _ = select.select([self.sock], [], [], timeout)
        if not r:
            raise GdbTimeout("gdb read timeout")
        data = self.sock.recv(4096)
        if not data:
            raise GdbError("gdb stub closed connection")
        b, self.buf = data[:1], data[1:]
        return b

    def _recv_packet(self, timeout: float) -> bytes:
        deadline = time.time() + timeout
        while True:  # skip acks until '$'
            b = self._read_byte(max(0.0, deadline - time.time()))
            if b == b"$":
                break
        payload = bytearray()
        while True:
            b = self._read_byte(max(0.0, deadline - time.time()))
            if b == b"#":
                break
            payload += b
        self._read_byte(max(0.0, deadline - time.time()))
        self._read_byte(max(0.0, deadline - time.time()))  # checksum chars
        self.sock.sendall(b"+")
        return bytes(payload)

    def cmd(self, payload: bytes, timeout: float = 10.0) -> bytes:
        self._send_frame(payload)
        while True:
            pkt = self._recv_packet(timeout)
            if len(pkt) >= 3 and pkt[:1] in (b"T", b"S"):
                continue  # async stop notification, not our reply
            if pkt == b"":
                continue  # stray empty packet (seen around \x03 handling)
            return pkt

    def cont(self):
        self._send_frame(b"c")  # no reply until a stop; we never break

    def read(self, addr: int, count: int) -> bytes:
        out = bytearray()
        while count:
            n = min(count, 0x180)
            for _ in range(3):
                reply = self.cmd(f"m{addr:x},{n:x}".encode())
                if reply.startswith(b"E"):
                    raise GdbError(f"read {addr:#x}+{n:#x}: {reply!r}")
                chunk = binascii.unhexlify(reply)
                if len(chunk) == n:
                    break
                time.sleep(0.1)
            else:
                raise GdbError(f"short read at {addr:#x}: {len(chunk)}/{n}")
            out += chunk
            addr += n
            count -= n
        return bytes(out)

    def r32(self, addr: int) -> int:
        return struct.unpack(">I", self.read(addr, 4))[0]


def read_cstr(g: Gdb, addr: int, maxlen: int = 24) -> str:
    if not 0x80000000 <= addr < 0x81800000:
        return ""
    raw = g.read(addr, maxlen)
    return raw.split(b"\0")[0].decode("ascii", "replace")


def read_overlay_text(g: Gdb, meta) -> list:
    w, h = meta["buf_w"], meta["buf_h"]
    raw = g.read(meta["buf"], w * h * 2)
    rows = []
    for y in range(h):
        chars = bytes(raw[(y * w + x) * 2] for x in range(w))
        rows.append("".join(chr(c) if 0x20 <= c < 0x7F else " "
                            for c in chars).rstrip())
    return [r for r in rows if r]


# ---------------------------------------------------------------------------
def launch_dolphin(binary: str, iso: str, port: int, extra: list, log):
    user_dir = tempfile.mkdtemp(prefix="pr2939-dolphin-")
    gs = Path(user_dir) / "GameSettings"
    gs.mkdir(parents=True)
    shutil.copy(HERE / "autosweep.gecko.ini", gs / "GALE01.ini")
    cmd = [binary,
           "-u", user_dir,
           "-C", f"Dolphin.General.GDBPort={port}",
           "-C", "Dolphin.Core.CPUThread=False",
           "-C", "Dolphin.Core.EmulationSpeed=0.0",
           "-C", "Dolphin.Core.EnableCheats=True",
           *extra,
           "--exec", iso]
    log(f"launch: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    return proc, user_dir


def audit_table(g: Gdb, expected: dict, emit):
    raw = g.read(STAGE_ID_MAP, STAGE_ID_MAP_BYTES)
    live = [struct.unpack(">i", raw[i * 12:i * 12 + 4])[0]
            for i in range(STAGE_ID_MAP_BYTES // 12)]
    exp = expected["table"]
    mismatches = [
        {"external": i, "expected": e, "live": l}
        for i, (e, l) in enumerate(zip(exp, live)) if e != l]
    emit({"type": "table", "entries": len(live), "pass": not mismatches,
          "mismatches": mismatches})
    return not mismatches


def run_sweep(args, expected, meta, emit, log) -> bool:
    inv_int = {v: k for k, v in expected["internal"].items()}
    inv_ext = {v: k for k, v in expected["external"].items()}
    lo, hi, skip = meta["ext_range"]
    want = len([e for e in range(lo, hi + 1) if e != skip])

    proc, user_dir = launch_dolphin(args.dolphin, args.iso, args.port,
                                    args.dolphin_arg, log)
    g = None
    try:
        g = Gdb("127.0.0.1", args.port)
        log("connected; starting emulation")
        g.cont()  # with a debugger attached, Dolphin boots paused
        table_ok = None
        seen = 0
        deadline = time.time() + args.timeout
        progress_deadline = time.time() + 240
        while time.time() < deadline:
            time.sleep(2.0)
            if table_ok is None:
                # any time after boot: the table is const .data
                table_ok = audit_table(g, expected, emit)
                log(f"stage_id_map table diff vs PR source: "
                    f"{'PASS' if table_ok else 'FAIL'}")
            n = g.r32(meta["res_n"])
            done = g.r32(meta["res_done"])
            while seen < min(n, meta["res_max"]):
                row = g.read(meta["res_rows"] + seen * 12, 12)
                ext, map_int, live_int = struct.unpack(">3i", row)
                name = ""
                if 0 <= live_int < STAGE_DATA_TABLE_LEN:
                    sd = g.r32(STAGE_DATA_TABLE + live_int * 4)
                    if sd:
                        name = read_cstr(g, g.r32(sd + STAGE_DATA_NAME_OFF))
                exp_int = (expected["table"][ext]
                           if 0 <= ext < len(expected["table"]) else None)
                ok = map_int == live_int == exp_int
                emit({"type": "sweep", "external": ext,
                      "external_name": inv_ext.get(ext, "?"),
                      "expected_internal": exp_int,
                      "map_internal": map_int,
                      "live_internal": live_int,
                      "live_internal_name": inv_int.get(live_int, "?"),
                      "stage_file": name,
                      "overlay": read_overlay_text(g, meta),
                      "pass": ok})
                log(f"  ext {ext:#04x} ({inv_ext.get(ext, '?')}): map={map_int}"
                    f" live={live_int} ({inv_int.get(live_int, '?')}, {name})"
                    f" {'PASS' if ok else 'FAIL'}")
                seen += 1
                progress_deadline = time.time() + 240
            if done and seen >= min(n, meta["res_max"]):
                log(f"autosweep done: {seen} stages recorded "
                    f"(expected {want})")
                return seen >= want and bool(table_ok)
            if time.time() > progress_deadline:
                log("no autosweep progress for 240s; giving up this run")
                return False
        log("timed out waiting for autosweep")
        return False
    finally:
        if g:
            g.close()
        if proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        shutil.rmtree(user_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
def write_report(jsonl: Path, out: Path):
    rows = [json.loads(l) for l in jsonl.read_text().splitlines() if l.strip()]
    expected = json.loads((HERE / "expected.json").read_text())
    table_rows = [r for r in rows if r["type"] == "table"]
    sweeps = {}
    for r in rows:
        if r["type"] == "sweep":
            sweeps[r["external"]] = r  # last attempt wins
    lines = [
        "# Runtime audit: doldecomp/melee PR #2939",
        "",
        f"PR head: `{expected['head_sha']}` — game: GALE01 rev2 (NTSC 1.02),"
        " stock Dolphin, driven by the game itself via the committed Gecko"
        " hooks (autosweep.gecko.ini); results read back over Dolphin's"
        " built-in GDB stub.",
        "",
        "## 1. stage_id_map table vs RAM",
        "",
    ]
    if table_rows:
        t = table_rows[-1]
        lines.append(
            f"- {t['entries']} entries compared at `0x803E9960`: "
            + ("**all match** the PR's `stage_id_map` initializer."
               if t["pass"] else
               f"**{len(t['mismatches'])} MISMATCHES**: {t['mismatches']}"))
    else:
        lines.append("- (not run)")
    lines += [
        "",
        "## 2. Live stage-load sweep",
        "",
        "For each VS external id, the game itself set `StartMeleeRules::xE`,"
        " restarted the match through its own scene flow, waited 90 stable"
        " frames, and recorded `stage_id_map[ext].internal_id` alongside the"
        " engine's `stage_info.internal_stage_id`. The archive filename comes"
        " from the loaded stage's own `StageData::data1`. PASS iff"
        " map == live == the PR's expected internal id.",
        "",
        "| ext | enum | map→int | live int | live enum | archive | on-screen overlay | result |",
        "|-----|------|---------|----------|-----------|---------|-------------------|--------|",
    ]
    for ext in sorted(sweeps):
        r = sweeps[ext]
        ov = " / ".join(r["overlay"]) if r.get("overlay") else "—"
        lines.append(
            f"| 0x{ext:02X} | {r['external_name']} | {r['map_internal']}"
            f" | {r['live_internal']} | {r['live_internal_name']}"
            f" | {r['stage_file']} | {ov}"
            f" | {'PASS' if r['pass'] else 'FAIL'} |")
    npass = sum(1 for r in sweeps.values() if r["pass"])
    lines += ["", f"**{npass}/{len(sweeps)} externals PASS.**", ""]
    out.write_text("\n".join(lines))
    print(f"wrote {out}", flush=True)


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dolphin", help="dolphin-emu-nogui (or dolphin-emu) binary")
    ap.add_argument("--iso", help="SSBM NTSC 1.02 (GALE01 rev2) ISO")
    ap.add_argument("--port", type=int, default=53100)
    ap.add_argument("--timeout", type=float, default=900.0,
                    help="overall per-run timeout in seconds")
    ap.add_argument("--dolphin-arg", action="append", default=[],
                    help="extra argument passed through to dolphin "
                         "(e.g. --dolphin-arg=--platform --dolphin-arg=headless)")
    ap.add_argument("--jsonl", default=str(HERE / "audit.jsonl"))
    ap.add_argument("--report", action="store_true",
                    help="only regenerate REPORT.md from audit.jsonl")
    args = ap.parse_args()

    jsonl = Path(args.jsonl)
    if args.report:
        write_report(jsonl, HERE / "REPORT.md")
        return 0
    if not (args.dolphin and args.iso):
        ap.error("--dolphin and --iso are required")

    def log(msg):
        print(msg, flush=True)

    expected = json.loads((HERE / "expected.json").read_text())
    meta = json.loads((HERE / "overlay_meta.json").read_text())
    fh = jsonl.open("a")

    def emit(row):
        row["ts"] = time.time()
        fh.write(json.dumps(row) + "\n")
        fh.flush()

    ok = False
    for attempt in range(3):
        try:
            ok = run_sweep(args, expected, meta, emit, log)
        except (GdbError, OSError) as e:
            log(f"session error: {e}")
        if ok:
            break
        log("retrying with a fresh emulator")
    fh.close()
    write_report(jsonl, HERE / "REPORT.md")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
