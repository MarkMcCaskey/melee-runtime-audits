# Dolphin integration results

**10 scenarios passed through the actual game SDK and Dolphin card hardware.**

The separate [117-scenario report](../REPORT.md) uses a Python CARD model.
These ten scenarios remove that model. They are corroboration for the specific
flows below, not independent verification of every enum name.

## Results

| Scenario | Result |
|---|---|
| `write_mode_0_roundtrip_header_and_verified_result` | passed |
| `write_mode_1_roundtrip_header_and_verified_result` | passed |
| `write_mode_2_roundtrip_header_and_verified_result` | passed |
| `write_mode_3_roundtrip_header_and_verified_result` | passed |
| `mirrored_file_zero_mode_1_reopen_error` | passed |
| `mirrored_file_zero_mode_2_reopen_error` | passed |
| `write_mode_0_persists_across_dolphin_restart` | passed |
| `write_mode_1_persists_across_dolphin_restart` | passed |
| `write_mode_2_persists_across_dolphin_restart` | passed |
| `write_mode_3_persists_across_dolphin_restart` | passed |

Each normal mode test creates and reads 9,000 bytes, writes different bytes,
checks unchanged-write completion result 1, updates/reads the comment,
reopens with a fresh state, and verifies both logical files. Logical file zero
contains 180 bytes in mode 3. The restart cases re-read those bytes and comments
from the same raw card in a fresh Dolphin process.

Both file-zero mirror counterexamples reproduced `-0x102` on reopen while
logical file one remained readable. They are observed decomp behavior, not
failures introduced by the naming PR (the DOL is byte-identical).

## What remains unverified

- No direct coverage claim for every CardCmd, CardRequest, CardActive or CardTask value.
- No independent validation yet for the model’s entire fault matrix, all corruption/repair cases,
  graphical header variants, or precise SDK launch/completion contracts.
- Result 1 for an unchanged write is verified; absence of physical writes is not counted here.
- Neither original names, ordinary gameplay reachability of every configuration,
  nor behavior on physical GameCube hardware is established.
- Both `UNK_0x03` intended roles remain unknown.

## Provenance

- Melee commit: `26a2fdf763b56fd2071cb115f92925379c0a6701`.
- ISO embedded DOL SHA-1: `08e0bf20134dfcb260699671004527b2d6bb1a45` (equal to the matching decomp build).
- Dolphin: `Dolphin [feature/dap-server] 1225d09`.
- Dolphin executable SHA-256: `63abd556cce4ce3968d4e22347025f3d53a58ad0dc8db2fa1fef28a3ea299184`.
- Compiler: `Homebrew clang version 23.1.0`.
- Injected C driver text SHA-256: `74aa27107df6c6a9ac946858673221539ad746afe2e2a0b8be5c61ed5d2da901`.
- Two fresh emulator processes; single CPU thread; interpreter; accurate CPU cache disabled.
- One bootstrap branch patch before game heap/scene initialization. Save and CARD routines are unmodified.
- Local Dolphin fork build, not a claim about a tested stock release. No DAP interface is used.

The [runner and setup](README.md) explain the C mailbox driver and address handling.
[Machine-readable evidence](../reports/dolphin-evidence.json) records scenario outcomes,
every requested operation/result, completion results, payload hashes, and input/code hashes.
