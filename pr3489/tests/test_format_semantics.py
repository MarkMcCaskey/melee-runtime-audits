import pytest

SEED = bytes.fromhex("0123456789abcdeffedcba9876543210")


def independent_digest(data):
    out = list(SEED)
    for i, value in enumerate(data):
        out[i % 16] = (out[i % 16] + value) & 255
    for i in range(1, 16):
        if out[i - 1] == out[i]:
            out[i] ^= 255
    return bytes(out)


@pytest.mark.parametrize("length", [0, 1, 15, 16, 17, 8192])
def test_digest_matches_independent_byte_reference(lab, length):
    data = bytes((i * 13 + 5) & 255 for i in range(length))
    src = lab.m.alloc(length, data)
    dest = lab.m.alloc(16)
    lab.m.call("hsd_803B2B20", src, length, dest)
    assert lab.m.read(dest, 16) == independent_digest(data)


@pytest.mark.parametrize("length", [32, 128, 8192])
def test_sector_codec_roundtrip_and_corruption_detection(lab, length):
    original = bytes((i * 7) & 255 for i in range(length))
    pointer = lab.m.alloc(length, original)
    assert lab.m.call("hsd_803B2FA0", pointer, length) == 0
    encoded = lab.m.read(pointer, length)
    assert encoded[:16] == independent_digest(original[16:])
    assert encoded[16:] != original[16:]
    assert lab.m.call("hsd_803B31CC", pointer, length) == 0
    assert lab.m.read(pointer + 16, length - 16) == original[16:]
    damaged = bytearray(encoded)
    damaged[-1] ^= 1
    lab.m.write(pointer, damaged)
    assert lab.m.call("hsd_803B31CC", pointer, length) == -1


@pytest.mark.parametrize(
    "a,b,sign",
    [
        (0, 255, 1),
        (255, 0, -1),
        (1, 2, -1),
        (2, 1, 1),
        (42, 42, 0),
        (-1, 3, -1),
        (3, -1, 1),
        (5, 200, 1),
        (200, 5, -1),
    ],
)
def test_sequence_order_including_wrap(lab, a, b, sign):
    result = lab.m.call("fn_803ACB74", a, b)
    assert (result > 0) - (result < 0) == sign


@pytest.mark.parametrize(
    "banner,formats,speeds,expected",
    [
        (0, [], [], 64),
        (1, [], [], 64 + 0xE00),
        (2, [], [], 64 + 0x1800),
        (0, [1], [1], 64 + 0x400 + 0x200),
        (0, [1, 1], [1, 2], 64 + 2 * 0x400 + 0x200),
        (0, [2, 2], [1, 1], 64 + 2 * 0x800),
        (2, [2] * 8, [1] * 8, 64 + 0x1800 + 8 * 0x800),
        (0, [2, 2], [0, 1], 64),
    ],
)
def test_header_size_banner_icons_shared_palette_and_zero_speed_terminator(
    lab, banner, formats, speeds, expected
):
    lab.configure(banner=banner, formats=formats, speeds=speeds)
    assert lab.field(0x24) == expected


def test_file_table_pack_and_unpack(lab):
    sizes = [0x12345, 0x23456, 0x34567]
    flags = [0, 2, 3]
    for i in range(3):
        lab.m.call("hsd_803AC3E0", lab.state, i, sizes[i], flags[i], 0)
    table = lab.m.alloc(12)
    lab.m.call("fn_803AC3F8", lab.state, table, 0)
    expected = b"".join(
        bytes(
            [
                i,
                (flags[i] << 6) | ((sizes[i] >> 16) & 0x3F),
                (sizes[i] >> 8) & 255,
                sizes[i] & 255,
            ]
        )
        for i in range(3)
    )
    assert lab.m.read(table, 12) == expected
    target = lab.m.alloc(0x464)
    lab.m.call("hsd_803AC558", target, table)
    for i in range(3):
        assert lab.m.u32(target + 0x28 + 4 * i) == flags[i]
        assert lab.m.u32(target + 0x4C + 4 * i) == sizes[i]


@pytest.mark.parametrize("change", ["none", "id", "sequence", "payload"])
def test_block_verifier_checks_id_sequence_and_payload(lab, change):
    lab.configure()
    lab.create()
    expected = lab.m.alloc(128, lab.m.read(lab.payloads[1], 128))
    if change == "payload":
        lab.m.write(expected, b"changed")
    result = lab.m.call(
        "fn_803ACC0C",
        lab.state,
        1,
        2 if change == "id" else 1,
        1 if change == "sequence" else 0,
        expected,
        128,
    )
    assert result == (0 if change == "none" else 1)


def test_zero_length_verification_returns_without_card_io(lab):
    assert lab.m.call("fn_803ACC0C", lab.state, 1, 1, 0, 0, 0) == 0
    assert not lab.card.events
