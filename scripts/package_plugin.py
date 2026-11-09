#!/usr/bin/env python3
"""Assemble CI-built binaries into the self-contained Git marketplace package."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ("Darwin-arm64", "Darwin-x86_64", "Linux-x86_64")


def package(artifacts, source_commit):
    plugin = ROOT / "plugins/asm"
    version = json.loads((plugin / ".codex-plugin/plugin.json").read_text())["version"]
    manifest = {}
    paths = {}
    for target in TARGETS:
        matches = list(artifacts.rglob(target + ".json"))
        if len(matches) != 1:
            raise ValueError("Expected one build record per supported platform")
        record = json.loads(matches[0].read_text())
        if record.get("source_commit") != source_commit or record.get("version") != "asm " + version or record.get("file") != "asm-" + target:
            raise ValueError("Build provenance/version mismatch")
        binary = matches[0].parent / record["file"]
        if hashlib.sha256(binary.read_bytes()).hexdigest() != record.get("sha256"):
            raise ValueError("Build checksum mismatch")
        manifest[target] = record
        paths[target] = binary
    destination = plugin / "bin"
    destination.mkdir(exist_ok=True)
    for target, binary in paths.items():
        shutil.copyfile(binary, destination / ("asm-" + target))
        (destination / ("asm-" + target)).chmod(0o755)
    # Publish metadata last; interrupted assembly fails closed on checksum mismatch.
    fd, temporary = tempfile.mkstemp(dir=destination)
    try:
        with os.fdopen(fd, "w") as file:
            json.dump(manifest, file, indent=2)
            file.write("\n")
        os.replace(temporary, destination / "manifest.json")
    finally:
        Path(temporary).unlink(missing_ok=True)
    (plugin / "config").mkdir(exist_ok=True)
    shutil.copyfile(ROOT / "examples/demo.json", plugin / "config/demo.json")
    shutil.copyfile(ROOT / "LICENSE", plugin / "LICENSE")
    print("Packaged three native binaries with pinned checksums and source commit")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("artifacts", type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    package(args.artifacts, args.source_commit)
