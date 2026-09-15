import pytest


@pytest.mark.parametrize("busy_count", [1, 9])
def test_busy_open_is_retried_up_to_ten_attempts(lab, busy_count):
    lab.configure()
    lab.create()
    lab.card.events.clear()
    lab.card.fail("CARDFastOpen", *([-1] * busy_count))
    dest = lab.m.alloc(128)
    lab.m.call("hsd_803B29D8", lab.state, 1, dest, lab.m.callback_addr)
    lab.drain()
    opens = [e for e in lab.card.events if e[0] == "CARDFastOpen"]
    assert len(opens) == busy_count + 1
    assert lab.m.callbacks[-1] == (1, 0)


def test_tenth_busy_result_is_reported_and_remaining_commands_are_cancelled(lab):
    lab.configure()
    lab.create()
    lab.card.events.clear()
    lab.card.fail("CARDFastOpen", *([-1] * 10))
    dest = lab.m.alloc(128, b"X" * 128)
    lab.m.call("hsd_803B29D8", lab.state, 1, dest, lab.m.callback_addr)
    lab.drain()
    assert len([e for e in lab.card.events if e[0] == "CARDFastOpen"]) == 10
    assert lab.m.callbacks[-1] == (1, -1)
    assert lab.m.read(dest, 128) == b"X" * 128
    assert not lab.ring()


@pytest.mark.parametrize(
    "api,completion",
    [("CARDFastOpen", False), ("CARDReadAsync", False), ("CARDReadAsync", True)],
)
def test_read_errors_propagate_without_modifying_destination(lab, api, completion):
    lab.configure()
    lab.create()
    lab.card.fail(api, -5, completion=completion)
    dest = lab.m.alloc(128, b"X" * 128)
    lab.m.call("hsd_803B29D8", lab.state, 1, dest, lab.m.callback_addr)
    lab.drain()
    assert lab.m.callbacks[-1] == (1, -5)
    assert lab.m.read(dest, 128) == b"X" * 128
    assert not lab.ring() and not lab.card.pending


def test_read_callback_is_deferred_and_blocked_while_interrupts_disabled(lab):
    lab.configure()
    lab.create()
    dest = lab.m.alloc(128, b"X" * 128)
    before = list(lab.m.callbacks)
    lab.m.call("hsd_803B29D8", lab.state, 1, dest, lab.m.callback_addr)
    assert lab.m.callbacks == before and not lab.card.pending
    lab.pump()
    assert lab.m.u32("hsd_804D799C") == 1
    assert lab.card.pending and lab.m.callbacks == before
    assert lab.m.read(dest, 128) == b"X" * 128
    lab.m.interrupts = False
    with pytest.raises(AssertionError, match="interrupt restoration"):
        lab.card.complete()
    lab.m.interrupts = True
    lab.card.complete()
    assert lab.m.read(dest, 128) == lab.m.read(lab.payloads[1], 128)
    assert lab.m.callbacks == before  # HSD request completion needs the pump.
    lab.pump()
    assert lab.m.callbacks[-1] == (1, 0)


def test_card_removal_before_io_is_reported(lab):
    lab.configure()
    lab.create()
    lab.card.present = False
    dest = lab.m.alloc(128)
    lab.m.call("hsd_803B29D8", lab.state, 1, dest, lab.m.callback_addr)
    lab.drain()
    assert lab.m.callbacks[-1] == (1, -3)


def test_card_capacity_failure_is_not_reported_as_successful_creation(lab):
    lab.configure()
    lab.card.capacity = 8192
    comment = lab.m.alloc(64)
    assert (
        lab.m.call(
            "hsd_803B286C",
            lab.state,
            lab.m.string("full"),
            comment,
            0,
            0,
            lab.m.callback_addr,
        )
        == 0
    )
    lab.drain()
    assert lab.m.callbacks == [(0, -9)]
    assert not lab.card.files


def test_write_completion_failure_does_not_commit_new_payload(lab):
    lab.configure(flags=(0, 3))
    file = lab.create()
    original = bytes(file.data)
    lab.card.fail("CARDWriteAsync", -5, completion=True)
    payload = lab.m.alloc(128, b"W" * 128)
    lab.m.call("hsd_803B2A4C", lab.state, 1, payload, lab.m.callback_addr)
    lab.drain()
    assert lab.m.callbacks[-1] == (1, -5)
    assert bytes(file.data) == original


def test_inline_card_callback_is_ignored_and_leaves_request_waiting(lab):
    lab.configure()
    lab.create()
    dest = lab.m.alloc(128, b"X" * 128)
    before = list(lab.m.callbacks)
    lab.card.inline_callbacks = True
    lab.m.call("hsd_803B29D8", lab.state, 1, dest, lab.m.callback_addr)
    lab.pump()
    # The real callback ran, but saw mode != 1 and returned immediately.
    assert lab.m.u32("hsd_804D799C") == 1
    assert not lab.card.pending
    assert lab.ring() and lab.m.callbacks == before
    assert lab.m.read(dest, 128) == b"X" * 128
    lab.pump()
    assert lab.m.u32("hsd_804D799C") == 1 and lab.m.callbacks == before
