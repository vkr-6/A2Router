"""Compact Qt Widgets UI. Backend and disk work runs on one serialized worker."""

import json
import sys
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSystemTrayIcon,
    QTableWidget,
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
        self._pending_actions = deque()
        self._sync_edits = {}
        self._background = False
        self._poll_error = ""
        self._vbcable_page = self.backend.capabilities().get("virtual_device_provider") == "VB-CABLE"
        self.setWindowTitle("A2Router — Advanced Audio Router")
        self.setWindowIcon(QIcon(str(Path(__file__).parent / "assets/a2router.svg")))
        self.resize(1050, 700)
        self.setMinimumSize(820, 560)
        self.setStyleSheet(
            "QPushButton { padding: 5px 12px; } QTabBar::tab { padding: 9px 15px; } "
            "QTreeView::item { padding: 3px 0; } QGroupBox { margin-top: 8px; } "
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; }"
        )
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        brand = QLabel()
        brand.setPixmap(self.windowIcon().pixmap(26, 26))
        brand.setContentsMargins(8, 2, 12, 2)
        brand.setToolTip("A2Router · Advanced Audio Router")
        self.tabs.setCornerWidget(brand)
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
            self.tray = QSystemTrayIcon(self.windowIcon(), self)
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
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
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
        tree.setUniformRowHeights(True)
        tree.setSelectionBehavior(QTreeWidget.SelectRows)
        tree.header().setSectionResizeMode(QHeaderView.Interactive)
        for index in range(len(columns)):
            tree.setColumnWidth(index, 190 if index == 0 else 135)
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
        self.button(layout, "Refresh devices", lambda: self.refresh(manual=True))

    def inspect_device(self):
        selected = self.device_tree.selectedItems()
        if selected:
            self._update_text(
                self.device_details, json.dumps(self.view_devices[selected[0].data(0, Qt.UserRole)], indent=2)
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
        self._channel_pair = None
        self.channel_group = QGroupBox("Custom channel routing")
        self.channel_group.setCheckable(True)
        self.channel_group.setChecked(False)
        self.channel_group.setEnabled(self.backend.capabilities().get("channel_routing", False))
        self.channel_group.setToolTip(
            "Optional remapping, duplication and summing. Unmapped outputs are silent; mixed peaks are clipped to ±1."
        )
        group_layout = QVBoxLayout(self.channel_group)
        self.channel_panel = QWidget()
        channel_layout = QVBoxLayout(self.channel_panel)
        channel_layout.setContentsMargins(0, 0, 0, 0)
        self.channel_table = QTableWidget(0, 3)
        self.channel_table.setHorizontalHeaderLabels(["Source channel", "Destination channel", "Gain"])
        self.channel_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.channel_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.channel_table.setMaximumHeight(165)
        channel_layout.addWidget(self.channel_table)
        channel_buttons = QHBoxLayout()
        add = QPushButton("Add connection")
        add.clicked.connect(self.add_channel_connection)
        remove = QPushButton("Remove connection")
        remove.clicked.connect(self.remove_channel_connection)
        channel_buttons.addWidget(add)
        channel_buttons.addWidget(remove)
        channel_buttons.addStretch()
        channel_layout.addLayout(channel_buttons)
        group_layout.addWidget(self.channel_panel)
        self.channel_panel.hide()
        self.channel_group.toggled.connect(self.channel_panel.setVisible)
        self.source.currentIndexChanged.connect(self._reset_channel_editor)
        self.destination.currentIndexChanged.connect(self._reset_channel_editor)
        layout.addWidget(self.channel_group)
        self.monitor_confirm = QCheckBox("Allow microphone monitoring")
        self.monitor_confirm.setToolTip(
            "Confirm that this microphone-to-speaker route cannot create acoustic feedback."
        )
        action_row = QHBoxLayout()
        action_row.addWidget(self.monitor_confirm)
        action_row.addStretch()
        layout.addLayout(action_row)
        capable = self.backend.capabilities()["routing"]
        self.add_route_button = self.button(action_row, "Add route", self.add_route, capable)
        self.add_route_button.setDefault(True)
        self.route_tree = self.tree(
            layout, ["Source", "Destination", "Enabled", "Status", "Channels", "Error"]
        )
        row = QHBoxLayout()
        layout.addLayout(row)
        self.button(row, "Enable", lambda: self.route_action("enable_route"), capable)
        self.button(row, "Disable", lambda: self.route_action("disable_route"), capable)
        self.button(row, "Remove route", lambda: self.route_action("remove_route"), capable)

    def add_route(self):
        source, dest = self.source.currentData(), self.destination.currentData()
        confirmed = self.monitor_confirm.isChecked()
        if source and dest:
            mapping = []
            if self.channel_group.isChecked():
                for row in range(self.channel_table.rowCount()):
                    mapping.append(
                        {
                            "source": self.channel_table.cellWidget(row, 0).currentData(),
                            "destination": self.channel_table.cellWidget(row, 1).currentData(),
                            "gain": 10 ** (self.channel_table.cellWidget(row, 2).value() / 20),
                        }
                    )
                if not mapping:
                    self.error.setText("Add at least one channel connection or turn off custom routing")
                    return
            if mapping:
                used = {connection["source"] for connection in mapping}
                omitted = set(range(self.view_devices.get(source, {}).get("channels") or 0)) - used
                if (
                    omitted
                    and QMessageBox.question(
                        self,
                        "Omit source channels?",
                        "This mapping omits source channels "
                        + ", ".join(str(i + 1) for i in sorted(omitted))
                        + ". Create the route?",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No,
                    )
                    != QMessageBox.Yes
                ):
                    return
            self.submit(
                lambda: self.backend.create_route(
                    source, dest, monitoring_confirmed=confirmed, channel_map=mapping
                )
            )
        else:
            self.error.setText("Select an available source and destination")

    def _reset_channel_editor(self):
        pair = (self.source.currentData(), self.destination.currentData())
        if pair == self._channel_pair:
            return
        self._channel_pair = pair
        self.channel_table.setRowCount(0)
        source = self.view_devices.get(pair[0], {})
        destination = self.view_devices.get(pair[1], {})
        for index in range(min(source.get("channels") or 0, destination.get("channels") or 0, 64)):
            self.add_channel_connection(source_index=index, destination_index=index)

    def add_channel_connection(self, checked=False, *, source_index=0, destination_index=0):
        endpoints = [
            self.view_devices.get(self.source.currentData(), {}),
            self.view_devices.get(self.destination.currentData(), {}),
        ]
        if not all(device.get("channels") for device in endpoints):
            return
        row = self.channel_table.rowCount()
        if row >= 1024:
            return
        self.channel_table.insertRow(row)
        for column, device in enumerate(endpoints):
            combo = QComboBox()
            for index in range(min(device["channels"], 64)):
                positions = device.get("positions", [])
                label = (
                    positions[index].replace("-", " ").title()
                    if index < len(positions)
                    else f"Channel {index + 1}"
                )
                combo.addItem(f"{index + 1} · {label}", index)
            combo.setCurrentIndex(source_index if column == 0 else destination_index)
            self.channel_table.setCellWidget(row, column, combo)
        gain = QDoubleSpinBox()
        gain.setRange(-60, 12)
        gain.setDecimals(1)
        gain.setSingleStep(0.5)
        gain.setSuffix(" dB")
        self.channel_table.setCellWidget(row, 2, gain)

    def remove_channel_connection(self):
        rows = sorted({index.row() for index in self.channel_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.channel_table.removeRow(row)

    def route_action(self, method):
        selected = self.route_tree.selectedItems()
        if selected:
            ident = selected[0].data(0, Qt.UserRole)
            self.submit(lambda: getattr(self.backend, method)(ident))

    def _virtual_page(self):
        layout = self.page("Virtual devices")
        if self._vbcable_page:
            row = QHBoxLayout()
            self.virtual_name = QLineEdit()
            self.virtual_name.setPlaceholderText("Display name in A2Router")
            row.addWidget(self.virtual_name, 1)
            self.install_cable_button = self.button(
                row,
                "Create output",
                self.create_cable,
                self.backend.capabilities().get("install_virtual_driver", False),
            )
            self.create_virtual_button = self.install_cable_button
            layout.addLayout(row)
            self.vbcable_status = QLabel("Checking…")
            layout.addWidget(self.vbcable_status)
            self.virtual_tree = self.tree(layout, ["Endpoint", "Channels", "Status", "Windows ID"])
            row = QHBoxLayout()
            layout.addLayout(row)
            self.button(row, "Configure channels / Windows name…", self.configure_windows_cable)
            self.button(
                row,
                "Remove driver…",
                self.remove_cable,
                self.backend.capabilities().get("install_virtual_driver", False),
            )
            row.addStretch()
            label = QLabel(
                'One shared cable · <a href="https://vb-audio.com/Cable/">VB-Audio Software</a> · '
                '<a href="https://vb-audio.com/Services/licensing.htm">Donate / license</a>'
            )
            label.setOpenExternalLinks(True)
            layout.addWidget(label)
            self.virtual_name.setToolTip(
                "Saved display name in A2Router. Change the system name and speaker layout in Windows configuration."
            )
            return
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

    def create_cable(self):
        name = self.virtual_name.text()
        self.submit(lambda: self.backend.configure_cable(name))

    def configure_windows_cable(self):
        from a2router.backends import windows_vbcable

        self.submit(windows_vbcable.open_configuration, persist=False)

    def remove_cable(self):
        if (
            QMessageBox.question(
                self,
                "Remove VB-CABLE?",
                "This removes the shared VB-CABLE driver for all applications. Close audio applications first. Continue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            == QMessageBox.Yes
        ):
            self.submit(self.backend.uninstall_virtual_driver)

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
        self.sync_route = QComboBox()
        self.sync_route.setMinimumContentsLength(28)
        self.sync_delay = QSpinBox()
        self.sync_delay.setRange(0, 10000)
        self.sync_delay.setSuffix(" ms")
        self.sync_route.currentIndexChanged.connect(self._sync_selection_changed)
        self.sync_delay.valueChanged.connect(self._sync_edited)
        row = QHBoxLayout()
        row.addWidget(QLabel("Route"))
        row.addWidget(self.sync_route, 1)
        row.addWidget(QLabel("Additional delay"))
        row.addWidget(self.sync_delay)
        layout.addLayout(row)
        self.sync_restart = QCheckBox("Allow a source restart if the current buffer cannot hold this delay")
        self.sync_restart.setChecked(not self.backend.capabilities().get("live_route_delay", False))
        layout.addWidget(self.sync_restart)
        self.sync_edit_status = QLabel()
        layout.addWidget(self.sync_edit_status)
        actions = QHBoxLayout()
        layout.addLayout(actions)
        self.sync_apply = self.button(actions, "Apply delay", self.apply_sync_delay)
        self.sync_reset = self.button(actions, "Discard edit", self.reset_sync_edit)
        actions.addStretch()
        note = QLabel(
            "Clock drift is managed automatically. Additional delay adjusts timing; acoustic alignment is unmeasured."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.sync = self.tree(
            layout,
            [
                "Source → output",
                "Route",
                "Requested delay",
                "Buffer / target",
                "Rate correction",
                "Underruns",
                "Clipped samples",
            ],
        )
        for column, width in enumerate((220, 140, 110, 140, 120, 80)):
            self.sync.setColumnWidth(column, width)
        self.sync_summary = QLabel("No routes configured.")
        self.sync_summary.setWordWrap(True)
        layout.addWidget(self.sync_summary)
        self._update_sync_controls()

    def _sync_selection_changed(self):
        ident = self.sync_route.currentData()
        route = self.view_routes.get(ident, {})
        value = self._sync_edits.get(ident, route.get("delay_ms", 0))
        if self.sync_delay.value() != value:
            with QSignalBlocker(self.sync_delay):
                self.sync_delay.setValue(value)
        self._update_sync_controls()

    def _sync_edited(self, value):
        ident = self.sync_route.currentData()
        if ident in self.view_routes:
            if value == self.view_routes[ident].get("delay_ms", 0):
                self._sync_edits.pop(ident, None)
            else:
                self._sync_edits[ident] = value
        self._update_sync_controls()

    def _update_sync_controls(self):
        ident = self.sync_route.currentData()
        route = self.view_routes.get(ident)
        capable = self.backend.capabilities().get("route_delay", False)
        mutating = self.busy and not self._background
        editable = capable and route is not None and not mutating
        dirty = route is not None and ident in self._sync_edits
        self.sync_route.setEnabled(capable and not mutating)
        self.sync_delay.setEnabled(editable)
        self.sync_restart.setEnabled(editable)
        self.sync_apply.setEnabled(editable and dirty)
        self.sync_reset.setEnabled(editable and dirty)
        if not capable:
            text = "Additional delay is unsupported by this backend; on Windows rebuild the native bridge."
        elif route is None:
            text = "Add a route, then select it here."
        else:
            text = f"Saved request: {route.get('delay_ms', 0)} ms" + (" — unapplied edit" if dirty else "")
        self.sync_edit_status.setText(text)

    def reset_sync_edit(self):
        self._sync_edits.pop(self.sync_route.currentData(), None)
        self._sync_selection_changed()

    def apply_sync_delay(self):
        ident, delay, restart = (
            self.sync_route.currentData(),
            self.sync_delay.value(),
            self.sync_restart.isChecked(),
        )
        if ident:

            def apply():
                self.backend.set_route_delay(ident, delay, allow_restart=restart)
                return f"Requested {delay} ms additional delay; see route status and buffering below."

            self.submit(apply)

    def _settings_page(self):
        layout = self.page("Settings")
        layout.addWidget(QLabel("Save or restore your routing profile."))
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

    def refresh(self, manual=False):
        self.submit(lambda: None, persist=False, background=not manual)

    def submit(self, operation, persist=True, background=False):
        if self.exiting:
            return
        if self.busy:
            if not background:
                self._pending_actions.append((operation, persist))
                for button in self.buttons:
                    button.setEnabled(False)
            return
        self.busy, self._background = True, background
        if not background:
            for button in self.buttons:
                button.setEnabled(False)
            self.error.setText("Updating…")
        self._update_sync_controls()

        def work():
            message = ""
            try:
                result = operation()
                if isinstance(result, list) and result:
                    message = "; ".join(map(str, result))
                elif isinstance(result, str):
                    message = result
                self.controller.refresh()
                if persist and self.state_path:
                    self.controller.save(self.state_path)
            except Exception as exc:  # noqa: BLE001 — display worker failures and keep Qt alive
                message = str(exc)
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
                self.results.ready.emit(snapshot, background, message)
            except Exception as exc:  # noqa: BLE001 — display worker failures and keep Qt alive
                self.results.ready.emit(None, background, str(exc))

        future.add_done_callback(done)

    def _finished(self, snapshot, background, message):
        self.busy = False
        for button in self.buttons:
            button.setEnabled(bool(button.property("capable")))
        if snapshot:
            self.populate(snapshot)
        backend_error = (snapshot or {}).get("diagnostics", {}).get("error")
        if not background:
            self.error.setText(message or backend_error or self.backend.name)
            self._poll_error = ""
        elif message or backend_error:
            self._poll_error = message or backend_error
            self.error.setText(self._poll_error)
        elif self._poll_error:
            if self.error.text() == self._poll_error:
                self.error.setText(self.backend.name)
            self._poll_error = ""
        elif not self.error.text():
            self.error.setText(self.backend.name)
        self._update_sync_controls()
        if self.exiting:
            self._pending_actions.clear()
            self._finish_exit()
        elif self._pending_actions:
            operation, persist = self._pending_actions.popleft()
            self.submit(operation, persist=persist)

    @staticmethod
    def _update_tree(tree, rows):
        """Update cells in place so selection, scroll and item identity survive polls."""
        wanted = {ident for ident, _ in rows}
        existing = {
            tree.topLevelItem(i).data(0, Qt.UserRole): tree.topLevelItem(i)
            for i in range(tree.topLevelItemCount())
        }
        if len(existing) == len(rows) and all(
            ident in existing and all(existing[ident].text(i) == value for i, value in enumerate(texts))
            for ident, texts in rows
        ):
            return
        with QSignalBlocker(tree):
            tree.setUpdatesEnabled(False)
            try:
                for ident, texts in rows:
                    item = existing.get(ident)
                    if item is None:
                        item = QTreeWidgetItem(texts)
                        item.setData(0, Qt.UserRole, ident)
                        for column, text in enumerate(texts):
                            item.setToolTip(column, text)
                        tree.addTopLevelItem(item)
                    else:
                        for column, text in enumerate(texts):
                            if item.text(column) != text:
                                item.setText(column, text)
                            item.setToolTip(column, text)
                for index in range(tree.topLevelItemCount() - 1, -1, -1):
                    if tree.topLevelItem(index).data(0, Qt.UserRole) not in wanted:
                        tree.takeTopLevelItem(index)
            finally:
                tree.setUpdatesEnabled(True)

    @staticmethod
    def _update_combo(combo, rows):
        current = combo.currentData()
        old = [(combo.itemData(i), combo.itemText(i)) for i in range(combo.count())]
        if dict(old) == dict(rows):
            return
        was_empty = combo.count() == 0
        with QSignalBlocker(combo):
            wanted = {ident for ident, _ in rows}
            for index in range(combo.count() - 1, -1, -1):
                if combo.itemData(index) not in wanted:
                    combo.removeItem(index)
            for ident, label in rows:
                index = combo.findData(ident)
                if index < 0:
                    combo.addItem(label, ident)
                elif combo.itemText(index) != label:
                    combo.setItemText(index, label)
            index = combo.findData(current)
            combo.setCurrentIndex(index if index >= 0 else (0 if was_empty and combo.count() else -1))

    @staticmethod
    def _update_text(widget, text):
        if widget.toPlainText() == text:
            return
        scroll = widget.verticalScrollBar().value()
        cursor = widget.textCursor()
        widget.setPlainText(text)
        cursor.setPosition(min(cursor.position(), len(text)))
        widget.setTextCursor(cursor)
        widget.verticalScrollBar().setValue(scroll)

    def populate(self, snapshot):
        self.view_devices = {d["id"]: d for d in snapshot["devices"]}
        self.view_routes = {r["id"]: r for r in snapshot["routes"]}
        device_rows, source_rows, destination_rows = [], [], []
        for device in snapshot["devices"]:
            label = device["name"] + (" (default)" if device["default"] else "")
            classification = (
                "unknown" if device["virtual"] is None else ("virtual" if device["virtual"] else "physical")
            )
            format_text = f"{device['sample_format'] or '?'} / {device['sample_rate'] or '?'} Hz / {device['channels'] or '?'} ch"
            device_rows.append(
                (device["id"], [label, device["kind"], classification, device["state"], format_text])
            )
            (source_rows if device["kind"] == "input" else destination_rows).append((device["id"], label))
        self._update_tree(self.device_tree, device_rows)
        self._update_combo(self.source, source_rows)
        self._update_combo(self.destination, destination_rows)
        self.inspect_device()
        self._reset_channel_editor()
        route_rows, sync_rows, metric_rows = [], [], []
        sessions = snapshot["diagnostics"].get("telemetry", {}).get("sessions", [])
        for route in snapshot["routes"]:
            names = [
                self.view_devices.get(route[key], {}).get("name", route[key])
                for key in ("source_id", "destination_id")
            ]
            label = " → ".join(names)
            channel_text = (
                f"Custom · {len(route['channel_map'])} links" if route.get("channel_map") else "Automatic"
            )
            route_rows.append(
                (
                    route["id"],
                    [
                        *names,
                        "Yes" if route["enabled"] else "No",
                        route["status"],
                        channel_text,
                        route["error"],
                    ],
                )
            )
            sync_rows.append((route["id"], label))
            source = self.view_devices.get(route["source_id"], {})
            native_source = (
                source.get("properties", {}).get("capture_endpoint_id")
                or source.get("monitor_of")
                or route["source_id"]
            )
            session = next((s for s in sessions if s.get("source_id") == native_source), {})
            output = next(
                (d for d in session.get("devices", []) if d.get("id") == route["destination_id"]), {}
            )
            rate, block = session.get("sample_rate", 0), session.get("block_align", 0)
            buffer_text = "—"
            if rate and block and "fill_bytes" in output and "target_bytes" in output:
                divisor = rate * block / 1000
                buffer_text = (
                    f"{output['fill_bytes'] / divisor:.1f} / {output['target_bytes'] / divisor:.1f} ms"
                )
            correction = (
                f"{(output['sample_rate'] / rate - 1) * 1e6:+.0f} ppm"
                if rate and output.get("sample_rate")
                else "—"
            )
            state = route["status"]
            if output.get("delay_adjusting"):
                state += " / adjusting"
            elif output.get("prebuffering"):
                state += " / buffering"
            metric_rows.append(
                (
                    route["id"],
                    [
                        label,
                        state,
                        f"{route.get('delay_ms', 0)} ms",
                        buffer_text,
                        correction,
                        str(output.get("underflows", "—")),
                        str(output.get("clipped_samples", "—")),
                    ],
                )
            )
            if self._sync_edits.get(route["id"]) == route.get("delay_ms", 0):
                self._sync_edits.pop(route["id"], None)
        self._sync_edits = {key: value for key, value in self._sync_edits.items() if key in self.view_routes}
        self._update_tree(self.route_tree, route_rows)
        self._update_combo(self.sync_route, sync_rows)
        self._sync_selection_changed()
        self._update_tree(self.sync, metric_rows)
        self.sync_summary.setText(
            "Automatic clock drift compensation; acoustic alignment is unmeasured."
            if sessions
            else "No running native sessions. Configured delay is retained for stopped or pending routes."
        )
        virtual_rows = []
        if self._vbcable_page:
            for device in snapshot["devices"]:
                props = device.get("properties", {})
                if props.get("virtual_driver") == "VB-CABLE" and (
                    device["kind"] == "output" or props.get("capture_endpoint_id")
                ):
                    virtual_rows.append(
                        (
                            device["id"],
                            [
                                device["name"],
                                f"{device['kind']} / {device['channels'] or '?'} ch",
                                device["state"],
                                device["id"],
                            ],
                        )
                    )
            present = bool(virtual_rows)
            self.vbcable_status.setText(
                "Ready · Send apps to CABLE Input; route CABLE Output here."
                if present
                else "Click Create output to install VB-CABLE. Administrator approval is required."
            )
            if present and not self.virtual_name.text():
                alias = next(
                    (
                        self.backend.endpoint_aliases.get(ident)
                        for ident, _ in virtual_rows
                        if self.backend.endpoint_aliases.get(ident)
                    ),
                    None,
                )
                if alias:
                    self.virtual_name.setText(alias)
            self.install_cable_button.setText("Save display name" if present else "Create output")
            self.install_cable_button.setEnabled(
                bool(self.install_cable_button.property("capable"))
                and not (self.busy and not self._background)
            )
        for config in snapshot["virtual_devices"]:
            ident = "sink:a2router_v_" + config["id"].replace("-", "")
            state = self.view_devices.get(ident, {}).get("state", "unavailable")
            if self._vbcable_page:
                state = "Unsupported definition: VB-CABLE uses shared endpoints"
            virtual_rows.append((config["id"], [config["name"], config["layout"], state, ident]))
        self._update_tree(self.virtual_tree, virtual_rows)
        self._update_text(self.diagnostics, json.dumps(snapshot["diagnostics"], indent=2))

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
