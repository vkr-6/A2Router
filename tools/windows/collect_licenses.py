"""Collect actual installed runtime/license notices beside the portable EXEs."""

import importlib.metadata
import json
import platform
import shutil
import sys
from pathlib import Path


def main():
    destination = Path(sys.argv[1])
    licenses = destination / "licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    versions = {}
    for name in ("PySide6-Essentials", "shiboken6", "numpy", "pyinstaller"):
        distribution = importlib.metadata.distribution(name)
        versions[name] = distribution.version
        for file in distribution.files or ():
            if any(
                part.lower() in ("licenses", "license", "copying", "copyright", "license.txt", "copying.txt")
                for part in file.parts
            ):
                source = Path(distribution.locate_file(file))
                if source.is_file():
                    target = licenses / name / Path(*file.parts[1:])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.exists() and sys.platform == "linux":
        python_license = Path(
            f"/usr/share/doc/python{sys.version_info.major}.{sys.version_info.minor}/copyright"
        )
    if python_license.exists():
        shutil.copy2(python_license, licenses / "Python-LICENSE.txt")
    data = {
        "python": sys.version,
        "platform": platform.platform(),
        "packages": versions,
        "native_bridge_api": 2 if sys.platform == "win32" else None,
        "virtual_endpoint_driver": (
            "VB-CABLE included unchanged; installation and playback unverified"
            if (destination / "vendor" / "vb-cable" / "VBCABLE_Setup_x64.exe").exists()
            else "VB-CABLE payload absent"
        ),
    }
    (destination / "build-info.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
