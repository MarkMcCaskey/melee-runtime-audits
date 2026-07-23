#!/usr/bin/env python3
"""Run the Venom platform-field audit against GALE01 rev2 in stock Dolphin."""

import argparse
import binascii
import json
import select
import shutil
import socket
import struct
import subprocess
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
AUDIT_INI = HERE / "audit.gecko.ini"
RESULT = 0x8049FA50
RESULT_SIZE = 0x50

STAGE_INFO = 0x8049E6C8
INTERNAL_STAGE_ID = STAGE_INFO + 0x88
MAP_GOBJS = STAGE_INFO + 0x180
EXTERNAL_SMASH_TAUNT_VENOM = 0xE4
VENOM = 15


class Gdb:
    def __init__(self, port):
        deadline = time.time() + 90
        while True:
            try:
                self.sock = socket.create_connection(("127.0.0.1", port), 5)
                break
            except OSError:
                if time.time() >= deadline:
                    raise
                time.sleep(0.25)
        self.buf = b""
        self.cmd(b"qSupported:")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def _byte(self, timeout):
        if self.buf:
            result, self.buf = self.buf[:1], self.buf[1:]
            return result
        ready, _, _ = select.select([self.sock], [], [], timeout)
        if not ready:
            raise TimeoutError
        data = self.sock.recv(4096)
        if not data:
            raise EOFError
        result, self.buf = data[:1], data[1:]
        return result

    def _packet(self, timeout=10):
        deadline = time.time() + timeout
        while self._byte(deadline - time.time()) != b"$":
            pass
        payload = bytearray()
        while True:
            char = self._byte(deadline - time.time())
            if char == b"#":
                break
            payload += char
        self._byte(deadline - time.time())
        self._byte(deadline - time.time())
        self.sock.sendall(b"+")
        return bytes(payload)

    def cmd(self, payload):
        checksum = sum(payload) & 0xFF
        self.sock.sendall(b"$" + payload + b"#" +
                          f"{checksum:02x}".encode())
        while True:
            packet = self._packet()
            if not packet or packet[:1] in (b"S", b"T"):
                continue
            return packet

    def cont(self):
        payload = b"c"
        checksum = sum(payload) & 0xFF
        self.sock.sendall(b"$c#" + f"{checksum:02x}".encode())

    def read(self, address, size):
        result = bytearray()
        while size:
            count = min(size, 0x180)
            for _ in range(5):
                packet = self.cmd(f"m{address:x},{count:x}".encode())
                if packet.startswith(b"E"):
                    time.sleep(0.05)
                    continue
                try:
                    chunk = binascii.unhexlify(packet)
                except (binascii.Error, ValueError):
                    time.sleep(0.05)
                    continue
                if len(chunk) == count:
                    break
                time.sleep(0.05)
            else:
                raise RuntimeError(
                    f"failed read at {address:#x}: {packet!r}"
                )
            result += chunk
            address += count
            size -= count
        return bytes(result)

    def u32(self, address):
        return struct.unpack(">I", self.read(address, 4))[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dolphin", required=True)
    parser.add_argument("--iso", required=True)
    parser.add_argument("--port", type=int, default=53101)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument(
        "--dolphin-arg",
        action="append",
        default=[],
        help="extra argument passed to Dolphin; repeat as needed",
    )
    parser.add_argument("--jsonl", type=Path, default=HERE / "audit.jsonl")
    args = parser.parse_args()

    output = args.jsonl.open("w")

    def emit(kind, **values):
        row = {"type": kind, **values}
        output.write(json.dumps(row) + "\n")
        output.flush()
        return row

    user_dir = Path(tempfile.mkdtemp(prefix="venom-platform-audit-"))
    settings = user_dir / "GameSettings"
    settings.mkdir()
    (settings / "GALE01.ini").write_text(AUDIT_INI.read_text())

    cmd = [
        args.dolphin,
        "-u", str(user_dir),
        "-C", f"Dolphin.General.GDBPort={args.port}",
        "-C", "Dolphin.Core.CPUThread=False",
        "-C", "Dolphin.Core.EmulationSpeed=0.0",
        "-C", "Dolphin.Core.EnableCheats=True",
        *args.dolphin_arg,
        "--exec", args.iso,
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    gdb = None
    passed = False
    try:
        gdb = Gdb(args.port)
        gdb.cont()
        deadline = time.time() + args.timeout
        while time.time() < deadline:
            if gdb.u32(RESULT) == 0x56504C54:
                raw = gdb.read(RESULT, RESULT_SIZE)
                values = struct.unpack(">20I", raw)
                if values[9] == 0x1F and values[10] and values[19]:
                    break
            time.sleep(0.05)
        else:
            emit("timeout", external=gdb.u32(0x804D49E8),
                 internal=gdb.u32(INTERNAL_STAGE_ID),
                 target=gdb.u32(MAP_GOBJS),
                 platform=gdb.u32(MAP_GOBJS + 5 * 4))
            raise RuntimeError("Venom platform audit did not complete")

        (magic, platform, ground, target_field, timer, upper, lower,
         calls, max_timer, seen_mask, dialogue, dialogue_timer,
         upper_y_bits, lower_y_bits, target_map, external, internal,
         target_jobj, platform_jobj, translation_equal) = values
        timer_signed = struct.unpack(">i", struct.pack(">I", timer))[0]
        upper_y = struct.unpack(">f", struct.pack(">I", upper_y_bits))[0]
        lower_y = struct.unpack(">f", struct.pack(">I", lower_y_bits))[0]
        checks = {
            "result_magic": magic == 0x56504C54,
            "special_venom_loaded": (
                external == EXTERNAL_SMASH_TAUNT_VENOM and internal == VENOM
            ),
            "target_is_map_gobj_0": (
                target_field != 0 and target_field == target_map
            ),
            "target_follows_platform": (
                target_jobj != 0
                and platform_jobj != 0
                and bool(translation_equal)
            ),
            "joints_are_valid_and_ordered": (
                upper != 0 and lower != 0 and upper != lower
                and upper_y > lower_y
            ),
            "timer_sequence_seen": (
                seen_mask & 0x1F == 0x1F
                and calls >= 61
                and max_timer >= 61
            ),
            "dialogue_created_at_60": (
                dialogue != 0 and dialogue_timer == 60
            ),
        }
        passed = all(checks.values())
        emit(
            "result",
            passed=passed,
            checks=checks,
            external=external,
            internal=internal,
            platform=platform,
            ground=ground,
            target_field=target_field,
            target_map=target_map,
            target_jobj=target_jobj,
            platform_jobj=platform_jobj,
            translation_equal=bool(translation_equal),
            timer=timer_signed,
            calls=calls,
            max_timer=max_timer,
            seen_mask=seen_mask,
            dialogue=dialogue,
            dialogue_timer=dialogue_timer,
            upper=upper,
            lower=lower,
            upper_y=upper_y,
            lower_y=lower_y,
        )
        print(f"Venom platform runtime audit: "
              f"{'PASS' if passed else 'FAIL'}")
        for name, ok in checks.items():
            print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        print(
            f"  target {target_field:#010x} == map_gobjs[0] "
            f"{target_map:#010x}"
        )
        print(
            f"  upper {upper:#010x} y={upper_y:.6f}; "
            f"lower {lower:#010x} y={lower_y:.6f}"
        )
        print(
            f"  timer mask={seen_mask:#04x}, max={max_timer}, "
            f"dialogue={dialogue:#010x} first seen at {dialogue_timer}"
        )
        print(f"  wrote {args.jsonl}")
    finally:
        if gdb:
            gdb.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        shutil.rmtree(user_dir, ignore_errors=True)
        output.close()
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
