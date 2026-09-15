import pytest

from cardlab.lab import TASK


@pytest.mark.parametrize(
    "name,handler,event",
    [
        ("CARD_TASK_MOUNT_CARD", "lb_8001A184", "CARDMountAsync"),
        ("CARD_TASK_CHECK_CARD", "lb_8001A3A4", "CARDCheckAsync"),
        ("CARD_TASK_FORMAT_CARD", "lb_8001A8A4", "CARDFormatAsync"),
        ("CARD_TASK_DELETE_FILE", "lb_8001A9CC", "CARDDeleteAsync"),
        ("CARD_TASK_RENAME_FILE", "lb_8001AAE4", "CARDRenameAsync"),
    ],
)
def test_card_task_dispatch_runs_real_handler_and_card_operation(
    lab, name, handler, event
):
    lab.bind_lb()
    old = lab.card.add_file("old", b"old contents".ljust(8192, b"\0"))
    assert lab.run_task(name) == 11
    assert lab.m.visited[handler] == 1
    assert any(e[0] == event for e in lab.card.events)
    assert lab.m.u32(lab.lb + 0x510) == TASK["CARD_TASK_NONE"]
    assert not lab.m.lb_callbacks
    assert old.number in lab.card.files  # Async mutation has not completed.
    assert lab.drain_lb() == 0
    assert lab.m.lb_callbacks == [0]
    if name in ["CARD_TASK_FORMAT_CARD", "CARD_TASK_DELETE_FILE"]:
        assert not lab.card.files
    elif name == "CARD_TASK_RENAME_FILE":
        assert old.name == b"new" and bytes(old.data).startswith(b"old contents")


@pytest.mark.parametrize(
    "stored,expected",
    [(0, 1), (1, 1), (2, 1), (3, 3), (4, 4), (7, 7), (10, 10), (13, 13)],
)
def test_unknown_task_03_only_normalizes_observed_result_values(lab, stored, expected):
    lab.bind_lb()
    lab.m.put32(lab.lb + 0x34, stored)
    assert lab.run_task("CARD_TASK_UNK_0x03") == expected
    assert lab.m.visited["lb_8001A860"] == 1
    assert lab.m.i32(lab.lb + 0x34) == expected
    assert [e[0] for e in lab.card.events] == ["CARDUnmount"]


def test_result_mask_rejects_task_and_clears_remaining_slots(lab):
    lab.bind_lb()
    lab.m.put32(lab.lb + 0x510 + 0x54, TASK["CARD_TASK_FORMAT_CARD"])
    assert lab.run_task("CARD_TASK_DELETE_FILE", result=4, mask=1 << 1) == 4
    assert all(
        lab.m.u32(lab.lb + 0x510 + 0x54 * i) == TASK["CARD_TASK_NONE"]
        for i in range(11)
    )
    assert not any(
        e[0] in ["CARDDeleteAsync", "CARDFormatAsync"] for e in lab.card.events
    )
    assert lab.m.lb_callbacks == [4]


def test_unused_slots_do_not_dispatch_mount_even_though_mount_is_zero(lab):
    lab.bind_lb()
    assert lab.m.call("lb_80019CB0", 16) == 16
    assert not lab.m.visited["lb_8001A184"]


@pytest.mark.parametrize("filename,expected", [("needle", 0), ("missing", 13)])
def test_find_file_matches_filename_company_and_game(lab, filename, expected):
    lab.bind_lb()
    lab.m.write(lab.lb + 0x2C, b"01")
    lab.m.write(lab.lb + 0x2F, b"GALE")
    lab.card.add_file("needle", bytes(8192), number=37)
    lab.card.add_file("needle", bytes(8192), number=1, company=b"XX")
    assert lab.run_task("CARD_TASK_FIND_FILE", filename=filename) == expected
    assert lab.m.visited["lb_8001B614"] == 1
    assert not lab.card.pending
    assert not any("Read" in e[0] for e in lab.card.events)


