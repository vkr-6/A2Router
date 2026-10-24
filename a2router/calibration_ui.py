"""Review-first calibration UI. Native calls and FFT analysis run on the worker."""

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class CalibrationPanel(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.running = False
        self.timestamp = None
        self.current_result = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        form_group = QGroupBox("Measure speaker arrival times")
        form = QFormLayout(form_group)
        self.microphone, self.reference = QComboBox(), QComboBox()
        self.channel = QSpinBox()
        self.channel.setRange(1, 1)
        self.microphone.currentIndexChanged.connect(self.microphone_changed)
        form.addRow("Microphone", self.microphone)
        form.addRow("Microphone channel", self.channel)
        self.outputs = QListWidget()
        self.outputs.setMaximumHeight(110)
        form.addRow("Outputs to measure", self.outputs)
        form.addRow("Reference output", self.reference)
        self.passes = QSpinBox()
        self.passes.setRange(1, 5)
        self.passes.setValue(3)
        form.addRow("Passes per output", self.passes)
        self.level = QDoubleSpinBox()
        self.level.setRange(-50, -20)
        self.level.setValue(-36)
        self.level.setSuffix(" dBFS")
        form.addRow("Test level", self.level)
        note = QLabel(
            "Keep the microphone fixed at the listening position. A quiet chirp tests the first output channel, one device at a time. Other managed routes stop temporarily and are restored. Close noisy apps; their playback is not controlled here."
        )
        note.setWordWrap(True)
        form.addRow(note)
        layout.addWidget(form_group)
        actions = QHBoxLayout()
        self.start = QPushButton("Measure delays…")
        self.start.clicked.connect(self.measure)
        self.cancel = QPushButton("Cancel")
        self.cancel.clicked.connect(self.cancel_measurement)
        self.cancel.setEnabled(False)
        actions.addWidget(self.start)
        actions.addWidget(self.cancel)
        actions.addStretch()
        layout.addLayout(actions)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Output", "Relative arrival", "Compensation (ms)", "Confidence", "Pass spread"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate([250, 150, 180, 120, 120]):
            self.table.setColumnWidth(column, width)
        layout.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.restart = QCheckBox("Allow source restart if delay exceeds current buffer")
        row.addWidget(self.restart)
        self.apply = QPushButton("Apply reviewed delays…")
        self.apply.clicked.connect(self.apply_delays)
        self.revert = QPushButton("Revert edits")
        self.revert.clicked.connect(self.revert_edits)
        self.export = QPushButton("Export measurement…")
        self.export.clicked.connect(self.export_results)
        row.addWidget(self.apply)
        row.addWidget(self.revert)
        row.addWidget(self.export)
        layout.addLayout(row)
        self.form_group = form_group
        self.devices = {}
        window.results.progress.connect(self.report_progress)
        self.populate(None, [])

    def microphone_changed(self):
        device = self.devices.get(self.microphone.currentData(), {})
        self.channel.setMaximum(max(1, device.get("channels") or 1))

    def populate(self, result, devices):
        w = self.window
        self.devices = {d["id"]: d for d in devices}
        if not self.running:
            w._update_combo(
                self.microphone,
                [
                    (d["id"], d["name"])
                    for d in devices
                    if d["kind"] == "input" and not d.get("monitor_of") and d.get("virtual") is not True
                ],
            )
            w._update_combo(
                self.reference,
                [
                    (d["id"], d["name"])
                    for d in devices
                    if d["kind"] == "output" and d.get("virtual") is not True
                ],
            )
            wanted = {
                d["id"]: d["name"] for d in devices if d["kind"] == "output" and d.get("virtual") is not True
            }
            existing = {
                self.outputs.item(i).data(Qt.UserRole): self.outputs.item(i)
                for i in range(self.outputs.count())
            }
            for i in reversed(range(self.outputs.count())):
                if self.outputs.item(i).data(Qt.UserRole) not in wanted:
                    self.outputs.takeItem(i)
            for ident, name in wanted.items():
                if ident in existing:
                    existing[ident].setText(name)
                else:
                    item = QListWidgetItem(name)
                    item.setData(Qt.UserRole, ident)
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Unchecked)
                    self.outputs.addItem(item)
            self.microphone_changed()
        capable = w.backend.capabilities().get("calibration", False)
        self.start.setEnabled(
            capable
            and not self.running
            and not w.busy
            and self.microphone.count() > 0
            and self.outputs.count() >= 2
        )
        self.start.setToolTip(
            "Real WASAPI microphone capture and chirp playback"
            if capable
            else "Requires the updated native Windows calibration API; not available on Linux"
        )
        self.apply.setEnabled(
            result is not None
            and not self.running
            and not w.busy
            and w.backend.capabilities().get("route_delay", False)
        )
        self.revert.setEnabled(result is not None and not self.running)
        self.export.setEnabled(result is not None and not self.running)
        if not capable and not self.running:
            self.status.setText(
                "Native acoustic calibration is unavailable with this backend. Manual route delays remain available where supported."
            )
        if result and result.get("timestamp") != self.timestamp:
            self.current_result = result
            self.timestamp = result["timestamp"]
            self.render_result()

    def render_result(self):
        if not self.current_result:
            return
        self.table.setRowCount(len(self.current_result["outputs"]))
        for row, item in enumerate(self.current_result["outputs"]):
            name = self.devices.get(item["device_id"], {}).get("name", item["device_id"])
            for col, text in [
                (0, name),
                (1, f"{item['relative_ms']:+.2f} ms"),
                (3, f"{item['confidence']:.0%}"),
                (4, f"{item['spread_ms']:.2f} ms"),
            ]:
                cell = QTableWidgetItem(text)
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, col, cell)
            delay = QSpinBox()
            delay.setRange(0, 10000)
            delay.setValue(round(item["compensation_ms"]))
            delay.setProperty("device_id", item["device_id"])
            self.table.setCellWidget(row, 2, delay)
        self.status.setText(
            f"Stored measurement: {self.timestamp}. Compensation aligns to the slowest measured output. Native delays round to integer milliseconds. Startup scheduling, room reflections and transport variability limit accuracy."
        )

    def measure(self):
        w = self.window
        if w.busy or self.running:
            return
        outputs = [
            self.outputs.item(i).data(Qt.UserRole)
            for i in range(self.outputs.count())
            if self.outputs.item(i).checkState() == Qt.Checked
        ]
        if (
            not self.microphone.currentData()
            or len(outputs) < 2
            or self.reference.currentData() not in outputs
        ):
            w.error.setText(
                "Choose a microphone, at least two outputs, and a reference among the checked outputs"
            )
            return
        if (
            QMessageBox.question(
                self,
                "Start acoustic measurement?",
                "Quiet chirps will play through the selected speakers. Keep the microphone fixed, use a safe hardware volume and keep all other audio quiet. Temporarily stop managed routes and measure?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return
        mic, ref, passes, level, channel = (
            self.microphone.currentData(),
            self.reference.currentData(),
            self.passes.value(),
            self.level.value(),
            self.channel.value() - 1,
        )
        self.running = True
        self.start.setEnabled(False)
        self.apply.setEnabled(False)
        self.cancel.setEnabled(True)
        self.form_group.setEnabled(False)
        self.progress.setRange(0, len(outputs) * passes)
        self.progress.setValue(0)

        def work():
            return w.controller.measure_calibration(
                mic, outputs, ref, passes, level, channel, w.results.progress.emit
            )

        w.submit(work)

    def operation_finished(self, message=""):
        if self.running:
            self.running = False
            self.cancel.setEnabled(False)
            self.form_group.setEnabled(True)
            if message:
                self.status.setText(message)

    def report_progress(self, done, total, message):
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.status.setText(message)

    def cancel_measurement(self):
        if self.running and hasattr(self.window.backend, "cancel_calibration"):
            self.window.backend.cancel_calibration()
            self.status.setText("Cancelling; previous routing will be restored…")

    def revert_edits(self):
        self.render_result()

    def apply_delays(self):
        if not self.current_result:
            return
        delays = {
            self.table.cellWidget(row, 2).property("device_id"): self.table.cellWidget(row, 2).value()
            for row in range(self.table.rowCount())
        }
        if (
            QMessageBox.question(
                self,
                "Apply compensation?",
                "Replace the delay requests for all configured routes to these measured outputs? Acoustic results are estimates; native clock compensation remains automatic.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return
        restart = self.restart.isChecked()
        self.window.submit(lambda: self.window.controller.apply_calibration(delays, restart))

    def export_results(self):
        if not self.current_result:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export measured calibration", "calibration.json", "JSON (*.json)"
        )
        if path:
            from a2router.calibration import validate_result
            from a2router.storage import atomic_json

            payload = json.loads(json.dumps(self.current_result))
            self.window.submit(
                lambda: atomic_json(path, validate_result(payload)), persist=False, refresh_backend=False
            )
