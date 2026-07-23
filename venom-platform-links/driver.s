.text
.global hook
hook:
    lis 11, 0x804D
    ori 11, 11, 0x49E8
    lwz 12, 0(11)
    cmplwi 12, 0xE4
    beq done
    li 12, 3
    lis 11, 0x8047
    ori 11, 11, 0x9D35
    stb 12, 0(11)
    li 12, 1
    lis 11, 0x8047
    ori 11, 11, 0x9D64
    stw 12, 0(11)
done:
    nop
    mflr 0
