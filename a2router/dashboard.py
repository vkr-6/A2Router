"""Compact device mixer with observed peak meters and real control callbacks."""

import math
from collections import deque

from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from a2router.models import device_state_label


class PeakMeter(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.samples = deque(maxlen=160)
        self.available = False
        self.setFixedHeight(6)
        self.setAccessibleName("Observed endpoint level")
        self.setToolTip("Current observed peak level, from −60 to 0 dBFS. No history graph.")

    def observe(self, timestamp, peak):
        available = timestamp is not None and peak is not None and math.isfinite(peak)
        if available != self.available:
            self.available = available
            self.update()
        if not available:
            return
        if self.samples and timestamp <= self.samples[-1][0]:
            return
        self.samples.append((timestamp, max(0.0, min(1.0, peak))))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.fillRect(rect, self.palette().mid())
        if self.available and self.samples:
            peak = self.samples[-1][1]
            fraction = max(0.0, min(1.0, (20 * math.log10(max(peak, 0.001)) + 60) / 60))
            rect.setWidth(round(rect.width() * fraction))
            painter.fillRect(rect, self.palette().highlight())


class DeviceCard(QFrame):
    def __init__(self, device_id, on_volume, on_mute, parent=None):
        super().__init__(parent)
        self.setObjectName("DeviceCard")
        self.device_id, self.on_volume, self.on_mute = device_id, on_volume, on_mute
        self.volume_timer = QTimer(self)
        self.volume_timer.setSingleShot(True)
        self.volume_timer.setInterval(180)
        self.volume_timer.timeout.connect(lambda: on_volume(device_id, self.volume.value() / 100))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        header = QHBoxLayout()
        self.name = QLabel()
        self.name.setObjectName("CardTitle")
        self.name.setWordWrap(True)
        self.direction = QLabel()
        self.direction.setObjectName("Badge")
        header.addWidget(self.name, 1)
        header.addWidget(self.direction)
        layout.addLayout(header)
        self.format_label = QLabel()
        self.format_label.setObjectName("MutedText")
        layout.addWidget(self.format_label)
        self.graph = PeakMeter()
        layout.addWidget(self.graph)
        row = QHBoxLayout()
        self.peak = QLabel("— dBFS")
        self.peak.setObjectName("MutedText")
        row.addWidget(QLabel("Peak"))
        row.addStretch()
        row.addWidget(self.peak)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.mute = QPushButton("Mute")
        self.mute.setCheckable(True)
        self.mute.setFixedWidth(72)
        self.mute.clicked.connect(lambda checked: on_mute(device_id, checked))
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setAccessibleName("Master device volume")
        self.volume.valueChanged.connect(self.volume_changed)
        self.percent = QLabel("—")
        self.percent.setFixedWidth(42)
        self.percent.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self.mute)
        row.addWidget(self.volume, 1)
        row.addWidget(self.percent)
        layout.addLayout(row)

    def volume_changed(self, value):
        self.percent.setText(f"{value}%")
        self.volume_timer.start()

    def populate(self, device):
        self.name.setText(device["name"])
        cable = device.get("properties", {}).get("virtual_driver") == "VB-CABLE"
        self.direction.setText("CABLE" if cable else "OUTPUT" if device["kind"] == "output" else "INPUT")
        self.graph.setToolTip(
            "Incoming cable peak before routed-stream gain" if cable else "Observed system endpoint peak"
        )
        rate = device.get("sample_rate")
        text = (
            f"{device.get('channels') or '?'} ch  ·  {rate / 1000:g} kHz"
            if rate
            else f"{device.get('channels') or '?'} ch"
        )
        self.format_label.setText(text + "  ·  " + device_state_label(device.get("state", "unknown")))
        controls = device.get("properties", {}).get("controls", {})
        volume_available = controls.get("volume_available", False)
        self.volume.setToolTip(
            controls.get("reason", "")
            if not volume_available
            else controls.get("scope", "System endpoint volume")
        )
        self.mute.setToolTip(self.volume.toolTip())
        self.volume.setEnabled(volume_available)
        self.mute.setEnabled(volume_available)
        if volume_available:
            if not self.volume.isSliderDown() and not self.volume_timer.isActive():
                value = round(controls["volume"] * 100)
                with QSignalBlocker(self.volume):
                    self.volume.setValue(value)
                self.percent.setText(f"{value}%")
            with QSignalBlocker(self.mute):
                self.mute.setChecked(controls.get("muted", False))
            self.mute.setText("Unmute" if controls.get("muted") else "Mute")
        else:
            self.percent.setText("—")
            self.volume.setToolTip(controls.get("reason", "Master volume is unavailable for this endpoint"))
        peak = controls.get("peak") if controls.get("peak_available") else None
        self.graph.observe(controls.get("observed_at"), peak)
        self.peak.setText(
            "— dBFS" if peak is None else "−∞ dBFS" if peak <= 0 else f"{20 * math.log10(peak):.1f} dBFS"
        )


