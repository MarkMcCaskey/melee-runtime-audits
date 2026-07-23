# Runtime audit: doldecomp/melee PR #2939

PR head: `ce27a5268a7ae25b04593128530f773eaad3e9da` — game: GALE01 rev2 (NTSC 1.02), stock Dolphin via its GDB stub.

## 1. stage_id_map table vs RAM

- (not run)

## 2. Live stage-load sweep

For each external ID: written to `StartMeleeRules::xE`, match started by the game's own scene flow, `Stage_802251E8`'s argument observed, then `stage_info.internal_stage_id` and the loaded archive name read back. PASS iff the live internal ID equals `stage_id_map[external].internal_id`.

| ext | enum | map→int | live int | live enum | archive | on-screen overlay | result |
|-----|------|---------|----------|-----------|---------|-------------------|--------|

**0/0 externals PASS.**
