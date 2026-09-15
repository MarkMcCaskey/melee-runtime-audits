# Independent Dolphin integration audit

This runs the original Melee save routines **and the original Dolphin SDK CARD
routines** inside Dolphin. There is no `card.py`, Unicorn, or host implementation
of save or CARD operations on this path.

```text
Python test inputs/results over GDB
                ↕
Small compiled C driver in the initialized game thread
                ↓
Matching Melee save/queue code → original CARD/EXI SDK code
                ↓
Dolphin's emulated EXI memory-card hardware → disposable .raw card
```

See [REPORT.md](REPORT.md) for the recorded results and
[../reports/dolphin-evidence.json](../reports/dolphin-evidence.json) for calls,
callbacks, payload hashes, source/binary provenance, and scenario outcomes.

## Run

First prepare the matching decomp inputs using the [parent instructions](../README.md).
Then, from `pr3489/`:

```sh
.venv/bin/python dolphin/run.py \
  --dolphin /path/to/dolphin-emu-nogui \
  --dolphin-arg=--platform --dolphin-arg=headless \
  --iso /path/to/ssbm_rev2.iso \
  --clang /path/to/llvm/bin/clang
```

Dependencies are the parent's Python environment, an LLVM Clang build supporting
`--target=powerpc-unknown-eabi`, an uncompressed GALE01 revision 2 ISO, and a
Dolphin build with the GDB stub. Apple Clang may lack the PowerPC backend; the
recorded run used Homebrew LLVM. No linker or SDK headers are required to build
the small freestanding driver; its function signatures specify the PPC ABI and
its function addresses are extracted from the matching ELF.

The runner creates a fresh temporary Dolphin user folder and raw memory card,
then starts two emulator processes sequentially using that same isolated card.
It never uses the ordinary Dolphin user folder or an existing user save.
The temporary path is printed and retained for inspection. Only JSON evidence
and audit source belong in git; no game binary or generated card is committed.

## What is independently tested

For each write mode 0, 1, 2, and 3:

1. Create a save with 180 bytes in logical file zero (mode 3), and 9,000 bytes
   in logical file one. Read file one and compare every byte to its known input.
2. Write a different 9,000-byte payload, crossing the 8,160-byte data boundary.
   Read file zero and verify that its original payload survives.
3. Submit identical data again and require completion result 1. This verifies
   the observed result, **not** the absence of physical card writes: this layer
   does not count CARD/EXI writes.
4. Update the 64-byte comment and read it back through the header API.
5. Initialize a fresh `CardState`, open the existing save, check its restored
   size/mode, and read both logical files again.
6. Terminate Dolphin cleanly, start a fresh emulator process with the same card,
   mount/check it through the SDK, reopen, and compare both files and the comment.

Two further scenarios reproduce the model suite's counterexample: nonempty
logical file zero in mirror mode 0, with logical file one in mode 1 or 2.
Reopening reports `-0x102` while file one's bytes remain readable. This is a
prediction from the model-tested decomp that the independent path can confirm
or disprove; it is not silently excluded from the successful configurations.

## How it works

- The ISO's embedded DOL SHA-1 must equal the matching build's recorded hash.
  The linked ELF is also verified against its snapshot hash.
- GDB stops at `db_GetGameLaunchButtonState`, after `OSInit`, `CARDInit`, and
  `OSInitAlarm`, before ordinary game heaps/scenes are initialized.
- One bootstrap instruction branches into `driver.c` at `0x81000000`, in the
  unused arena. Code must fit below `0x81001000`; the mailbox, completion record,
  mount work area, and data buffers occupy separate regions after it.
- The compiled driver invokes typed function pointers into the original game.
  It pumps the real save queue while real emulated interrupts complete CARD I/O.
  It reports via volatile mailbox fields; the host changes no CPU registers.
- `DebugModeEnabled=True` is required for breakpoints. The run uses a single CPU
  thread, the interpreter, and `AccurateCPUCache=False`, explicitly recorded here.
  GDB memory access retries `E00` while exception entry temporarily changes the
  CPU's effective address space. It does not synthesize SDK completions.
- The driver object must have no unresolved relocations. Its exact text hash,
  compiler version, and emulator binary hash/version are recorded.

Dolphin's [GDB implementation](https://github.com/dolphin-emu/dolphin/blob/master/Source/Core/Core/PowerPC/GDBStub.cpp)
provides the debugger transport. Its
[EXI memory-card device](https://github.com/dolphin-emu/dolphin/blob/master/Source/Core/Core/HW/EXI/EXI_DeviceMemoryCard.cpp)
emulates the hardware below the SDK, rather than providing a host `CARDReadAsync`
function that could simply replace `card.py`.

## Limits

This is focused integration coverage, not the complete 117-scenario model suite.
It does not independently cover every task/command tag, graphical banner/icon
variants, all injected errors, every repair/corruption case, power loss, or
real GameCube hardware. It calls the save subsystem before normal game scene
initialization; it does not establish which configurations ordinary gameplay
uses. Original symbol names and both `UNK_0x03` intended roles remain unresolved.

The recorded emulator is the local `feature/dap-server` build `1225d09`, identified
by its binary hash; the audit uses its GDB interface, not DAP. A stock GUI build
was not successfully launched for this audit. Results should not be represented
as validation of every stock Dolphin release.
