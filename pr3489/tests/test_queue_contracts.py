import pytest

from cardlab.lab import ACTIVE, CMD, REQ


def test_command_descriptor_is_copied_but_payload_pointer_is_borrowed(lab):
    target = lab.m.alloc(16, b"X" * 16)
    assert lab.enqueue("CARD_CMD_CLEAR_BUF", 0, 0, 0, 0, target, 0, 16) == 0
    lab.m.write(lab.command, b"\xcc" * 0x24)
    lab.m.write(target, b"Y" * 16)
    lab.drain()
    assert lab.m.read(target, 16) == bytes(16)
    assert not lab.card.events


def test_command_queue_capacity_and_wrap(lab):
    target = lab.m.alloc(1, b"X")
    for _ in range(128):
        assert lab.enqueue("CARD_CMD_CLEAR_BUF", 0, 0, 0, 0, target, 0, 1) == 0
    assert lab.enqueue("CARD_CMD_CLEAR_BUF", 0, 0, 0, 0, target, 0, 1) == -265
    lab.drain()
    assert lab.m.read(target, 1) == b"\0"
    assert lab.enqueue("CARD_CMD_CLEAR_BUF", 0, 0, 0, 0, target, 0, 1) == 0
    lab.drain()


@pytest.mark.parametrize("builder", ["hsd_803B286C", "hsd_803B2928"])
def test_full_request_queue_still_copies_comment_without_callback(lab, builder):
    for _ in range(32):
        assert lab.m.call("hsd_803B27F4", lab.state, 0, 0, 0, lab.m.callback_addr) == 0
    assert lab.m.call("hsd_803B27F4", lab.state, 0, 0, 0, lab.m.callback_addr) == -265
    comment = lab.m.alloc(64, b"C" * 64)
    args = [lab.state]
    if builder == "hsd_803B286C":
        args.append(lab.m.string("new"))
    args += [comment, 0, 0, lab.m.callback_addr]
    assert lab.m.call(builder, *args) == -265
    assert lab.m.read(lab.state + 0x370, 64) == b"C" * 64
    assert not lab.m.callbacks and not lab.card.events


def test_request_queue_reuses_drained_slots(lab):
    lab.configure()
    lab.create()
    for _ in range(40):
        assert lab.m.call("hsd_803B27F4", lab.state, 0, 0, 0, lab.m.callback_addr) == 0
        lab.drain()
        assert lab.m.callbacks[-1] == (0, 0)
    assert lab.m.u32("hsd_804D7990") == lab.m.u32("hsd_804D7994")


def test_write_empty_logical_file_fails_before_queueing(lab):
    assert lab.m.call("hsd_803B2A4C", lab.state, 1, 0, lab.m.callback_addr) == -257
    assert lab.m.u32("hsd_804D7994") == 0
    assert not lab.m.callbacks and not lab.card.events


@pytest.mark.parametrize("previous,expected", [(0, 1), (1, 1), (2, 0)])
def test_check_verified_controls_following_clear(lab, previous, expected):
    target = lab.m.alloc(4, b"KEEP")
    lab.m.put32("hsd_804D7988", previous)
    lab.enqueue("CARD_CMD_CHECK_VERIFIED")
    lab.enqueue("CARD_CMD_CLEAR_BUF", 0, 0, 0, 0, target, 0, 4)
    # Install a real active completion so result is captured before idle reset.
    active = lab.m.addr("hsd_804D1138")
    for offset, value in [
        (0, ACTIVE["CARD_ACTIVE_READ_FILE"]),
        (4, lab.state),
        (8, lab.m.callback_addr),
        (12, 1),
    ]:
        lab.m.put32(active + offset, value)
    lab.drain()
    assert lab.m.callbacks == [(1, expected)]
    assert lab.m.read(target, 4) == (bytes(4) if previous == 2 else b"KEEP")


def test_unknown_command_stalls_without_an_invented_operation(lab):
    lab.enqueue("CARD_CMD_UNK_0x03")
    lab.pump()
    assert lab.m.u32("hsd_804D7980") == 0
    assert lab.ring()[0][0] == CMD["CARD_CMD_UNK_0x03"]
    assert not lab.card.events and not lab.m.callbacks


def test_request_queue_reset_marks_every_slot_empty(lab):
    for _ in range(32):
        lab.m.call("hsd_803B27F4", lab.state, 0, 0, 0, lab.m.callback_addr)
    lab.m.call("hsd_803B2374")
    assert all(
        lab.m.u32(lab.m.addr("hsd_804D2348") + i * 0x18) == REQ["CARD_REQ_NONE"]
        for i in range(32)
    )
    assert lab.m.u32("hsd_804D7990") == lab.m.u32("hsd_804D7994") == 0
