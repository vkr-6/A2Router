#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
python3 -m PyInstaller --noconfirm --clean --onedir --windowed --name a2router \
  --hidden-import PySide6.QtSvg --hidden-import numpy.fft --add-data "$PWD/a2router/assets:a2router/assets" \
  --paths . --distpath build/linux-freeze --workpath build/linux-pyinstaller \
  --specpath build tools/windows/portable_entry.py
bundle=build/linux-freeze/a2router
cp LICENSE LICENSING.md THIRD_PARTY_NOTICES.md "$bundle/"
cp tools/linux/README.txt "$bundle/README.txt"
python3 tools/windows/collect_licenses.py "$bundle"
QT_QPA_PLATFORM=offscreen "$bundle/a2router" --self-test "$bundle/packaged-smoke.json" --mock
python3 tools/linux/package.py --bundle "$bundle" --output dist
