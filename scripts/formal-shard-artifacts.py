import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


BASE = "939438ce12e4e5cb156a0de22ac221b5384edb0b"
ACTION = re.compile(r"action-[0-9a-f]{24}\.json\.gz\Z")
CACHE = Path(".spec-cache/formal")


def info(file):
    if file.is_symlink() or not file.is_file():
        raise ValueError(f"Expected a regular action receipt: {file}")
    with file.open("rb") as contents:
        return {"bytes": file.stat().st_size, "sha256": hashlib.file_digest(contents, "sha256").hexdigest()}


def assignment(shard):
    output = subprocess.check_output(["node", "scripts/precompute-formal-shard.ts", str(shard), "2", "--list"], text=True)
    return json.loads(output)


def identity():
    return {"source": BASE, "checkout": os.environ["GITHUB_SHA"], "run": os.environ["GITHUB_RUN_ID"], "attempt": os.environ["GITHUB_RUN_ATTEMPT"]}


def stage(shard, dest):
    raw = dest / "raw"
    raw.mkdir(parents=True)
    actions = {}
    for file in sorted(CACHE.iterdir()):
        if ACTION.fullmatch(file.name):
            actions[file.name] = info(file)
            shutil.copyfile(file, raw / file.name)
    if not actions or any(meta["bytes"] <= 0 for meta in actions.values()):
        raise ValueError(f"No usable actions for shard {shard}")
    (dest / "manifest.json").write_text(json.dumps({**identity(), "assignment": assignment(shard), "actions": actions}, indent=2) + "\n")
    print(f"Shard {shard} publishes {len(actions)} actions ({sum(meta['bytes'] for meta in actions.values())} bytes)")


def restore(source):
    CACHE.mkdir(parents=True, exist_ok=True)
    if any(CACHE.iterdir()):
        raise ValueError("Final formal action cache was not empty")
    expected = identity()
    folders = {f"formal-raw-{expected['attempt']}-{shard}" for shard in (1, 2)}
    if {item.name for item in source.iterdir()} != folders:
        raise ValueError("Expected exactly the two current attempt shards")
    verified = {}
    modules = []
    for shard in (1, 2):
        folder = source / f"formal-raw-{expected['attempt']}-{shard}"
        manifest_path = folder / "manifest.json"
        if manifest_path.is_symlink() or {item.name for item in folder.iterdir()} != {"manifest.json", "raw"}:
            raise ValueError(f"Unexpected shard bundle {folder}")
        manifest = json.loads(manifest_path.read_text())
        if any(manifest.get(key) != value for key, value in expected.items()) or manifest.get("assignment") != assignment(shard):
            raise ValueError(f"Source, run, or assignment mismatch in shard {shard}")
        modules.extend(manifest["assignment"]["modules"])
        raw = folder / "raw"
        declared = manifest["actions"]
        if raw.is_symlink() or not declared or {item.name for item in raw.iterdir()} != set(declared):
            raise ValueError(f"Action manifest mismatch in shard {shard}")
        for name, sha in declared.items():
            if not ACTION.fullmatch(name) or sha["bytes"] <= 0 or info(raw / name) != sha:
                raise ValueError(f"Receipt integrity mismatch in shard {shard}: {name}")
            if name in verified and verified[name][1] != sha:
                raise ValueError(f"Conflicting receipts between shards: {name}")
            verified[name] = (raw / name, sha)
    if len(modules) != 150 or len(set(modules)) != 150:
        raise ValueError("Expected each of the 150 models in exactly one shard")
    for name, (file, _) in verified.items():
        shutil.copyfile(file, CACHE / name)
    print(f"Verified both manifests for all {len(modules)} models and seeded {len(verified)} unique current-run actions ({sum(v['bytes'] for _, v in verified.values())} bytes)")


if sys.argv[1] == "stage":
    stage(int(sys.argv[2]), Path(sys.argv[3]))
elif sys.argv[1] == "restore":
    restore(Path(sys.argv[2]))
else:
    raise ValueError("Expected stage or restore")
