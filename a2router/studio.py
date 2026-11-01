"""Professional workspace composition around the existing serialized controller."""

import json
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStyle,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from a2router import storage
from a2router.controller import config_dir
from a2router.tables import DeviceTable


class Navigation(QWidget):
    currentRowChanged = Signal(int)

    def __init__(self):
        super().__init__()
        self.buttons = []
        self.row = -1
        self.group = QButtonGroup(self)
        self.group.idClicked.connect(self.setCurrentRow)
        self.setFixedHeight(52)
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(4, 0, 4, 0)
        self.layout.setSpacing(2)
        self.layout.addStretch()

    def addItem(self, title):
        button = QToolButton()
        button.setText(title)
        button.setCheckable(True)
        button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        icons = [
            QStyle.SP_ArrowRight,
            QStyle.SP_MediaVolume,
            QStyle.SP_ComputerIcon,
            QStyle.SP_DriveNetIcon,
            QStyle.SP_FileDialogContentsView,
            QStyle.SP_MessageBoxInformation,
            QStyle.SP_FileDialogDetailedView,
        ]
        button.setIcon(self.style().standardIcon(icons[len(self.buttons) % len(icons)]))
        button.setIconSize(QSize(18, 18))
        button.setMinimumHeight(48)
        self.group.addButton(button, len(self.buttons))
        self.buttons.append(button)
        self.layout.insertWidget(self.layout.count() - 1, button)

    def clear(self):
        for button in self.buttons:
            self.group.removeButton(button)
            self.layout.removeWidget(button)
            button.deleteLater()
        self.buttons.clear()
        self.row = -1

    def item(self, index):
        return self.buttons[index]

    def currentRow(self):
        return self.row

    def setCurrentRow(self, index):
        if 0 <= index < len(self.buttons):
            self.buttons[index].setChecked(True)
            self.row = index
            self.currentRowChanged.emit(index)


