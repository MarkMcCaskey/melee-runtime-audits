from cardlab.machine import Machine


def test_powerpc_executes_decomp_initializers_and_real_checksum():
    m = Machine()
    assert m.call("lb_80019BB8", -4) == 4
    m.call("hsd_803B2374")
    assert m.i32("hsd_804D799C") == 2
    state = m.alloc(0x464)
    work = m.alloc(8192)
    m.call("hsd_803B24E4", state, 1, 8192, work)
    assert m.u32(state) == work
    assert m.u32(state + 4) == 1
    assert m.i32(state + 0x20) == -1
    src = m.alloc(32, bytes(range(32)))
    dst = m.alloc(16)
    m.call("hsd_803B2B20", src, 32, dst)
    assert m.read(dst, 16) == bytes(
        (v + i + i + 16) & 255
        for i, v in enumerate(bytes.fromhex("0123456789abcdeffedcba9876543210"))
    )
    m.check_canaries()
