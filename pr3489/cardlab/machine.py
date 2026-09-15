"""Run the repository's linked, matching PowerPC decomp without rewriting C."""

import os
import re
import struct
from collections import Counter
from functools import lru_cache
from pathlib import Path

from elftools.elf.elffile import ELFFile
from unicorn import UC_ARCH_PPC, UC_HOOK_CODE, UC_MODE_BIG_ENDIAN, UC_MODE_PPC32, Uc
from unicorn.ppc_const import UC_PPC_REG_0, UC_PPC_REG_LR, UC_PPC_REG_PC

REPO = Path(
    os.environ.get("MELEE_REPO", Path(__file__).resolve().parents[1] / ".local-inputs")
)
ELF = REPO / "build/GALE01/main.elf"


def signed(value):
    return value - 0x100000000 if value & 0x80000000 else value


@lru_cache(maxsize=1)
def load_image():
    segments, symbols, functions = [], {}, {}
    with ELF.open("rb") as stream:
        elf = ELFFile(stream)
        assert elf.elfclass == 32 and not elf.little_endian
        for segment in elf.iter_segments():
            if segment["p_type"] == "PT_LOAD" and segment["p_filesz"]:
                segments.append((segment["p_vaddr"], segment.data()))
        for symbol in elf.get_section_by_name(".symtab").iter_symbols():
            if symbol["st_value"]:
                symbols[symbol.name] = symbol["st_value"]
                if symbol["st_info"]["type"] == "STT_FUNC":
                    functions[symbol.name] = (symbol["st_value"], symbol["st_size"])
    return segments, symbols, functions


class Redirect:
    def __init__(self, address):
        self.address = address


