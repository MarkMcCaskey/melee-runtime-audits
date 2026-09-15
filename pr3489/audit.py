#!/usr/bin/env python3
"""Prepare immutable local inputs, run the PowerPC audit, and render evidence."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCES = [
    "src/melee/lb/lbcardnew.c",
    "src/melee/lb/lbcardnew.h",
    "src/sysdolphin/baselib/hsd_3A94.c",
    "src/sysdolphin/baselib/hsd_3A94.h",
    "src/sysdolphin/baselib/hsd_3B27.c",
    "src/sysdolphin/baselib/hsd_3B27.h",
    "src/sysdolphin/baselib/hsd_3B2B.c",
    "src/sysdolphin/baselib/hsd_3B2B.h",
    "src/sysdolphin/baselib/hsd_3B2E.c",
    "src/sysdolphin/baselib/hsd_3B2E.h",
    "src/sysdolphin/baselib/hsd_4D11.c",
    "extern/dolphin/include/dolphin/card.h",
    "extern/dolphin/include/dolphin/card/CARDStat.h",
    "extern/dolphin/src/dolphin/card/CARDCreate.c",
]


def digest(path, algorithm="sha256"):
    return hashlib.new(algorithm, path.read_bytes()).hexdigest()


def prepare(repo):
    repo = repo.resolve()
    status = subprocess.check_output(
        ["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=no"],
        text=True,
    )
    if status:
        raise SystemExit(
            "Use a clean decomp checkout; the snapshot must correspond to a recorded commit."
        )
    subprocess.run(["ninja"], cwd=repo, check=True)
    commit = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    dol = repo / "build/GALE01/main.dol"
    expected = (repo / "config/GALE01/build.sha1").read_text().split()[0]
    actual = digest(dol, "sha1")
    if actual != expected:
        raise SystemExit(f"DOL mismatch: {actual} != {expected}")
    destination = ROOT / ".local-inputs"
    paths = SOURCES + ["build/GALE01/main.elf"]
    for path in paths:
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo / path, target)
    objects = {}
    for source in SOURCES:
        if source.startswith("src/") and source.endswith(".c"):
            obj = "build/GALE01/" + source[:-2] + ".o"
            objects[obj] = digest(repo / obj)
    provenance = {
        "source_repository": "https://github.com/doldecomp/melee",
        "source_pr": "https://github.com/doldecomp/melee/pull/3489",
        "commit": commit,
        "dol_sha1": actual,
        "elf_sha256": digest(destination / "build/GALE01/main.elf"),
        "source_sha256": {path: digest(destination / path) for path in SOURCES},
        "object_sha256": objects,
    }
    (destination / "provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )
    print(
        f"Prepared matching decomp commit {commit}; generated inputs are ignored by git."
    )


def validate_inputs():
    root = ROOT / ".local-inputs"
    manifest = root / "provenance.json"
    if not manifest.exists():
        raise SystemExit(
            "First run: python audit.py prepare --melee /path/to/configured/melee"
        )
    provenance = json.loads(manifest.read_text())
    assert digest(root / "build/GALE01/main.elf") == provenance["elf_sha256"], (
        "ELF input changed"
    )
    for path, expected in provenance["source_sha256"].items():
        assert digest(root / path) == expected, f"source snapshot changed: {path}"
    return provenance


def render():
    report = json.loads((ROOT / "reports/evidence.json").read_text())
    counts = Counter(report["outcomes"].values())
    commit = report["provenance"]["commit"]
    sections = [
        ("command", "commands_dispatched"),
        ("request", "requests_dispatched"),
        ("active", "active_types_observed"),
        ("task", "tasks_dispatched"),
    ]
    lines = [
        "# Card queue and save semantics audit",
        "",
        f"**{counts.get('passed', 0)} passed; {counts.get('failed', 0)} failed.**",
        "",
        (
            f"Source: [PR #3489](https://github.com/doldecomp/melee/pull/3489), "
            f"commit [`{commit[:9]}`](https://github.com/MarkMcCaskey/melee/commit/{commit})."
        ),
        "",
        "These are executions of the locally built, matching PowerPC decomp in Unicorn,",
        "with an in-memory Dolphin CARD interface. They are not live-game or hardware tests.",
        "",
        "## Findings",
        "",
        "- All 18 command tags were dispatched, including the empty and unknown tags.",
        "- All six nonempty request tags, all eight active tags, and all 14 nonempty task tags were observed.",
        "  The two remaining NONE sentinels have explicit empty-queue/unused-slot tests.",
        "- Known operation names are supported by CARD traces and byte/state assertions.",
        "  Trace coverage alone is not treated as proof of every semantic claim.",
        "- `CARD_CMD_UNK_0x03` stalls at the head without performing an operation.",
        "  `CARD_TASK_UNK_0x03` maps results 0 and 2 to 1; its intended role remains unknown.",
        "- Writes in modes 0, 1, 2 and 3 survive readback and reopening across sector boundaries.",
        "  Identical writes return the verified result and avoid CARD writes.",
        "- Header tests cover comments, both banner formats, indexed/direct-color icons,",
        "  one shared palette, all three header sectors, nullable destinations, and shared block-zero preservation.",
        "- Sector reads decode/check the work buffer. Sector writes re-encode that buffer and update",
        "  RAM block-id/sequence bookkeeping; unlike WRITE_BLOCK, they do not construct those header fields.",
        "- Mirrored nonempty logical file zero can produce `-0x102` on reopening when a spare block",
        "  invites a repair through the unsupported physical-block-zero copy path. Data can still be readable.",
        "  The ordinary cross-mode round trips use file-zero mode 3. The mode-zero counterexample is retained.",
        "- With all mirrors corrupted, the error can be `-0x101` when file-table metadata is also lost,",
        "  or `-0x103` when that metadata survives in block zero. REPAIR is not unconditional recovery.",
        "- A deliberately inline CARD callback is ignored before the busy flag is set and leaves the",
        "  request waiting. Deferred callbacks work; completion remains blocked while interrupts are disabled.",
        "- Snapshot listing filters by game/company and an initial decimal filename prefix;",
        "  it does not validate a snapshot payload type.",
        "",
        "## Evidence by enum",
        "",
        "Counts below are successful test cases observing each runtime tag, not branch-coverage percentages.",
        "",
    ]
    sentinel_tests = {
        "CARD_REQ_NONE": "test_request_queue_reset_marks_every_slot_empty",
        "CARD_TASK_NONE": "test_unused_slots_do_not_dispatch_mount_even_though_mount_is_zero",
    }
    for category, field in sections:
        lines += [
            f"### {category.title()}",
            "",
            "| Name | Value | Passing tests observing it |",
            "|---|---:|---:|",
        ]
        for name, value in report["enums"][category].items():
            tests = [
                node
                for node, data in report["tests"].items()
                if value in data[field] and report["outcomes"].get(node) == "passed"
            ]
            count = str(len(tests))
            if not tests and name in sentinel_tests:
                assert any(
                    sentinel_tests[name] in node and outcome == "passed"
                    for node, outcome in report["outcomes"].items()
                ), name
                count = "explicit sentinel test"
            else:
                assert tests, f"No runtime coverage for {name}"
            lines.append(f"| `{name}` | `0x{value:02X}` | {count} |")
        lines.append("")
    lines += [
        "## Scope and limits",
        "",
        "The suite validates finite scenarios at the CARD boundary. It does not establish original symbol",
        "names, complete branch coverage, power-loss atomicity, timing on real hardware, compatibility with",
        "every existing save, or a working native PC port. No stock-game save fixture is claimed: save bytes",
        "are generated by the real decomp, then independently inspected, corrupted, and read back.",
        "",
        "The CARD model implements the calls these tests exercise, deterministic deferred callbacks,",
        "capacity/file metadata, and injected launch/completion errors. It does not emulate the SDK FAT,",
        "card hardware, permissions, two independent slots, or CARDStat derived icon offsets.",
        "Platform allocation/interrupt functions and selected C-library functions are host adapters;",
        "card task/queue/format/checksum/codec routines execute as PowerPC instructions.",
        "",
        "Every dynamically allocated guest test buffer has checked guard bytes. This detects boundary",
        "writes into those guards; it is not a general memory-safety proof or a check of every guest read.",
        "",
        "Machine-readable per-test traces, outcomes, source hashes, and binary hashes are in",
        "[`reports/evidence.json`](reports/evidence.json). Generated ELF/source snapshots are not committed.",
        "",
    ]
    (ROOT / "REPORT.md").write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--melee", type=Path, required=True)
    sub.add_parser("test")
    sub.add_parser("report")
    args, extra = parser.parse_known_args()
    if args.command == "prepare":
        if extra:
            parser.error(str(extra))
        prepare(args.melee)
    elif args.command == "test":
        validate_inputs()
        import os

        env = dict(os.environ, MELEE_REPO=str(ROOT / ".local-inputs"))
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--tb=short", *extra],
            cwd=ROOT,
            env=env,
            check=False,
        )
        if result.returncode == 0:
            render()
        raise SystemExit(result.returncode)
    else:
        render()


if __name__ == "__main__":
    main()
