"""Small GDB remote client for Dolphin; no game or CARD semantics live here."""

import select
import socket
import time


class Remote:
    def __init__(self, port, timeout=20):
        deadline = time.monotonic() + timeout
        while True:
            try:
                self.sock = socket.create_connection(("127.0.0.1", port), timeout=1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.buffer = bytearray()
        self.command("qSupported:")

    def close(self):
        self.sock.close()

    def send(self, message):
        payload = message.encode()
        self.sock.sendall(b"$" + payload + b"#" + f"{sum(payload) & 255:02x}".encode())

    def byte(self, deadline):
        if not self.buffer:
            if not select.select(
                [self.sock], [], [], max(0, deadline - time.monotonic())
            )[0]:
                raise TimeoutError("Dolphin GDB response timed out")
            self.buffer.extend(self.sock.recv(4096))
            if not self.buffer:
                raise EOFError("Dolphin GDB connection closed")
        result = self.buffer[0]
        del self.buffer[0]
        return result

    def receive(self, timeout=30):
        deadline = time.monotonic() + timeout
        while self.byte(deadline) != ord("$"):
            pass
        payload = bytearray()
        while (char := self.byte(deadline)) != ord("#"):
            payload.append(char)
        checksum = bytes([self.byte(deadline), self.byte(deadline)])
        if sum(payload) & 255 != int(checksum, 16):
            raise RuntimeError("GDB packet checksum mismatch")
        self.sock.sendall(b"+")
        return bytes(payload)

    def command(self, message):
        self.send(message)
        while True:
            reply = self.receive()
            if reply and reply[:1] not in (b"T", b"S"):
                return reply

    def ok(self, message):
        reply = self.command(message)
        if reply != b"OK":
            raise RuntimeError(f"{message}: {reply!r}")

    def read(self, address, length):
        result = bytearray()
        for offset in range(0, length, 256):
            size = min(256, length - offset)
            # GDB checks effective addresses using the current MSR. Exception
            # entry briefly disables translation, so a valid cached RAM address
            # can return E00 while the guest is running. Retry after it advances.
            for attempt in range(100):
                reply = self.command(f"m{address + offset:x},{size:x}")
                if reply != b"E00":
                    break
                time.sleep(0.01)
            if len(reply) == 3 and reply.startswith(b"E"):
                raise RuntimeError(f"Debugger memory read: {reply!r}")
            chunk = bytes.fromhex(reply.decode())
            if len(chunk) != size:
                raise RuntimeError("Short debugger memory read")
            result.extend(chunk)
        return bytes(result)

    def write(self, address, data):
        for offset in range(0, len(data), 256):
            chunk = data[offset : offset + 256]
            for attempt in range(100):
                reply = self.command(
                    f"M{address + offset:x},{len(chunk):x}:{chunk.hex()}"
                )
                if reply != b"E00":
                    break
                time.sleep(0.01)
            if reply != b"OK":
                raise RuntimeError(f"Debugger memory write: {reply!r}")

    def u32(self, address):
        return int.from_bytes(self.read(address, 4), "big")
