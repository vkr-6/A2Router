"""Embed provenance before freezing; original checkout supplies the Git identity."""

import argparse
import json
from pathlib import Path

from a2router.build_info import collect_build_info


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--native-dll")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(collect_build_info(args.source_root, args.native_dll), indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
