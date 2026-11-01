"""Sparse channel-map editor; the native engine owns every sample operation."""

import math

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from a2router.models import BackendError


class MatrixEditor(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.pair = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        endpoints = QHBoxLayout()
        self.source_selector = QComboBox()
        self.destination_selector = QComboBox()
        for caption, selector, original in (
            ("Source", self.source_selector, window.source),
            ("Output", self.destination_selector, window.destination),
        ):
            endpoints.addWidget(QLabel(caption))
            endpoints.addWidget(selector, 1)
            selector.currentIndexChanged.connect(
                lambda _, selected=selector, target=original: target.setCurrentIndex(
                    target.findData(selected.currentData())
                )
            )
        layout.addLayout(endpoints)
        row = QHBoxLayout()
        self.preset = QComboBox()
        self.preset.addItems(
            [
                "Identity",
                "Stereo swap",
                "Mono sum (normalized)",
                "Downmix to stereo",
                "Downmix to mono",
                "Upmix stereo → surround",
            ]
        )
        row.addWidget(self.preset)
        self.conversion_level = QComboBox()
        self.conversion_level.addItem("Preserve front level", "preserve")
        self.conversion_level.addItem("−3 dB headroom", "headroom")
        self.conversion_level.addItem("Normalize peaks (quieter)", "normalize")
        self.conversion_level.setToolTip(
            "Conversion presets: preserve front channels at unity, reserve 3 dB, or normalize worst-case summed peaks. "
            "Summed channels can exceed full scale; inspect clipping counters and reduce gain if needed."
        )
        row.addWidget(self.conversion_level)
        apply_preset = QPushButton("Load preset")
        apply_preset.clicked.connect(self.load_preset)
        row.addWidget(apply_preset)
        self.gain = QDoubleSpinBox()
        self.gain.setRange(-60, 12)
        self.gain.setSuffix(" dB")
        row.addWidget(self.gain)
        set_gain = QPushButton("Set selected gains")
        set_gain.clicked.connect(self.apply_gain)
        row.addWidget(set_gain)
        remove = QPushButton("Disconnect selected")
        remove.clicked.connect(self.disconnect_selected)
        row.addWidget(remove)
        layout.addLayout(row)
        self.grid = QTableWidget()
        self.grid.setEditTriggers(QTableWidget.NoEditTriggers)
        self.grid.setSelectionMode(QTableWidget.ExtendedSelection)
        self.grid.cellDoubleClicked.connect(self.toggle_cell)
        self.grid.setToolTip(
            "Rows are source channels, columns are output channels. Double-click to connect/disconnect. Select cells to edit gains in bulk."
        )
        layout.addWidget(self.grid, 1)
        layout.addWidget(window.channel_group)
        row = QHBoxLayout()
        load = QPushButton("Load selected route")
        load.clicked.connect(self.load_route)
        row.addWidget(load)
        apply = QPushButton("Apply to selected route…")
        apply.clicked.connect(self.apply_route)
        row.addWidget(apply)
        row.addStretch()
        layout.addLayout(row)
        self.state = QLabel()
        self.state.setWordWrap(True)
        layout.addWidget(self.state)
        self.setEnabled(window.backend.capabilities().get("channel_routing", False))
        self.setToolTip("Requires the native channel-matrix API; unsupported on the current Linux backend.")
        window.source.currentIndexChanged.connect(self.refresh)
        window.destination.currentIndexChanged.connect(self.refresh)
        window.channel_group.toggled.connect(self.refresh)

    def connections(self):
        w = self.window
        rows = {}
        for row in range(w.channel_table.rowCount()):
            source = w.channel_table.cellWidget(row, 0).currentData()
            dest = w.channel_table.cellWidget(row, 1).currentData()
            rows[(source, dest)] = (row, w.channel_table.cellWidget(row, 2).value())
        return rows

    @staticmethod
    def labels(device):
        positions = device.get("positions", [])
        return [
            f"{i + 1} {positions[i]}" if i < len(positions) else f"Channel {i + 1}"
            for i in range(min(device.get("channels") or 0, 64))
        ]

    def refresh(self, *_):
        w = self.window
        for selector, original in (
            (self.source_selector, w.source),
            (self.destination_selector, w.destination),
        ):
            with QSignalBlocker(selector):
                entries = [(original.itemText(i), original.itemData(i)) for i in range(original.count())]
                current = [(selector.itemText(i), selector.itemData(i)) for i in range(selector.count())]
                if entries != current:
                    selector.clear()
                    for label, ident in entries:
                        selector.addItem(label, ident)
                selector.setCurrentIndex(selector.findData(original.currentData()))
        source = w.view_devices.get(w.source.currentData(), {})
        dest = w.view_devices.get(w.destination.currentData(), {})
        rows, columns = self.labels(source), self.labels(dest)
        pair = (source.get("id"), tuple(rows), dest.get("id"), tuple(columns))
        if pair != self.pair:
            self.pair = pair
            self.grid.setRowCount(len(rows))
            self.grid.setColumnCount(len(columns))
            self.grid.setVerticalHeaderLabels(rows)
            self.grid.setHorizontalHeaderLabels(columns)
            self.grid.horizontalHeader().setDefaultSectionSize(85)
            self.grid.verticalHeader().setDefaultSectionSize(23)
        connections = self.connections() if w.channel_group.isChecked() else {}
        for row in range(len(rows)):
            for col in range(len(columns)):
                text = f"{connections[(row, col)][1]:+.1f} dB" if (row, col) in connections else "·"
                item = self.grid.item(row, col)
                if item is None:
                    item = QTableWidgetItem()
                    item.setTextAlignment(Qt.AlignCenter)
                    self.grid.setItem(row, col, item)
                if item.text() != text:
                    item.setText(text)
        self.state.setText(
            f"{source.get('name', 'No source')} → {dest.get('name', 'No output')} | "
            "Unmapped outputs are silent. Presets and matrix edits change the draft until Add route or Apply."
        )

    def connect_cell(self, source, dest, gain):
        w = self.window
        old = self.connections().get((source, dest))
        if old:
            w.channel_table.cellWidget(old[0], 2).setValue(gain)
        else:
            w.add_channel_connection(source_index=source, destination_index=dest)
            w.channel_table.cellWidget(w.channel_table.rowCount() - 1, 2).setValue(gain)

    def toggle_cell(self, row, col):
        w = self.window
        if not w.channel_group.isChecked():
            w.channel_group.setChecked(True)
        existing = self.connections().get((row, col))
        if existing:
            w.channel_table.removeRow(existing[0])
        else:
            self.connect_cell(row, col, self.gain.value())
        self.refresh()

    def apply_gain(self):
        self.window.channel_group.setChecked(True)
        for index in self.grid.selectedIndexes():
            self.connect_cell(index.row(), index.column(), self.gain.value())
        self.refresh()

    def disconnect_selected(self):
        rows = self.connections()
        selected = {(i.row(), i.column()) for i in self.grid.selectedIndexes()}
        for row in sorted((rows[key][0] for key in selected if key in rows), reverse=True):
            self.window.channel_table.removeRow(row)
        self.refresh()

    def load_preset(self):
        w = self.window
        inputs, outputs = self.grid.rowCount(), self.grid.columnCount()
        name = self.preset.currentText()
        if name.startswith(("Downmix", "Upmix")):
            from a2router.channels import conversion_preset

            source = w.view_devices.get(w.source.currentData(), {})
            destination = w.view_devices.get(w.destination.currentData(), {})
            try:
                mapping = conversion_preset(
                    name,
                    source.get("positions", []),
                    destination.get("positions", []),
                    level=self.conversion_level.currentData(),
                )
            except BackendError as exc:
                w.error.setText(str(exc))
                return
            w.channel_table.setRowCount(0)
            w.channel_group.setChecked(True)
            for item in mapping:
                self.connect_cell(item["source"], item["destination"], 20 * math.log10(item["gain"]))
            self.refresh()
            self.state.setText(
                "Conversion draft ready: use Apply to selected route or Add route to activate. "
                "LFE is excluded; upmix duplicates channels. Preserve-level sums can clip; choose headroom if needed."
            )
            return
        if name == "Stereo swap" and (inputs != 2 or outputs != 2):
            w.error.setText("Stereo swap requires two source and two destination channels")
            return
        if not inputs or not outputs:
            w.error.setText("Select endpoints with reported channel counts")
            return
        if name == "Identity" and inputs > outputs:
            w.error.setText("Identity would omit source channels; create an explicit custom map instead")
            return
        if name.startswith("Mono sum") and inputs * outputs > 1024:
            w.error.setText("This preset exceeds the 1024-connection engine limit")
            return
        w.channel_table.setRowCount(0)
        w.channel_group.setChecked(True)
        if name == "Stereo swap":
            self.connect_cell(0, 1, 0)
            self.connect_cell(1, 0, 0)
        elif name.startswith("Mono sum"):
            # Equal-power safety is not guaranteed for coherent signals: use 1/N
            # to keep full-scale coherent inputs within the native peak ceiling.
            gain = max(-60, 20 * math.log10(1 / inputs))
            for source in range(inputs):
                for dest in range(outputs):
                    self.connect_cell(source, dest, gain)
        else:
            for channel in range(inputs):
                self.connect_cell(channel, channel, 0)
        self.refresh()

    def selected_route(self):
        selected = self.window.route_tree.selectedItems()
        if not selected:
            self.window.error.setText("Select a route in Routing Configuration first")
            return None
        return self.window.view_routes.get(selected[0].data(0, Qt.UserRole))

    def load_route(self):
        route = self.selected_route()
        if not route:
            return
        w = self.window
        w.source.setCurrentIndex(w.source.findData(route["source_id"]))
        w.destination.setCurrentIndex(w.destination.findData(route["destination_id"]))
        if (
            w.source.currentData() != route["source_id"]
            or w.destination.currentData() != route["destination_id"]
        ):
            w.error.setText(
                "Cannot edit a map while its endpoints are unavailable; profile definition is retained"
            )
            return
        if any(c["gain"] <= 0 or not -60 <= 20 * math.log10(c["gain"]) <= 12 for c in route["channel_map"]):
            w.error.setText(
                "This map contains a gain outside this dB editor's range; the original route is unchanged"
            )
            return
        w.channel_group.setChecked(bool(route["channel_map"]))
        if route["channel_map"]:
            w.channel_table.setRowCount(0)
            for connection in route["channel_map"]:
                self.connect_cell(
                    connection["source"], connection["destination"], 20 * math.log10(connection["gain"])
                )
        self.refresh()

    def apply_route(self):
        route = self.selected_route()
        w = self.window
        if not route:
            return
        if (w.source.currentData(), w.destination.currentData()) != (
            route["source_id"],
            route["destination_id"],
        ):
            w.error.setText("Load the selected route before applying its map")
            return
        mapping = (
            [
                {"source": source, "destination": dest, "gain": 10 ** (gain / 20)}
                for (source, dest), (_, gain) in self.connections().items()
            ]
            if w.channel_group.isChecked()
            else []
        )
        if w.channel_group.isChecked() and not mapping:
            w.error.setText("An empty custom map is invalid; disable custom routing for automatic mapping")
            return
        if (
            QMessageBox.question(
                w,
                "Apply channel mapping?",
                "This can restart the selected source and its outputs. Unmapped channels are silent. Apply?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return
        w.submit(lambda: w.backend.set_route_channel_map(route["id"], mapping))
