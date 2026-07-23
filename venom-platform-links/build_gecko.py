#!/usr/bin/env python3
"""Rebuild audit.gecko.ini from the reviewable PowerPC assembly sources."""

import argparse
import struct
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def assemble(source, binutils):
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        obj = temp / "hook.o"
        binary = temp / "hook.bin"
        subprocess.run(
            [binutils / "powerpc-eabi-as", "-mgekko", "-o", obj, source],
            check=True,
        )
        subprocess.run(
            [
                binutils / "powerpc-eabi-objcopy",
                "-O",
                "binary",
                "--only-section=.text",
                obj,
                binary,
            ],
            check=True,
        )
        return binary.read_bytes()


def c2(address, code):
    words = [
        code[offset:offset + 4]
        for offset in range(0, len(code), 4)
    ]
    if len(words) % 2 == 0:
        words.append(struct.pack(">I", 0x60000000))
    words.append(b"\0\0\0\0")
    result = [f"C2{address & 0x01FFFFFF:06X} {len(words) // 2:08X}"]
    for i in range(0, len(words), 2):
        result.append(
            f"{words[i].hex().upper()} {words[i + 1].hex().upper()}"
        )
    return result


def write8(address, value):
    return f"00{address & 0x01FFFFFF:06X} 000000{value:02X}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--melee",
        type=Path,
        default=Path.home() / "etc/melee",
        help="doldecomp/melee checkout containing build/binutils",
    )
    parser.add_argument(
        "--output", type=Path, default=HERE / "audit.gecko.ini"
    )
    args = parser.parse_args()
    binutils = args.melee / "build/binutils"

    driver = assemble(HERE / "driver.s", binutils)
    match = assemble(HERE / "matchhook.s", binutils)
    logger = assemble(HERE / "logger.s", binutils)

    lines = [
        "[Gecko]",
        "+$Venom platform field runtime audit [doldecomp audit]",
        *c2(0x80302608, driver),
        "0401CE78 3860002D",
        "0401CE7C 4E800020",
        "C21A42E8 00000002",
        "38600002 3C808048",
        "60000000 00000000",
        "C21A42F8 00000002",
        "38600002 3C808048",
        "60000000 00000000",
        "C21A42A0 00000002",
        "38600002 3C808048",
        "60000000 00000000",
        *c2(0x8016E730, match),
    ]

    for base in (0x8045AC58, 0x80480530):
        for player in range(6):
            p = base + 0x60 + player * 0x24
            if player < 2:
                for offset, value in (
                    (0, player),
                    (1, 1),
                    (2, 4),
                    (4, player),
                    (0xF, 1),
                ):
                    lines.append(write8(p + offset, value))
            else:
                lines.append(write8(p + 1, 3))

    lines.extend(c2(0x80204284, logger))
    args.output.write_text("\n".join(lines) + "\n")
    print(args.output)


if __name__ == "__main__":
    main()