def test_list_snapshots_filters_and_sorts_numeric_filenames(lab):
    lab.bind_lb()
    lab.m.put32(lab.lb + 0x8C, 8192 * 20)
    lab.m.put32(lab.lb + 0x90, 120)
    entries = lab.m.alloc(127 * 8, label="snapshot entries")
    free_blocks, free_files = lab.m.alloc(4), lab.m.alloc(4)
    lab.m.put32(lab.lb + 0x20, entries)
    lab.m.put32(lab.lb + 0x24, free_blocks)
    lab.m.put32(lab.lb + 0x28, free_files)
    for number, name, company in [
        (3, "100", b"01"),
        (6, "300", b"01"),
        (1, "200-extra", b"01"),
        (2, "not-snapshot", b"01"),
        (8, "400", b"XX"),
    ]:
        lab.card.add_file(name, bytes(8192 * 2), number=number, company=company)
    assert lab.run_task("CARD_TASK_LIST_SNAPSHOTS") == 0
    assert lab.m.visited["lb_8001B14C"] == 1
    assert [lab.m.u32(entries + i * 8) for i in range(3)] == [300, 200, 100]
    assert [
        int.from_bytes(lab.m.read(entries + i * 8 + 4, 2), "big", signed=True)
        for i in range(4)
    ] == [6, 1, 3, -1]
    assert lab.m.u32(free_blocks) == 20 and lab.m.u32(free_files) == 120


@pytest.mark.parametrize(
    "name,handler",
    [
        ("CARD_TASK_OPEN_FILE", "lb_8001A594"),
        ("CARD_TASK_READ_FILES", "lb_8001ACEC"),
        ("CARD_TASK_WRITE_FILES", "lb_8001AE38"),
        ("CARD_TASK_SET_STATUS", "lb_8001AF84"),
        ("CARD_TASK_READ_HEADER", "lb_8001B068"),
    ],
)
def test_save_tasks_execute_through_hsd_and_card(lab, name, handler):
    lab.configure()
    file = lab.create(name="old")
    lab.bind_lb()
    lab.m.callbacks.clear()
    entries = lab.m.alloc(9 * 12, label="CardEntry array")
    data = lab.m.alloc(128, b"R" * 128, label="task file buffer")
    lab.m.put32(entries + 12 + 8, data)
    comment = lab.m.alloc(64, b"H" * 64)
    lab.m.put32(lab.lb + 0x14, comment)
    lab.m.put32(lab.lb + 0x18, lab.banner)
    lab.m.put32(lab.lb + 0x1C, lab.icons)
    assert lab.run_task(name, entries=entries) == 11
    assert lab.m.visited[handler] == 1
    assert lab.drain_lb() == 0
    if name == "CARD_TASK_READ_FILES":
        assert lab.m.read(data, 128) == lab.m.read(lab.payloads[1], 128)
    elif name == "CARD_TASK_READ_HEADER":
        assert lab.m.read(comment, 64) == bytes(range(64))
    elif name == "CARD_TASK_SET_STATUS":
        assert file.data[:64] == b"H" * 64
    elif name == "CARD_TASK_WRITE_FILES":
        lab.card.mounted = True
        dest = lab.m.alloc(128)
        lab.m.call("hsd_803B29D8", lab.state, 1, dest, lab.m.callback_addr)
        lab.drain()
        assert lab.m.read(dest, 128) == b"R" * 128


def test_create_task_creates_file_using_stored_filename_and_header(lab):
    lab.configure()
    lab.bind_lb()
    comment = lab.m.alloc(64, b"C" * 64)
    lab.m.put32(lab.lb + 0x14, comment)
    assert lab.run_task("CARD_TASK_CREATE_FILE", filename="created") == 11
    assert lab.m.visited["lb_8001AC04"] == 1
    assert lab.drain_lb() == 0
    file = next(iter(lab.card.files.values()))
    assert file.name == b"created" and file.data[:64] == b"C" * 64
