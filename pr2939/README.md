# PR #2939 runtime audit — external vs internal stage IDs

Audits [doldecomp/melee PR #2939](https://github.com/doldecomp/melee/pull/2939)
against the live game (GALE01 rev2 / SSBM NTSC 1.02).

The PR claims, beyond what byte-matching CI can check:

1. `unk_arr_803E9960` (renamed `stage_id_map`) maps **external** stage IDs to
   **internal** stage IDs, and the new `ExternalStageId` enum names its
   indices correctly (`0x07` = Corneria, `0x16` = Venom, ...).
2. `Stage_802251E8` / `Stage_8022519C` / `StartMeleeRules::xE` /
   `lbAudioAx_80026EBC` take external IDs, not internal ones.
3. `stage_info.internal_stage_id` and the `Ground_803DFEDC` table index are
   the internal side of that mapping.

## Interactive audit (any Dolphin, no tooling)

Add `kiosk.gecko.ini` to GALE01's Gecko codes (right-click the game →
Properties → Gecko Codes → Edit config, or copy into
`GameSettings/GALE01.ini` in your Dolphin user folder), enable cheats, and
boot the game. It goes straight into a CPU-vs-CPU match; then:

- **D-pad Right / Left (P1)** steps to the next / previous external stage ID
  (0x02..0x20, skipping the deleted 0x15). Each press reloads the match
  through the game's own scene flow.
- The overlay (game's own develop-mode text console) shows live:

      ext=07 CORNERIA map=0E     <- selected external id, PR enum name,
      live=0E GrCn.dat OK           stage_id_map claim; engine's internal id,
      next=16                       loaded archive, verdict; pending target

  `OK` means `stage_id_map[ext].internal_id` equals the internal ID the
  engine actually loaded; the archive name (`GrCn.dat` = Corneria, ...) is
  read from the loaded stage's own `StageData`, so you can eyeball that the
  enum name, the stage on screen, and the file agree.

`overlay.gecko.ini` is a passive variant: just the overlay, no stage cycling
or scene pinning — safe to leave on while playing normally.

## Machine audit (headless, stock Dolphin)

    python3 audit_pr2939.py --dolphin /path/to/dolphin-emu-nogui \
        --iso /path/to/ssbm_rev2.iso \
        --dolphin-arg=--platform --dolphin-arg=headless \
        --dolphin-arg=-v --dolphin-arg=Null

Uses `autosweep.gecko.ini` (the kiosk plus an autopilot: the game itself
walks all VS external IDs, waits 90 stable frames each, and records
`{ext, map, live}` into develop-mode-only debug memory). The script launches
Dolphin with cheats enabled, then only *reads* memory over Dolphin's
built-in GDB stub (`Dolphin.General.GDBPort`) — no breakpoints — and:

- diffs all 286 `stage_id_map` entries in RAM against the PR's initializer,
- collects each sweep row, the loaded archive filename, and a snapshot of
  the on-screen overlay text,
- checks every row against `expected.json`.

Results stream to `audit.jsonl`; `REPORT.md` is the human-readable summary
(regenerate anytime with `--report`).

## Provenance / rebuilding

- `extract_expected.py` fetches `gr/forward.h` + `gr/stage.c` at the PR head
  SHA and parses the enums and table into `expected.json` — the audit checks
  the PR's actual content, never a hand-copied table.
- `build_overlay.py` generates `overlay.s` / `matchhook.s`, assembles them
  (powerpc-eabi binutils), and emits the three `.gecko.ini` files plus
  `overlay_meta.json`. Every game address is annotated in `addresses.py`
  and traceable to `config/GALE01/symbols.txt`.
- All payload code/data lives in `db_CpuHandicapInfo` / `db_AnimationInfo` /
  `db_CameraInfoDisplay_buf` / `db_SoundInfoText_buf` — develop-mode debug
  buffers retail play never touches. The overlay hooks `DevText_DrawAll`;
  the kiosk additionally pins the three scene-flow setters to VS/match,
  writes the pending ID in `fn_8016E730`, and disables the memory-card
  prompt.

## Caveats

- The kiosk/autosweep hooks deliberately hijack the scene flow — those code
  sets are for auditing, not normal play.
- The sweep covers the VS-loadable external range 0x02..0x20. Entries
  0x21+ (1P/event variants, `BIGBLUEROUTE`, `HEAL`) are covered by the
  table diff but not load-tested by default.
