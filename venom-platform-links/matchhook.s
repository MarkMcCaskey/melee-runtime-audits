.text
.global hook
hook:
    li 11, 0xE4
    sth 11, 0xE(3)
    nop
    mflr 0
