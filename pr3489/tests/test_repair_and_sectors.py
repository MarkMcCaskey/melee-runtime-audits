import pytest

from cardlab.lab import ACTIVE, CMD


def reopen(lab):
    lab.state = lab.m.alloc(0x464)
    lab.m.call("hsd_803B24E4", lab.state, 0, 8192, lab.work)
    assert lab.m.call("hsd_803B2550", lab.state, lab.filename, lab.m.callback_addr) == 0
    lab.drain()


def test_scan_and_repair_rebuild_a_corrupted_mirror_from_valid_copy(lab):
    lab.configure(flags=(3, 0))
    file = lab.create()
    valid = bytes(file.data[2 * 8192 : 3 * 8192])
    file.data[8192 + 25] ^= 1
    lab.card.events.clear()
    reopen(lab)
    assert lab.m.callbacks[-1] == (0, 0)
    assert bytes(file.data[8192 : 2 * 8192]) == valid
    assert lab.field(0x170 + 4) == lab.field(0x170 + 8) == 1
    assert {
        CMD[n]
        for n in [
            "CARD_CMD_SCAN_FILE",
            "CARD_CMD_SCAN_BLOCK",
            "CARD_CMD_REPAIR",
            "CARD_CMD_READ_SECTOR",
            "CARD_CMD_WRITE_SECTOR",
        ]
    } <= lab.executed_commands
    assert any(e[0] == "CARDWriteAsync" for e in lab.card.events)
    assert not any(e[0] == "CARDMountAsync" for e in lab.card.events)


def test_repair_replaces_stale_mirror_sequence_and_payload(lab):
    lab.configure(flags=(3, 0))
    file = lab.create()
    sector = lab.m.alloc(8192, bytes(file.data[2 * 8192 : 3 * 8192]))
    assert lab.m.call("hsd_803B31CC", sector, 8192) == 0
    lab.m.write(sector + 0x12, b"\x01")
    lab.m.write(sector + 0x20, b"Z" * 128)
    lab.m.call("hsd_803B2FA0", sector, 8192)
    file.data[2 * 8192 : 3 * 8192] = lab.m.read(sector, 8192)
    reopen(lab)
    assert lab.m.callbacks[-1] == (0, 0)
    assert file.data[8192 : 2 * 8192] == file.data[2 * 8192 : 3 * 8192]
    assert lab.field(0x270 + 4) == lab.field(0x270 + 8) == 1
    dest = lab.m.alloc(128)
    lab.m.call("hsd_803B29D8", lab.state, 1, dest, lab.m.callback_addr)
    lab.drain()
    assert lab.m.read(dest, 128) == b"Z" * 128


def test_repair_clears_a_surplus_mirror_but_preserves_other_logical_file(lab):
    lab.configure(sizes=(0, 128, 128), flags=(3, 0, 1))
    file = lab.create()
    file.data[4 * 8192 : 5 * 8192] = file.data[8192 : 2 * 8192]
    reopen(lab)
    assert lab.m.callbacks[-1] == (0, 0)
    ids = [lab.field(0x170 + i * 4) for i in range(1, 5)]
    assert ids.count(1) == 2 and ids.count(2) == 1 and ids.count(-0x7FFF) == 1
    dest = lab.m.alloc(128)
    lab.m.call("hsd_803B29D8", lab.state, 2, dest, lab.m.callback_addr)
    lab.drain()
    assert lab.m.read(dest, 128) == lab.m.read(lab.payloads[2], 128)


@pytest.mark.parametrize(
    "metadata_retained,expected", [(False, -0x101), (True, -0x103)]
)
def test_missing_all_mirrors_reports_metadata_or_missing_data_error(
    lab, metadata_retained, expected
):
    lab.configure(sizes=(180 if metadata_retained else 0, 128), flags=(3, 0))
    file = lab.create()
    file.data[8192 + 25] ^= 1
    file.data[2 * 8192 + 25] ^= 1
    reopen(lab)
    assert lab.m.callbacks[-1] == (0, expected)


def test_read_sector_decodes_and_write_sector_reencodes_the_work_buffer(lab):
    lab.configure(flags=(3, 0))
    file = lab.create()
    expected = bytes(file.data[8192 : 2 * 8192])
    lab.enqueue("CARD_CMD_READ_SECTOR", 0, 1, 0, 0, 0, 8192)
    lab.drain()
    assert lab.m.read(lab.work + 0x20, 128) == lab.m.read(lab.payloads[1], 128)
    assert lab.m.read(lab.work, 8192) != expected
    lab.enqueue("CARD_CMD_WRITE_SECTOR", 0, 2, 1, 7, 0, 2 * 8192)
    lab.drain()
    assert bytes(file.data[2 * 8192 : 3 * 8192]) == expected
    assert lab.field(0x170 + 8) == 1 and lab.field(0x270 + 8) == 7
    # The tag's id/seq fields update bookkeeping; the buffer's encoded header
    # is preserved. This is different from WRITE_BLOCK, which constructs it.
    assert lab.m.read(lab.work, 8192) == expected


def test_corrupt_read_sector_reports_checksum_error(lab):
    lab.configure()
    file = lab.create()
    file.data[8192 + 25] ^= 1
    lab.enqueue("CARD_CMD_READ_SECTOR", 0, 1, 0, 0, 0, 8192)
    active = lab.m.addr("hsd_804D1138")
    for offset, value in [
        (0, ACTIVE["CARD_ACTIVE_READ_FILE"]),
        (4, lab.state),
        (8, lab.m.callback_addr),
        (12, 1),
    ]:
        lab.m.put32(active + offset, value)
    lab.drain()
    assert lab.m.callbacks[-1] == (1, -0x105)
