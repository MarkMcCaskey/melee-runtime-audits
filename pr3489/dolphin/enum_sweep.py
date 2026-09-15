#!/usr/bin/env python3
"""Focused Dolphin cases for every PR #3489 command/request/active/task tag."""

import argparse
import json
import struct
import tempfile
from pathlib import Path

from enum_trace import Trace, enums
from run import (
    COMMENT,
    COMPLETION,
    DATA,
    DEST,
    NAME,
    ROOT,
    STATE,
    WORK,
    ZERO,
    Session,
    build,
    sha,
)

COMMAND = 0x81020000
RAW_INFO, RAW_BUFFER, ENTRIES, SNAPSHOTS = (
    0x81021000,
    0x81024000,
    0x81022000,
    0x81023000,
)


class Sweep:
    def __init__(self, session, trace, symbols, evidence):
        self.s, self.t, self.sym, self.e = session, trace, symbols, evidence
        self.values = enums()

    def put(self, address, value):
        self.s.g.write(address, struct.pack(">I", value & 0xFFFFFFFF))

    def case(self, name, action, required=(), effects=""):
        before = self.t.counts(self.s.g)
        action()
        after = self.t.counts(self.s.g)
        delta = {
            family: {
                key: count - before[family][key]
                for key, count in counts.items()
                if count > before[family][key]
            }
            for family, counts in after.items()
        }
        for family, tag in required:
            assert delta[family].get(tag, 0) > 0, (name, tag, delta)
        row = {
            "name": name,
            "outcome": "passed",
            "effects_asserted": effects,
            "observed": delta,
        }
        self.e["cases"].append(row)
        print("PASS", name, flush=True)
        return delta

    def command(self, name, *args):
        data = [self.values["command"][name], STATE, *args]
        data += [0] * (9 - len(data))
        self.s.g.write(COMMAND, struct.pack(">9I", *[v & 0xFFFFFFFF for v in data]))
        assert self.s.call("QUEUE_COMMAND", COMMAND) == 0

    def raw(self, write=False, offset=8192, data=None):
        assert self.s.call("RAW_OPEN", NAME, RAW_INFO) == 0
        if write:
            self.s.g.write(RAW_BUFFER, data)
            assert self.s.call("RAW_WRITE", RAW_INFO, RAW_BUFFER, 8192, offset) == 0
            result = None
        else:
            assert self.s.call("RAW_READ", RAW_INFO, RAW_BUFFER, 8192, offset) == 0
            result = self.s.g.read(RAW_BUFFER, 8192)
        assert self.s.call("RAW_CLOSE", RAW_INFO) == 0
        return result

    def command_cases(self):
        s = self.s
        for mode in range(4):
            s.initialize(mode, f"enum-mode-{mode}", size=128)

            def exercise():
                s.completion("CREATE_SAVE", STATE, NAME, COMMENT)
                s.read_payload(1, bytes((i * 37 + 17) & 255 for i in range(128)))
                s.g.write(DATA, b"W" * 128)
                s.completion("WRITE_FILE", STATE, 1, DATA, expected=(1, 0))
                s.read_payload(1, b"W" * 128)
                before = self.t.counts(s.g)["sdk"]["CARDWriteAsync"]
                s.completion("WRITE_FILE", STATE, 1, DATA, expected=(1, 1))
                assert self.t.counts(s.g)["sdk"]["CARDWriteAsync"] == before
                # Both equal and changed headers: VERIFY_HEADER then WRITE_HEADER.
                s.completion("UPDATE_HEADER", STATE, COMMENT, expected=(0, 1))
                s.g.write(COMMENT, b"H" * 64)
                s.completion("UPDATE_HEADER", STATE, COMMENT)
                s.completion("READ_HEADER", STATE, COMMENT)
                assert s.g.read(COMMENT, 64) == b"H" * 64
                s.reopen()
                s.read_payload(1, b"W" * 128)
                s.read_payload(0, b"F" * 180)

            self.case(
                f"write_mode_{mode}_named_flows",
                exercise,
                required=[("request", "CARD_REQ_WRITE_FILE")],
                effects="Create/read/write/reopen exact bytes, header read/update, and no SDK writes for verified data.",
            )
        # A simple mirrored save makes sector transfer and repair semantics visible.
        s.initialize(0, "enum-mirror", size=128)
        s.completion("CREATE_SAVE", STATE, NAME, COMMENT)
        original = self.raw()

        def sector():
            self.command("CARD_CMD_READ_SECTOR", 0, 1, 0, 0, 0, 8192)
            s.call("DRAIN")
            assert s.g.read(WORK + 0x20, 128) == s.g.read(DATA, 128)
            assert s.g.read(WORK, 8192) != original
            self.command("CARD_CMD_WRITE_SECTOR", 0, 2, 1, 7, 0, 16384)
            s.call("DRAIN")
            assert self.raw(offset=16384) == original
            assert s.g.u32(STATE + 0x170 + 8) == 1 and s.g.u32(STATE + 0x270 + 8) == 7

        self.case(
            "sector_decode_reencode_and_bookkeeping",
            sector,
            [("command", "CARD_CMD_READ_SECTOR"), ("command", "CARD_CMD_WRITE_SECTOR")],
            "Sector read decodes payload; sector write preserves embedded header while recording descriptor sequence 7 in RAM.",
        )
        damaged = bytearray(original)
        damaged[25] ^= 1
        self.raw(write=True, data=damaged)

        def repair():
            mounts = self.t.counts(s.g)["sdk"]["CARDMountAsync"]
            s.reopen()
            assert self.t.counts(s.g)["sdk"]["CARDMountAsync"] == mounts
            assert self.raw() == self.raw(offset=16384) == original
            assert s.g.u32(STATE + 0x170 + 4) == s.g.u32(STATE + 0x170 + 8) == 1

        self.case(
            "scan_file_scans_blocks_and_repairs_corrupt_mirror",
            repair,
            [
                ("command", "CARD_CMD_SCAN_FILE"),
                ("command", "CARD_CMD_SCAN_BLOCK"),
                ("command", "CARD_CMD_REPAIR"),
            ],
            "Reopen restores corrupted physical sector from valid mirror, reconstructs block IDs, and does not mount.",
        )

        def clear():
            s.g.write(DEST, b"KEEP")
            self.command("CARD_CMD_CLEAR_BUF", 0, 0, 0, 0, DEST, 0, 4)
            s.g.write(COMMAND, b"X" * 0x24)
            s.call("DRAIN")
            assert s.g.read(DEST, 4) == bytes(4)

        delta = self.case(
            "clear_buffer_copies_descriptor",
            clear,
            [("command", "CARD_CMD_CLEAR_BUF")],
            "Queued descriptor survives caller overwrite and clears precisely four destination bytes.",
        )
        assert not delta["sdk"]
        for previous, expected in [(0, 1), (2, 0)]:

            def gate():
                s.g.write(DEST, b"KEEP")
                self.put(self.sym["hsd_804D7988"], previous)
                active = self.sym["hsd_804D1138"]
                for offset, value in [
                    (0, 1),
                    (4, STATE),
                    (8, s.exports["callback"]),
                    (12, 1),
                ]:
                    self.put(active + offset, value)
                self.command("CARD_CMD_CHECK_VERIFIED")
                self.command("CARD_CMD_CLEAR_BUF", 0, 0, 0, 0, DEST, 0, 4)
                s.g.write(COMPLETION, bytes(12))
                s.call("DRAIN")
                assert s.g.u32(COMPLETION + 8) == expected
                assert s.g.read(DEST, 4) == (b"KEEP" if expected else bytes(4))

            self.case(
                f"check_verified_result_{previous}",
                gate,
                [("command", "CARD_CMD_CHECK_VERIFIED")],
                f"Prior result {previous} becomes {expected}; following clear is gated accordingly.",
            )

        def unknown():
            s.call("RESET_QUEUE")
            head = s.g.u32(self.sym["hsd_804D7980"])
            self.command("CARD_CMD_UNK_0x03")
            s.call("PUMP_ONCE")
            s.call("PUMP_ONCE")
            assert s.g.u32(self.sym["hsd_804D7980"]) == head
            assert s.g.u32(self.sym["hsd_804D1148"] + head * 0x24) == 3
            s.call("RESET_QUEUE")

        delta = self.case(
            "unknown_command_03_stays_at_head",
            unknown,
            [("command", "CARD_CMD_UNK_0x03")],
            "Two pumps leave unknown tag at head; no invented operation or intended name.",
        )
        assert not delta["sdk"]

        def sentinels():
            s.call("RESET_QUEUE")
            s.call("PUMP_ONCE")
            assert s.g.u32(self.sym["hsd_804D1138"]) == 0
            assert all(
                s.g.u32(self.sym["hsd_804D2348"] + i * 0x18) == 0 for i in range(32)
            )

        self.case(
            "empty_command_request_active_sentinels",
            sentinels,
            [("command", "CARD_CMD_NONE"), ("active", "CARD_ACTIVE_NONE")],
            "Empty pump leaves no active operation and all 32 request slots marked NONE.",
        )

    def bind(self):
        s = self.s
        s.mount()
        state = s.g.read(STATE, 0x464)
        s.call("LB_INIT", s.exports["lb_callback"])
        self.lb = self.sym["lb_80432A68"]
        for offset, value in [
            (0, 0x81002000),
            (4, WORK),
            (0x80, 1),
            (0x88, 8192),
            (0x8AC, 0),
            (0x14, COMMENT),
        ]:
            self.put(self.lb + offset, value)
        s.g.write(self.lb + 0xA8, state)
        s.g.write(self.lb + 0x2C, b"01")
        s.g.write(self.lb + 0x2F, b"GALE")

    def task(self, name, filename="enum-mirror", new="renamed", entries=0, result=16):
        s = self.s
        task = self.lb + 0x510
        for offset, value in [
            (0, self.values["task"][name]),
            (4, 0xFFFFFFFF),
            (8, entries),
            (12, task + 16),
        ]:
            self.put(task + offset, value)
        s.g.write(task + 16, filename.encode().ljust(33, b"\0"))
        s.g.write(task + 0x31, new.encode().ljust(33, b"\0"))
        s.g.write(COMPLETION, bytes(12))
        result = s.call("LB_RUN", result)
        result = s.call("LB_DRAIN", result)
        assert s.g.u32(task) == 14
        return result

    def task_cases(self):
        s = self.s
        assert s.call("HEAP_INIT") >= 0
        for name in ["CARD_TASK_MOUNT_CARD", "CARD_TASK_CHECK_CARD"]:
            self.bind()
            if name == "CARD_TASK_MOUNT_CARD":
                s.call("UNMOUNT")
                self.put(self.lb + 0x80, 0)

            def run_task():
                assert self.task(name) == 0

            sdk = "CARDMountAsync" if name.endswith("MOUNT_CARD") else "CARDCheckAsync"
            self.case(
                name,
                run_task,
                [("task", name), ("sdk", sdk)],
                "Real task reaches named asynchronous SDK operation and completes successfully.",
            )
        for name in [
            "CARD_TASK_OPEN_FILE",
            "CARD_TASK_READ_FILES",
            "CARD_TASK_WRITE_FILES",
            "CARD_TASK_SET_STATUS",
            "CARD_TASK_READ_HEADER",
        ]:
            self.bind()
            s.g.write(ENTRIES, bytes(9 * 12))
            self.put(ENTRIES + 8, ZERO)
            self.put(ENTRIES + 12 + 8, DATA)
            s.g.write(DATA, b"T" * 128)
            s.g.write(COMMENT, b"L" * 64)

            def operation():
                assert self.task(name, entries=ENTRIES) == 0
                s.mount()  # wrapper unmounts after completion
                if name == "CARD_TASK_OPEN_FILE":
                    assert s.g.u32(self.lb + 0xA8 + 0x4C + 4) == 128
                elif name == "CARD_TASK_READ_FILES":
                    assert s.g.read(DATA, 128) == bytes(
                        (i * 37 + 17) & 255 for i in range(128)
                    )
                elif name == "CARD_TASK_WRITE_FILES":
                    s.g.write(NAME, b"enum-mirror\0")
                    s.reopen()
                    s.read_payload(1, b"T" * 128)
                elif name == "CARD_TASK_SET_STATUS":
                    assert self.raw(offset=0)[:64] == b"L" * 64
                else:
                    assert s.g.read(COMMENT, 64) == b"L" * 64

            self.case(
                name,
                operation,
                [("task", name)],
                "Task completes and its opened metadata, read/write bytes, or header contents match the requested operation.",
            )
        self.bind()
        s.g.write(COMMENT, b"C" * 64)

        def create():
            assert self.task("CARD_TASK_CREATE_FILE", filename="task-created") == 0
            s.mount()
            s.g.write(NAME, b"task-created\0")
            assert self.raw(offset=0)[:64] == b"C" * 64

        self.case(
            "CARD_TASK_CREATE_FILE",
            create,
            [("task", "CARD_TASK_CREATE_FILE"), ("sdk", "CARDCreateAsync")],
            "Creates named file containing supplied comment.",
        )
        self.bind()

        def rename():
            assert (
                self.task(
                    "CARD_TASK_RENAME_FILE", filename="task-created", new="task-renamed"
                )
                == 0
            )
            s.mount()
            s.g.write(NAME, b"task-created\0")
            assert s.call("RAW_OPEN", NAME, RAW_INFO) == -4
            s.g.write(NAME, b"task-renamed\0")
            assert self.raw(offset=0)[:64] == b"C" * 64

        self.case(
            "CARD_TASK_RENAME_FILE",
            rename,
            [("task", "CARD_TASK_RENAME_FILE"), ("sdk", "CARDRenameAsync")],
            "Old name no longer opens; new name preserves file contents.",
        )
        self.bind()
        self.case(
            "CARD_TASK_FIND_FILE",
            lambda: self.expect_task("CARD_TASK_FIND_FILE", 0, filename="task-renamed"),
            [("task", "CARD_TASK_FIND_FILE")],
            "Finds exact filename with matching game/company metadata.",
        )
        self.bind()
        self.case(
            "CARD_TASK_FIND_FILE_missing",
            lambda: self.expect_task("CARD_TASK_FIND_FILE", 13, filename="absent"),
            [("task", "CARD_TASK_FIND_FILE")],
            "Missing filename produces result 13.",
        )
        self.bind()

        def delete():
            assert self.task("CARD_TASK_DELETE_FILE", filename="task-renamed") == 0
            s.mount()
            s.g.write(NAME, b"task-renamed\0")
            assert s.call("RAW_OPEN", NAME, RAW_INFO) == -4

        self.case(
            "CARD_TASK_DELETE_FILE",
            delete,
            [("task", "CARD_TASK_DELETE_FILE"), ("sdk", "CARDDeleteAsync")],
            "Deleted name no longer opens through real SDK.",
        )
        for stored, expected in [(0, 1), (2, 1), (4, 4)]:
            self.bind()
            self.put(self.lb + 0x34, stored)
            self.case(
                f"CARD_TASK_UNK_0x03_result_{stored}",
                lambda: self.expect_task("CARD_TASK_UNK_0x03", expected),
                [("task", "CARD_TASK_UNK_0x03")],
                f"Stored result {stored} becomes {expected}; intended role remains unknown.",
            )
        s.mount()
        for name in ["100", "300", "200-extra"]:
            s.g.write(NAME, name.encode() + b"\0")
            s.completion("CREATE_RAW", NAME, 8192, RAW_INFO, sdk=True)
        self.bind()
        self.put(self.lb + 0x20, SNAPSHOTS)
        self.put(self.lb + 0x24, SNAPSHOTS + 0x500)
        self.put(self.lb + 0x28, SNAPSHOTS + 0x504)
        self.put(self.lb + 0x8C, 20 * 8192)
        self.put(self.lb + 0x90, 120)

        def snapshots():
            assert self.task("CARD_TASK_LIST_SNAPSHOTS") == 0
            assert [s.g.u32(SNAPSHOTS + i * 8) for i in range(3)] == [300, 200, 100]
            assert s.g.read(SNAPSHOTS + 3 * 8 + 4, 2) == b"\xff\xff"
            assert (
                s.g.u32(SNAPSHOTS + 0x500) == 20 and s.g.u32(SNAPSHOTS + 0x504) == 120
            )

        self.case(
            "CARD_TASK_LIST_SNAPSHOTS",
            snapshots,
            [
                ("task", "CARD_TASK_LIST_SNAPSHOTS"),
                ("sdk", "HSD_MemAlloc"),
                ("sdk", "HSD_Free"),
            ],
            "Lists decimal filename prefixes newest first, accepts 200-extra, excludes nonnumeric names; real SDK and allocator.",
        )
        self.bind()

        def none():
            assert s.call("LB_RUN", 16) == 16
            assert all(s.g.u32(self.lb + 0x510 + i * 0x54) == 14 for i in range(11))

        self.case(
            "CARD_TASK_NONE",
            none,
            effects="Eleven unused task slots do not dispatch mount, whose enum value is zero.",
        )
        self.bind()

        def format_card():
            assert self.task("CARD_TASK_FORMAT_CARD") == 0
            s.mount()
            s.g.write(NAME, b"100\0")
            assert s.call("RAW_OPEN", NAME, RAW_INFO) == -4

        self.case(
            "CARD_TASK_FORMAT_CARD",
            format_card,
            [("task", "CARD_TASK_FORMAT_CARD"), ("sdk", "CARDFormatAsync")],
            "Formats disposable card; previously present file no longer opens.",
        )

    def expect_task(self, name, expected, **kwargs):
        assert self.task(name, **kwargs) == expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dolphin", type=Path, required=True)
    parser.add_argument("--iso", type=Path, required=True)
    parser.add_argument("--clang", default="clang")
    parser.add_argument("--dolphin-arg", action="append", default=[])
    args = parser.parse_args()
    args.dolphin = args.dolphin.resolve()
    args.iso = args.iso.resolve()
    folder = Path(tempfile.mkdtemp(prefix="pr3489-enums-"))
    user = folder / "user"
    user.mkdir()
    print("Local card/logs:", folder, flush=True)
    built = build(args, folder)
    trace = Trace(built[0], args.clang, folder)
    args.install_trace = trace.install
    evidence = {
        "status": "running",
        "provenance": built[3],
        "enums": enums(),
        "cases": [],
        "calls": [],
        "callbacks": [],
        "cards": [],
        "trace_code_sha256": sha(trace.code),
        "trace_patches": trace.patches,
    }
    session = None
    try:
        session = Session(args, user, built, "enum_sweep", evidence)
        session.mount()
        sweep = Sweep(session, trace, built[0], evidence)
        sweep.command_cases()
        sweep.task_cases()
        totals = trace.counts(session.g)
        evidence["totals"] = totals
        for family, values in enums().items():
            for name in values:
                if name not in ("CARD_REQ_NONE", "CARD_TASK_NONE"):
                    assert totals[family][name] > 0, ("missing emulator coverage", name)
        evidence["status"] = "passed"
    except BaseException as exc:
        evidence["status"] = "failed"
        evidence["error"] = f"{type(exc).__name__}: {exc}"
        if session:
            evidence["totals"] = trace.counts(session.g)
        raise
    finally:
        if session:
            session.close()
        output = ROOT / "reports/enum-evidence.json"
        output.write_text(json.dumps(evidence, indent=2) + "\n")
        print("Evidence:", output, flush=True)


if __name__ == "__main__":
    main()
