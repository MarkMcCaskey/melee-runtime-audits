"""Deterministic CARD interface model, deliberately separate from save logic."""

from collections import defaultdict, deque
from dataclasses import dataclass

from .machine import signed


@dataclass
class File:
    number: int
    name: bytes
    data: bytearray
    stat: bytearray


class Card:
    def __init__(self, machine, capacity=8 * 1024 * 1024):
        self.m = machine
        self.capacity = capacity
        self.files = {}
        self.present = True
        self.mounted = True
        self.events = []
        self.pending = deque()
        self.failures = defaultdict(deque)
        self.completion_failures = defaultdict(deque)
        self.transferred = 0
        self.inline_callbacks = False
        for name in [
            "CARDProbe",
            "CARDProbeEx",
            "CARDMountAsync",
            "CARDCheckAsync",
            "CARDUnmount",
            "CARDFreeBlocks",
            "CARDOpen",
            "CARDFastOpen",
            "CARDClose",
            "CARDRead",
            "CARDReadAsync",
            "CARDWrite",
            "CARDWriteAsync",
            "CARDCreateAsync",
            "CARDGetStatus",
            "CARDSetStatusAsync",
            "CARDGetXferredBytes",
            "CARDFormatAsync",
            "CARDDeleteAsync",
            "CARDRenameAsync",
        ]:
            method = getattr(self, name)
            self.m.hook(name, method)

    def add_file(
        self,
        name,
        data,
        number=None,
        banner_format=0,
        icon_format=0,
        icon_speed=0,
        game=b"GALE",
        company=b"01",
    ):
        if isinstance(name, str):
            name = name.encode()
        assert len(name) <= 32
        if number is None:
            number = next(i for i in range(127) if i not in self.files)
        stat = bytearray(0x6C)
        stat[:32] = name.ljust(32, b"\0")
        stat[0x20:0x24] = len(data).to_bytes(4, "big")
        stat[0x28:0x2C] = game
        stat[0x2C:0x2E] = company
        stat[0x2E] = banner_format
        stat[0x30:0x34] = (0x40).to_bytes(4, "big")
        stat[0x34:0x36] = icon_format.to_bytes(2, "big")
        stat[0x36:0x38] = icon_speed.to_bytes(2, "big")
        file = File(number, name, bytearray(data), stat)
        self.files[number] = file
        return file

    def fail(self, name, *results, completion=False):
        (self.completion_failures if completion else self.failures)[name].extend(
            results
        )

    def _begin(self, name, *args):
        self.events.append((name, *args))
        if self.failures[name]:
            return self.failures[name].popleft()
        if not self.present:
            return -3
        if self.pending and name not in ["CARDGetXferredBytes"]:
            return -1
        return 0

    def _async(self, name, channel, callback, action):
        if self.pending:
            return -1
        if self.inline_callbacks:
            result = action()
            return self.m.inline_card_callback(callback, channel, result)
        self.pending.append((name, channel, callback, action))
        return 0

    def complete(self):
        assert self.m.interrupts, "CARD callbacks must wait for interrupt restoration"
        assert self.pending
        name, channel, callback, action = self.pending.popleft()
        result = (
            self.completion_failures[name].popleft()
            if self.completion_failures[name]
            else 0
        )
        if result == 0:
            result = action()
        self.events.append(("complete", name, result))
        if callback:
            self.m.call(callback, channel, result)
        return result

    def _open(self, channel, file, info):
        if file is None:
            return -4
        self.m.put32(info, channel)
        self.m.put32(info + 4, file.number)
        self.m.put32(info + 8, 0)
        self.m.put32(info + 12, len(file.data))
        return 0

    def CARDProbe(self, channel):
        return self._begin("CARDProbe", channel)

    def CARDProbeEx(self, channel, memsize, sector_size):
        result = self._begin("CARDProbeEx", channel)
        if result == 0:
            self.m.put32(memsize, self.capacity // (1024 * 1024) * 8)
            self.m.put32(sector_size, 8192)
        return result

    def CARDMountAsync(self, channel, work, detach, callback):
        result = self._begin("CARDMountAsync", channel, work, detach, callback)

        def mount():
            self.mounted = True
            return 0

        return result or self._async("CARDMountAsync", channel, callback, mount)

    def CARDCheckAsync(self, channel, callback):
        result = self._begin("CARDCheckAsync", channel, callback)
        return result or self._async("CARDCheckAsync", channel, callback, lambda: 0)

    def CARDUnmount(self, channel):
        result = self._begin("CARDUnmount", channel)
        self.mounted = False
        return result

    def CARDFreeBlocks(self, channel, free_bytes, free_files):
        result = self._begin("CARDFreeBlocks", channel)
        if result == 0:
            self.m.put32(
                free_bytes,
                self.capacity - sum(len(f.data) for f in self.files.values()),
            )
            self.m.put32(free_files, 127 - len(self.files))
        return result

    def CARDOpen(self, channel, filename, info):
        name = self.m.cstr(filename)
        result = self._begin("CARDOpen", channel, name)
        return result or self._open(
            channel,
            next((f for f in self.files.values() if f.name == name), None),
            info,
        )

    def CARDFastOpen(self, channel, number, info):
        result = self._begin("CARDFastOpen", channel, signed(number))
        return result or self._open(channel, self.files.get(number), info)

    def CARDClose(self, info):
        return self._begin("CARDClose", self.m.i32(info + 4))

    def _transfer(self, name, info, buffer, length, offset, callback=None):
        channel, number = self.m.u32(info), self.m.u32(info + 4)
        result = self._begin(name, number, offset, length, buffer)
        if result:
            return result
        if not self.mounted:
            return -3
        file = self.files.get(number)
        if file is None:
            return -4
        if offset + length > len(file.data):
            return -128
        assert buffer % 32 == 0 and length % 512 == 0 and offset % 512 == 0, (
            name,
            buffer,
            length,
            offset,
        )

        def action():
            if "Write" in name:
                file.data[offset : offset + length] = self.m.read(buffer, length)
            else:
                self.m.write(buffer, file.data[offset : offset + length])
            self.transferred += length
            return 0

        if callback is None:
            return action()
        return self._async(name, channel, callback, action)

    def CARDRead(self, info, buffer, length, offset):
        return self._transfer("CARDRead", info, buffer, length, offset)

    def CARDWrite(self, info, buffer, length, offset):
        return self._transfer("CARDWrite", info, buffer, length, offset)

    def CARDReadAsync(self, info, buffer, length, offset, callback):
        return self._transfer("CARDReadAsync", info, buffer, length, offset, callback)

    def CARDWriteAsync(self, info, buffer, length, offset, callback):
        return self._transfer("CARDWriteAsync", info, buffer, length, offset, callback)

    def CARDCreateAsync(self, channel, filename, length, info, callback):
        name = self.m.cstr(filename)
        result = self._begin("CARDCreateAsync", channel, name, length)
        if result:
            return result
        if any(f.name == name for f in self.files.values()):
            return -7
        if len(name) > 32:
            return -12
        if length <= 0 or length % 8192:
            return -128
        if len(self.files) >= 127:
            return -8
        if sum(len(f.data) for f in self.files.values()) + length > self.capacity:
            return -9

        def action():
            file = self.add_file(name, bytes(length))
            return self._open(channel, file, info)

        return self._async("CARDCreateAsync", channel, callback, action)

    def CARDGetStatus(self, channel, number, stat):
        result = self._begin("CARDGetStatus", channel, signed(number))
        if result:
            return result
        if number not in self.files:
            return -4
        self.m.write(stat, self.files[number].stat)
        return 0

    def _status(self, name, channel, number, stat, callback=None):
        result = self._begin(name, channel, number)
        if result:
            return result
        if number not in self.files:
            return -4

        def action():
            self.files[number].stat[:] = self.m.read(stat, 0x6C)
            return 0

        return (
            action()
            if callback is None
            else self._async(name, channel, callback, action)
        )

    def CARDSetStatusAsync(self, channel, number, stat, callback):
        return self._status("CARDSetStatusAsync", channel, number, stat, callback)

    def CARDSetStatus(self, channel, number, stat):
        return self._status("CARDSetStatus", channel, number, stat)

    def CARDGetXferredBytes(self, channel):
        return self.transferred

    def CARDFormatAsync(self, channel, callback):
        result = self._begin("CARDFormatAsync", channel)

        def action():
            self.files.clear()
            return 0

        return result or self._async("CARDFormatAsync", channel, callback, action)

    def CARDDeleteAsync(self, channel, filename, callback):
        name = self.m.cstr(filename)
        result = self._begin("CARDDeleteAsync", channel, name)
        file = next((f for f in self.files.values() if f.name == name), None)
        if result or file is None:
            return result or -4

        def action():
            del self.files[file.number]
            return 0

        return self._async("CARDDeleteAsync", channel, callback, action)

    def CARDRenameAsync(self, channel, old, new, callback):
        old, new = self.m.cstr(old), self.m.cstr(new)
        result = self._begin("CARDRenameAsync", channel, old, new)
        file = next((f for f in self.files.values() if f.name == old), None)
        if result or file is None:
            return result or -4
        if any(f.name == new for f in self.files.values()):
            return -7

        def action():
            file.name = new
            file.stat[:32] = new.ljust(32, b"\0")
            return 0

        return self._async("CARDRenameAsync", channel, callback, action)
