import pytest


@pytest.mark.parametrize(
    "banner_format,icon_format,icons_count", [(0, 0, 0), (1, 1, 3), (2, 2, 8)]
)
def test_create_read_update_header_and_preserve_shared_block(
    lab, banner_format, icon_format, icons_count
):
    banner_size = {0: 0, 1: 0xE00, 2: 0x1800}[banner_format]
    icons_size = icons_count * {0: 0, 1: 0x400, 2: 0x800}[icon_format] + (
        0x200 if icon_format == 1 else 0
    )
    banner = bytes((i * 3) & 255 for i in range(banner_size))
    icons = bytes((i * 7 + 5) & 255 for i in range(icons_size))
    lab.configure(
        sizes=(180, 128),
        flags=(3, 3),
        banner=banner_format,
        formats=[icon_format] * icons_count,
        speeds=[1] * icons_count,
    )
    file = lab.create(banner=banner, icons=icons)
    assert (
        file.data[: 64 + banner_size + icons_size] == bytes(range(64)) + banner + icons
    )
    comment_out = lab.m.alloc(64)
    banner_out, icons_out = lab.m.alloc(banner_size), lab.m.alloc(icons_size)
    lab.m.call(
        "hsd_803B27F4",
        lab.state,
        comment_out,
        banner_out,
        icons_out,
        lab.m.callback_addr,
    )
    lab.drain()
    assert lab.m.callbacks[-1] == (0, 0)
    assert lab.m.read(comment_out, 64) == bytes(range(64))
    assert lab.m.read(banner_out, banner_size) == banner
    assert lab.m.read(icons_out, icons_size) == icons
    # Unchanged header verifies without writes, then changed comment is saved.
    lab.card.events.clear()
    lab.m.call(
        "hsd_803B2928",
        lab.state,
        lab.comment,
        lab.banner,
        lab.icons,
        lab.m.callback_addr,
    )
    lab.drain()
    assert not any(e[0] == "CARDWriteAsync" for e in lab.card.events)
    new_comment = lab.m.alloc(64, b"N" * 64)
    lab.m.call(
        "hsd_803B2928",
        lab.state,
        new_comment,
        lab.banner,
        lab.icons,
        lab.m.callback_addr,
    )
    lab.drain()
    assert lab.m.callbacks[-1] == (0, 0)
    assert file.data[:64] == b"N" * 64
    dest = lab.m.alloc(180)
    lab.m.call("hsd_803B29D8", lab.state, 0, dest, lab.m.callback_addr)
    lab.drain()
    assert lab.m.read(dest, 180) == lab.m.read(lab.payloads[0], 180)


@pytest.mark.parametrize(
    "null_comment,null_banner,null_icons",
    [
        (True, False, False),
        (False, True, False),
        (False, False, True),
        (True, True, True),
    ],
)
def test_header_output_buffers_are_independently_optional(
    lab, null_comment, null_banner, null_icons
):
    lab.configure(banner=1, formats=[1], speeds=[1])
    lab.create(banner=b"B" * 0xE00, icons=b"I" * 0x600)
    outputs = [lab.m.alloc(64), lab.m.alloc(0xE00), lab.m.alloc(0x600)]
    args = [
        0 if null else ptr
        for null, ptr in zip([null_comment, null_banner, null_icons], outputs)
    ]
    lab.m.call("hsd_803B27F4", lab.state, *args, lab.m.callback_addr)
    lab.drain()
    assert lab.m.callbacks[-1] == (0, 0)
    for ptr, null, expected in zip(
        outputs,
        [null_comment, null_banner, null_icons],
        [bytes(range(64)), b"B" * 0xE00, b"I" * 0x600],
    ):
        assert lab.m.read(ptr, len(expected)) == (
            bytes(len(expected)) if null else expected
        )


def test_corrupt_header_digest_rejected_on_open(lab):
    lab.configure()
    file = lab.create()
    file.data[3] ^= 1
    lab.m.call("hsd_803B2550", lab.state, lab.filename, lab.m.callback_addr)
    lab.drain()
    assert lab.m.callbacks[-1] == (0, -0x107)
