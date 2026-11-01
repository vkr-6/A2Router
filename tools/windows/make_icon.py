"""Package the supplied PNG as a multiresolution Windows icon, preserving its aspect ratio."""

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage, QPainter


def create(source, destination):
    original = QImage(str(source))
    if original.isNull():
        raise ValueError("Invalid application logo")
    sizes = (16, 24, 32, 48, 64, 128, 256)
    entries, payloads = [], []
    offset = 6 + 16 * len(sizes)
    for size in sizes:
        image = QImage(size, size, QImage.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        scaled = original.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        painter.drawImage((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
        painter.end()
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        if not image.save(buffer, "PNG"):
            raise ValueError("Cannot encode application icon")
        payload = bytes(data)
        entries.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(payload), offset))
        payloads.append(payload)
        offset += len(payload)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(struct.pack("<HHH", 0, 1, len(sizes)) + b"".join(entries + payloads))


if __name__ == "__main__":
    create(sys.argv[1], sys.argv[2])
