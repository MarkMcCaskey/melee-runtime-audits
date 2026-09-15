"""Count actual switch dispatches and SDK entry calls without replacing behavior."""

import re
import struct
import subprocess

from elftools.elf.elffile import ELFFile
from run import ROOT

TRACE_CODE = 0x81030000
COUNTERS = 0x81040000
FAMILIES = {"command": 0, "request": 0x80, "active": 0x100, "task": 0x180, "sdk": 0x200}
SDK = [
    "CARDMountAsync",
    "CARDCheckAsync",
    "CARDFormatAsync",
    "CARDDeleteAsync",
    "CARDRenameAsync",
    "CARDCreateAsync",
    "CARDReadAsync",
    "CARDWriteAsync",
    "CARDGetStatus",
    "CARDSetStatusAsync",
    "CARDOpen",
    "CARDFastOpen",
    "CARDClose",
    "CARDUnmount",
    "HSD_MemAlloc",
    "HSD_Free",
]


def enums():
    result = {}
    for family, path, name in [
        ("command", "src/sysdolphin/baselib/hsd_3A94.h", "CardCmdType"),
        ("request", "src/sysdolphin/baselib/hsd_3A94.h", "CardRequestType"),
        ("active", "src/sysdolphin/baselib/hsd_3A94.h", "CardActiveType"),
        ("task", "src/melee/lb/lbcardnew.c", "CardTaskType"),
    ]:
        body = re.search(
            r"typedef enum " + name + r"\s*\{(.*?)\}",
            (ROOT / ".local-inputs" / path).read_text(),
            re.S,
        )[1]
        body = re.sub(r"/\*.*?\*/|//[^\n]*", "", body, flags=re.S)
        values, value = {}, -1
        for item in body.split(","):
            if not item.strip():
                continue
            label, *explicit = item.strip().split("=")
            value = int(explicit[0].strip(), 0) if explicit else value + 1
            values[label.strip()] = value
        result[family] = values
    return result


class Trace:
    def __init__(self, symbols, clang, output):
        self.symbols = symbols
        with (ROOT / ".local-inputs/build/GALE01/main.elf").open("rb") as stream:
            elf = ELFFile(stream)
            functions = {
                s.name: (s["st_value"], s["st_size"])
                for s in elf.get_section_by_name(".symtab").iter_symbols()
            }
            segments = [
                (seg["p_vaddr"], seg.data())
                for seg in elf.iter_segments()
                if seg["p_type"] == "PT_LOAD"
            ]

        def read(address, size):
            return next(
                data[address - base : address - base + size]
                for base, data in segments
                if base <= address < base + len(data)
            )

        def switch(name):
            address, size = functions[name]
            data = read(address, size)
            sites = [
                address + i
                for i in range(0, size, 4)
                if data[i : i + 4] == bytes.fromhex("4e800420")
            ]
            assert len(sites) == 1, (name, sites)
            return sites[0]

        def load(reg, address):
            return [
                f"lis {reg}, {address >> 16}",
                f"ori {reg}, {reg}, {address & 65535}",
            ]

        def absolute_tag(address):
            return [*load(11, address), "lwz 11, 0(11)"]

        def ring_tag(queue, head, stride):
            return [
                *absolute_tag(symbols[head]),
                f"mulli 11, 11, {stride}",
                *load(12, symbols[queue]),
                "add 11, 11, 12",
                "lwz 11, 0(11)",
            ]

        specs = [
            (
                "command",
                switch("hsd_803AAA48"),
                ring_tag("hsd_804D1148", "hsd_804D7980", 0x24),
            ),
            (
                "request",
                symbols["fn_803AA790"],
                ring_tag("hsd_804D2348", "hsd_804D7990", 0x18),
            ),
            # Matched lb dispatcher holds the selected CardTask in r29 at bctr.
            ("task", switch("lb_80019CB0"), ["lwz 11, 0(29)"]),
            ("active", symbols["hsd_803AAA48"], absolute_tag(symbols["hsd_804D1138"])),
            ("active", symbols["fn_8001A0B0"], absolute_tag(symbols["hsd_804D1138"])),
        ]
        specs += [("sdk", symbols[name], [f"li 11, {i}"]) for i, name in enumerate(SDK)]
        self.patches = []
        assembly = [".text"]
        for i, (family, site, tag) in enumerate(specs):
            original = int.from_bytes(read(site, 4), "big")
            assert original == 0x4E800420 or original >> 26 not in (16, 18, 19), (
                hex(site),
                hex(original),
            )
            # Stack frame, volatile GPRs, and CR restored before displaced opcode.
            # No calls, LR/CTR changes, carry/overflow instructions, or return edits.
            body = [
                "stwu 1,-32(1)",
                "stw 0,8(1)",
                "stw 11,12(1)",
                "stw 12,16(1)",
                "mfcr 0",
                "stw 0,20(1)",
                *tag,
                "slwi 11,11,2",
                *load(12, COUNTERS + FAMILIES[family]),
                "add 11,11,12",
                "lwz 12,0(11)",
                "addi 12,12,1",
                "stw 12,0(11)",
                "lwz 0,20(1)",
                "mtcrf 255,0",
                "lwz 12,16(1)",
                "lwz 11,12(1)",
                "lwz 0,8(1)",
                "addi 1,1,32",
                f".long 0x{original:08x}",
            ]
            if original != 0x4E800420:
                body += [f"tail_{i}: .long 0"]
            assembly += [f".globl hook_{i}", f"hook_{i}:", *body]
            self.patches.append(
                {"site": site, "original": original, "family": family, "index": i}
            )
        (output / "trace.s").write_text("\n".join(assembly) + "\n")
        subprocess.run(
            [
                clang,
                "--target=powerpc-unknown-eabi",
                "-c",
                str(output / "trace.s"),
                "-o",
                str(output / "trace.o"),
            ],
            check=True,
        )
        with (output / "trace.o").open("rb") as stream:
            elf = ELFFile(stream)
            code = bytearray(elf.get_section_by_name(".text").data())
            offsets = {
                s.name: s["st_value"]
                for s in elf.get_section_by_name(".symtab").iter_symbols()
            }
        assert len(code) < 0x4000
        for p in self.patches:
            p["target"] = TRACE_CODE + offsets[f"hook_{p['index']}"]
            if p["original"] != 0x4E800420:
                offset = offsets[f"tail_{p['index']}"]
                struct.pack_into(
                    ">I", code, offset, self.branch(TRACE_CODE + offset, p["site"] + 4)
                )
        self.code = bytes(code)

    @staticmethod
    def branch(source, dest):
        distance = dest - source
        assert -(1 << 25) <= distance < (1 << 25) and distance % 4 == 0
        return 0x48000000 | (distance & 0x03FFFFFC)

    def install(self, g):
        g.write(TRACE_CODE, self.code)
        g.write(COUNTERS, bytes(0x300))
        for patch in self.patches:
            assert g.u32(patch["site"]) == patch["original"]
            g.write(
                patch["site"],
                struct.pack(">I", self.branch(patch["site"], patch["target"])),
            )

    def counts(self, g):
        data = g.read(COUNTERS, 0x300)
        result = {}
        for family, offset in FAMILIES.items():
            names = SDK if family == "sdk" else list(enums()[family])
            result[family] = {
                name: struct.unpack_from(">I", data, offset + 4 * i)[0]
                for i, name in enumerate(names)
            }
        return result
