# Focused Dolphin enum audit

**29 scenarios passed, covering all 48 values**: 18 commands, 7 requests, 8 active states, and 15 tasks. Forty-six values were observed at real dispatch/state probes; the two non-dispatched empty sentinels have explicit state tests.

This runs the original matching Melee code and its CARD/EXI SDK code in Dolphin, using a small compiled C driver. `card.py` and Unicorn are not involved. The card and Dolphin user directory are disposable. See [how to run](README.md#focused-enum-sweep) and [machine-readable evidence](../reports/enum-evidence.json).

## What the result supports

The named operations have focused runtime evidence: requested bytes survive create/read/write/reopen; verified unchanged data causes no SDK writes; damaged mirrored sectors are repaired; rename/delete/format change real card contents; snapshot listing uses the real allocator and sorts numeric filename prefixes. Passing a scenario is not proof of every branch or of the original source name. Several tags participate in one end-to-end scenario, so the table distinguishes an observed tag from that scenario’s asserted effects.

Both unknown tags remain **UNK**. Command `0x03` stayed at the queue head through two pumps with no SDK calls. Task `0x03` changed stored results 0 and 2 to 1, and left 4 unchanged. Those observations do not identify their intended purpose.

## Per-value coverage

Scenario numbers below refer to the assertion list at the end. Counts are dispatches for commands, requests, and tasks; active-state counts are samples at the pump and wrapper callback. They are not I/O counts or performance measurements.

### Command

| Value | Name | Observed count | Passing scenarios |
| --- | --- | ---: | --- |
| `0x00` | `CARD_CMD_NONE` | 1,970,505 | 1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 23, 29 |
| `0x01` | `CARD_CMD_WRITE_BLOCK` | 30 | 1, 2, 3, 4, 16, 19 |
| `0x02` | `CARD_CMD_READ_BLOCK` | 35 | 1, 2, 3, 4, 15, 16, 17, 19 |
| `0x03` | `CARD_CMD_UNK_0x03` | 2 | 10 |
| `0x04` | `CARD_CMD_CLEAR_BUF` | 9 | 1, 2, 3, 4, 7, 8, 9, 19 |
| `0x05` | `CARD_CMD_VERIFY_BLOCK` | 13 | 1, 2, 3, 4, 16 |
| `0x06` | `CARD_CMD_CHECK_VERIFIED` | 21 | 1, 2, 3, 4, 8, 9, 16, 17 |
| `0x07` | `CARD_CMD_CREATE_FILE` | 6 | 1, 2, 3, 4, 19 |
| `0x08` | `CARD_CMD_SET_STATUS` | 15 | 1, 2, 3, 4, 17, 19 |
| `0x09` | `CARD_CMD_WRITE_HEADER` | 15 | 1, 2, 3, 4, 17, 19 |
| `0x0A` | `CARD_CMD_VERIFY_HEADER` | 9 | 1, 2, 3, 4, 17 |
| `0x0B` | `CARD_CMD_READ_HEADER` | 12 | 1, 2, 3, 4, 6, 14, 16, 18 |
| `0x0C` | `CARD_CMD_GET_STATUS` | 7 | 1, 2, 3, 4, 6, 14, 16 |
| `0x0D` | `CARD_CMD_SCAN_BLOCK` | 20 | 1, 2, 3, 4, 6, 14, 16 |
| `0x0E` | `CARD_CMD_REPAIR` | 7 | 1, 2, 3, 4, 6, 14, 16 |
| `0x0F` | `CARD_CMD_READ_SECTOR` | 2 | 5, 6 |
| `0x10` | `CARD_CMD_WRITE_SECTOR` | 2 | 5, 6 |
| `0x11` | `CARD_CMD_SCAN_FILE` | 7 | 1, 2, 3, 4, 6, 14, 16 |

### Request

| Value | Name | Observed count | Passing scenarios |
| --- | --- | ---: | --- |
| `0x00` | `CARD_REQ_NONE` | 0 | 11 (empty-state assertion) |
| `0x01` | `CARD_REQ_READ_FILE` | 19 | 1, 2, 3, 4, 15, 16 |
| `0x02` | `CARD_REQ_WRITE_FILE` | 10 | 1, 2, 3, 4, 16 |
| `0x03` | `CARD_REQ_CREATE_FILE` | 6 | 1, 2, 3, 4, 19 |
| `0x04` | `CARD_REQ_SET_STATUS` | 9 | 1, 2, 3, 4, 17 |
| `0x05` | `CARD_REQ_OPEN_FILE` | 7 | 1, 2, 3, 4, 6, 14, 16 |
| `0x06` | `CARD_REQ_READ_HEADER` | 5 | 1, 2, 3, 4, 18 |

### Active

| Value | Name | Observed count | Passing scenarios |
| --- | --- | ---: | --- |
| `0x00` | `CARD_ACTIVE_NONE` | 2,872,975 | 1, 2, 3, 4, 5, 6, 7, 10, 11, 12, 14, 15, 16, 17, 18, 19, 20, 23, 29 |
| `0x01` | `CARD_ACTIVE_READ_FILE` | 1,443,663 | 1, 2, 3, 4, 8, 9, 15, 16 |
| `0x02` | `CARD_ACTIVE_WRITE_FILE` | 3,317,202 | 1, 16 |
| `0x03` | `CARD_ACTIVE_WRITE_FILE_1_2` | 1,959,772 | 2, 3 |
| `0x04` | `CARD_ACTIVE_WRITE_FILE_3` | 1,044,137 | 4, 16 |
| `0x05` | `CARD_ACTIVE_OPEN_OR_READ_HEADER` | 3,312,558 | 1, 2, 3, 4, 6, 14, 16, 18 |
| `0x06` | `CARD_ACTIVE_CREATE_FILE` | 26,086,988 | 1, 2, 3, 4, 19 |
| `0x07` | `CARD_ACTIVE_SET_STATUS` | 7,035,839 | 1, 2, 3, 4, 17 |

### Task

| Value | Name | Observed count | Passing scenarios |
| --- | --- | ---: | --- |
| `0x00` | `CARD_TASK_MOUNT_CARD` | 1 | 12 |
| `0x01` | `CARD_TASK_CHECK_CARD` | 1 | 13 |
| `0x02` | `CARD_TASK_OPEN_FILE` | 1 | 14 |
| `0x03` | `CARD_TASK_UNK_0x03` | 3 | 24, 25, 26 |
| `0x04` | `CARD_TASK_FORMAT_CARD` | 1 | 29 |
| `0x05` | `CARD_TASK_DELETE_FILE` | 1 | 23 |
| `0x06` | `CARD_TASK_RENAME_FILE` | 1 | 20 |
| `0x07` | `CARD_TASK_CREATE_FILE` | 1 | 19 |
| `0x08` | `CARD_TASK_READ_FILES` | 1 | 15 |
| `0x09` | `CARD_TASK_WRITE_FILES` | 1 | 16 |
| `0x0A` | `CARD_TASK_SET_STATUS` | 1 | 17 |
| `0x0B` | `CARD_TASK_READ_HEADER` | 1 | 18 |
| `0x0C` | `CARD_TASK_LIST_SNAPSHOTS` | 1 | 27 |
| `0x0D` | `CARD_TASK_FIND_FILE` | 2 | 21, 22 |
| `0x0E` | `CARD_TASK_NONE` | 0 | 28 (empty-state assertion) |

## Scenario assertions

1. **`write_mode_0_named_flows`** — Create/read/write/reopen exact bytes, header read/update, and no SDK writes for verified data.
2. **`write_mode_1_named_flows`** — Create/read/write/reopen exact bytes, header read/update, and no SDK writes for verified data.
3. **`write_mode_2_named_flows`** — Create/read/write/reopen exact bytes, header read/update, and no SDK writes for verified data.
4. **`write_mode_3_named_flows`** — Create/read/write/reopen exact bytes, header read/update, and no SDK writes for verified data.
5. **`sector_decode_reencode_and_bookkeeping`** — Sector read decodes payload; sector write preserves embedded header while recording descriptor sequence 7 in RAM.
6. **`scan_file_scans_blocks_and_repairs_corrupt_mirror`** — Reopen restores corrupted physical sector from valid mirror, reconstructs block IDs, and does not mount.
7. **`clear_buffer_copies_descriptor`** — Queued descriptor survives caller overwrite and clears precisely four destination bytes.
8. **`check_verified_result_0`** — Prior result 0 becomes 1; following clear is gated accordingly.
9. **`check_verified_result_2`** — Prior result 2 becomes 0; following clear is gated accordingly.
10. **`unknown_command_03_stays_at_head`** — Two pumps leave unknown tag at head; no invented operation or intended name.
11. **`empty_command_request_active_sentinels`** — Empty pump leaves no active operation and all 32 request slots marked NONE.
12. **`CARD_TASK_MOUNT_CARD`** — Real task reaches named asynchronous SDK operation and completes successfully.
13. **`CARD_TASK_CHECK_CARD`** — Real task reaches named asynchronous SDK operation and completes successfully.
14. **`CARD_TASK_OPEN_FILE`** — Task completes and its opened metadata, read/write bytes, or header contents match the requested operation.
15. **`CARD_TASK_READ_FILES`** — Task completes and its opened metadata, read/write bytes, or header contents match the requested operation.
16. **`CARD_TASK_WRITE_FILES`** — Task completes and its opened metadata, read/write bytes, or header contents match the requested operation.
17. **`CARD_TASK_SET_STATUS`** — Task completes and its opened metadata, read/write bytes, or header contents match the requested operation.
18. **`CARD_TASK_READ_HEADER`** — Task completes and its opened metadata, read/write bytes, or header contents match the requested operation.
19. **`CARD_TASK_CREATE_FILE`** — Creates named file containing supplied comment.
20. **`CARD_TASK_RENAME_FILE`** — Old name no longer opens; new name preserves file contents.
21. **`CARD_TASK_FIND_FILE`** — Finds exact filename with matching game/company metadata.
22. **`CARD_TASK_FIND_FILE_missing`** — Missing filename produces result 13.
23. **`CARD_TASK_DELETE_FILE`** — Deleted name no longer opens through real SDK.
24. **`CARD_TASK_UNK_0x03_result_0`** — Stored result 0 becomes 1; intended role remains unknown.
25. **`CARD_TASK_UNK_0x03_result_2`** — Stored result 2 becomes 1; intended role remains unknown.
26. **`CARD_TASK_UNK_0x03_result_4`** — Stored result 4 becomes 4; intended role remains unknown.
27. **`CARD_TASK_LIST_SNAPSHOTS`** — Lists decimal filename prefixes newest first, accepts 200-extra, excludes nonnumeric names; real SDK and allocator.
28. **`CARD_TASK_NONE`** — Eleven unused task slots do not dispatch mount, whose enum value is zero.
29. **`CARD_TASK_FORMAT_CARD`** — Formats disposable card; previously present file no longer opens.

## Provenance and limits

- Decomp source: [`26a2fdf`](https://github.com/MarkMcCaskey/melee/commit/26a2fdf763b56fd2071cb115f92925379c0a6701). Embedded ISO DOL and matching build SHA-1: `08e0bf20134dfcb260699671004527b2d6bb1a45`.
- Emulator: local `Dolphin [feature/dap-server] 1225d09`, GDB transport, interpreter, single CPU thread, accurate CPU cache disabled. This is not a recorded stock Dolphin run. Binary/compiler/driver/source hashes are in the evidence.
- The enum sweep adds PPC counter probes to original dispatches and SDK entries. Each preserves registers/CR and executes its displaced instruction; it does not supply function results, bytes, or completions. Instrumentation affects timing. Exact patch sites and trace hash are recorded.
- Empty sentinel tests inspect real idle queue state; no fake sentinel dispatch is counted. Active states are sampled rather than independently dispatched.
- Most enum flows use 128-byte data payloads. The earlier [10-scenario integration run](REPORT.md) additionally covers 9,000-byte transfers and persistence across emulator restarts. Its evidence records the runner version used then.
- This is focused behavioral coverage, not exhaustive error, corruption, power-loss, timing, graphical banner/icon, normal-gameplay, or physical GameCube validation. Shared end-to-end checks and static control-flow analysis together support the descriptive names; the tests cannot recover original identifiers.

## Subsequent source cleanup

The PR subsequently replaced `CMD_FIELD`/`CMD_HEAD`/`CMD_STATE` with direct union
member access and moved the globals into `hsd_3A94.c`, removing `hsd_4D11.c`.
The full DOL still matches the SHA-1 above. These recorded emulator results
retain their original source provenance; preparation also supports the newer
layout. No enum names or numeric values changed in that cleanup.
