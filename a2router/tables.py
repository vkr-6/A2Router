"""Stable-identity, sortable device tables. No backend operations run in models."""

import csv

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHeaderView,
    QLineEdit,
    QMenu,
    QStyledItemDelegate,
    QTableView,
    QVBoxLayout,
    QWidget,
)


class DeviceModel(QAbstractTableModel):
    edit_requested = Signal(str, str, object)

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind, self.rows = kind, []
        self.columns = ["Name", "Type", "Device ID", "Channels", "Rate (Hz)", "Format", "State"]
        if kind == "output":
            self.columns += ["Volume (%)", "Mute", "Peak (dBFS)"]

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.rows)

    def columnCount(self, parent=None):
        return len(self.columns)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.columns[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        device = self.rows[index.row()]
        controls = device.get("properties", {}).get("controls", {})
        if role == Qt.UserRole:
            return device["id"]
        if role == Qt.ToolTipRole:
            return device["id"]
        if role not in (Qt.DisplayRole, Qt.EditRole):
            return None
        values = [
            device["name"],
            "Virtual" if device.get("virtual") else "Endpoint",
            device["id"],
            device.get("channels"),
            device.get("sample_rate"),
            device.get("sample_format"),
            device["state"],
        ]
        if self.kind == "output":
            import math

            peak = controls.get("peak") if controls.get("peak_available") else None
            values += [
                round(controls["volume"] * 100) if controls.get("volume_available") else None,
                ("Yes" if controls.get("muted") else "No") if controls.get("volume_available") else None,
                f"{20 * math.log10(max(peak, 1e-6)):.1f}" if peak is not None else None,
            ]
        value = values[index.column()]
        return value if value is not None else ("N/A" if role == Qt.DisplayRole else None)

    def flags(self, index):
        flags = super().flags(index)
        if (
            index.isValid()
            and self.kind == "output"
            and index.column() in (7, 8)
            and self.rows[index.row()].get("properties", {}).get("controls", {}).get("volume_available")
        ):
            flags |= Qt.ItemIsEditable
        return flags

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole or not self.flags(index) & Qt.ItemIsEditable:
            return False
        try:
            if index.column() == 7:
                value = float(value)
                if not 0 <= value <= 100:
                    return False
                field, value = "volume", value / 100
            else:
                text = str(value).strip().lower()
                if text not in ("yes", "no", "true", "false", "1", "0"):
                    return False
                field, value = "mute", text in ("yes", "true", "1")
        except (TypeError, ValueError):
            return False
        self.edit_requested.emit(self.rows[index.row()]["id"], field, value)
        # The next observed snapshot confirms the edit; no optimistic fake state.
        return True

    def update_devices(self, devices):
        wanted = [d for d in devices if d["kind"] == self.kind]
        wanted_ids = {d["id"] for d in wanted}
        for i in reversed(range(len(self.rows))):
            if self.rows[i]["id"] not in wanted_ids:
                self.beginRemoveRows(QModelIndex(), i, i)
                self.rows.pop(i)
                self.endRemoveRows()
        positions = {d["id"]: i for i, d in enumerate(self.rows)}
        for device in wanted:
            index = positions.get(device["id"])
            if index is None:
                index = len(self.rows)
                self.beginInsertRows(QModelIndex(), index, index)
                self.rows.append(device)
                self.endInsertRows()
            elif self.rows[index] != device:
                before = [self.data(self.index(index, col)) for col in range(len(self.columns))]
                self.rows[index] = device
                for col, old in enumerate(before):
                    cell = self.index(index, col)
                    if self.data(cell) != old:
                        self.dataChanged.emit(cell, cell)


class EndpointDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        if index.column() == 7:
            editor = QDoubleSpinBox(parent)
            editor.setRange(0, 100)
            editor.setDecimals(1)
            editor.setSuffix(" %")
            return editor
        if index.column() == 8:
            editor = QComboBox(parent)
            editor.addItems(["No", "Yes"])
            return editor
        return super().createEditor(parent, option, index)

    def setEditorData(self, editor, index):
        if isinstance(editor, QDoubleSpinBox):
            editor.setValue(float(index.data(Qt.EditRole)))
        elif isinstance(editor, QComboBox):
            editor.setCurrentText(index.data(Qt.EditRole))
        else:
            super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        if isinstance(editor, QDoubleSpinBox):
            model.setData(index, editor.value())
        elif isinstance(editor, QComboBox):
            model.setData(index, editor.currentText())
        else:
            super().setModelData(editor, model, index)


class DeviceTable(QWidget):
    selected = Signal(str)

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(f"Filter {kind} devices…")
        layout.addWidget(self.filter)
        self.model = DeviceModel(kind, self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterKeyColumn(-1)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.filter.textChanged.connect(self.proxy.setFilterFixedString)
        self.view = QTableView()
        self.view.setModel(self.proxy)
        self.view.setItemDelegate(EndpointDelegate(self.view))
        self.view.setSelectionBehavior(QTableView.SelectRows)
        self.view.setSelectionMode(QTableView.ExtendedSelection)
        self.view.setAlternatingRowColors(True)
        self.view.setSortingEnabled(True)
        self.view.verticalHeader().setDefaultSectionSize(23)
        self.view.verticalHeader().hide()
        self.view.horizontalHeader().setSectionsMovable(True)
        self.view.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.view.setColumnWidth(0, 210)
        self.view.setColumnWidth(2, 155)
        self.view.selectionModel().currentRowChanged.connect(
            lambda current, previous: (
                self.selected.emit(current.data(Qt.UserRole)) if current.isValid() else None
            )
        )
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self.context_menu)
        self.view.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.horizontalHeader().customContextMenuRequested.connect(self.column_menu)
        layout.addWidget(self.view)

    def column_menu(self, point):
        menu = QMenu(self)
        for index, title in enumerate(self.model.columns):
            action = menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(not self.view.isColumnHidden(index))
            action.toggled.connect(
                lambda checked, column=index: self.view.setColumnHidden(column, not checked)
            )
        menu.exec(self.view.horizontalHeader().mapToGlobal(point))

    def selected_text(self):
        rows = sorted({i.row() for i in self.view.selectionModel().selectedRows()})
        return "\n".join(
            "\t".join(str(self.proxy.index(r, c).data()) for c in range(self.proxy.columnCount()))
            for r in rows
        )

    def context_menu(self, point):
        menu = QMenu(self)
        copy = menu.addAction("Copy selected rows")
        copy.triggered.connect(lambda: QApplication.clipboard().setText(self.selected_text()))
        export = menu.addAction("Export table to CSV…")
        export.triggered.connect(self.export_csv)
        menu.exec(self.view.viewport().mapToGlobal(point))

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export device table", "devices.csv", "CSV (*.csv)")
        if path:
            try:
                with open(path, "w", newline="", encoding="utf-8-sig") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(self.model.columns)
                    for row in range(self.proxy.rowCount()):
                        writer.writerow(
                            self.proxy.index(row, col).data() for col in range(self.proxy.columnCount())
                        )
            except OSError as exc:
                from PySide6.QtWidgets import QMessageBox

                QMessageBox.warning(self, "Export failed", str(exc))
