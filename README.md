# melee-runtime-audits

Runtime audits for [doldecomp/melee](https://github.com/doldecomp/melee)
documentation/semantics PRs.

The decomp's CI already proves byte-equivalence: any PR that still builds a
matching DOL cannot have changed behavior. What CI *cannot* check is renames
and documentation — claims like "this argument is the external stage ID" or
"this table maps external to internal stage IDs". These audits test those
claims using the game or its matching compiled code:

1. **Machine audit** — a standalone Python script (stdlib only) that drives
   **any stock Dolphin** through its built-in GDB stub
   (`-C Dolphin.General.GDBPort=...`): boots the game headless, forces the
   relevant code paths, and reads back what the engine actually does. Results
   stream to JSONL and render to a markdown report.
2. **Human-verifiable Gecko artifact** — Gecko codes usable on any Dolphin,
   with reviewable assembly and a documented result block. Audits may also
   render the values on screen with the game's develop-mode text console.
3. **Isolated PowerPC audit** — execute the matching decomp ELF in Unicorn
   against a deterministic mock of the Dolphin SDK CARD interface. This checks
   save bytes, queue behavior, callbacks, errors, and semantic names without
   booting the whole game.

Each audit lives in its own directory, self-contained:

- `pr2939/` — external vs internal stage IDs
  ([PR #2939](https://github.com/doldecomp/melee/pull/2939)).
- `venom-platform-links/` — the target object, ordered platform joints, and
  smash-taunt timer in Venom's platform controller
  ([refactor commit](https://github.com/MarkMcCaskey/melee/commit/079bee437e70819ac6932cae51cfc1b27dedcb82)).
- `grkind-stkind/` — which stage-id space the game's own `grkind` / `stkind`
  names refer to (PR #2939 follow-up). Also the one audit here whose main
  result needs no emulator: the claim is checkable against the stage archives
  on the disc.
- [`pr3489/`](pr3489/) — card command/request/task names, tagged queue
  descriptors, and save format behavior
  ([PR #3489](https://github.com/doldecomp/melee/pull/3489)).

## Requirements

See each audit's README for its exact setup. The live-game audits use:

- A stock Dolphin build recent enough to have the GDB stub config keys
  (mainline since ~2022). `dolphin-emu-nogui` is ideal for headless runs;
  the GUI build works for the interactive overlay.
- An SSBM NTSC 1.02 (GALE01 rev2) ISO.
- Python 3.9+ (stdlib only).
- Rebuilding the overlay payloads additionally needs powerpc-eabi binutils
  and a doldecomp/melee checkout, but the built artifacts are committed.

The [PR #3489 audit](pr3489/) instead needs Python 3.11+, pinned Unicorn/pytest
dependencies, and a configured matching decomp build. Its original game inputs,
ELF, and source snapshot stay local and are not committed.
