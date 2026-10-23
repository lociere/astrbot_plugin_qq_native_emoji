"""Validate and copy QQ's metadata to an existing shared directory; never copy pictures."""

import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="QQ's face_config.json")
    parser.add_argument("destination", type=Path, help="Output JSON in a shared data directory")
    args = parser.parse_args()
    if args.source.resolve() == args.destination.resolve():
        parser.error("Source and destination must differ")
    if args.destination.exists():
        parser.error("Destination already exists; choose a new name or replace it yourself")
    if args.source.stat().st_size > 8 * 1024 * 1024:
        parser.error("Source exceeds the 8 MiB limit")
    data = json.loads(args.source.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or not isinstance(data.get("sysface"), list):
        parser.error("Not a QQ face_config.json: missing sysface array")
    # O_EXCL prevents accidental overwrites, including races with another export.
    fd = os.open(args.destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        json.dump(data, output, ensure_ascii=False)
    print(
        f"Exported metadata: {len(data['sysface'])} faces, {len(data.get('emoji', []))} Unicode entries"
    )


if __name__ == "__main__":
    main()