class Machine:
    STOP = 0x817FF000
    STACK = 0x817F0000

    def __init__(self):
        self.uc = Uc(UC_ARCH_PPC, UC_MODE_PPC32 | UC_MODE_BIG_ENDIAN)
        self.uc.mem_map(0x80000000, 0x1800000)
        segments, self.symbols, self.functions = load_image()
        for address, data in segments:
            self.uc.mem_write(address, data)
        self.next_alloc = 0x81000000
        self.allocations = []
        self.hooks = []
        self.callbacks = []
        self.lb_callbacks = []
        self.visited = Counter()
        self.interrupts = True
        self.uc.mem_write(self.STOP, bytes.fromhex("4e800020"))
        self.callback_addr = self.STOP + 0x20
        self.hook(self.callback_addr, self._callback)
        self.lb_callback_addr = self.STOP + 0x40
        self.hook(
            self.lb_callback_addr,
            lambda result: self.lb_callbacks.append(signed(result)),
        )
        self.hook("OSDisableInterrupts", self._disable)
        self.hook("OSRestoreInterrupts", self._restore)
        self.hook("__assert", self._assert)
        self.hook("HSD_MemAlloc", lambda n: self.alloc(n, label="HSD_MemAlloc"))
        self.hook("HSD_Free", lambda address: 0)
        # Only platform/standard-library boundaries are mocked. All card/save
        # algorithms, queue builders and checksum/codec routines execute in PPC.
        self.hook("memcpy", self._memcpy)
        self.hook("memset", self._memset)
        self.hook("memcmp", self._memcmp)
        self.hook("strncpy", self._strncpy)
        self.hook("strcmp", lambda a, b: self._compare(self.cstr(a), self.cstr(b)))
        self.hook(
            "strncmp", lambda a, b, n: self._compare(self.cstr(a, n), self.cstr(b, n))
        )
        self.hook("strlen", lambda a: len(self.cstr(a)))
        self.hook("strtoul", self._strtoul)
        self.disk_id = self.alloc(32, label="DVD disk id")
        self.write(self.disk_id, b"GALE01")
        self.hook("DVDGetCurrentDiskID", lambda: self.disk_id)
        self.hook("OSReport", lambda *args: 0)
        for name, (address, size) in self.functions.items():
            if 0x803A949C <= address < 0x803B32A0 or 0x80019BB8 <= address < 0x8001C600:
                self.hooks.append(
                    self.uc.hook_add(
                        UC_HOOK_CODE,
                        lambda uc, pc, sz, data, n=name: self.visited.update([n]),
                        begin=address,
                        end=address,
                    )
                )

    def addr(self, symbol):
        return self.symbols[symbol] if isinstance(symbol, str) else symbol

    def read(self, address, size):
        return bytes(self.uc.mem_read(self.addr(address), size))

    def write(self, address, data):
        self.uc.mem_write(self.addr(address), bytes(data))

    def u32(self, address):
        return struct.unpack(">I", self.read(address, 4))[0]

    def i32(self, address):
        return signed(self.u32(address))

    def put32(self, address, value):
        self.write(address, struct.pack(">I", value & 0xFFFFFFFF))

    def put16(self, address, value):
        self.write(address, struct.pack(">H", value & 0xFFFF))

    def alloc(self, size, data=None, label="buffer"):
        size = max(size, 1)
        address = (self.next_alloc + 63) & ~31
        assert address + size + 32 < self.STACK - 0x10000
        self.write(address - 32, b"\xa5" * 32)
        self.write(address, b"\0" * size)
        self.write(address + size, b"\x5a" * 32)
        self.next_alloc = address + size + 32
        self.allocations.append((address, size, label))
        if data is not None:
            assert len(data) <= size
            self.write(address, data)
        return address

    def string(self, value):
        data = value.encode() if isinstance(value, str) else value
        return self.alloc(len(data) + 1, data + b"\0", "string")

    def cstr(self, address, limit=4096):
        result = bytearray()
        for i in range(limit):
            char = self.read(address + i, 1)
            if char == b"\0":
                break
            result.extend(char)
        return bytes(result)

    def check_canaries(self):
        for address, size, label in self.allocations:
            assert self.read(address - 32, 32) == b"\xa5" * 32, (label, "underflow")
            assert self.read(address + size, 32) == b"\x5a" * 32, (label, "overflow")

    def call(self, function, *args, budget=30_000_000):
        assert len(args) <= 8
        for n in range(3, 11):
            self.uc.reg_write(
                UC_PPC_REG_0 + n, args[n - 3] & 0xFFFFFFFF if n - 3 < len(args) else 0
            )
        self.uc.reg_write(UC_PPC_REG_0 + 1, self.STACK)
        self.uc.reg_write(UC_PPC_REG_0 + 2, self.addr("_SDA2_BASE_"))
        self.uc.reg_write(UC_PPC_REG_0 + 13, self.addr("_SDA_BASE_"))
        self.uc.reg_write(UC_PPC_REG_LR, self.STOP)
        try:
            self.uc.emu_start(self.addr(function), self.STOP, count=budget)
        except Exception as exc:
            raise RuntimeError(
                f"{function}: PC={self.uc.reg_read(UC_PPC_REG_PC):#x}: {exc}"
            ) from exc
        assert self.uc.reg_read(UC_PPC_REG_PC) == self.STOP, (
            f"instruction budget exceeded: {function}"
        )
        return signed(self.uc.reg_read(UC_PPC_REG_0 + 3))

    def hook(self, symbol, callback):
        import inspect

        address = self.addr(symbol)
        count = len(inspect.signature(callback).parameters)

        def handler(uc, pc, size, data):
            args = [uc.reg_read(UC_PPC_REG_0 + i) for i in range(3, 3 + count)]
            result = callback(*args)
            if isinstance(result, Redirect):
                uc.reg_write(UC_PPC_REG_PC, result.address)
                return
            if result is not None:
                uc.reg_write(UC_PPC_REG_0 + 3, result & 0xFFFFFFFF)
            uc.reg_write(UC_PPC_REG_PC, uc.reg_read(UC_PPC_REG_LR))

        handle = self.uc.hook_add(UC_HOOK_CODE, handler, begin=address, end=address)
        self.hooks.append(handle)
        return handle

    def _callback(self, argument, result):
        self.callbacks.append((signed(argument), signed(result)))
        return 0

    def _disable(self):
        previous = self.interrupts
        self.interrupts = False
        return int(previous)

    def _restore(self, enabled):
        previous = self.interrupts
        self.interrupts = bool(enabled)
        return int(previous)

    def _assert(self, filename, line, expression):
        raise AssertionError((self.cstr(filename), line, self.cstr(expression)))

    def _memcpy(self, dst, src, size):
        if size:
            self.write(dst, self.read(src, size))
        return dst

    def _memset(self, dst, value, size):
        self.write(dst, bytes([value & 255]) * size)
        return dst

    @staticmethod
    def _compare(a, b):
        return (a > b) - (a < b)

    def _memcmp(self, a, b, size):
        return self._compare(self.read(a, size), self.read(b, size))

    def _strncpy(self, dst, src, size):
        self.write(dst, self.cstr(src, size).ljust(size, b"\0"))
        return dst

    def inline_card_callback(self, callback, channel, result):
        # A deliberately broken mock: invoke the real callback inside the CARD
        # call, before its caller records the busy state. Preserve the PPC ABI.
        address = self.STOP + 0x100
        words = [
            0x9421FFE0,
            0x7C0802A6,
            0x90010024,
            0x38600000 | channel,
            0x38800000 | (result & 0xFFFF),
            0x3D800000 | (callback >> 16),
            0x618C0000 | (callback & 0xFFFF),
            0x7D8903A6,
            0x4E800421,
            0x38600000,
            0x80010024,
            0x7C0803A6,
            0x38210020,
            0x4E800020,
        ]
        self.write(address, b"".join(struct.pack(">I", word) for word in words))
        return Redirect(address)

    def _strtoul(self, address, end, base):
        assert base == 10, (
            "audit only models the decimal conversion used by snapshot listing"
        )
        match = re.match(rb"[ \t\r\n]*[+-]?[0-9]+", self.cstr(address))
        if end:
            self.put32(end, address + (match.end() if match else 0))
        return int(match[0]) & 0xFFFFFFFF if match else 0