class Studio:
    def __init__(self, window):
        self.window = w = window
        self.settings = QSettings("A2Router", "Studio")
        self.profile_path = None
        self.saved_fingerprint = None
        self.last_fingerprint = None
        self.events = []
        self.last_event = None
        self.system_palette = QPalette(QApplication.style().standardPalette())
        self.routing_tabs = QTabWidget()
        # Retain existing pages and their real action wiring, then compose the new workspace.
        mixer, devices, routing, virtual, sync, settings = [w.tabs.widget(i) for i in range(6)]
        for page in (mixer, devices, routing, virtual, sync, settings):
            w.tabs.removeWidget(page)
        self.routing = routing
        w.route_tree.setMinimumHeight(75)
        w.route_tree.setMaximumHeight(180)
        w.sync.setMaximumHeight(130)
        routing_layout = routing.layout()
        routing_layout.removeWidget(w.channel_group)
        self.routing_tabs.addTab(routing, "Routing Configuration")
        from a2router.matrix_ui import MatrixEditor

        self.matrix = MatrixEditor(w)
        self.routing_tabs.addTab(self.matrix, "Channel Matrix")
        self.delay_group = QGroupBox("Synchronization & delay")
        self.delay_group.setCheckable(True)
        self.delay_group.setChecked(False)
        delay_box = QVBoxLayout(self.delay_group)
        delay_box.setContentsMargins(6, 12, 6, 6)
        delay_box.addWidget(sync)
        sync.hide()
        self.delay_group.toggled.connect(sync.setVisible)
        routing_layout.addWidget(self.delay_group)
        w.route_tree.setMaximumHeight(16777215)
        self.input_table, self.output_table = DeviceTable("input"), DeviceTable("output")
        self.output_table.model.edit_requested.connect(self.edit_endpoint)
        device_tabs = QTabWidget()
        device_tabs.addTab(self.output_table, "Outputs")
        device_tabs.addTab(self.input_table, "Inputs")
        config_scroll = QScrollArea()
        config_scroll.setWidgetResizable(True)
        config_scroll.setFrameShape(QFrame.NoFrame)
        config_scroll.setWidget(virtual)
        virtual.show()
        device_tabs.addTab(config_scroll, "Configure")
        self.devices_page = QWidget()
        device_layout = QVBoxLayout(self.devices_page)
        device_layout.setContentsMargins(0, 0, 0, 0)
        device_layout.addWidget(device_tabs, 1)
        device_layout.addWidget(w.device_details)
        w.device_details.hide()
        w.virtual_tree.setMaximumHeight(110)
        device_tabs.currentChanged.connect(
            lambda index: w.device_details.setVisible(index != 2 and bool(w.device_details.toPlainText()))
        )
        self.legacy_devices = devices
        devices.setParent(self.devices_page)
        devices.hide()
        self.device_tabs = device_tabs
        for table in (self.input_table, self.output_table):
            table.selected.connect(self.select_device)
        # Configuration and virtual-driver management share one Devices workspace.
        self.splitter = QSplitter(Qt.Vertical)
        self.route_scroll = QScrollArea()
        self.route_scroll.setWidgetResizable(True)
        self.route_scroll.setFrameShape(QFrame.NoFrame)
        self.routing_tabs.removeTab(self.routing_tabs.indexOf(routing))
        self.route_scroll.setWidget(routing)
        routing.show()
        self.splitter.addWidget(self.route_scroll)
        self.routing_tabs.insertTab(0, self.splitter, "Routes")
        self.routing_tabs.setCurrentIndex(0)
        from a2router.calibration_ui import CalibrationPanel

        self.calibration_panel = CalibrationPanel(w)
        calibration = QScrollArea()
        calibration.setWidgetResizable(True)
        calibration.setFrameShape(QFrame.NoFrame)
        calibration.setWidget(self.calibration_panel)
        diagnostics = QWidget()
        box = QVBoxLayout(diagnostics)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(w.diagnostics)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        box.addWidget(self.log)
        row = QHBoxLayout()
        export = QPushButton("Export diagnostics…")
        export.clicked.connect(self.export_diagnostics)
        row.addWidget(export)
        clear = QPushButton("Clear visible log")
        clear.clicked.connect(self.clear_log)
        row.addWidget(clear)
        box.addLayout(row)
        # Preferences are separate from audio-profile JSON.
        preferences = QGroupBox("Interface")
        form = QFormLayout(preferences)
        self.theme = QComboBox()
        self.theme.addItems(["Orange", "System", "White", "Dark", "Lime", "Blue", "Violet"])
        saved_theme = self.settings.value("theme", "Orange")
        self.theme.setCurrentText("White" if saved_theme == "Light" else saved_theme)
        self.theme.currentTextChanged.connect(self.apply_theme)
        form.addRow("Theme", self.theme)
        self.density = QComboBox()
        self.density.addItems(["Compact", "Extra compact"])
        self.density.setCurrentText(self.settings.value("density", "Compact"))
        self.density.currentTextChanged.connect(self.apply_theme)
        form.addRow("Density", self.density)
        settings.layout().insertWidget(0, preferences)
        for index in reversed(range(settings.layout().count())):
            item = settings.layout().itemAt(index)
            if (
                item.widget()
                and isinstance(item.widget(), QGroupBox)
                and item.widget().title() in ("Diagnostics", "Routing profiles")
            ):
                item.widget().hide()
        w.navigation.clear()
        for title, page in zip(
            (
                "Audio Routing",
                "Mixer",
                "Devices",
                "Calibration",
                "Diagnostics",
                "Settings",
            ),
            (self.routing_tabs, mixer, self.devices_page, calibration, diagnostics, settings),
        ):
            w.tabs.addWidget(page)
            w.navigation.addItem(title)
        w.header_title.hide()
        self.toolbar()
        self.menus()
        self.status = QLabel()
        w.statusBar().addPermanentWidget(self.status)
        w.route_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        w.route_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        w.route_tree.customContextMenuRequested.connect(self.route_menu)
        QApplication.instance().styleHints().colorSchemeChanged.connect(self.system_theme_changed)
        self.apply_theme()
        geometry = self.settings.value("geometry")
        if geometry:
            w.restoreGeometry(geometry)
        for key, splitter in (("routingSplitVerticalV1", self.splitter),):
            state = self.settings.value(key)
            if state:
                splitter.restoreState(state)
        for key, table in (("inputs", self.input_table), ("outputs", self.output_table)):
            state = self.settings.value(key + "Header")
            if state:
                table.view.horizontalHeader().restoreState(state)
        self.saved_fingerprint = self.fingerprint(w.controller.snapshot())

    def toolbar(self):
        w = self.window
        bar = QToolBar("Routing controls", w)
        bar.setMovable(False)
        bar.setIconSize(QSize(16, 16))
        self.profiles = QComboBox()  # Internal recent-file state; never shown outside File.
        self.profiles.hide()
        self.profiles.setMinimumContentsLength(16)
        self.profiles.setToolTip("Recent profiles; switching replaces routes after confirmation")
        self.profiles.addItem("Unsaved profile", "")
        for path in self.settings.value("recentProfiles", [], type=list):
            if isinstance(path, str) and path:
                self.profiles.addItem(Path(path).stem, path)
        self.profiles.activated.connect(self.choose_profile)

        self.actions = {}
        for key, title, shortcut, callback in (
            ("new", "New", "Ctrl+N", self.new_profile),
            ("open", "Open…", "Ctrl+O", self.open_profile),
            ("save", "Save", "Ctrl+S", self.save),
            ("save_as", "Save As…", "Ctrl+Shift+S", lambda: self.save(True)),
            ("refresh", "Refresh Devices", "Ctrl+R", lambda: w.refresh(manual=True)),
            ("start", "Start Routing", "", lambda: w.submit(w.controller.resume_routes)),
            ("stop", "Stop Routing", "", lambda: w.submit(w.controller.pause_routes)),
            ("emergency", "Emergency Mute", "Ctrl+Shift+M", self.emergency),
        ):
            action = QAction(title, w)
            if shortcut:
                action.setShortcut(shortcut)
            action.triggered.connect(
                lambda checked=False, operation=callback, label=title: self.invoke(label, operation)
            )
            if key in ("start", "stop", "emergency"):
                action.setEnabled(w.backend.capabilities().get("routing", False))
                action.setToolTip(
                    "Controls only A2Router-managed audio streams"
                    if action.isEnabled()
                    else "Routing is unavailable; inspect backend diagnostics"
                )
            self.actions[key] = action
            w.addAction(action)
            if key in ("refresh", "start", "stop", "emergency"):
                bar.addAction(action)
        w.addToolBar(bar)
        # Central navigation must appear above the global toolbar.
        w.removeToolBar(bar)
        w.centralWidget().layout().insertWidget(1, bar)
        bar.show()

    def invoke(self, title, callback):
        self.record(f"Requested: {title}")
        callback()

    def menus(self):
        w = self.window
        menus = {
            name: w.menuBar().addMenu(name)
            for name in ("File", "Edit", "View", "Routing", "Devices", "Tools", "Help")
        }
        for key in ("new", "open", "save", "save_as"):
            menus["File"].addAction(self.actions[key])
        recent = menus["File"].addMenu("Recent profiles")
        self.recent_menu = recent
        self.rebuild_recent_menu()
        menus["File"].addSeparator()
        menus["File"].addAction("Exit", w.exit_application)
        menus["Edit"].addAction("Copy selected device rows", self.copy_rows)
        menus["Edit"].addAction("Filter inputs", lambda: self.input_table.filter.setFocus(), "Ctrl+F")
        for index, button in enumerate(w.navigation.buttons):
            menus["View"].addAction(
                button.text(), lambda checked=False, i=index: w.navigation.setCurrentRow(i)
            )
        themes = menus["View"].addMenu("Theme")
        group = QActionGroup(w)
        for name in ("System", "White", "Dark", "Lime", "Blue", "Violet"):
            action = themes.addAction(name)
            action.setCheckable(True)
            action.setChecked(name == self.theme.currentText())
            action.triggered.connect(lambda checked=False, value=name: self.theme.setCurrentText(value))
            group.addAction(action)
        for key in ("start", "stop", "emergency"):
            menus["Routing"].addAction(self.actions[key])
        for title, method in (
            ("Enable selected routes", "enable_route"),
            ("Disable selected routes", "disable_route"),
            ("Remove selected routes", "remove_route"),
        ):
            menus["Routing"].addAction(title, lambda checked=False, m=method: w.route_action(m))
        menus["Routing"].addAction("Delay compensation", self.open_delay)
        menus["Devices"].addAction(self.actions["refresh"])
        menus["Devices"].addAction("Selected device properties", self.device_properties)
        sound = menus["Tools"].addAction(
            "Windows Sound settings", lambda: QDesktopServices.openUrl(QUrl("ms-settings:sound"))
        )
        mixer = menus["Tools"].addAction(
            "Windows Volume Mixer", lambda: QDesktopServices.openUrl(QUrl("ms-settings:apps-volume"))
        )
        import sys

        for action in (sound, mixer):
            action.setEnabled(sys.platform == "win32")
            action.setToolTip("Requires Windows")
        menus["Tools"].addAction("Export diagnostics…", self.export_diagnostics)
        menus["Help"].addAction(
            "User guide",
            lambda: QDesktopServices.openUrl(
                QUrl("https://github.com/vkr-6/A2Router/blob/main/docs/user-guide.md")
            ),
            "F1",
        )
        menus["Help"].addAction(
            "About A2Router",
            lambda: QMessageBox.about(
                w,
                "A2Router",
                "A2Router — Advanced Audio Router\nNative WASAPI / PipeWire audio routing\nBased on MultiRoute. Developed with OpenAI Codex.\nVB-CABLE © VB-Audio Software.",
            ),
        )
        refresh = QAction(w)
        refresh.setShortcut("F5")
        refresh.triggered.connect(lambda: w.refresh(manual=True))
        w.addAction(refresh)

    def route_menu(self, point):
        w = self.window
        menu = QMenu(w)
        for text, method in (
            ("Enable", "enable_route"),
            ("Disable", "disable_route"),
            ("Remove", "remove_route"),
        ):
            menu.addAction(text, lambda checked=False, m=method: w.route_action(m))
        menu.addAction("Edit delay", self.open_delay)
        menu.exec(w.route_tree.viewport().mapToGlobal(point))

    def open_delay(self):
        w = self.window
        w.navigation.setCurrentRow(0)
        self.routing_tabs.setCurrentIndex(0)
        self.delay_group.setChecked(True)
        QTimer.singleShot(0, lambda: self.route_scroll.ensureWidgetVisible(w.sync_delay, 0, 16))
        selected = w.route_tree.selectedItems()
        if selected:
            w.sync_route.setCurrentIndex(w.sync_route.findData(selected[0].data(0, Qt.UserRole)))

    def edit_endpoint(self, ident, field, value):
        w = self.window
        if field == "volume":
            w.change_device_volume(ident, value)
        else:
            w.change_device_mute(ident, value)

    def emergency(self):
        w = self.window
        # Discard queued mutations that could restart transport after the stop.
        w.controller.request_emergency_stop()
        w._pending_actions.clear()
        w.submit(w.controller.pause_routes, persist=False)

    @staticmethod
    def fingerprint(data):
        return json.dumps(data, sort_keys=True)

    def confirm_replace(self):
        if self.last_fingerprint == self.saved_fingerprint:
            return True
        return (
            QMessageBox.question(
                self.window,
                "Replace routing profile?",
                "Unsaved profile changes will be replaced. Continue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            == QMessageBox.Yes
        )

    def new_profile(self):
        if self.confirm_replace():
            self.load_data({"version": 1, "routes": [], "virtual_devices": []}, None)

    def choose_profile(self, index):
        path = self.profiles.itemData(index)
        if path and self.confirm_replace():
            self.open_path(path)

    def open_profile(self):
        if not self.confirm_replace():
            return
        path, _ = QFileDialog.getOpenFileName(self.window, "Open profile", str(config_dir()), "JSON (*.json)")
        if path:
            self.open_path(path)

    def open_path(self, path):
        # Parsing and disk IO stay on the serialized worker; failures keep current state.
        self.window.submit(lambda: self._load(path))

    def _load(self, path):
        data = storage.load(path)
        result = self.window.controller.replace_profile(data)
        self.profile_path = Path(path)
        self.saved_fingerprint = self.fingerprint(self.window.controller.snapshot())
        return result

    def load_data(self, data, path):
        def work():
            result = self.window.controller.replace_profile(data)
            self.profile_path = path
            self.saved_fingerprint = self.fingerprint(self.window.controller.snapshot())
            return result

        self.window.submit(work)

    def save(self, save_as=False):
        path = self.profile_path
        if path is None or save_as:
            path, _ = QFileDialog.getSaveFileName(
                self.window, "Save profile", str(config_dir() / "profile.json"), "JSON (*.json)"
            )
        if path:

            def work():
                self.window.controller.save(path)
                self.profile_path = Path(path)
                self.saved_fingerprint = self.fingerprint(self.window.controller.snapshot())
                return "Profile saved"

            self.window.submit(work, persist=False, refresh_backend=False)

    def copy_rows(self):
        QApplication.clipboard().setText(
            self.input_table.selected_text() + "\n" + self.output_table.selected_text()
        )

    def device_properties(self):
        selected = self.output_table.view.currentIndex().data(
            Qt.UserRole
        ) or self.input_table.view.currentIndex().data(Qt.UserRole)
        if selected:
            self.window.navigation.setCurrentRow(2)
            for index in range(self.window.device_tree.topLevelItemCount()):
                item = self.window.device_tree.topLevelItem(index)
                if item.data(0, Qt.UserRole) == selected:
                    self.window.device_tree.setCurrentItem(item)
                    break

    def export_diagnostics(self):
        if (
            QMessageBox.question(
                self.window,
                "Review diagnostics",
                "This export includes device names, stable IDs, native library paths and route errors. Review the Diagnostics page before sharing. Export?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return
        path, _ = QFileDialog.getSaveFileName(
            self.window, "Export diagnostics", "a2router-diagnostics.json", "JSON (*.json)"
        )
        if path:
            payload = self.window.diagnostics.toPlainText()
            events = list(self.events)

            def write():
                # Reuse the atomic writer for arbitrary support data without changing profile validation.
                import os
                import tempfile

                temporary = None
                try:
                    with tempfile.NamedTemporaryFile(
                        "w", encoding="utf-8", dir=Path(path).parent, delete=False
                    ) as stream:
                        temporary = stream.name
                        json.dump({"diagnostics": json.loads(payload), "events": events}, stream, indent=2)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, path)
                finally:
                    if temporary and os.path.exists(temporary):
                        os.unlink(temporary)
                return "Diagnostics exported"

            self.window.submit(write, persist=False, refresh_backend=False)

    def clear_log(self):
        self.events.clear()
        self.last_event = None
        self.log.clear()

    def record(self, message):
        if message and message != self.last_event:
            from datetime import datetime, timezone

            line = f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}  {message}"
            self.events.append(line)
            self.events = self.events[-2000:]
            self.log.appendPlainText(line)
            self.last_event = message

    def update(self, snapshot):
        self.matrix.refresh()
        for table in (self.input_table, self.output_table):
            table.model.update_devices(snapshot["devices"])
        diagnostics = snapshot["diagnostics"]
        self.calibration_panel.populate(snapshot.get("calibration"), snapshot["devices"])
        count_in = len({r["source_id"] for r in snapshot["routes"] if r["status"] == "connected"})
        count_out = len({r["destination_id"] for r in snapshot["routes"] if r["status"] == "connected"})
        profile = self.profile_path.stem if self.profile_path else "Unsaved profile"
        self.last_fingerprint = self.fingerprint(self.window.controller.snapshot())
        dirty = self.last_fingerprint != self.saved_fingerprint
        state = (
            "Stopped" if not self.window.backend.transport_running else ("Routing" if count_out else "Idle")
        )
        if diagnostics.get("error"):
            state = "Error"
        self.status.setText(
            f"{state} · {self.window.backend.name} · {count_in} sources / {count_out} outputs"
        )
        self.window.setWindowTitle(f"A2Router — {profile}{' *' if dirty else ''}")
        if self.profile_path:
            path = str(self.profile_path)
            index = self.profiles.findData(path)
            if index < 0:
                self.profiles.addItem(profile, path)
                self.rebuild_recent_menu()
                index = self.profiles.count() - 1
            self.profiles.setCurrentIndex(index)
        else:
            self.profiles.setCurrentIndex(0)

    def select_device(self, ident):
        w = self.window
        for index in range(w.device_tree.topLevelItemCount()):
            item = w.device_tree.topLevelItem(index)
            if item.data(0, Qt.UserRole) == ident:
                w.device_tree.setCurrentItem(item)
                w.inspect_device()
                w.device_details.setVisible(self.device_tabs.currentIndex() != 2)
                break
        if w._vbcable_page:
            index = w.cable_endpoint.findData(ident)
            if index >= 0:
                w.cable_endpoint.setCurrentIndex(index)

    def rebuild_recent_menu(self):
        self.recent_menu.clear()
        for index in range(1, self.profiles.count()):
            path = self.profiles.itemData(index)
            self.recent_menu.addAction(str(path), lambda checked=False, p=path: self.open_recent(p))
        self.recent_menu.setEnabled(self.profiles.count() > 1)

    def open_recent(self, path):
        if self.confirm_replace():
            self.open_path(path)

    def system_theme_changed(self, *_):
        if self.theme.currentText() == "System":
            self.apply_theme()

    def apply_theme(self, *_):
        from a2router.themes import apply_theme

        apply_theme(self.window, self.theme.currentText(), self.density.currentText())
        self.settings.setValue("theme", self.theme.currentText())
        self.settings.setValue("density", self.density.currentText())

    def persist_layout(self):
        try:
            QApplication.instance().styleHints().colorSchemeChanged.disconnect(self.system_theme_changed)
        except (RuntimeError, TypeError):
            pass  # Already disconnected during repeated shutdown.
        self.settings.setValue("geometry", self.window.saveGeometry())
        self.settings.setValue("routingSplitVerticalV1", self.splitter.saveState())

        for key, table in (("inputs", self.input_table), ("outputs", self.output_table)):
            self.settings.setValue(key + "Header", table.view.horizontalHeader().saveState())
        paths = [self.profiles.itemData(i) for i in range(1, self.profiles.count())]
        self.settings.setValue("recentProfiles", paths[-12:])
        self.settings.sync()
