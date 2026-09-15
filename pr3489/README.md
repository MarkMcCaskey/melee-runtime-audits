# Card queue and save semantics — PR #3489

Execute the **locally built PowerPC decomp** against a deterministic in-memory
Dolphin `CARD*` interface. This audit checks the semantic names in
[doldecomp/melee PR #3489](https://github.com/doldecomp/melee/pull/3489).
The recorded run targets commit `26a2fdf763b56fd2071cb115f92925379c0a6701`.

Read [REPORT.md](REPORT.md) for the results and limitations, and
[reports/evidence.json](reports/evidence.json) for per-test runtime observations
and input hashes. The suite exercises every command tag, every nonempty request
and task tag, and every active tag. It is **not** exhaustive branch coverage or
a proof that every save configuration is supported.

## Run locally

Requirements:

- Python 3.11 or newer and the pinned packages in `requirements.txt`.
- A clean, configured Melee checkout at the audited commit, capable of running
  `ninja` and producing an exactly matching GALE01 DOL and its linked ELF.
  Follow the decomp repository's normal build setup for the required original
  game inputs and compiler. The audit does not download a game image.
- [Unicorn](https://github.com/unicorn-engine/unicorn) with PowerPC support
  (provided by the pinned wheel on the tested Apple Silicon host).

From this directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python audit.py prepare --melee /path/to/configured/melee
.venv/bin/python audit.py test
```

`prepare` runs the decomp build, verifies its DOL hash, records the clean source
commit, and copies the ELF and relevant source declarations into `.local-inputs/`.
That directory is ignored by git. No decomp source is patched. Subsequent tests
use the immutable snapshot and verify its hashes before execution, so deleting
the original temporary worktree does not invalidate a prepared local audit.

To refresh after changing the decomp, commit those changes locally and run
`prepare` again. Enum names are parsed from the recorded source declarations;
the test runner does not substitute its own enum numbering.

For focused development:

```sh
.venv/bin/python -m pytest -q tests/test_repair_and_sectors.py
.venv/bin/python -m pytest -q tests/test_errors_and_timing.py
```

`audit.py test` renders the complete report after a successful full run. Use
plain pytest for subsets: the coverage report intentionally requires all enum
families. A later full run regenerates the authoritative evidence and report.

Optional tooling:

```sh
.venv/bin/python -m pip install ruff==0.16.7
.venv/bin/python -m ruff check cardlab tests audit.py
.venv/bin/python -m ruff format --check cardlab tests audit.py
```

The recorded host was Apple Silicon/macOS with Unicorn 2.1.4. Its JIT needed an
ordinary unsandboxed process; running it inside the coding tool's restricted
sandbox caused an emulator initialization trap. No guest system or real card
access is needed.

## What executes and what is modeled

`cardlab/machine.py` loads the decomp's ELF at its original addresses, preserves
PowerPC big-endian/32-bit layout, initializes the SDA registers and stack, and
calls the linked functions. The command/request arrays retain their original
contiguous layout. No host port, pointer-width rewriting, or test-only C fork is
used.

The real routines in `lbcardnew.c`, `hsd_3A94.c`, `hsd_3B27.c`, `hsd_3B2B.c`, and
`hsd_3B2E.c` implement task dispatch, queues, serialization, checksum, encoding,
verification, and repair. `cardlab/card.py` models the external CARD calls with
file bytes, metadata, deferred completions, busy responses, and injected errors.
Allocator/interrupt functions and selected C-library functions are host adapters.
The inline-callback negative test uses a small PPC trampoline to invoke the real
completion handler at the deliberately wrong time.

Runtime tag coverage is collected at the compiled switch dispatch instructions,
request-dispatch entry, and completion callbacks. Guard bytes surround dynamic
guest test buffers. Tests assert output bytes, metadata, return values, callback
order, and CARD traces; neither visitation nor guard checks establish general
memory safety or complete semantic correctness.

## Test map

| File | Main claims |
|---|---|
| `test_smoke.py` | Original addresses, initialized state, executable checksum |
| `test_format_semantics.py` | Independent checksum reference, codec/corruption, sequence wrap, header sizes, file table, block verification |
| `test_queue_contracts.py` | Descriptor copy vs borrowed data, capacities/wrap, result gating, unknown/empty tags |
| `test_roundtrip.py` | Four write modes, sector boundaries, reopen/readback, no-op writes, block-zero limitation |
| `test_headers.py` | Banner/icons/comment contents, three sectors, nullable outputs, preservation and corruption |
| `test_tasks.py` | Every named task, result-mask gating, unknown task 0x03, filename lookup and snapshot candidates |
| `test_errors_and_timing.py` | Retry limits, launch/completion errors, removal/capacity, deferred/inline callback behavior |
| `test_repair_and_sectors.py` | Corrupt/stale/surplus mirrors, missing data vs metadata, sector work-buffer semantics |

The CARD model is intentionally narrower than the real SDK: no FAT or device
emulation, permissions, two independent slots, derived CARDStat icon offsets,
or power-loss model. The report keeps those limits and observed counterexamples
visible. No original game binary, save image, or copied decomp source is committed.
