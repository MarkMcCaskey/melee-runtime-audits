import pytest


def test_create_and_logical_file_read_roundtrip(lab):
    lab.configure()
    file = lab.create()
    assert file.name == b"test-save"
    assert file.data[:64] == bytes(range(64))
    dst = lab.m.alloc(128, b"\xcc" * 128)
    assert lab.m.call("hsd_803B29D8", lab.state, 1, dst, lab.m.callback_addr) == 0
    lab.drain()
    assert lab.m.callbacks[-1] == (1, 0)
    assert lab.m.read(dst, 128) == lab.m.read(lab.payloads[1], 128)
    assert "hsd_803B2FA0" in lab.m.visited and "hsd_803B31CC" in lab.m.visited


@pytest.mark.parametrize("mode", [0, 1, 2, 3])
@pytest.mark.parametrize("size", [1, 8160, 8161, 16331])
def test_create_write_read_reopen_across_modes_and_sector_boundaries(lab, mode, size):
    lab.configure(sizes=(180, size), flags=(3, mode))
    file = lab.create()
    fresh = bytes((i * 19 + 3) & 255 for i in range(size))
    source = lab.m.alloc(size, fresh)
    assert lab.m.call("hsd_803B2A4C", lab.state, 1, source, lab.m.callback_addr) == 0
    assert lab.m.callbacks == [(0, 0)]
    lab.drain()
    assert lab.m.callbacks[-1] == (1, 0)
    dest = lab.m.alloc(size, b"\xaa" * size)
    assert lab.m.call("hsd_803B29D8", lab.state, 1, dest, lab.m.callback_addr) == 0
    lab.drain()
    assert lab.m.callbacks[-1] == (1, 0)
    assert lab.m.read(dest, size) == fresh
    # File zero shares the final header sector and must survive other writes.
    first = lab.m.alloc(180)
    assert lab.m.call("hsd_803B29D8", lab.state, 0, first, lab.m.callback_addr) == 0
    lab.drain()
    assert lab.m.read(first, 180) == lab.m.read(lab.payloads[0], 180)
    lab.state = lab.m.alloc(0x464)
    lab.m.call("hsd_803B24E4", lab.state, 0, 8192, lab.work)
    assert lab.m.call("hsd_803B2550", lab.state, lab.filename, lab.m.callback_addr) == 0
    lab.drain()
    assert lab.m.callbacks[-1] == (0, 0)
    assert lab.field(0x20) == file.number
    assert lab.field(0x4C + 4) == size
    assert lab.field(0x28 + 4) == mode
    assert lab.m.call("hsd_803B29D8", lab.state, 1, dest, lab.m.callback_addr) == 0
    lab.drain()
    assert lab.m.read(dest, size) == fresh


@pytest.mark.parametrize("mode", [0, 1, 2, 3])
def test_unchanged_write_verifies_and_avoids_card_writes(lab, mode):
    lab.configure(flags=(0, mode))
    lab.create()
    lab.card.events.clear()
    assert (
        lab.m.call("hsd_803B2A4C", lab.state, 1, lab.payloads[1], lab.m.callback_addr)
        == 0
    )
    lab.drain()
    assert lab.m.callbacks[-1] == (1, 1)
    assert any(e[0] == "CARDReadAsync" for e in lab.card.events)
    assert not any(e[0] == "CARDWriteAsync" for e in lab.card.events)


@pytest.mark.parametrize("mode", [1, 2])
def test_mirrored_shared_block_zero_can_report_repair_error_despite_readable_data(
    lab, mode
):
    # A counterexample to "every file_flags combination reopens successfully":
    # shared physical block zero cannot use the ordinary mirror-copy path.
    lab.configure(sizes=(180, 128), flags=(0, mode))
    lab.create()
    source = lab.m.alloc(128, b"Z" * 128)
    lab.m.call("hsd_803B2A4C", lab.state, 1, source, lab.m.callback_addr)
    lab.drain()
    lab.state = lab.m.alloc(0x464)
    lab.m.call("hsd_803B24E4", lab.state, 0, 8192, lab.work)
    lab.m.call("hsd_803B2550", lab.state, lab.filename, lab.m.callback_addr)
    lab.drain()
    assert lab.m.callbacks[-1] == (0, -0x102)
    dest = lab.m.alloc(128)
    lab.m.call("hsd_803B29D8", lab.state, 1, dest, lab.m.callback_addr)
    lab.drain()
    assert lab.m.callbacks[-1] == (1, 0)
    assert lab.m.read(dest, 128) == b"Z" * 128
