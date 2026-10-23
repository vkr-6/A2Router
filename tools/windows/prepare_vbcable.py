"""Verify and unpack the original vendor package; never execute it during builds."""

import argparse
import hashlib
import zipfile
from pathlib import Path

ARCHIVE_SHA256 = "b950e39f01af1d04ea623c8f6d8eb9b6ea5c477c637295fabf20631c85116bfb"


def prepare(archive, destination):
    archive, destination = Path(archive), Path(destination)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("VB-CABLE package hash differs from the supplied Pack45 archive")
    with zipfile.ZipFile(archive) as source:
        # Pack45 contains flat files. Reject paths/symlinks and oversized payloads.
        for item in source.infolist():
            if "/" in item.filename or "\\" in item.filename or item.file_size > 10_000_000:
                raise ValueError("Unexpected entry in VB-CABLE archive")
        required = {"VBCABLE_Setup_x64.exe", "readme.txt", "vbMmeCable64_win10.inf"}
        if not required.issubset(source.namelist()):
            raise ValueError("Incomplete VB-CABLE package")
        destination.mkdir(parents=True, exist_ok=True)
        source.extractall(destination)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("destination", type=Path)
    options = parser.parse_args()
    print(prepare(options.archive, options.destination))