class Dashboard(QWidget):
    def __init__(self, on_volume, on_mute):
        super().__init__()
        self.on_volume, self.on_mute = on_volume, on_mute
        self.cards = {}
        self.card_order = []
        self.latest_devices, self.latest_routes = [], []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        summary = QHBoxLayout()
        self.counters = {}
        for key, label in (
            ("outputs", "Outputs"),
            ("inputs", "Inputs"),
            ("routes", "Active routes"),
            ("errors", "Route errors"),
        ):
            frame = QFrame(self)
            frame.setObjectName("SummaryCard")
            box = QVBoxLayout(frame)
            number = QLabel("0")
            number.setObjectName("SummaryNumber")
            box.addWidget(number)
            caption = QLabel(label)
            caption.setObjectName("MutedText")
            box.addWidget(caption)
            summary.addWidget(frame)
            self.counters[key] = number
        # Counters remain internal observations; the mixer displays compact strips.
        for index in range(summary.count()):
            summary.itemAt(index).widget().hide()
        tools = QHBoxLayout()
        heading = QLabel("Device mixer")
        heading.setObjectName("SectionTitle")
        tools.addWidget(heading, 1)
        self.filter_kind = QComboBox()
        self.filter_kind.addItems(["All devices", "Outputs", "Inputs", "Virtual"])
        self.filter_kind.setMinimumWidth(125)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter devices…")
        self.search.setMaximumWidth(235)
        tools.addWidget(self.filter_kind)
        tools.addWidget(self.search)
        layout.addLayout(tools)
        self.filter_kind.currentTextChanged.connect(self.filter_changed)
        self.search.textChanged.connect(self.filter_changed)
        self.empty = QLabel("No audio endpoints available. Connect a device and refresh.")
        layout.addWidget(self.empty)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        self.grid = QGridLayout(content)
        self.grid.setContentsMargins(0, 0, 6, 0)
        self.grid.setSpacing(6)
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 1)
        self.grid.setRowStretch(1000, 1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

    def filter_changed(self):
        self.populate(self.latest_devices, self.latest_routes)

    def populate(self, devices, routes):
        self.latest_devices, self.latest_routes = devices, routes
        all_devices = []
        cable_groups = set()
        for device in devices:
            props = device.get("properties", {})
            if device.get("monitor_of") and not props.get("capture_endpoint_id"):
                continue
            if props.get("virtual_driver") == "VB-CABLE":
                if not props.get("capture_endpoint_id"):
                    continue
                group = props.get("feedback_group", "vbcable:base")
                if group in cable_groups:
                    continue
                cable_groups.add(group)
            all_devices.append(device)
        routed_outputs = {r["destination_id"] for r in routes if r.get("enabled")}
        all_devices.sort(
            key=lambda d: (
                0
                if d.get("properties", {}).get("virtual_driver") == "VB-CABLE"
                else 1
                if d["id"] in routed_outputs
                else 2,
                d["name"].casefold(),
            )
        )
        query = self.search.text().strip().casefold()
        kind = self.filter_kind.currentText()
        visible = [
            device
            for device in all_devices
            if query in device["name"].casefold()
            and (
                kind == "All devices"
                or (kind == "Outputs" and device["kind"] == "output")
                or (kind == "Inputs" and device["kind"] == "input")
                or (kind == "Virtual" and device.get("virtual") is True)
            )
        ]
        wanted = {d["id"] for d in all_devices}
        for ident in set(self.cards) - wanted:
            card = self.cards.pop(ident)
            card.volume_timer.stop()
            self.grid.removeWidget(card)
            card.deleteLater()
        order = [d["id"] for d in visible]
        relayout = order != self.card_order
        self.card_order = order
        for ident, card in self.cards.items():
            card.setVisible(ident in order)
        for index, device in enumerate(visible):
            ident = device["id"]
            if ident not in self.cards:
                self.cards[ident] = DeviceCard(ident, self.on_volume, self.on_mute)
            card = self.cards[ident]
            card.show()
            if relayout:
                self.grid.addWidget(card, index, 0, 1, 2)
            card.populate(device)
        self.empty.setText(
            "No devices match your filter."
            if all_devices
            else "No audio endpoints available. Connect a device and refresh."
        )
        self.empty.setVisible(not visible)
        values = {
            "outputs": sum(d["kind"] == "output" for d in all_devices),
            "inputs": sum(d["kind"] == "input" for d in all_devices),
            "routes": sum(r["status"] == "connected" for r in routes),
            "errors": sum(r["status"] == "error" for r in routes),
        }
        for key, value in values.items():
            self.counters[key].setText(str(value))
