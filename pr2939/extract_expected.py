"""Extract the expected external->internal stage id mapping from PR #2939.

Fetches src/melee/gr/forward.h and src/melee/gr/stage.c at the PR head SHA
(so the audit checks the PR's actual content, not a hand-copied table),
parses both enums and the stage_id_map initializer, and writes expected.json:

  { "head_sha": ..., "external": {name: value}, "internal": {name: value},
    "table": [internal_value, ...] }   # indexed by external id
"""
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = "doldecomp/melee"
PR = 2939


def fetch(path: str, ref: str) -> str:
    out = subprocess.run(
        ["gh", "api", f"repos/{REPO}/contents/{path}?ref={ref}",
         "-H", "Accept: application/vnd.github.raw"],
        check=True, capture_output=True)
    return out.stdout.decode()


def strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def parse_enum(src: str, name: str) -> dict:
    m = re.search(rf"typedef enum {name}\s*\{{(.*?)\}}\s*{name}\s*;",
                  strip_comments(src), flags=re.S)
    if not m:
        raise SystemExit(f"enum {name} not found")
    values, next_val = {}, 0
    for entry in m.group(1).split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "=" in entry:
            ident, _, val = entry.partition("=")
            next_val = int(val.strip(), 0)
            entry = ident.strip()
        values[entry] = next_val
        next_val += 1
    return values


def parse_table(stage_c: str, internal: dict) -> list:
    m = re.search(r"struct StageIdMapEntry stage_id_map\[\]\s*=\s*\{(.*?)\};",
                  strip_comments(stage_c), flags=re.S)
    if not m:
        raise SystemExit("stage_id_map initializer not found")
    table = []
    for ent in re.finditer(r"\{\s*([A-Za-z0-9_]+)\s*,\s*0\s*,\s*0\s*\}", m.group(1)):
        name = ent.group(1)
        if name not in internal:
            raise SystemExit(f"unknown InternalStageId {name!r}")
        table.append(internal[name])
    return table


def main() -> None:
    sha = subprocess.run(
        ["gh", "pr", "view", str(PR), "--repo", REPO, "--json", "headRefOid",
         "-q", ".headRefOid"], check=True, capture_output=True
    ).stdout.decode().strip()
    forward_h = fetch("src/melee/gr/forward.h", sha)
    stage_c = fetch("src/melee/gr/stage.c", sha)

    internal = parse_enum(forward_h, "InternalStageId")
    external = parse_enum(forward_h, "ExternalStageId")
    table = parse_table(stage_c, internal)
    if len(table) != 0xD68 // 12:
        raise SystemExit(f"expected 286 table entries, parsed {len(table)}")

    out = {"pr": PR, "head_sha": sha, "external": external,
           "internal": internal, "table": table}
    (HERE / "expected.json").write_text(json.dumps(out, indent=1))
    print(f"expected.json written: head={sha} entries={len(table)}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
