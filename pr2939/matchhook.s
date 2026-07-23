
.set STATE, 0x8049fe18
.text
.global match_hook
match_hook:
    lis 12, STATE@h
    ori 12, 12, STATE@l
    lwz 11, 0(12)
    cmplwi 11, 0
    beq init_pending
    sth 11, 0xE(3)
    b tail
init_pending:
    lhz 11, 0xE(3)
    stw 11, 0(12)
tail:
