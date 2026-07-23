
.set STATE, 0x8049fe18
.text
.global match_hook
match_hook:
    lis 12, STATE@h
    ori 12, 12, STATE@l
    lwz 11, 0(12)
    cmplwi 11, 0
    bne have_pending
    li 11, 2
    stw 11, 0(12)
have_pending:
    sth 11, 0xE(3)
