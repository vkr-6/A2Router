"""Package an already-frozen Linux bundle; does not install or activate anything."""

import argparse
import hashlib
import math
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path


def package(bundle, output, version="0.1.0", deb=True):
    root = Path(__file__).resolve().parents[2]
    bundle, output = Path(bundle).resolve(), Path(output).resolve()
    if not (bundle / "a2router").is_file():
        raise ValueError("Frozen a2router executable is missing")
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "a2router-linux-x86_64.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        stream.add(bundle, arcname="A2Router-linux-x86_64")
    artifacts = [archive]
    if deb:
        if not shutil.which("dpkg-deb"):
            raise RuntimeError("dpkg-deb is required for the Debian package")
        with tempfile.TemporaryDirectory(prefix="a2router-deb-") as directory:
            stage = Path(directory)
            target = stage / "opt/a2router"
            shutil.copytree(bundle, target, symlinks=True)
            launcher = stage / "usr/bin/a2router"
            launcher.parent.mkdir(parents=True)
            launcher.write_text('#!/bin/sh\nexec /opt/a2router/a2router "$@"\n')
            launcher.chmod(0o755)
            desktop = stage / "usr/share/applications/a2router.desktop"
            desktop.parent.mkdir(parents=True)
            desktop.write_text(
                "[Desktop Entry]\nType=Application\nName=A2Router\nComment=Advanced audio routing\nExec=a2router\nIcon=a2router\nTerminal=false\nCategories=AudioVideo;Audio;Mixer;\n"
            )
            icon = stage / "usr/share/pixmaps/a2router.png"
            icon.parent.mkdir(parents=True)
            shutil.copy2(root / "a2router/assets/a2router.png", icon)
            control = stage / "DEBIAN/control"
            control.parent.mkdir()
            size = math.ceil(sum(p.stat().st_size for p in stage.rglob("*") if p.is_file()) / 1024)
            control.write_text(
                f"Package: a2router\nVersion: {version}\nArchitecture: amd64\nMaintainer: A2Router contributors <vkr-6@users.noreply.github.com>\nSection: sound\nPriority: optional\nInstalled-Size: {size}\nDepends: pipewire, pipewire-pulse, pulseaudio-utils, libegl1, libopengl0, libxcb-cursor0, libxkbcommon-x11-0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-render-util0, libxcb-xinerama0\nHomepage: https://github.com/vkr-6/A2Router\nDescription: Compact desktop audio router\n Native PipeWire routing with a bundled Python/Qt runtime.\n"
            )
            artifact = output / f"a2router_{version}_amd64.deb"
            subprocess.run(
                ["dpkg-deb", "--root-owner-group", "--build", str(stage), str(artifact)], check=True
            )
            artifacts.append(artifact)
    checksum = output / "SHA256SUMS-linux.txt"
    lines = []
    for artifact in artifacts:
        with artifact.open("rb") as stream:
            lines.append(f"{hashlib.file_digest(stream, 'sha256').hexdigest()}  {artifact.name}\n")
    checksum.write_text("".join(lines))
    return artifacts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--output", default="dist")
    parser.add_argument("--version", default="0.1.0")
    parser.add_argument("--no-deb", action="store_true")
    args = parser.parse_args()
    package(args.bundle, args.output, args.version, not args.no_deb)


if __name__ == "__main__":
    main()
