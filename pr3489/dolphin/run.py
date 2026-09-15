#!/usr/bin/env python3
"""Independent Dolphin audit: real game SDK, EXI hardware, and disposable card."""

import argparse
import hashlib
import json
import re
import socket
import struct
import subprocess
import tempfile
import time
from pathlib import Path

from elftools.elf.elffile import ELFFile
from elftools.elf.relocation import RelocationSection
from rsp import Remote

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CODE, MAILBOX, COMPLETION = 0x81000000, 0x81001000, 0x81001800
STATE, WORK, ZERO, DATA, DEST, NAME, COMMENT = (
    0x81010000,
    0x81012000,
    0x81015000,
    0x81016000,
    0x8101A000,
    0x8101E000,
    0x8101E040,
)
OPERATIONS = {
    name: i + 1
    for i, name in enumerate(
        [
            "PROBE",
            "MOUNT",
            "CHECK",
            "RESET_QUEUE",
            "INIT_STATE",
            "REGISTER_FILE",
            "BLOCK_COUNT",
            "CREATE_SAVE",
            "READ_FILE",
            "WRITE_FILE",
            "OPEN_SAVE",
            "READ_HEADER",
            "UPDATE_HEADER",
            "UNMOUNT",
            "WAIT_CALLBACK",
            "DRAIN",
            "CREATE_RAW",
            "QUEUE_COMMAND",
            "PUMP_ONCE",
            "RAW_OPEN",
            "RAW_READ",
            "RAW_WRITE",
            "RAW_CLOSE",
            "LB_INIT",
            "LB_RUN",
            "LB_DRAIN",
            "HEAP_INIT",
        ]
    )
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def disc_dol_hash(iso):
    with iso.open("rb") as stream:
        assert stream.read(8) == b"GALE01\0\x02", (
            "Requires uncompressed GALE01 revision 2 ISO"
        )
        stream.seek(0x420)
        offset = struct.unpack(">I", stream.read(4))[0]
        stream.seek(offset)
        header = stream.read(256)
        offsets = struct.unpack(">18I", header[:72])
        sizes = struct.unpack(">18I", header[0x90:0xD8])
        length = max(a + b for a, b in zip(offsets, sizes))
        stream.seek(offset)
        return hashlib.sha1(stream.read(length)).hexdigest()


def build(args, output):
    inputs = ROOT / ".local-inputs"
    provenance = json.loads((inputs / "provenance.json").read_text())
    elf_path = inputs / "build/GALE01/main.elf"
    assert sha(elf_path.read_bytes()) == provenance["elf_sha256"]
    assert disc_dol_hash(args.iso) == provenance["dol_sha1"], (
        "ISO DOL differs from matching build"
    )
    with elf_path.open("rb") as stream:
        elf = ELFFile(stream)
        symbols = {
            s.name: s["st_value"]
            for s in elf.get_section_by_name(".symtab").iter_symbols()
        }
    source = HERE / "driver.c"
    names = sorted(set(re.findall(r"FN\((\w+),", source.read_text())) - {"name"})
    names.append("hsd_804D799C")
    command = [
        args.clang,
        "--target=powerpc-unknown-eabi",
        "-O2",
        "-ffreestanding",
        "-fno-builtin",
        "-fno-stack-protector",
        "-fno-jump-tables",
        *[f"-D{name}_ADDR=0x{symbols[name]:08x}" for name in names],
        "-c",
        str(source),
        "-o",
        str(output / "driver.o"),
    ]
    subprocess.run(command, check=True)
    with (output / "driver.o").open("rb") as stream:
        obj = ELFFile(stream)
        assert not any(
            isinstance(section, RelocationSection) and section.num_relocations()
            for section in obj.iter_sections()
        ), "Driver requires a linker"
        code = obj.get_section_by_name(".text").data()
        exports = {
            s.name: CODE + s["st_value"]
            for s in obj.get_section_by_name(".symtab").iter_symbols()
            if s.name in ("driver", "callback", "lb_callback")
        }
    assert len(code) < 0x1000, "Driver overlaps mailbox"
    provenance = {
        **provenance,
        "iso_dol_sha1": disc_dol_hash(args.iso),
        "dolphin_version": subprocess.check_output(
            [str(args.dolphin), "--version"], text=True
        ).strip(),
        "dolphin_binary_sha256": sha(args.dolphin.read_bytes()),
        "clang_version": subprocess.check_output(
            [args.clang, "--version"], text=True
        ).splitlines()[0],
        "driver_code_sha256": sha(code),
        "audit_sha256": {
            p.name: sha(p.read_bytes())
            for p in sorted(HERE.iterdir())
            if p.suffix in (".c", ".py")
        },
        "target_addresses": {name: symbols[name] for name in names},
        "bootstrap_address": symbols["db_GetGameLaunchButtonState"],
    }
    return symbols, code, exports, provenance


class Session:
    def __init__(self, args, user, build_result, phase, evidence):
        symbols, code, exports, _ = build_result
        self.exports, self.evidence, self.phase = exports, evidence, phase
        self.g = None
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.log = (user / f"dolphin-{phase}.log").open("w")
        settings = [
            f"General.GDBPort={port}",
            "Interface.DebugModeEnabled=True",
            "Core.CPUThread=False",
            "Core.CPUCore=0",
            "Core.AccurateCPUCache=False",
            "Core.EmulationSpeed=0.0",
            "Core.SlotA=1",
            "Core.SlotB=255",
            "Core.MemoryCardSize=4",
            "Core.EnableCheats=False",
            "DSP.Backend=No audio output",
        ]
        command = [
            str(args.dolphin),
            *args.dolphin_arg,
            "-u",
            str(user),
            "-v",
            "Null",
            *[part for setting in settings for part in ("-C", "Dolphin." + setting)],
            "-e",
            str(args.iso),
        ]
        self.proc = subprocess.Popen(command, stdout=self.log, stderr=self.log)
        try:
            self.g = Remote(port)
            start = symbols["db_GetGameLaunchButtonState"]
            self.g.ok(f"Z0,{start:x},4")
            self.g.send("c")
            assert self.g.receive(30).startswith((b"T", b"S"))
            assert int(self.g.command("p40"), 16) == start
            self.g.ok(f"z0,{start:x},4")
            # Reserve otherwise unused arena memory before game heap initialization.
            # Only the bootstrap entry is patched; all audited SDK/save code is intact.
            self.g.write(CODE, code)
            assert self.g.read(CODE, len(code)) == code
            self.g.write(MAILBOX, bytes(40))
            displacement = exports["driver"] - start
            assert -(1 << 25) <= displacement < (1 << 25)
            self.g.write(
                start, struct.pack(">I", 0x48000000 | (displacement & 0x03FFFFFC))
            )
            if getattr(args, "install_trace", None):
                args.install_trace(self.g)
            self.g.send("c")
            self.until(MAILBOX + 36, 0x34890001)
        except BaseException:
            self.close()
            raise

    def until(self, address, value, timeout=40):
        deadline = time.monotonic() + timeout
        while self.g.u32(address) != value:
            if time.monotonic() >= deadline:
                pc = self.g.command("p40").decode()
                raise TimeoutError(f"Guest did not complete; PC={pc}")
            time.sleep(0.01)

    def call(self, operation, *args):
        assert len(args) <= 6
        packet = [
            0,
            OPERATIONS[operation],
            *args,
            *([0] * (6 - len(args))),
            0,
            0x34890001,
        ]
        self.g.write(MAILBOX, struct.pack(">10I", *packet))
        self.g.write(MAILBOX, struct.pack(">I", 1))
        self.until(MAILBOX, 2)
        result = struct.unpack(">i", self.g.read(MAILBOX + 32, 4))[0]
        self.evidence["calls"].append(
            {
                "phase": self.phase,
                "operation": operation,
                "args": list(args),
                "result": result,
            }
        )
        return result

    def completion(self, operation, *args, expected=(0, 0), sdk=False):
        self.g.write(COMPLETION, bytes(12))
        assert self.call(operation, *args, self.exports["callback"]) == 0
        self.call("WAIT_CALLBACK" if sdk else "DRAIN")
        observed = struct.unpack(">iii", self.g.read(COMPLETION, 12))
        assert observed == (1, *expected), (operation, observed, expected)
        self.evidence["callbacks"].append(
            {
                "phase": self.phase,
                "operation": operation,
                "argument": observed[1],
                "result": observed[2],
            }
        )

    def mount(self):
        deadline = time.monotonic() + 30
        while self.call("PROBE", COMPLETION + 32, COMPLETION + 36) != 0:
            if time.monotonic() >= deadline:
                raise TimeoutError("CARDProbeEx never became ready")
            time.sleep(0.05)
        size, sector = struct.unpack(">II", self.g.read(COMPLETION + 32, 8))
        assert sector == 8192
        self.evidence["cards"].append(
            {"phase": self.phase, "capacity_mbits": size, "sector_bytes": sector}
        )
        self.completion("MOUNT", 0x81002000, sdk=True)
        self.completion("CHECK", sdk=True)
        self.call("RESET_QUEUE")

    def initialize(self, mode, name, size=9000, zero_mode=3):
        self.call("INIT_STATE", STATE, WORK)
        self.g.write(NAME, name.encode() + b"\0")
        self.g.write(COMMENT, bytes(range(64)))
        self.g.write(ZERO, b"F" * 180)
        self.g.write(DATA, bytes((i * 37 + 17) & 255 for i in range(size)))
        self.call("REGISTER_FILE", STATE, 0, 180, zero_mode, ZERO)
        self.call("REGISTER_FILE", STATE, 1, size, mode, DATA)
        return self.call("BLOCK_COUNT", STATE)

    def read_payload(self, file_idx, expected):
        self.g.write(DEST, b"X" * len(expected))
        self.completion("READ_FILE", STATE, file_idx, DEST, expected=(file_idx, 0))
        assert self.g.read(DEST, len(expected)) == expected, "Logical file bytes differ"

    def reopen(self, result=0):
        self.call("INIT_STATE", STATE, WORK)
        self.completion("OPEN_SAVE", STATE, NAME, expected=(0, result))

    def close(self):
        if self.g:
            self.g.close()
            self.g = None
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
                raise RuntimeError(
                    "Dolphin required forced termination; persistence not verified"
                )
        self.log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dolphin", type=Path, required=True)
    parser.add_argument("--iso", type=Path, required=True)
    parser.add_argument("--clang", default="clang")
    parser.add_argument("--dolphin-arg", action="append", default=[])
    args = parser.parse_args()
    args.dolphin, args.iso = args.dolphin.resolve(), args.iso.resolve()
    run = Path(tempfile.mkdtemp(prefix="pr3489-dolphin-"))
    user = run / "user"
    user.mkdir()
    print(f"Isolated inputs, card, and logs: {run}", flush=True)
    built = build(args, run)
    evidence = {
        "provenance": built[3],
        "cases": [],
        "calls": [],
        "callbacks": [],
        "cards": [],
        "status": "running",
    }
    output = ROOT / "reports/dolphin-evidence.json"

    def passed(name, **details):
        evidence["cases"].append({"name": name, "outcome": "passed", **details})
        print("PASS", name, flush=True)

    session = None
    try:
        session = Session(args, user, built, "write", evidence)
        session.mount()
        for mode in range(4):
            session.initialize(mode, f"audit-mode-{mode}")
            session.completion("CREATE_SAVE", STATE, NAME, COMMENT)
            session.read_payload(1, bytes((i * 37 + 17) & 255 for i in range(9000)))
            changed = bytes((i * 19 + 3) & 255 for i in range(9000))
            session.g.write(DATA, changed)
            session.completion("WRITE_FILE", STATE, 1, DATA, expected=(1, 0))
            session.read_payload(0, b"F" * 180)
            session.completion("WRITE_FILE", STATE, 1, DATA, expected=(1, 1))
            session.g.write(COMMENT, b"H" * 64)
            session.completion("UPDATE_HEADER", STATE, COMMENT)
            session.g.write(COMMENT, b"X" * 64)
            session.completion("READ_HEADER", STATE, COMMENT)
            assert session.g.read(COMMENT, 64) == b"H" * 64
            session.reopen()
            session.read_payload(1, changed)
            session.read_payload(0, b"F" * 180)
            assert session.g.u32(STATE + 0x4C + 4) == 9000
            assert session.g.u32(STATE + 0x28 + 4) == mode
            passed(
                f"write_mode_{mode}_roundtrip_header_and_verified_result",
                payload_bytes=9000,
                payload_sha256=sha(changed),
                file_zero_bytes=180,
            )
        # Test the earlier mock-based counterexample against the actual SDK/card.
        for mode in (1, 2):
            session.initialize(mode, f"audit-zero-{mode}", size=128, zero_mode=0)
            session.completion("CREATE_SAVE", STATE, NAME, COMMENT)
            session.g.write(DATA, b"Z" * 128)
            session.completion("WRITE_FILE", STATE, 1, DATA, expected=(1, 0))
            session.reopen(result=-0x102)
            session.read_payload(1, b"Z" * 128)
            passed(f"mirrored_file_zero_mode_{mode}_reopen_error", reopen_result=-0x102)
        assert session.call("UNMOUNT") == 0
        session.close()
        session = None
        cards = list((user / "GC").glob("MemoryCardA*.raw"))
        assert len(cards) == 1 and cards[0].stat().st_size > 8192
        evidence["card_after_write_sha256"] = sha(cards[0].read_bytes())
        session = Session(args, user, built, "fresh_boot", evidence)
        session.mount()
        for mode in range(4):
            session.g.write(NAME, f"audit-mode-{mode}".encode() + b"\0")
            session.reopen()
            session.read_payload(1, bytes((i * 19 + 3) & 255 for i in range(9000)))
            session.read_payload(0, b"F" * 180)
            session.completion("READ_HEADER", STATE, COMMENT)
            assert session.g.read(COMMENT, 64) == b"H" * 64
            passed(f"write_mode_{mode}_persists_across_dolphin_restart")
        assert session.call("UNMOUNT") == 0
        evidence["status"] = "passed"
    except BaseException as exc:
        evidence["status"] = "failed"
        evidence["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        try:
            if session:
                session.close()
        finally:
            output.parent.mkdir(exist_ok=True)
            output.write_text(json.dumps(evidence, indent=2) + "\n")
            print(f"Evidence: {output}", flush=True)


if __name__ == "__main__":
    main()
