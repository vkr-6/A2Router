"""Compact Qt Widgets UI. Backend and disk work runs on one serialized worker."""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

from PySide6.QtCore import QObject, QProcess, Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStyle,
    QSystemTrayIcon,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from a2router.controller import config_dir
from a2router.models import VirtualDevice


class Results(QObject):
    ready = Signal(object, object, str)
    closed = Signal(str)


class MainWindow(QMainWindow):
    def __init__(self, controller, state_path=None):
        super().__init__()
        self.controller, self.backend = controller, controller.backend
        self.state_path = state_path
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="a2router-control")
        self.results = Results(self)
        self.results.ready.connect(self._finished)
        self.results.closed.connect(self._closed)
        self.closing_worker = False
        self.exit_ready = False
        self.busy, self.exiting = False, False
        self.view_devices, self.view_routes = {}, {}
        self.setWindowTitle("A2Router — Advanced Audio Router")
        self.resize(940, 620)
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.statusBar().addWidget(self.error, 1)
        self.buttons = []
        self._devices_page()
        self._routing_page()
        self._virtual_page()
        self._status_page()
        self._settings_page()
        menu = self.menuBar().addMenu("Application")
        show = QAction("Show window", self)
        show.triggered.connect(self.showNormal)
        exit_label = (
            "Exit controller" if sys.platform == "win32" else "Exit controller (leave server routes running)"
        )
        exit_action = QAction(exit_label, self)
        exit_action.triggered.connect(self.exit_application)
        menu.addAction(show)
        menu.addAction(exit_action)
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self.style().standardIcon(QStyle.SP_MediaVolume), self)
            self.tray.setToolTip("A2Router — Advanced Audio Router")
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(lambda _: self.showNormal())
            self.tray.show()
        self.timer = QTimer(self)
        self.timer.setInterval(3000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.subscription = None
        from a2router.backends.linux_pipewire import PipeWireBackend

        if sys.platform == "linux" and isinstance(self.backend, PipeWireBackend):
            self.event_timer = QTimer(self)
            self.event_timer.setSingleShot(True)
            self.event_timer.setInterval(250)
            self.event_timer.timeout.connect(self.refresh)
            self.subscription = QProcess(self)
            self.subscription.setProgram("pactl")
            self.subscription.setArguments(["subscribe"])
            self.subscription.readyReadStandardOutput.connect(self._audio_event)
            self.subscription.start()
        self.refresh()

    def _audio_event(self):
        self.subscription.readAllStandardOutput()
        self.event_timer.start()

    def page(self, title):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.tabs.addTab(widget, title)
        return layout

    def button(self, layout, title, action, capability=True):
        button = QPushButton(title)
        button.clicked.connect(action)
        button.setProperty("capable", capability)
        button.setEnabled(capability)
        layout.addWidget(button)
        self.buttons.append(button)
        return button

    def tree(self, layout, columns):
        tree = QTreeWidget()
        tree.setHeaderLabels(columns)
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        layout.addWidget(tree)
        return tree

    def _devices_page(self):
        layout = self.page("Devices")
        self.device_tree = self.tree(
            layout, ["Device", "Type", "Physical / virtual", "State", "Active format"]
        )
        self.device_details = QPlainTextEdit()
        self.device_details.setReadOnly(True)
        self.device_details.setMaximumHeight(190)
        layout.addWidget(self.device_details)
        self.device_tree.itemSelectionChanged.connect(self.inspect_device)
        self.button(layout, "Refresh devices", self.refresh)

    def inspect_device(self):
        selected = self.device_tree.selectedItems()
        if selected:
            self.device_details.setPlainText(
                json.dumps(self.view_devices[selected[0].data(0, Qt.UserRole)], indent=2)
            )

    def _routing_page(self):
        layout = self.page("Routing")
        row = QHBoxLayout()
        self.source, self.destination = QComboBox(), QComboBox()
        self.source.setMinimumContentsLength(20)
        self.destination.setMinimumContentsLength(20)
        row.addWidget(QLabel("Source"))
        row.addWidget(self.source, 1)
        row.addWidget(QLabel("Destination"))
        row.addWidget(self.destination, 1)
        layout.addLayout(row)
        self.monitor_confirm = QCheckBox(
            "I confirm input monitoring is safe (feedback risk with microphones and speakers)"
        )
        layout.addWidget(self.monitor_confirm)
        capable = self.backend.capabilities()["routing"]
        self.add_route_button = self.button(layout, "Add route", self.add_route, capable)
        self.route_tree = self.tree(layout, ["Source", "Destination", "Enabled", "Status", "Error"])
        row = QHBoxLayout()
        layout.addLayout(row)
        self.button(row, "Enable", lambda: self.route_action("enable_route"), capable)
        self.button(row, "Disable", lambda: self.route_action("disable_route"), capable)
        self.button(row, "Remove route", lambda: self.route_action("remove_route"), capable)

    def add_route(self):
        source, dest = self.source.currentData(), self.destination.currentData()
        confirmed = self.monitor_confirm.isChecked()
        if source and dest:
            self.submit(lambda: self.backend.create_route(source, dest, monitoring_confirmed=confirmed))
        else:
            self.error.setText("Select an available source and destination")

    def route_action(self, method):
        selected = self.route_tree.selectedItems()
        if selected:
            ident = selected[0].data(0, Qt.UserRole)
            self.submit(lambda: getattr(self.backend, method)(ident))

    def _virtual_page(self):
        layout = self.page("Virtual devices")
        row = QHBoxLayout()
        self.virtual_name = QLineEdit()
        self.virtual_name.setPlaceholderText("Virtual device name")
        self.layout_choice = QComboBox()
        self.layout_choice.addItems(self.backend.capabilities()["layouts"])
        self.layout_choice.setCurrentText("stereo")
        row.addWidget(self.virtual_name, 1)
        row.addWidget(self.layout_choice)
        layout.addLayout(row)
        capable = self.backend.capabilities()["virtual_devices"]
        self.create_virtual_button = self.button(
            layout, "Create virtual output", self.create_virtual, capable
        )
        self.virtual_tree = self.tree(layout, ["Managed device", "Layout", "Status", "Stable ID"])
        self.button(layout, "Remove selected virtual device", self.remove_virtual, capable)
        layout.addWidget(
            QLabel(
                "Remove dependent routes before removing a virtual device. Applications can select created sinks."
            )
        )
        if not capable:
            layout.addWidget(
                QLabel(
                    "Windows: build the native helper and signed A2Router driver package first. "
                    "See drivers/windows/README.md; creating/removing a device requests UAC approval."
                )
            )

    def create_virtual(self):
        config = VirtualDevice(self.virtual_name.text(), self.layout_choice.currentText())
        self.submit(lambda: self.backend.create_virtual_device(config))

    def remove_virtual(self):
        selected = self.virtual_tree.selectedItems()
        if selected:
            ident = selected[0].data(0, Qt.UserRole)

            def remove():
                self.backend.remove_virtual_device(ident)
                self.controller.virtual_definitions.pop(ident, None)

            self.submit(remove)

    def _status_page(self):
        layout = self.page("Synchronization")
        capable = self.backend.capabilities().get("route_delay", False)
        self.sync_route = QComboBox()
        self.sync_delay = QSpinBox()
        self.sync_delay.setRange(0, 10000)
        self.sync_delay.setSuffix(" ms")
        self.sync_route.currentIndexChanged.connect(self._sync_selection_changed)
        self.sync_delay.setEnabled(capable)
        self.sync_route.setEnabled(capable)
        if capable:
            row = QHBoxLayout()
            row.addWidget(QLabel("Route"))
            row.addWidget(self.sync_route, 1)
            row.addWidget(QLabel("Additional delay"))
            row.addWidget(self.sync_delay)
            layout.addLayout(row)
            self.button(layout, "Apply delay (restarts this source)", self.apply_sync_delay)
            label = (
                "WASAPI drift compensation runs automatically for each output. Additional delay is "
                "software buffering, not measured speaker latency. Applying it briefly restarts all "
                "destinations of this source. Physical/acoustic alignment requires measurement."
            )
        else:
            label = (
                "The backend manages clock adaptation. Adjustable delay is unavailable here. "
                "On Windows, rebuild the WASAPI DLL to enable native delay controls. "
                "Equal sample rates alone do not guarantee synchronized speakers."
            )
        message = QLabel(label)
        message.setWordWrap(True)
        layout.addWidget(message)
        self.sync = QPlainTextEdit()
        self.sync.setReadOnly(True)
        layout.addWidget(self.sync)

    def _sync_selection_changed(self):
        route = self.view_routes.get(self.sync_route.currentData(), {})
        self.sync_delay.setValue(route.get("delay_ms", 0))

    def apply_sync_delay(self):
        ident, delay = self.sync_route.currentData(), self.sync_delay.value()
        if ident:
            self.submit(lambda: self.backend.set_route_delay(ident, delay))

    def _settings_page(self):
        layout = self.page("Settings / profiles")
        layout.addWidget(
            QLabel(
                "Profiles are named JSON files. Loading merges definitions; Stop routes explicitly disables audio."
            )
        )
        self.button(layout, "Save profile…", self.save_profile)
        self.button(layout, "Load profile…", self.load_profile)
        capable = self.backend.capabilities()["routing"]
        self.button(
            layout, "Start all managed routes", lambda: self.submit(self.controller.start_routes), capable
        )
        self.button(
            layout, "Stop all managed routes", lambda: self.submit(self.controller.stop_routes), capable
        )
        self.button(layout, "Refresh diagnostics", self.refresh)
        self.diagnostics = QPlainTextEdit()
        self.diagnostics.setReadOnly(True)
        layout.addWidget(self.diagnostics)
        layout.addWidget(
            QLabel(
                "Close hides to tray when available. Exit leaves Linux server modules running; Windows exit stops its engine."
            )
        )

    def save_profile(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save routing profile", str(config_dir() / "profile.json"), "JSON (*.json)"
        )
        if path:
            self.submit(lambda: self.controller.save(path))

    def load_profile(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load routing profile", str(config_dir()), "JSON (*.json)"
        )
        if path:
            self.submit(lambda: self.controller.load(path))

    def refresh(self):
        if not self.busy:
            self.submit(lambda: None, persist=False)

    def submit(self, operation, persist=True):
        if self.busy or self.exiting:
            return
        self.busy = True
        for button in self.buttons:
            button.setEnabled(False)
        self.error.setText("Updating…")

        def work():
            message = ""
            try:
                result = operation()
                if isinstance(result, list) and result:
                    message = "; ".join(map(str, result))
                self.controller.refresh()
                if persist and self.state_path:
                    self.controller.save(self.state_path)
            except Exception as exc:  # noqa: BLE001 — display worker failures and keep Qt alive
                message = str(exc)
                # Never overwrite session state on failed profile parsing.
            snapshot = {
                "devices": [asdict(d) for d in self.backend.list_devices()],
                "routes": [asdict(r) for r in self.backend.list_routes()],
                "virtual_devices": self.controller.snapshot()["virtual_devices"],
                "diagnostics": self.backend.diagnostics(),
            }
            return snapshot, message

        future = self.executor.submit(work)

        def done(task):
            try:
                snapshot, message = task.result()
                self.results.ready.emit(snapshot, None, message)
            except Exception as exc:  # noqa: BLE001 — display worker failures and keep Qt alive
                self.results.ready.emit(None, None, str(exc))

        future.add_done_callback(done)

    def _finished(self, snapshot, _, message):
        self.busy = False
        for button in self.buttons:
            button.setEnabled(bool(button.property("capable")))
        if snapshot:
            self.populate(snapshot)
        self.error.setText(
            message or (snapshot or {}).get("diagnostics", {}).get("error") or self.backend.name
        )
        if self.exiting:
            self._finish_exit()

    def populate(self, snapshot):
        source_id, dest_id = self.source.currentData(), self.destination.currentData()
        sync_id = self.sync_route.currentData()
        selected_route = self.route_tree.selectedItems()
        route_id = selected_route[0].data(0, Qt.UserRole) if selected_route else None
        selected_virtual = self.virtual_tree.selectedItems()
        virtual_id = selected_virtual[0].data(0, Qt.UserRole) if selected_virtual else None
        self.view_devices = {d["id"]: d for d in snapshot["devices"]}
        self.view_routes = {r["id"]: r for r in snapshot["routes"]}
        self.device_tree.clear()
        self.source.clear()
        self.destination.clear()
        for d in snapshot["devices"]:
            label = d["name"] + (" (default)" if d["default"] else "")
            classification = (
                "unknown" if d["virtual"] is None else ("virtual" if d["virtual"] else "physical")
            )
            format_text = (
                f"{d['sample_format'] or '?'} / {d['sample_rate'] or '?'} Hz / {d['channels'] or '?'} ch"
            )
            item = QTreeWidgetItem([label, d["kind"], classification, d["state"], format_text])
            item.setData(0, Qt.UserRole, d["id"])
            self.device_tree.addTopLevelItem(item)
            combo = self.source if d["kind"] == "input" else self.destination
            combo.addItem(label, d["id"])
        for combo, ident in ((self.source, source_id), (self.destination, dest_id)):
            index = combo.findData(ident)
            if index >= 0:
                combo.setCurrentIndex(index)
        self.sync_route.blockSignals(True)
        self.sync_route.clear()
        for route in snapshot["routes"]:
            source_name = self.view_devices.get(route["source_id"], {}).get("name", route["source_id"])
            destination_name = self.view_devices.get(route["destination_id"], {}).get(
                "name", route["destination_id"]
            )
            self.sync_route.addItem(f"{source_name} → {destination_name}", route["id"])
        sync_index = self.sync_route.findData(sync_id)
        if sync_index >= 0:
            self.sync_route.setCurrentIndex(sync_index)
        self.sync_route.blockSignals(False)
        if not self.sync_delay.hasFocus():
            self._sync_selection_changed()
        self.route_tree.clear()
        for route in snapshot["routes"]:
            names = [
                self.view_devices.get(route[k], {}).get("name", route[k])
                for k in ("source_id", "destination_id")
            ]
            item = QTreeWidgetItem([*names, str(route["enabled"]), route["status"], route["error"]])
            item.setData(0, Qt.UserRole, route["id"])
            self.route_tree.addTopLevelItem(item)
            item.setSelected(route["id"] == route_id)
        self.virtual_tree.clear()
        for config in snapshot["virtual_devices"]:
            ident = "sink:a2router_v_" + config["id"].replace("-", "")
            state = self.view_devices.get(ident, {}).get("state", "unavailable")
            item = QTreeWidgetItem([config["name"], config["layout"], state, ident])
            item.setData(0, Qt.UserRole, config["id"])
            self.virtual_tree.addTopLevelItem(item)
            item.setSelected(config["id"] == virtual_id)
        self.diagnostics.setPlainText(json.dumps(snapshot["diagnostics"], indent=2))
        self.sync.setPlainText(
            json.dumps(
                {
                    "capabilities": snapshot["diagnostics"]["capabilities"],
                    "native_telemetry": snapshot["diagnostics"].get("telemetry", {}),
                    "configured_additional_delay_ms": {
                        r["id"]: r.get("delay_ms", 0) for r in snapshot["routes"]
                    },
                    "reported_device_latency_us": {d["name"]: d["latency"] for d in snapshot["devices"]},
                    "notes": "No measured acoustic alignment, end-to-end latency, or bit-perfect claim. Mixing can clip; reduce application volumes.",
                },
                indent=2,
            )
        )

    def closeEvent(self, event):
        if self.exit_ready:
            event.accept()
        elif self.exiting:
            event.ignore()
        elif self.tray:
            self.hide()
            event.ignore()
        else:
            # With no tray, minimize so the running Windows engine stays reachable.
            self.showMinimized()
            event.ignore()

    def exit_application(self):
        self.timer.stop()
        if self.subscription:
            self.event_timer.stop()
            self.subscription.terminate()
            self.subscription.waitForFinished(1000)
        self.exiting = True
        if not self.busy:
            self._finish_exit()

    def _finish_exit(self):
        if self.closing_worker:
            return
        self.closing_worker = True
        future = self.executor.submit(self.backend.close)

        def closed(task):
            try:
                task.result()
                message = ""
            except Exception as exc:  # noqa: BLE001 — complete UI shutdown after worker failure
                message = str(exc)
            self.results.closed.emit(message)

        future.add_done_callback(closed)

    def _closed(self, message):
        self.executor.shutdown(wait=False)
        if message:
            self.error.setText(message)
        if self.tray:
            self.tray.hide()
        self.exit_ready = True
        self.close()
        QApplication.instance().quit()
