# Card queue and save semantics audit

**117 passed; 0 failed.**

Source: [PR #3489](https://github.com/doldecomp/melee/pull/3489), commit [`26a2fdf76`](https://github.com/MarkMcCaskey/melee/commit/26a2fdf763b56fd2071cb115f92925379c0a6701).

These are executions of the locally built, matching PowerPC decomp in Unicorn,
with an in-memory Dolphin CARD interface. They are not live-game or hardware tests.

## Findings

- All 18 command tags were dispatched, including the empty and unknown tags.
- All six nonempty request tags, all eight active tags, and all 14 nonempty task tags were observed.
  The two remaining NONE sentinels have explicit empty-queue/unused-slot tests.
- Known operation names are supported by CARD traces and byte/state assertions.
  Trace coverage alone is not treated as proof of every semantic claim.
- `CARD_CMD_UNK_0x03` stalls at the head without performing an operation.
  `CARD_TASK_UNK_0x03` maps results 0 and 2 to 1; its intended role remains unknown.
- Writes in modes 0, 1, 2 and 3 survive readback and reopening across sector boundaries.
  Identical writes return the verified result and avoid CARD writes.
- Header tests cover comments, both banner formats, indexed/direct-color icons,
  one shared palette, all three header sectors, nullable destinations, and shared block-zero preservation.
- Sector reads decode/check the work buffer. Sector writes re-encode that buffer and update
  RAM block-id/sequence bookkeeping; unlike WRITE_BLOCK, they do not construct those header fields.
- Mirrored nonempty logical file zero can produce `-0x102` on reopening when a spare block
  invites a repair through the unsupported physical-block-zero copy path. Data can still be readable.
  The ordinary cross-mode round trips use file-zero mode 3. The mode-zero counterexample is retained.
- With all mirrors corrupted, the error can be `-0x101` when file-table metadata is also lost,
  or `-0x103` when that metadata survives in block zero. REPAIR is not unconditional recovery.
- A deliberately inline CARD callback is ignored before the busy flag is set and leaves the
  request waiting. Deferred callbacks work; completion remains blocked while interrupts are disabled.
- Snapshot listing filters by game/company and an initial decimal filename prefix;
  it does not validate a snapshot payload type.

## Evidence by enum

Counts below are successful test cases observing each runtime tag, not branch-coverage percentages.

### Command

| Name | Value | Passing tests observing it |
|---|---:|---:|
| `CARD_CMD_NONE` | `0x00` | 70 |
| `CARD_CMD_WRITE_BLOCK` | `0x01` | 59 |
| `CARD_CMD_READ_BLOCK` | `0x02` | 37 |
| `CARD_CMD_UNK_0x03` | `0x03` | 1 |
| `CARD_CMD_CLEAR_BUF` | `0x04` | 64 |
| `CARD_CMD_VERIFY_BLOCK` | `0x05` | 24 |
| `CARD_CMD_CHECK_VERIFIED` | `0x06` | 31 |
| `CARD_CMD_CREATE_FILE` | `0x07` | 60 |
| `CARD_CMD_SET_STATUS` | `0x08` | 59 |
| `CARD_CMD_WRITE_HEADER` | `0x09` | 59 |
| `CARD_CMD_VERIFY_HEADER` | `0x0A` | 4 |
| `CARD_CMD_READ_HEADER` | `0x0B` | 34 |
| `CARD_CMD_GET_STATUS` | `0x0C` | 25 |
| `CARD_CMD_SCAN_BLOCK` | `0x0D` | 24 |
| `CARD_CMD_REPAIR` | `0x0E` | 24 |
| `CARD_CMD_READ_SECTOR` | `0x0F` | 4 |
| `CARD_CMD_WRITE_SECTOR` | `0x10` | 3 |
| `CARD_CMD_SCAN_FILE` | `0x11` | 25 |

### Request

| Name | Value | Passing tests observing it |
|---|---:|---:|
| `CARD_REQ_NONE` | `0x00` | explicit sentinel test |
| `CARD_REQ_READ_FILE` | `0x01` | 35 |
| `CARD_REQ_WRITE_FILE` | `0x02` | 24 |
| `CARD_REQ_CREATE_FILE` | `0x03` | 60 |
| `CARD_REQ_SET_STATUS` | `0x04` | 4 |
| `CARD_REQ_OPEN_FILE` | `0x05` | 25 |
| `CARD_REQ_READ_HEADER` | `0x06` | 9 |

### Active

| Name | Value | Passing tests observing it |
|---|---:|---:|
| `CARD_ACTIVE_NONE` | `0x00` | 65 |
| `CARD_ACTIVE_READ_FILE` | `0x01` | 39 |
| `CARD_ACTIVE_WRITE_FILE` | `0x02` | 5 |
| `CARD_ACTIVE_WRITE_FILE_1_2` | `0x03` | 12 |
| `CARD_ACTIVE_WRITE_FILE_3` | `0x04` | 7 |
| `CARD_ACTIVE_OPEN_OR_READ_HEADER` | `0x05` | 34 |
| `CARD_ACTIVE_CREATE_FILE` | `0x06` | 60 |
| `CARD_ACTIVE_SET_STATUS` | `0x07` | 4 |

### Task

| Name | Value | Passing tests observing it |
|---|---:|---:|
| `CARD_TASK_MOUNT_CARD` | `0x00` | 1 |
| `CARD_TASK_CHECK_CARD` | `0x01` | 1 |
| `CARD_TASK_OPEN_FILE` | `0x02` | 1 |
| `CARD_TASK_UNK_0x03` | `0x03` | 8 |
| `CARD_TASK_FORMAT_CARD` | `0x04` | 1 |
| `CARD_TASK_DELETE_FILE` | `0x05` | 1 |
| `CARD_TASK_RENAME_FILE` | `0x06` | 1 |
| `CARD_TASK_CREATE_FILE` | `0x07` | 1 |
| `CARD_TASK_READ_FILES` | `0x08` | 1 |
| `CARD_TASK_WRITE_FILES` | `0x09` | 1 |
| `CARD_TASK_SET_STATUS` | `0x0A` | 1 |
| `CARD_TASK_READ_HEADER` | `0x0B` | 1 |
| `CARD_TASK_LIST_SNAPSHOTS` | `0x0C` | 1 |
| `CARD_TASK_FIND_FILE` | `0x0D` | 2 |
| `CARD_TASK_NONE` | `0x0E` | explicit sentinel test |

## Scope and limits

The suite validates finite scenarios at the CARD boundary. It does not establish original symbol
names, complete branch coverage, power-loss atomicity, timing on real hardware, compatibility with
every existing save, or a working native PC port. No stock-game save fixture is claimed: save bytes
are generated by the real decomp, then independently inspected, corrupted, and read back.

The CARD model implements the calls these tests exercise, deterministic deferred callbacks,
capacity/file metadata, and injected launch/completion errors. It does not emulate the SDK FAT,
card hardware, permissions, two independent slots, or CARDStat derived icon offsets.
Platform allocation/interrupt functions and selected C-library functions are host adapters;
card task/queue/format/checksum/codec routines execute as PowerPC instructions.

Every dynamically allocated guest test buffer has checked guard bytes. This detects boundary
writes into those guards; it is not a general memory-safety proof or a check of every guest read.

Machine-readable per-test traces, outcomes, source hashes, and binary hashes are in
[`reports/evidence.json`](reports/evidence.json). Generated ELF/source snapshots are not committed.
