"""Original outline icons rendered at device scale using Qt's painter."""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap, QPolygonF


def _draw(painter, title):
    def line(x1, y1, x2, y2):
        painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    if title == "Audio Routing":
        for x, y in ((4, 6), (4, 18), (20, 6), (20, 18)):
            painter.drawEllipse(QPointF(x, y), 2, 2)
        for start, end in ((6, 18), (18, 6)):
            path = QPainterPath(QPointF(6, start))
            path.cubicTo(12, start, 12, end, 18, end)
            painter.drawPath(path)
    elif title == "Mixer":
        for x, y in ((5, 8), (12, 15), (19, 10)):
            line(x, 3, x, y - 2)
            line(x, y + 2, x, 21)
            painter.drawRoundedRect(QRectF(x - 2.5, y - 2, 5, 4), 1, 1)
    elif title == "Devices":
        painter.drawRoundedRect(QRectF(3, 4, 18, 13), 1, 1)
        line(12, 17, 12, 21)
        line(8, 21, 16, 21)
    elif title == "Calibration":
        painter.drawRoundedRect(QRectF(9, 3, 6, 11), 3, 3)
        painter.drawArc(QRectF(6, 6, 12, 12), 180 * 16, 180 * 16)
        line(12, 18, 12, 21)
        line(8, 21, 16, 21)
    elif title == "Settings":
        points = []
        for i in range(32):
            radius = 9 if i % 4 in (1, 2) else 7
            angle = i * math.tau / 32
            points.append(QPointF(12 + radius * math.cos(angle), 12 + radius * math.sin(angle)))
        painter.drawPolygon(QPolygonF(points))
        painter.drawEllipse(QPointF(12, 12), 3, 3)


def navigation_icon(title, palette):
    icon = QIcon()
    for mode in (QIcon.Normal, QIcon.Active, QIcon.Disabled):
        for state in (QIcon.Off, QIcon.On):
            if mode == QIcon.Disabled:
                color = palette.color(QPalette.Disabled, QPalette.ButtonText)
            else:
                color = palette.color(
                    QPalette.Highlight if state == QIcon.On or mode == QIcon.Active else QPalette.ButtonText
                )
            for scale in (1, 2, 3):
                pixels = QPixmap(18 * scale, 18 * scale)
                pixels.fill(Qt.transparent)
                painter = QPainter(pixels)
                painter.setRenderHint(QPainter.Antialiasing)
                painter.scale(18 * scale / 24, 18 * scale / 24)
                painter.setPen(QPen(color, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                painter.setBrush(Qt.NoBrush)
                _draw(painter, title)
                painter.end()
                pixels.setDevicePixelRatio(scale)
                icon.addPixmap(pixels, mode, state)
    return icon
