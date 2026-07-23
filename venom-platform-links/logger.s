.text
.global hook
hook:
    lis 11, 0x8049
    ori 11, 11, 0xFA50
    lis 0, 0x5650
    ori 0, 0, 0x4C54
    stw 0, 0x00(11)
    stw 3, 0x04(11)
    lwz 12, 0x2C(3)
    cmplwi 12, 0
    beq done
    stw 12, 0x08(11)
    lwz 0, 0xC4(12)
    stw 0, 0x0C(11)
    lwz 10, 0xC8(12)
    stw 10, 0x10(11)
    lwz 9, 0xCC(12)
    stw 9, 0x14(11)
    lwz 8, 0xD0(12)
    stw 8, 0x18(11)

    lwz 7, 0x1C(11)
    addi 7, 7, 1
    stw 7, 0x1C(11)
    lwz 7, 0x20(11)
    cmpw 10, 7
    ble no_new_max
    stw 10, 0x20(11)
no_new_max:
    lwz 7, 0x24(11)
    cmpwi 10, -1
    bne not_minus_one
    ori 7, 7, 0x01
not_minus_one:
    cmpwi 10, 1
    bne not_one
    ori 7, 7, 0x02
not_one:
    cmpwi 10, 59
    bne not_fifty_nine
    ori 7, 7, 0x04
not_fifty_nine:
    cmpwi 10, 60
    bne not_sixty
    ori 7, 7, 0x08
not_sixty:
    cmpwi 10, 61
    blt not_after_sixty
    ori 7, 7, 0x10
not_after_sixty:
    stw 7, 0x24(11)

    lis 7, 0x8049
    ori 7, 7, 0xE848
    lwz 6, 0x00(7)
    stw 6, 0x38(11)
    lwz 6, 0x04(7)
    cmplwi 6, 0
    beq no_dialogue
    lwz 5, 0x28(11)
    cmplwi 5, 0
    bne no_dialogue
    stw 6, 0x28(11)
    stw 10, 0x2C(11)
no_dialogue:
    cmplwi 9, 0
    beq no_upper
    lwz 6, 0x60(9)
    stw 6, 0x30(11)
no_upper:
    cmplwi 8, 0
    beq done
    lwz 6, 0x60(8)
    stw 6, 0x34(11)
done:
    lis 7, 0x804D
    ori 7, 7, 0x49E8
    lwz 6, 0(7)
    stw 6, 0x3C(11)
    lis 7, 0x8049
    ori 7, 7, 0xE750
    lwz 6, 0(7)
    stw 6, 0x40(11)
    li 4, 0
    lwz 6, 0x0C(11)
    cmplwi 6, 0
    beq no_translation_match
    lwz 6, 0x28(6)
    stw 6, 0x44(11)
    lwz 5, 0x28(3)
    stw 5, 0x48(11)
    cmplwi 6, 0
    beq no_translation_match
    cmplwi 5, 0
    beq no_translation_match
    lwz 7, 0x38(6)
    lwz 0, 0x38(5)
    cmpw 7, 0
    bne no_translation_match
    lwz 7, 0x3C(6)
    lwz 0, 0x3C(5)
    cmpw 7, 0
    bne no_translation_match
    lwz 7, 0x40(6)
    lwz 0, 0x40(5)
    cmpw 7, 0
    bne no_translation_match
    li 4, 1
no_translation_match:
    stw 4, 0x4C(11)
    nop
    mflr 0
