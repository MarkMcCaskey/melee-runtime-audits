"""Typed test accessors. Layout constants mirror checked decomp declarations."""

import re

from .card import Card
from .machine import REPO, Machine


def enum_values(file, enum):
    text = (REPO / file).read_text()
    body = re.search(r"typedef enum " + enum + r"\s*\{(.*?)\}", text, re.DOTALL)[1]
    body = re.sub(r"/\*.*?\*/|//[^\n]*", "", body, flags=re.DOTALL)
    result, value = {}, -1
    for item in body.split(","):
        item = item.strip()
        if not item:
            continue
        name, *explicit = item.split("=")
        value = int(explicit[0].strip(), 0) if explicit else value + 1
        result[name.strip()] = value
    return result


CMD = enum_values("src/sysdolphin/baselib/hsd_3A94.h", "CardCmdType")
REQ = enum_values("src/sysdolphin/baselib/hsd_3A94.h", "CardRequestType")
ACTIVE = enum_values("src/sysdolphin/baselib/hsd_3A94.h", "CardActiveType")
TASK = enum_values("src/melee/lb/lbcardnew.c", "CardTaskType")


class Lab:
    def __init__(self):
        self.m = Machine()
        self.card = Card(self.m)
        self.m.call("hsd_803B2374")
        self.state = self.m.alloc(0x464, label="CardState")
        self.work = self.m.alloc(8192, label="sector buffer")
        self.m.call("hsd_803B24E4", self.state, 0, 8192, self.work)
        self.command = self.m.alloc(0x24, label="CardCmd")
        self.executed_commands = set()
        self.active_types = set()
        self.request_types = set()
        self.task_types = set()
        self.names = {}
        self.queued_commands = set()
        from unicorn import UC_HOOK_CODE

        def observe(function, action):
            address = self.m.addr(function)
            self.m.hooks.append(
                self.m.uc.hook_add(
                    UC_HOOK_CODE, lambda *args: action(), begin=address, end=address
                )
            )

        def switch_observer(function, action):
            start, size = self.m.functions[function]
            code = self.m.read(start, size)
            sites = [
                start + i
                for i in range(0, size, 4)
                if code[i : i + 4] == bytes.fromhex("4e800420")
            ]
            assert len(sites) == 1, (function, sites)
            observe(sites[0], action)

        switch_observer(
            "hsd_803AAA48",
            lambda: self.executed_commands.add(
                self.m.u32(
                    self.m.addr("hsd_804D1148") + self.m.u32("hsd_804D7980") * 0x24
                )
            ),
        )
        observe(
            "fn_803AA790",
            lambda: self.request_types.add(
                self.m.u32(
                    self.m.addr("hsd_804D2348") + self.m.u32("hsd_804D7990") * 0x18
                )
            ),
        )

        def task_tag():
            start = self.m.addr("lb_80432A68") + 0x510
            tag = next(
                self.m.u32(start + i * 0x54)
                for i in range(11)
                if self.m.u32(start + i * 0x54) != TASK["CARD_TASK_NONE"]
            )
            self.task_types.add(tag)

        switch_observer("lb_80019CB0", task_tag)
        for callback in [self.m.callback_addr, "fn_8001A0B0"]:
            observe(callback, lambda: self.active_types.add(self.m.u32("hsd_804D1138")))

    def field(self, offset, value=None):
        if value is not None:
            self.m.put32(self.state + offset, value)
        return self.m.i32(self.state + offset)

    def configure(self, sizes=(0, 128), flags=(0, 3), banner=0, formats=(), speeds=()):
        self.sizes = sizes
        self.flags = flags
        self.m.write(self.state + 0x3B0, bytes([banner]))
        self.m.write(self.state + 0x3B2, bytes(formats).ljust(8, b"\0"))
        self.m.write(self.state + 0x3BA, bytes(speeds).ljust(8, b"\0"))
        self.payloads = []
        for i, (size, flag) in enumerate(zip(sizes, flags)):
            data = bytes((j * 37 + i * 17) & 255 for j in range(size))
            pointer = self.m.alloc(size, data, f"logical file {i}")
            self.payloads.append(pointer)
            self.m.call("hsd_803AC3E0", self.state, i, size, flag, pointer)
        self.m.call("hsd_803B2674", self.state)
        return self

    def attach(self, data=None, number=7, name="test-save"):
        size = self.m.call("hsd_803B2674", self.state) * 8192
        file = self.card.add_file(
            name,
            data if data is not None else bytes(size),
            number=number,
            banner_format=self.m.read(self.state + 0x3B0, 1)[0],
        )
        self.field(0x20, number)
        self.card._open(0, file, self.state + 0xC)
        return file

    def enqueue(self, name, *args):
        self.m.write(self.command, bytes(0x24))
        self.m.put32(self.command, CMD[name])
        self.m.put32(self.command + 4, self.state)
        for i, arg in enumerate(args):
            self.m.put32(self.command + 8 + i * 4, arg)
        return self.m.call("fn_803AC168", self.command)

    def ring(self):
        head = self.m.u32("hsd_804D7980")
        result = []
        for i in range(128):
            address = self.m.addr("hsd_804D1148") + ((head + i) % 128) * 0x24
            tag = self.m.u32(address)
            if tag == CMD["CARD_CMD_NONE"]:
                break
            result.append((tag, address))
        return result

    def pump(self):
        self.queued_commands.update(tag for tag, _ in self.ring())
        self.active_types.add(self.m.u32("hsd_804D1138"))
        self.m.call("hsd_803AAA48")
        self.queued_commands.update(tag for tag, _ in self.ring())
        self.active_types.add(self.m.u32("hsd_804D1138"))

    def drain(self, limit=5000):
        for _ in range(limit):
            self.pump()
            if self.card.pending:
                self.card.complete()
                continue
            if self.m.u32("hsd_804D799C") == 2:
                return
        raise AssertionError("queue did not drain")

    def create(self, name="test-save", comment=None, banner=None, icons=None):
        self.comment = self.m.alloc(64, comment or bytes(range(64)), "comment")
        self.banner = self.m.alloc(len(banner or b""), banner or b"", "banner")
        self.icons = self.m.alloc(len(icons or b""), icons or b"", "icons")
        self.filename = self.m.string(name)
        result = self.m.call(
            "hsd_803B286C",
            self.state,
            self.filename,
            self.comment,
            self.banner,
            self.icons,
            self.m.callback_addr,
        )
        assert result == 0
        self.drain()
        assert self.m.callbacks[-1] == (0, 0), self.m.callbacks
        return self.card.files[self.field(0x20)]

    def bind_lb(self):
        """Initialize the real lb wrapper's storage and use its embedded state."""
        base = self.m.addr("lb_80432A68")
        state_bytes = self.m.read(self.state, 0x464)
        self.m.call("lb_80019EF0", 0, 0, 0, self.m.lb_callback_addr)
        self.m.put32(base, self.m.alloc(5 * 8192, label="CARD mount work area"))
        self.m.put32(base + 4, self.work)
        self.m.put32(base + 0x88, 8192)
        self.m.put32(base + 0x80, 1)
        self.state = base + 0xA8
        self.m.write(self.state, state_bytes)
        self.lb = base
        return base

    def run_task(
        self,
        name,
        result=16,
        mask=0xFFFFFFFF,
        filename="old",
        new_filename="new",
        entries=0,
    ):
        task = self.lb + 0x510
        self.m.put32(task, TASK[name])
        self.m.put32(task + 4, mask)
        self.m.put32(task + 8, entries)
        self.m.put32(task + 12, task + 0x10)
        self.m.write(task + 0x10, filename.encode().ljust(33, b"\0"))
        self.m.write(task + 0x31, new_filename.encode().ljust(33, b"\0"))
        return self.m.call("lb_80019CB0", result)

    def drain_lb(self, limit=5000):
        for _ in range(limit):
            if self.card.pending:
                self.card.complete()
            result = self.m.call("lb_8001B6F8")
            if result != 11:
                return result
        raise AssertionError("lb task did not complete")
