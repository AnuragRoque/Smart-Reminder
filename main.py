import sys
import json
import random
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, time as dtime

from PyQt6.QtCore import Qt, QTimer, QTime, QEvent, pyqtSignal
from PyQt6.QtGui import QAction, QIcon, QPixmap, QPainter, QColor, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QComboBox,
    QCheckBox,
    QTimeEdit,
    QMessageBox,
    QScrollArea,
    QTextEdit,
    QFrame,
    QSystemTrayIcon,
    QMenu,
    QGroupBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QFileDialog,
    QLineEdit,
    QDialog,
    QAbstractSpinBox,
)

try:
    from winotify import Notification
except Exception:
    Notification = None


APP_TITLE = "Focus Reminder Suite"
DB_PATH = "focus_reminder_suite.db"


@dataclass
class ReminderTemplate:
    key: str
    category: str
    name: str
    kind: str  # fixed | random | goal
    description: str
    default_interval: int = 0
    default_min: int = 0
    default_max: int = 0
    default_goal: int = 0


TEMPLATES = [
    ReminderTemplate(
        key="eye_202020",
        category="Eye Care",
        name="20-20-20 reminder",
        kind="fixed",
        description="Look at something 20 feet away for 20 seconds.",
        default_interval=20,
    ),
    ReminderTemplate(
        key="posture_random",
        category="Posture Care",
        name="Random posture check",
        kind="random",
        description="Random posture check during the work window.",
        default_min=25,
        default_max=45,
    ),
    ReminderTemplate(
        key="posture_neck",
        category="Posture Care",
        name="Neck straight reminder",
        kind="fixed",
        description="Straighten your neck and keep your head aligned.",
        default_interval=35,
    ),
    ReminderTemplate(
        key="posture_shoulder",
        category="Posture Care",
        name="Shoulder relaxation reminder",
        kind="fixed",
        description="Relax shoulders and release upper body tension.",
        default_interval=50,
    ),
    ReminderTemplate(
        key="movement_stand",
        category="Movement",
        name="Stand-up reminder",
        kind="fixed",
        description="Stand up and move for a moment.",
        default_interval=45,
    ),
    ReminderTemplate(
        key="movement_walk",
        category="Movement",
        name="Walk reminder",
        kind="fixed",
        description="Walk around briefly to reset your body.",
        default_interval=90,
    ),
    ReminderTemplate(
        key="movement_stretch",
        category="Movement",
        name="Stretch reminder",
        kind="fixed",
        description="Do a short stretch set to reduce stiffness.",
        default_interval=60,
    ),
    ReminderTemplate(
        key="hydration_water",
        category="Hydration",
        name="Water reminder",
        kind="goal",
        description="Daily hydration goal. The app spaces reminders across the work window.",
        default_goal=8,
    ),
]


class ReminderPopup(QDialog):
    def __init__(self, title: str, message: str, snooze_minutes: int, icon_path: str | None = None, auto_dismiss_mins: int = 0, parent=None):
        super().__init__(parent)
        self.action = "OK"
        self.snooze_minutes = snooze_minutes
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setModal(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)

        card = QFrame()
        card.setObjectName("PopupCard")
        card.setStyleSheet(
            """
            QFrame#PopupCard {
                background: #ffffff;
                border: 1px solid #d8deea;
                border-radius: 18px;
            }
            QLabel#PopupTitle {
                font-size: 15px;
                font-weight: 700;
                color: #0f172a;
            }
            QLabel#PopupMessage {
                color: #334155;
                font-size: 10pt;
            }
            QLabel#PopupHint {
                color: #64748b;
                font-size: 9pt;
            }
            QLabel#PopupCountdown {
                color: #e11d48;
                font-size: 9pt;
                font-weight: 600;
            }
            QPushButton#PopupPrimary {
                background: #2563eb;
            }
            QPushButton#PopupSecondary {
                background: #475569;
            }
            QPushButton#PopupWarning {
                background: #b45309;
            }
            QPushButton#PopupPrimary:hover { background: #1d4ed8; }
            QPushButton#PopupSecondary:hover { background: #334155; }
            QPushButton#PopupWarning:hover { background: #92400e; }
            """
        )
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        top = QHBoxLayout()
        self.icon_lbl = QLabel()
        self.icon_lbl.setFixedSize(60, 60)
        self.icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_lbl.setStyleSheet("background: #eff6ff; border-radius: 14px; border: 1px solid #dbeafe;")
        self.set_icon(icon_path)

        text_block = QVBoxLayout()
        self.title_lbl = QLabel(title)
        self.title_lbl.setObjectName("PopupTitle")
        self.message_lbl = QLabel(message)
        self.message_lbl.setObjectName("PopupMessage")
        self.message_lbl.setWordWrap(True)
        self.hint_lbl = QLabel(f"Snooze for {snooze_minutes} minutes from Settings.")
        self.hint_lbl.setObjectName("PopupHint")
        text_block.addWidget(self.title_lbl)
        text_block.addWidget(self.message_lbl)
        text_block.addWidget(self.hint_lbl)

        self.auto_dismiss_seconds = auto_dismiss_mins * 60
        self.seconds_remaining = self.auto_dismiss_seconds

        if self.auto_dismiss_seconds > 0:
            self.countdown_lbl = QLabel(f"Auto-dismissing in {self._format_time(self.seconds_remaining)}")
            self.countdown_lbl.setObjectName("PopupCountdown")
            text_block.addWidget(self.countdown_lbl)

            self.dismiss_timer = QTimer(self)
            self.dismiss_timer.setInterval(1000)
            self.dismiss_timer.timeout.connect(self._tick_countdown)
            self.dismiss_timer.start()

        top.addWidget(self.icon_lbl)
        top.addLayout(text_block, 1)
        layout.addLayout(top)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        self.snooze_btn = QPushButton(f"Snooze {snooze_minutes}m")
        self.snooze_btn.setObjectName("PopupWarning")
        self.snooze_btn.clicked.connect(lambda: self._finish("SNOOZE"))

        self.dnd_btn = QPushButton("DND")
        self.dnd_btn.setObjectName("PopupSecondary")
        self.dnd_btn.clicked.connect(lambda: self._finish("DND"))

        self.ok_btn = QPushButton("OK")
        self.ok_btn.setObjectName("PopupPrimary")
        self.ok_btn.clicked.connect(lambda: self._finish("OK"))

        for btn in (self.snooze_btn, self.dnd_btn, self.ok_btn):
            btn.setMinimumWidth(110)
            btn_row.addWidget(btn)

        layout.addLayout(btn_row)

        self.resize(420, 180)

    def _format_time(self, total_seconds: int) -> str:
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        if minutes > 0:
            return f"{minutes}m {seconds:02d}s"
        return f"{seconds}s"

    def _tick_countdown(self):
        self.seconds_remaining -= 1
        if self.seconds_remaining <= 0:
            self.dismiss_timer.stop()
            self._finish("TIMEOUT")
        else:
            self.countdown_lbl.setText(f"Auto-dismissing in {self._format_time(self.seconds_remaining)}")

    def set_icon(self, icon_path: str | None):
        if icon_path:
            pix = QPixmap(icon_path)
            if not pix.isNull():
                pix = pix.scaled(44, 44, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.icon_lbl.setPixmap(pix)
                return
        pix = QPixmap(44, 44)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#2563eb"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, 44, 44, 10, 10)
        painter.setPen(QColor("white"))
        font = QFont()
        font.setBold(True)
        font.setPointSize(14)
        painter.setFont(font)
        painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "FR")
        painter.end()
        self.icon_lbl.setPixmap(pix)

    def _finish(self, action: str):
        if hasattr(self, "dismiss_timer") and self.dismiss_timer.isActive():
            self.dismiss_timer.stop()
        self.action = action
        self.accept()


class ReminderCard(QFrame):
    changed = pyqtSignal()

    def __init__(self, template: ReminderTemplate, parent=None):
        super().__init__(parent)
        self.template = template
        self.key = template.key
        self.next_due: datetime | None = None
        self.last_fired: datetime | None = None
        self.awaiting_response = False
        self.last_popup_sent_at: datetime | None = None
        self.setObjectName("ReminderCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)

        main = QVBoxLayout(self)
        main.setContentsMargins(10, 8, 10, 8)
        main.setSpacing(5)

        header = QHBoxLayout()
        header.setSpacing(8)

        self.enable_cb = QCheckBox()
        self.enable_cb.setChecked(True)
        self.enable_cb.toggled.connect(self._on_enabled_changed)

        title_block = QVBoxLayout()
        title_block.setSpacing(2)

        self.title_lbl = QLabel(self.template.name)
        title_font = self.title_lbl.font()
        title_font.setPointSize(9)
        title_font.setBold(True)
        self.title_lbl.setFont(title_font)

        self.category_lbl = QLabel(self.template.category)
        self.category_lbl.setObjectName("CategoryLabel")

        title_block.addWidget(self.title_lbl)
        title_block.addWidget(self.category_lbl)

        header.addWidget(self.enable_cb)
        header.addLayout(title_block)
        header.addStretch(1)

        header.addWidget(QLabel("Mode"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Inherit", "Toast", "Popup", "Both", "Off"])
        self.mode_combo.currentTextChanged.connect(lambda *_: self.changed.emit())
        header.addWidget(self.mode_combo)

        main.addLayout(header)

        self.desc_lbl = QLabel(self.template.description)
        self.desc_lbl.setWordWrap(True)
        self.desc_lbl.setObjectName("DescriptionLabel")
        main.addWidget(self.desc_lbl)

        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.schedule_hint = QLabel("")
        self.schedule_hint.setObjectName("HintLabel")

        if self.template.kind == "fixed":
            controls.addWidget(QLabel("Interval"))
            self.interval_spin = QSpinBox()
            self.interval_spin.setRange(1, 720)
            self.interval_spin.setValue(self.template.default_interval or 20)
            self.interval_spin.setSuffix(" min")
            self.interval_spin.setSingleStep(1)
            self.interval_spin.setFixedWidth(120)
            self.interval_spin.valueChanged.connect(lambda *_: self.changed.emit())
            controls.addWidget(self.interval_spin)

        elif self.template.kind == "random":
            controls.addWidget(QLabel("Min"))
            self.min_spin = QSpinBox()
            self.min_spin.setRange(1, 720)
            self.min_spin.setValue(self.template.default_min or 20)
            self.min_spin.setSuffix(" min")
            self.min_spin.setSingleStep(1)
            self.min_spin.setFixedWidth(120)
            self.min_spin.valueChanged.connect(self._on_random_changed)
            controls.addWidget(self.min_spin)

            controls.addWidget(QLabel("Max"))
            self.max_spin = QSpinBox()
            self.max_spin.setRange(1, 720)
            self.max_spin.setValue(self.template.default_max or 45)
            self.max_spin.setSuffix(" min")
            self.max_spin.setSingleStep(1)
            self.max_spin.setFixedWidth(120)
            self.max_spin.valueChanged.connect(self._on_random_changed)
            controls.addWidget(self.max_spin)

        elif self.template.kind == "goal":
            controls.addWidget(QLabel("Daily goal"))
            self.goal_spin = QSpinBox()
            self.goal_spin.setRange(1, 100)
            self.goal_spin.setValue(self.template.default_goal or 8)
            self.goal_spin.setSuffix(" alerts")
            self.goal_spin.setSingleStep(1)
            self.goal_spin.setFixedWidth(120)
            self.goal_spin.valueChanged.connect(lambda *_: self.changed.emit())
            controls.addWidget(self.goal_spin)

        controls.addStretch(1)
        controls.addWidget(self.schedule_hint)
        main.addLayout(controls)

        footer = QHBoxLayout()
        self.next_lbl = QLabel("Next: --")
        self.last_lbl = QLabel("Last: --")
        self.next_lbl.setObjectName("MetaLabel")
        self.last_lbl.setObjectName("MetaLabel")
        footer.addWidget(self.next_lbl)
        footer.addWidget(self.last_lbl)
        footer.addStretch(1)
        main.addLayout(footer)

        self._toggle_schedule_controls()

    def _on_enabled_changed(self, _checked: bool):
        self._toggle_schedule_controls()
        self.changed.emit()

    def _on_random_changed(self, _value: int):
        if hasattr(self, "min_spin") and hasattr(self, "max_spin"):
            if self.min_spin.value() > self.max_spin.value():
                self.max_spin.blockSignals(True)
                self.max_spin.setValue(self.min_spin.value())
                self.max_spin.blockSignals(False)
        self.changed.emit()

    def _toggle_schedule_controls(self):
        enabled = self.enable_cb.isChecked()
        for widget in self._schedule_widgets():
            widget.setEnabled(enabled)
        self.setProperty("disabledCard", not enabled)
        self.style().unpolish(self)
        self.style().polish(self)

    def _schedule_widgets(self):
        widgets = []
        if hasattr(self, "interval_spin"):
            widgets.append(self.interval_spin)
        if hasattr(self, "min_spin"):
            widgets.append(self.min_spin)
        if hasattr(self, "max_spin"):
            widgets.append(self.max_spin)
        if hasattr(self, "goal_spin"):
            widgets.append(self.goal_spin)
        widgets.append(self.mode_combo)
        return widgets

    def is_enabled(self) -> bool:
        return self.enable_cb.isChecked()

    def effective_mode(self, global_mode: str, meeting_mode: bool, dnd_active: bool) -> str:
        if meeting_mode or dnd_active or not self.is_enabled():
            return "Off"
        mode = self.mode_combo.currentText()
        return global_mode if mode == "Inherit" else mode

    def schedule_interval_minutes(self, window_minutes: int) -> int:
        if self.template.kind == "fixed":
            return max(1, self.interval_spin.value())
        if self.template.kind == "random":
            lo = min(self.min_spin.value(), self.max_spin.value())
            hi = max(self.min_spin.value(), self.max_spin.value())
            return random.randint(lo, hi)
        if self.template.kind == "goal":
            goal = max(1, self.goal_spin.value())
            return max(1, round(window_minutes / goal))
        return 20

    def estimated_daily_count(self, window_minutes: int) -> int:
        if not self.is_enabled():
            return 0
        if self.template.kind == "fixed":
            interval = max(1, self.interval_spin.value())
            return max(1, window_minutes // interval)
        if self.template.kind == "random":
            lo = min(self.min_spin.value(), self.max_spin.value())
            hi = max(self.min_spin.value(), self.max_spin.value())
            avg = (lo + hi) / 2
            if avg <= 0:
                return 0
            return max(1, round(window_minutes / avg))
        if self.template.kind == "goal":
            return max(1, self.goal_spin.value())
        return 0

    def update_preview(self, window_minutes: int, global_mode: str, meeting_mode: bool, dnd_active: bool):
        mode = self.effective_mode(global_mode, meeting_mode, dnd_active)
        if not self.is_enabled():
            self.schedule_hint.setText("Disabled")
            self.next_lbl.setText("Next: disabled")
            return

        if self.template.kind == "fixed":
            interval = self.interval_spin.value()
            self.schedule_hint.setText(f"Every {interval} min · ~{self.estimated_daily_count(window_minutes)} / day")
        elif self.template.kind == "random":
            lo = min(self.min_spin.value(), self.max_spin.value())
            hi = max(self.min_spin.value(), self.max_spin.value())
            avg = round((lo + hi) / 2)
            self.schedule_hint.setText(f"Random {lo}-{hi} min · avg ~{avg} · ~{self.estimated_daily_count(window_minutes)} / day")
        elif self.template.kind == "goal":
            goal = self.goal_spin.value()
            interval = max(1, round(window_minutes / goal))
            self.schedule_hint.setText(f"Goal {goal}/day · spacing ~{interval} min")
        else:
            self.schedule_hint.setText("")

        if mode == "Off":
            self.next_lbl.setText("Next: muted")
        elif self.next_due is None:
            self.next_lbl.setText("Next: --")
        else:
            self.next_lbl.setText("Next: " + self.next_due.strftime("%H:%M:%S"))

        if self.last_fired is None:
            self.last_lbl.setText("Last: --")
        else:
            self.last_lbl.setText("Last: " + self.last_fired.strftime("%H:%M:%S"))

    def compute_next_due(self, now: datetime, window_start: datetime, window_end: datetime, window_minutes: int) -> datetime:
        interval = self.schedule_interval_minutes(window_minutes)
        base = max(now, window_start)
        due = base + timedelta(minutes=interval)
        if due > window_end:
            next_start = window_start + timedelta(days=1)
            due = next_start + timedelta(minutes=interval)
        return due

    def to_state(self) -> dict:
        state = {
            "enabled": self.enable_cb.isChecked(),
            "mode": self.mode_combo.currentText(),
        }
        if self.template.kind == "fixed":
            state["interval"] = self.interval_spin.value()
        elif self.template.kind == "random":
            state["min"] = self.min_spin.value()
            state["max"] = self.max_spin.value()
        elif self.template.kind == "goal":
            state["goal"] = self.goal_spin.value()
        if self.next_due is not None:
            state["next_due"] = self.next_due.strftime("%Y-%m-%d %H:%M:%S")
        if self.last_fired is not None:
            state["last_fired"] = self.last_fired.strftime("%Y-%m-%d %H:%M:%S")
        return state

    def apply_state(self, state: dict):
        self.enable_cb.blockSignals(True)
        self.mode_combo.blockSignals(True)
        self.enable_cb.setChecked(bool(state.get("enabled", True)))
        self.mode_combo.setCurrentText(state.get("mode", "Inherit"))
        self.enable_cb.blockSignals(False)
        self.mode_combo.blockSignals(False)

        if self.template.kind == "fixed" and "interval" in state:
            self.interval_spin.blockSignals(True)
            self.interval_spin.setValue(int(state["interval"]))
            self.interval_spin.blockSignals(False)
        elif self.template.kind == "random":
            if "min" in state:
                self.min_spin.blockSignals(True)
                self.min_spin.setValue(int(state["min"]))
                self.min_spin.blockSignals(False)
            if "max" in state:
                self.max_spin.blockSignals(True)
                self.max_spin.setValue(int(state["max"]))
                self.max_spin.blockSignals(False)
        elif self.template.kind == "goal" and "goal" in state:
            self.goal_spin.blockSignals(True)
            self.goal_spin.setValue(int(state["goal"]))
            self.goal_spin.blockSignals(False)

        if state.get("next_due"):
            try:
                self.next_due = datetime.strptime(state["next_due"], "%Y-%m-%d %H:%M:%S")
            except Exception:
                self.next_due = None
        if state.get("last_fired"):
            try:
                self.last_fired = datetime.strptime(state["last_fired"], "%Y-%m-%d %H:%M:%S")
            except Exception:
                self.last_fired = None
        self._toggle_schedule_controls()

    def reset_runtime(self):
        self.next_due = None
        self.last_fired = None
        self.awaiting_response = False
        self.last_popup_sent_at = None


class ReminderApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1000, 720)
        self.setMinimumSize(900, 600)

        self.loading = False
        self.popup_active = False
        self.session_dnd_until: datetime | None = None
        self.db = sqlite3.connect(DB_PATH)
        self.db.row_factory = sqlite3.Row
        self._init_db()

        self.rows: list[ReminderCard] = []
        self._build_ui()
        self._build_tray()
        self._connect_signals()

        self.loading = True
        self.load_config()
        self.load_logs_table()
        self.loading = False

        self.rebuild_schedules()
        self.refresh_dashboard()
        self.apply_icons()

        self.scheduler = QTimer(self)
        self.scheduler.setInterval(3000)
        self.scheduler.timeout.connect(self.check_reminders)
        self.scheduler.start()

    def _init_db(self):
        cur = self.db.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                category TEXT NOT NULL,
                name TEXT NOT NULL,
                event TEXT NOT NULL,
                mode TEXT NOT NULL,
                detail TEXT NOT NULL,
                due_at TEXT,
                response_at TEXT,
                next_due TEXT,
                snooze_minutes INTEGER,
                dnd_until TEXT,
                source TEXT,
                meta_json TEXT
            )
            """
        )
        self.db.commit()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        header = QVBoxLayout()
        title = QLabel("Focus Reminder Suite")
        title.setObjectName("TitleLabel")
        subtitle = QLabel(
            "Eye Care · Posture Care · Movement · Hydration"
            "Per reminder: Toast / Popup / Both / Off. Popup responses are logged with timing."
        )
        subtitle.setObjectName("SubtitleLabel")
        subtitle.setWordWrap(True)
        header.addWidget(title)
        header.addWidget(subtitle)
        root.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(False)
        root.addWidget(self.tabs, 1)

        self.home_tab = QWidget()
        self.eye_tab = QWidget()
        self.posture_tab = QWidget()
        self.movement_tab = QWidget()
        self.hydration_tab = QWidget()
        self.settings_tab = QWidget()
        self.logs_tab = QWidget()

        self.tabs.addTab(self.home_tab, "Home")
        self.tabs.addTab(self.eye_tab, "Eye")
        self.tabs.addTab(self.posture_tab, "Posture")
        self.tabs.addTab(self.movement_tab, "Movement")
        self.tabs.addTab(self.hydration_tab, "Hydration")
        self.tabs.addTab(self.settings_tab, "Settings")
        self.tabs.addTab(self.logs_tab, "Logs")

        self._build_home_tab()
        self._build_category_tab(self.eye_tab, "Eye Care")
        self._build_category_tab(self.posture_tab, "Posture Care")
        self._build_category_tab(self.movement_tab, "Movement")
        self._build_category_tab(self.hydration_tab, "Hydration")
        self._build_settings_tab()
        self._build_logs_tab()

        self.setStyleSheet(
            """
            QWidget {
                background: #f5f7fb;
                color: #172033;
                font-family: Segoe UI;
                font-size: 9pt;
            }
            QTabWidget::pane {
                border: 1px solid #d8deea;
                border-radius: 10px;
                background: white;
                top: -1px;
            }
            QTabBar::tab {
                background: #e8edf7;
                color: #334155;
                padding: 6px 12px;
                margin-right: 4px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                min-width: 80px;
            }
            QTabBar::tab:selected {
                background: white;
                color: #0f172a;
                font-weight: 700;
            }
            QGroupBox {
                border: 1px solid #d8deea;
                border-radius: 10px;
                margin-top: 10px;
                background: white;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 14px;
                padding: 0 6px;
                color: #334155;
                font-weight: 600;
            }
            QLabel#TitleLabel {
                font-size: 16px;
                font-weight: 700;
                color: #0f172a;
            }
            QLabel#SubtitleLabel {
                color: #5b6475;
                margin-bottom: 2px;
            }
            QLabel#CategoryHeader {
                font-size: 11px;
                font-weight: 700;
                color: #0f172a;
                margin-top: 4px;
                margin-bottom: 2px;
            }
            QLabel#CategoryLabel {
                color: #64748b;
                font-size: 8.5pt;
            }
            QLabel#DescriptionLabel {
                color: #475569;
            }
            QLabel#HintLabel {
                color: #334155;
                font-weight: 600;
            }
            QLabel#MetaLabel {
                color: #475569;
            }
            QLabel#DashboardValue {
                font-size: 14px;
                font-weight: 700;
                color: #0f172a;
            }
            QFrame#ReminderCard {
                background: white;
                border: 1px solid #d8deea;
                border-radius: 10px;
            }
            QFrame[disabledCard="true"] {
                background: #f8fafc;
            }
            QPushButton {
                padding: 5px 12px;
                border-radius: 6px;
                background: #2563eb;
                color: white;
                font-weight: 600;
                border: none;
            }
            QPushButton:hover { background: #1d4ed8; }
            QPushButton:pressed { background: #1e40af; }
            QPushButton#DangerButton { background: #dc2626; }
            QPushButton#DangerButton:hover { background: #b91c1c; }
            QComboBox, QSpinBox, QTimeEdit, QLineEdit {
                padding: 4px 6px;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                background: white;
                min-height: 24px;
            }
            QTextEdit {
                border-radius: 8px;
                border: 1px solid #cbd5e1;
                background: #0f172a;
                color: #dbeafe;
                font-family: Consolas;
            }
            QCheckBox { spacing: 6px; }
            QTableWidget {
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                background: white;
                gridline-color: #e2e8f0;
            }
            QHeaderView::section {
                background: #eff6ff;
                padding: 5px;
                border: none;
                font-weight: 700;
                color: #1e293b;
            }
            """
        )

    def _make_dashboard_card(self, title: str, value: str):
        card = QFrame()
        card.setObjectName("SummaryCard")
        card.setStyleSheet(
            """
            QFrame#SummaryCard {
                background: white;
                border: 1px solid #d8deea;
                border-radius: 14px;
            }
            """
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)
        label = QLabel(title)
        label.setStyleSheet("color: #64748b; font-weight: 600;")
        value_lbl = QLabel(value)
        value_lbl.setObjectName("DashboardValue")
        layout.addWidget(label)
        layout.addWidget(value_lbl)
        card.value_lbl = value_lbl
        return card

    def _build_home_tab(self):
        layout = QVBoxLayout(self.home_tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        dashboard_group = QGroupBox("Dashboard")
        grid = QGridLayout(dashboard_group)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        self.card_active = self._make_dashboard_card("Active reminders", "0")
        self.card_estimated = self._make_dashboard_card("Estimated / day", "0")
        self.card_fired_today = self._make_dashboard_card("Fired today", "0")
        self.card_window = self._make_dashboard_card("Work window", "--:-- → --:--")
        self.card_breaks = self._make_dashboard_card("Break planning", "--")
        self.card_dnd = self._make_dashboard_card("DND", "Inactive")

        grid.addWidget(self.card_active, 0, 0)
        grid.addWidget(self.card_estimated, 0, 1)
        grid.addWidget(self.card_fired_today, 0, 2)
        grid.addWidget(self.card_window, 0, 3)
        grid.addWidget(self.card_breaks, 1, 0, 1, 3)
        grid.addWidget(self.card_dnd, 1, 3)
        layout.addWidget(dashboard_group)

        quick_group = QGroupBox("Quick actions")
        quick_layout = QHBoxLayout(quick_group)
        self.pause_all_btn = QPushButton("Pause all")
        self.resume_all_btn = QPushButton("Resume all")
        self.meeting_mode_btn = QPushButton("Toggle meeting mode")
        self.test_toast_btn = QPushButton("Test toast")
        self.test_popup_btn = QPushButton("Test popup")
        quick_layout.addWidget(self.pause_all_btn)
        quick_layout.addWidget(self.resume_all_btn)
        quick_layout.addWidget(self.meeting_mode_btn)
        quick_layout.addWidget(self.test_toast_btn)
        quick_layout.addWidget(self.test_popup_btn)
        quick_layout.addStretch(1)
        layout.addWidget(quick_group)

        next_group = QGroupBox("Next reminders")
        next_layout = QVBoxLayout(next_group)
        self.next_table = QTableWidget(0, 5)
        self.next_table.setHorizontalHeaderLabels(["Category", "Name", "Mode", "Next due", "Status"])
        self.next_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.next_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.next_table.setAlternatingRowColors(True)
        self.next_table.horizontalHeader().setStretchLastSection(True)
        next_layout.addWidget(self.next_table)
        layout.addWidget(next_group, 1)

    def _build_category_tab(self, tab: QWidget, category: str):
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(4, 4, 4, 4)
        body_layout.setSpacing(12)

        header = QLabel(category)
        header.setObjectName("CategoryHeader")
        body_layout.addWidget(header)

        for template in TEMPLATES:
            if template.category != category:
                continue
            card = ReminderCard(template)
            self.rows.append(card)
            card.changed.connect(self.on_any_change)
            body_layout.addWidget(card)

        body_layout.addStretch(1)
        scroll.setWidget(body)
        layout.addWidget(scroll)

    def _build_settings_tab(self):
        layout = QVBoxLayout(self.settings_tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        planner_group = QGroupBox("Global planner")
        planner = QGridLayout(planner_group)
        planner.setHorizontalSpacing(12)
        planner.setVerticalSpacing(10)

        self.start_time_edit = QTimeEdit()
        self.start_time_edit.setDisplayFormat("HH:mm")
        self.start_time_edit.setTime(QTime(9, 0))
        self.start_time_edit.setFixedWidth(110)

        self.end_time_edit = QTimeEdit()
        self.end_time_edit.setDisplayFormat("HH:mm")
        self.end_time_edit.setTime(QTime(18, 0))
        self.end_time_edit.setFixedWidth(110)

        self.global_mode_combo = QComboBox()
        self.global_mode_combo.addItems(["Toast", "Popup", "Both", "Off"])
        self.global_mode_combo.setFixedWidth(120)

        self.meeting_mode_cb = QCheckBox("Meeting mode (mute all reminders)")

        self.short_breaks_spin = QSpinBox()
        self.short_breaks_spin.setRange(0, 50)
        self.short_breaks_spin.setValue(6)
        self.short_breaks_spin.setFixedWidth(100)

        self.long_breaks_spin = QSpinBox()
        self.long_breaks_spin.setRange(0, 20)
        self.long_breaks_spin.setValue(2)
        self.long_breaks_spin.setFixedWidth(100)

        self.snooze_minutes_spin = QSpinBox()
        self.snooze_minutes_spin.setRange(1, 240)
        self.snooze_minutes_spin.setValue(10)
        self.snooze_minutes_spin.setFixedWidth(100)

        self.auto_dismiss_spin = QSpinBox()
        self.auto_dismiss_spin.setRange(0, 60)
        self.auto_dismiss_spin.setValue(2)
        self.auto_dismiss_spin.setFixedWidth(100)
        self.auto_dismiss_spin.setSpecialValueText("Disabled")

        self.startup_cb = QCheckBox("Start with Windows")
        self.tray_close_cb = QCheckBox("Close to tray instead of exit")
        self.autosave_cb = QCheckBox("Auto-save changes")
        self.autosave_cb.setChecked(True)

        self.app_icon_edit = QLineEdit()
        self.app_icon_edit.setPlaceholderText("Optional .ico/.png path")
        self.app_icon_edit.setMinimumWidth(320)
        self.icon_browse_btn = QPushButton("Browse")

        self.short_interval_lbl = QLabel("Suggested short-break interval: --")
        self.long_interval_lbl = QLabel("Suggested long-break interval: --")
        self.short_interval_lbl.setObjectName("MetaLabel")
        self.long_interval_lbl.setObjectName("MetaLabel")

        planner.addWidget(QLabel("Start time"), 0, 0)
        planner.addWidget(self.start_time_edit, 0, 1)
        planner.addWidget(QLabel("End time"), 0, 2)
        planner.addWidget(self.end_time_edit, 0, 3)
        planner.addWidget(QLabel("Global output"), 0, 4)
        planner.addWidget(self.global_mode_combo, 0, 5)

        planner.addWidget(QLabel("Short breaks / day"), 1, 0)
        planner.addWidget(self.short_breaks_spin, 1, 1)
        planner.addWidget(QLabel("Long breaks / day"), 1, 2)
        planner.addWidget(self.long_breaks_spin, 1, 3)
        planner.addWidget(QLabel("Snooze minutes"), 1, 4)
        planner.addWidget(self.snooze_minutes_spin, 1, 5)

        planner.addWidget(self.meeting_mode_cb, 2, 0, 1, 3)
        planner.addWidget(QLabel("Auto-dismiss (min)"), 2, 4)
        planner.addWidget(self.auto_dismiss_spin, 2, 5)
        planner.addWidget(self.short_interval_lbl, 3, 0, 1, 3)
        planner.addWidget(self.long_interval_lbl, 3, 3, 1, 3)

        layout.addWidget(planner_group)

        behavior_group = QGroupBox("Behavior")
        behavior_layout = QVBoxLayout(behavior_group)
        behavior_layout.addWidget(self.startup_cb)
        behavior_layout.addWidget(self.tray_close_cb)
        behavior_layout.addWidget(self.autosave_cb)
        layout.addWidget(behavior_group)

        icon_group = QGroupBox("Icons")
        icon_layout = QHBoxLayout(icon_group)
        icon_layout.addWidget(QLabel("App icon path"))
        icon_layout.addWidget(self.app_icon_edit, 1)
        icon_layout.addWidget(self.icon_browse_btn)
        layout.addWidget(icon_group)

        buttons = QHBoxLayout()
        self.save_btn = QPushButton("Save settings")
        self.recalc_btn = QPushButton("Recalculate")
        self.export_btn = QPushButton("Export logs CSV")
        self.export_json_btn = QPushButton("Export logs JSONL")
        self.reset_btn = QPushButton("Reset all state")
        self.reset_btn.setObjectName("DangerButton")
        buttons.addWidget(self.save_btn)
        buttons.addWidget(self.recalc_btn)
        buttons.addWidget(self.export_btn)
        buttons.addWidget(self.export_json_btn)
        buttons.addWidget(self.reset_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        layout.addStretch(1)

    def _build_logs_tab(self):
        layout = QVBoxLayout(self.logs_tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        controls = QHBoxLayout()
        self.log_filter_combo = QComboBox()
        self.log_filter_combo.addItems(["All", "Today", "This week", "This month", "Sent only", "Responses only", "Muted only", "Config only"])
        self.refresh_logs_btn = QPushButton("Refresh")
        self.clear_logs_btn = QPushButton("Clear logs")
        self.logs_export_btn = QPushButton("Export CSV")
        self.logs_json_btn = QPushButton("Export JSONL")
        controls.addWidget(QLabel("Filter"))
        controls.addWidget(self.log_filter_combo)
        controls.addWidget(self.refresh_logs_btn)
        controls.addWidget(self.clear_logs_btn)
        controls.addWidget(self.logs_export_btn)
        controls.addWidget(self.logs_json_btn)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.logs_table = QTableWidget(0, 10)
        self.logs_table.setHorizontalHeaderLabels(["Time", "Event", "Category", "Name", "Mode", "Detail", "Due at", "Response at", "Next due", "Meta"])
        self.logs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.logs_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.logs_table.setAlternatingRowColors(True)
        self.logs_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.logs_table, 1)

        self.logs_summary = QLabel("Logs loaded: 0")
        self.logs_summary.setObjectName("MetaLabel")
        layout.addWidget(self.logs_summary)

    def _build_tray(self):
        self.tray = QSystemTrayIcon(self)
        self.tray_icon = self.make_app_icon()
        self.tray.setIcon(self.tray_icon)
        self.setWindowIcon(self.tray_icon)

        menu = QMenu()
        open_action = QAction("Open", self)
        open_action.triggered.connect(self.restore_window)
        meeting_action = QAction("Toggle meeting mode", self)
        meeting_action.triggered.connect(self.toggle_meeting_mode)
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.exit_app)
        menu.addAction(open_action)
        menu.addAction(meeting_action)
        menu.addSeparator()
        menu.addAction(exit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_clicked)
        self.tray.show()

    def _connect_signals(self):
        self.start_time_edit.timeChanged.connect(lambda *_: self.on_any_change())
        self.end_time_edit.timeChanged.connect(lambda *_: self.on_any_change())
        self.global_mode_combo.currentTextChanged.connect(lambda *_: self.on_any_change())
        self.meeting_mode_cb.toggled.connect(lambda *_: self.on_any_change())
        self.short_breaks_spin.valueChanged.connect(lambda *_: self.on_any_change())
        self.long_breaks_spin.valueChanged.connect(lambda *_: self.on_any_change())
        self.snooze_minutes_spin.valueChanged.connect(lambda *_: self.on_any_change())
        self.auto_dismiss_spin.valueChanged.connect(lambda *_: self.on_any_change())
        self.app_icon_edit.textChanged.connect(lambda *_: self.on_any_change())
        self.save_btn.clicked.connect(self.save_config)
        self.recalc_btn.clicked.connect(self.rebuild_schedules)
        self.export_btn.clicked.connect(self.export_logs_csv)
        self.export_json_btn.clicked.connect(self.export_logs_jsonl)
        self.reset_btn.clicked.connect(self.reset_all_state)
        self.pause_all_btn.clicked.connect(self.pause_all)
        self.resume_all_btn.clicked.connect(self.resume_all)
        self.meeting_mode_btn.clicked.connect(self.toggle_meeting_mode)
        self.test_toast_btn.clicked.connect(self.test_toast)
        self.test_popup_btn.clicked.connect(self.test_popup)
        self.refresh_logs_btn.clicked.connect(lambda: self.load_logs_table())
        self.clear_logs_btn.clicked.connect(lambda: self.clear_logs())
        self.logs_export_btn.clicked.connect(lambda: self.export_logs_csv())
        self.logs_json_btn.clicked.connect(lambda: self.export_logs_jsonl())
        self.log_filter_combo.currentTextChanged.connect(lambda *_: self.load_logs_table())
        self.icon_browse_btn.clicked.connect(self.browse_icon)

    def browse_icon(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select app icon", "", "Images (*.ico *.png *.jpg *.jpeg)")
        if path:
            self.app_icon_edit.setText(path)
            self.apply_icons()
            self.save_config()

    def on_any_change(self):
        if self.loading:
            return
        self.rebuild_schedules()
        self.refresh_dashboard()
        self.apply_icons()
        if self.autosave_cb.isChecked():
            self.save_config()

    def toggle_meeting_mode(self):
        self.meeting_mode_cb.setChecked(not self.meeting_mode_cb.isChecked())

    def _tray_clicked(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.restore_window()

    def restore_window(self):
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        if self.tray_close_cb.isChecked():
            event.ignore()
            self.hide()
        else:
            event.accept()
            self.exit_app()

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized():
            if self.tray_close_cb.isChecked():
                QTimer.singleShot(0, self.hide)
        super().changeEvent(event)

    def exit_app(self):
        self.save_config()
        self.tray.hide()
        QApplication.quit()

    def make_app_icon(self) -> QIcon:
        path = self.app_icon_edit.text().strip()
        if path:
            icon = QIcon(path)
            if not icon.isNull():
                return icon
        pix = QPixmap(64, 64)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#2563eb"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, 64, 64, 16, 16)
        painter.setPen(QColor("white"))
        font = QFont()
        font.setBold(True)
        font.setPointSize(18)
        painter.setFont(font)
        painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "FR")
        painter.end()
        return QIcon(pix)

    def apply_icons(self):
        icon = self.make_app_icon()
        self.setWindowIcon(icon)
        self.tray.setIcon(icon)
        self.tray_icon = icon

    def get_window_bounds(self, now: datetime):
        start_q = self.start_time_edit.time()
        end_q = self.end_time_edit.time()
        start_dt = datetime.combine(now.date(), dtime(start_q.hour(), start_q.minute()))
        end_dt = datetime.combine(now.date(), dtime(end_q.hour(), end_q.minute()))

        if start_q == end_q:
            return start_dt, start_dt + timedelta(days=1), True

        if start_q < end_q:
            if now < start_dt:
                return start_dt, end_dt, False
            if now <= end_dt:
                return start_dt, end_dt, True
            return start_dt + timedelta(days=1), end_dt + timedelta(days=1), False

        if now >= start_dt:
            return start_dt, end_dt + timedelta(days=1), True
        if now <= end_dt:
            return start_dt - timedelta(days=1), end_dt, True
        return start_dt, end_dt + timedelta(days=1), False

    def window_minutes(self) -> int:
        now = datetime.now()
        start_dt, end_dt, _ = self.get_window_bounds(now)
        mins = int((end_dt - start_dt).total_seconds() / 60)
        return max(1, mins)

    def dnd_active(self) -> bool:
        return self.session_dnd_until is not None and datetime.now() < self.session_dnd_until

    def active_rows(self):
        global_mode = self.global_mode_combo.currentText()
        meeting = self.meeting_mode_cb.isChecked()
        dnd = self.dnd_active()
        return [row for row in self.rows if row.is_enabled() and row.effective_mode(global_mode, meeting, dnd) != "Off"]

    def rebuild_schedules(self):
        now = datetime.now()
        window_start, window_end, _active = self.get_window_bounds(now)
        win_minutes = max(1, int((window_end - window_start).total_seconds() / 60))
        global_mode = self.global_mode_combo.currentText()
        meeting = self.meeting_mode_cb.isChecked()
        dnd = self.dnd_active()

        for row in self.rows:
            row.update_preview(win_minutes, global_mode, meeting, dnd)
            effective = row.effective_mode(global_mode, meeting, dnd)
            if not row.is_enabled() or effective == "Off":
                row.next_due = row.next_due if row.awaiting_response else None
                continue
            if row.next_due is None or row.next_due < now - timedelta(minutes=1):
                row.next_due = row.compute_next_due(now, window_start, window_end, win_minutes)
            row.update_preview(win_minutes, global_mode, meeting, dnd)

        self.refresh_dashboard()
        self.load_next_table()

    def refresh_dashboard(self):
        now = datetime.now()
        window_start, window_end, _ = self.get_window_bounds(now)
        window_minutes = max(1, int((window_end - window_start).total_seconds() / 60))
        global_mode = self.global_mode_combo.currentText()
        meeting = self.meeting_mode_cb.isChecked()
        dnd = self.dnd_active()

        active_count = len(self.active_rows())
        estimated_count = sum(
            row.estimated_daily_count(window_minutes)
            for row in self.rows
            if row.is_enabled() and row.effective_mode(global_mode, meeting, dnd) != "Off"
        )
        fired_today = self.get_fired_today_count()

        self.card_active.value_lbl.setText(str(active_count))
        self.card_estimated.value_lbl.setText(str(estimated_count))
        self.card_fired_today.value_lbl.setText(str(fired_today))
        self.card_window.value_lbl.setText(f"{window_start.strftime('%H:%M')} → {window_end.strftime('%H:%M')}")

        short_n = self.short_breaks_spin.value()
        long_n = self.long_breaks_spin.value()
        short_interval = f"~{round(window_minutes / short_n)} min" if short_n > 0 else "--"
        long_interval = f"~{round(window_minutes / long_n)} min" if long_n > 0 else "--"
        self.card_breaks.value_lbl.setText(f"Short: {short_n} ({short_interval})   Long: {long_n} ({long_interval})")

        if self.session_dnd_until is None:
            self.card_dnd.value_lbl.setText("Inactive")
        else:
            self.card_dnd.value_lbl.setText("Until " + self.session_dnd_until.strftime("%H:%M"))

        self.short_interval_lbl.setText(f"Suggested short-break interval: {short_interval} across {short_n} breaks")
        self.long_interval_lbl.setText(f"Suggested long-break interval: {long_interval} across {long_n} breaks")

    def get_fired_today_count(self) -> int:
        today = datetime.now().strftime("%Y-%m-%d")
        cur = self.db.cursor()
        cur.execute("SELECT COUNT(*) FROM logs WHERE ts >= ? AND event = 'SENT'", (f"{today} 00:00:00",))
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def log_event(
        self,
        category: str,
        name: str,
        event: str,
        mode: str,
        detail: str,
        due_at: str | None = None,
        response_at: str | None = None,
        next_due: str | None = None,
        snooze_minutes: int | None = None,
        dnd_until: str | None = None,
        source: str | None = None,
        meta: dict | None = None,
    ):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = self.db.cursor()
        cur.execute(
            """
            INSERT INTO logs
            (ts, category, name, event, mode, detail, due_at, response_at, next_due, snooze_minutes, dnd_until, source, meta_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ts,
                category,
                name,
                event,
                mode,
                detail,
                due_at,
                response_at,
                next_due,
                snooze_minutes,
                dnd_until,
                source,
                json.dumps(meta or {}, ensure_ascii=False),
            ),
        )
        self.db.commit()
        self.load_logs_table()
        self.logs_summary.setText(f"Logs loaded: {self.logs_table.rowCount()}")

    def load_logs_table(self):
        rows = self._fetch_logs()
        self.logs_table.setRowCount(0)
        for row in reversed(rows):
            r = self.logs_table.rowCount()
            self.logs_table.insertRow(r)
            values = [
                row["ts"],
                row["event"],
                row["category"],
                row["name"],
                row["mode"],
                row["detail"],
                row["due_at"] or "",
                row["response_at"] or "",
                row["next_due"] or "",
                row["meta_json"] or "",
            ]
            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                self.logs_table.setItem(r, c, item)
        self.logs_summary.setText(f"Logs loaded: {len(rows)}")

    def _fetch_logs(self):
        filter_mode = self.log_filter_combo.currentText()
        query = "SELECT ts, category, name, event, mode, detail, due_at, response_at, next_due, meta_json FROM logs"
        params = []
        where = []

        if filter_mode == "Today":
            today = datetime.now().strftime("%Y-%m-%d")
            where.append("ts >= ?")
            params.append(f"{today} 00:00:00")
        elif filter_mode == "This week":
            start = datetime.now() - timedelta(days=7)
            where.append("ts >= ?")
            params.append(start.strftime("%Y-%m-%d %H:%M:%S"))
        elif filter_mode == "This month":
            start = datetime.now() - timedelta(days=30)
            where.append("ts >= ?")
            params.append(start.strftime("%Y-%m-%d %H:%M:%S"))
        elif filter_mode == "Sent only":
            where.append("event = 'SENT'")
        elif filter_mode == "Responses only":
            where.append("event LIKE 'POPUP_%' OR event IN ('OK', 'SNOOZE', 'DND')")
        elif filter_mode == "Muted only":
            where.append("event = 'MUTED'")
        elif filter_mode == "Config only":
            where.append("event LIKE 'CONFIG_%'")

        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY id DESC LIMIT 1000"

        cur = self.db.cursor()
        cur.execute(query, params)
        return cur.fetchall()

    def load_next_table(self):
        rows_sorted = []
        for row in self.rows:
            if row.next_due is not None and row.is_enabled():
                rows_sorted.append(row)
        rows_sorted.sort(key=lambda r: r.next_due or datetime.max)

        self.next_table.setRowCount(0)
        global_mode = self.global_mode_combo.currentText()
        meeting_mode = self.meeting_mode_cb.isChecked()
        dnd = self.dnd_active()
        for row in rows_sorted:
            r = self.next_table.rowCount()
            self.next_table.insertRow(r)
            effective_mode = row.effective_mode(global_mode, meeting_mode, dnd)
            status = "Enabled" if row.is_enabled() and effective_mode != "Off" else "Muted"
            values = [
                row.template.category,
                row.template.name,
                effective_mode,
                row.next_due.strftime("%Y-%m-%d %H:%M:%S") if row.next_due else "--",
                status,
            ]
            for c, value in enumerate(values):
                self.next_table.setItem(r, c, QTableWidgetItem(str(value)))

    def save_config(self):
        if self.loading:
            return
        config = {
            "start_time": self.start_time_edit.time().toString("HH:mm"),
            "end_time": self.end_time_edit.time().toString("HH:mm"),
            "global_mode": self.global_mode_combo.currentText(),
            "meeting_mode": self.meeting_mode_cb.isChecked(),
            "short_breaks": self.short_breaks_spin.value(),
            "long_breaks": self.long_breaks_spin.value(),
            "snooze_minutes": self.snooze_minutes_spin.value(),
            "auto_dismiss_minutes": self.auto_dismiss_spin.value(),
            "startup": self.startup_cb.isChecked(),
            "tray_close": self.tray_close_cb.isChecked(),
            "autosave": self.autosave_cb.isChecked(),
            "app_icon_path": self.app_icon_edit.text().strip(),
            "rows": {row.key: row.to_state() for row in self.rows},
        }
        cur = self.db.cursor()
        cur.execute(
            """
            INSERT INTO settings(key, value)
            VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            ("config", json.dumps(config, ensure_ascii=False)),
        )
        self.db.commit()

    def load_config(self):
        cur = self.db.cursor()
        cur.execute("SELECT value FROM settings WHERE key='config'")
        row = cur.fetchone()
        if not row:
            self.rebuild_schedules()
            return
        try:
            config = json.loads(row["value"])
        except Exception:
            self.rebuild_schedules()
            return

        self.start_time_edit.setTime(QTime.fromString(config.get("start_time", "09:00"), "HH:mm"))
        self.end_time_edit.setTime(QTime.fromString(config.get("end_time", "18:00"), "HH:mm"))
        self.global_mode_combo.setCurrentText(config.get("global_mode", "Toast"))
        self.meeting_mode_cb.setChecked(bool(config.get("meeting_mode", False)))
        self.short_breaks_spin.setValue(int(config.get("short_breaks", 6)))
        self.long_breaks_spin.setValue(int(config.get("long_breaks", 2)))
        self.snooze_minutes_spin.setValue(int(config.get("snooze_minutes", 10)))
        self.auto_dismiss_spin.setValue(int(config.get("auto_dismiss_minutes", 2)))
        self.startup_cb.setChecked(bool(config.get("startup", False)))
        self.tray_close_cb.setChecked(bool(config.get("tray_close", True)))
        self.autosave_cb.setChecked(bool(config.get("autosave", True)))
        self.app_icon_edit.setText(config.get("app_icon_path", ""))

        row_states = config.get("rows", {})
        for row_widget in self.rows:
            if row_widget.key in row_states:
                row_widget.apply_state(row_states[row_widget.key])

        self.rebuild_schedules()
        self.load_logs_table()

    def test_toast(self):
        self.send_toast("Test reminder", "This is a manual toast test.")
        self.log_event("Test", "Manual toast", "SENT", self.global_mode_combo.currentText(), "Manual toast test.", source="manual")

    def test_popup(self):
        popup = ReminderPopup("Test reminder", "This is a manual popup test.", self.snooze_minutes_spin.value(), self.app_icon_edit.text().strip(), self.auto_dismiss_spin.value(), self)
        sent_at = datetime.now()
        self.log_event("Test", "Manual popup", "SENT", self.global_mode_combo.currentText(), "Manual popup test.", due_at=sent_at.strftime("%Y-%m-%d %H:%M:%S"), source="manual")
        result = popup.exec()
        response_at = datetime.now()
        elapsed = int((response_at - sent_at).total_seconds())
        self.log_event(
            "Test",
            "Manual popup",
            f"POPUP_{popup.action}",
            self.global_mode_combo.currentText(),
            f"User clicked {popup.action} after {elapsed}s.",
            response_at=response_at.strftime("%Y-%m-%d %H:%M:%S"),
            source="popup",
            meta={"elapsed_seconds": elapsed, "dialog_result": result},
        )

    def pause_all(self):
        self.global_mode_combo.setCurrentText("Off")
        self.save_config()
        self.refresh_dashboard()
        self.tray.showMessage(APP_TITLE, "All reminders paused.", QSystemTrayIcon.MessageIcon.Information, 1800)

    def resume_all(self):
        if self.global_mode_combo.currentText() == "Off":
            self.global_mode_combo.setCurrentText("Toast")
        self.refresh_dashboard()
        self.save_config()
        self.tray.showMessage(APP_TITLE, "Reminders resumed.", QSystemTrayIcon.MessageIcon.Information, 1800)

    def send_toast(self, title: str, message: str):
        icon_path = self.app_icon_edit.text().strip()
        if Notification is None:
            self.tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 3000)
            return
        try:
            toast = Notification(app_id=APP_TITLE, title=title, msg=message)
            toast.show()
        except Exception:
            self.tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 3000)

    def show_popup_for_row(self, row: ReminderCard, title: str, message: str, sent_at: datetime, due_at: datetime):
        if self.popup_active:
            return "SKIP"
        self.popup_active = True
        row.awaiting_response = True
        row.last_popup_sent_at = sent_at

        popup = ReminderPopup(title, message, self.snooze_minutes_spin.value(), self.app_icon_edit.text().strip(), self.auto_dismiss_spin.value(), self)
        popup.move(self.geometry().center() - popup.rect().center())
        popup.exec()
        response_at = datetime.now()
        elapsed = int((response_at - sent_at).total_seconds())
        action = popup.action or "OK"
        row.awaiting_response = False
        self.popup_active = False
        return action, response_at, elapsed

    def apply_post_popup_action(self, row: ReminderCard, action: str, response_at: datetime, due_at: datetime, elapsed: int):
        window_start, window_end, _active = self.get_window_bounds(response_at)
        window_minutes = max(1, int((window_end - window_start).total_seconds() / 60))
        interval = row.schedule_interval_minutes(window_minutes)
        next_due = None
        meta = {
            "elapsed_seconds": elapsed,
            "scheduled_due": due_at.strftime("%Y-%m-%d %H:%M:%S"),
            "response_at": response_at.strftime("%Y-%m-%d %H:%M:%S"),
            "interval_minutes": interval,
            "snooze_minutes": self.snooze_minutes_spin.value(),
        }

        if action == "SNOOZE":
            next_due = response_at + timedelta(minutes=self.snooze_minutes_spin.value())
            self.log_event(
                row.template.category,
                row.template.name,
                "POPUP_SNOOZE",
                row.mode_combo.currentText(),
                f"User snoozed for {self.snooze_minutes_spin.value()} minutes.",
                due_at=due_at.strftime("%Y-%m-%d %H:%M:%S"),
                response_at=response_at.strftime("%Y-%m-%d %H:%M:%S"),
                next_due=next_due.strftime("%Y-%m-%d %H:%M:%S"),
                snooze_minutes=self.snooze_minutes_spin.value(),
                source="popup",
                meta=meta,
            )
        elif action == "DND":
            self.session_dnd_until = window_end
            next_due = window_end + timedelta(minutes=interval)
            self.log_event(
                row.template.category,
                row.template.name,
                "POPUP_DND",
                row.mode_combo.currentText(),
                f"User enabled DND until {window_end.strftime('%H:%M:%S')}.",
                due_at=due_at.strftime("%Y-%m-%d %H:%M:%S"),
                response_at=response_at.strftime("%Y-%m-%d %H:%M:%S"),
                next_due=next_due.strftime("%Y-%m-%d %H:%M:%S"),
                dnd_until=window_end.strftime("%Y-%m-%d %H:%M:%S"),
                source="popup",
                meta=meta,
            )
            self.log_event(
                "Global",
                "DND",
                "CONFIG_DND_ON",
                self.global_mode_combo.currentText(),
                f"Global DND enabled until {window_end.strftime('%Y-%m-%d %H:%M:%S')}.",
                dnd_until=window_end.strftime("%Y-%m-%d %H:%M:%S"),
                source="popup",
                meta={"triggered_by": row.template.key},
            )
        elif action == "TIMEOUT":
            next_due = response_at + timedelta(minutes=interval)
            self.log_event(
                row.template.category,
                row.template.name,
                "POPUP_TIMEOUT",
                row.mode_combo.currentText(),
                f"Reminder auto-dismissed after {elapsed}s (not clicked).",
                due_at=due_at.strftime("%Y-%m-%d %H:%M:%S"),
                response_at=response_at.strftime("%Y-%m-%d %H:%M:%S"),
                next_due=next_due.strftime("%Y-%m-%d %H:%M:%S"),
                source="popup",
                meta=meta,
            )
        else:
            next_due = response_at + timedelta(minutes=interval)
            self.log_event(
                row.template.category,
                row.template.name,
                "POPUP_OK",
                row.mode_combo.currentText(),
                f"User acknowledged after {elapsed}s.",
                due_at=due_at.strftime("%Y-%m-%d %H:%M:%S"),
                response_at=response_at.strftime("%Y-%m-%d %H:%M:%S"),
                next_due=next_due.strftime("%Y-%m-%d %H:%M:%S"),
                source="popup",
                meta=meta,
            )

        row.last_fired = response_at
        row.next_due = next_due
        row.update_preview(window_minutes, self.global_mode_combo.currentText(), self.meeting_mode_cb.isChecked(), self.dnd_active())
        self.load_next_table()
        self.refresh_dashboard()

    def check_reminders(self):
        now = datetime.now()
        window_start, window_end, active_now = self.get_window_bounds(now)
        window_minutes = max(1, int((window_end - window_start).total_seconds() / 60))
        global_mode = self.global_mode_combo.currentText()
        meeting_mode = self.meeting_mode_cb.isChecked()
        dnd = self.dnd_active()

        if self.session_dnd_until is not None and now >= self.session_dnd_until:
            self.session_dnd_until = None

        for row in self.rows:
            row.update_preview(window_minutes, global_mode, meeting_mode, dnd)
            effective_mode = row.effective_mode(global_mode, meeting_mode, dnd)

            if not row.is_enabled() or effective_mode == "Off":
                if not row.awaiting_response:
                    row.next_due = None
                continue

            if row.awaiting_response:
                continue

            if row.next_due is None:
                row.next_due = row.compute_next_due(now, window_start, window_end, window_minutes)
                row.update_preview(window_minutes, global_mode, meeting_mode, dnd)
                continue

            if not active_now:
                continue

            if now >= row.next_due:
                if effective_mode in ("Popup", "Both") and self.popup_active:
                    continue
                sent_at = now
                due_at = row.next_due
                title = f"{row.template.category} · {row.template.name}"
                message = row.template.description
                mode = effective_mode

                self.log_event(
                    row.template.category,
                    row.template.name,
                    "SENT",
                    mode,
                    f"Reminder sent in {mode} mode.",
                    due_at=due_at.strftime("%Y-%m-%d %H:%M:%S"),
                    source="scheduler",
                    meta={"template": row.template.key},
                )

                if mode in ("Toast", "Both"):
                    self.send_toast(title, message)

                if mode in ("Popup", "Both"):
                    result = self.show_popup_for_row(row, title, message, sent_at, due_at)
                    if result == "SKIP":
                        continue
                    action, response_at, elapsed = result
                    self.apply_post_popup_action(row, action, response_at, due_at, elapsed)
                else:
                    next_due = sent_at + timedelta(minutes=row.schedule_interval_minutes(window_minutes))
                    row.last_fired = sent_at
                    row.next_due = next_due
                    self.log_event(
                        row.template.category,
                        row.template.name,
                        "RESCHEDULED",
                        mode,
                        f"Next reminder set after toast-only send.",
                        due_at=due_at.strftime("%Y-%m-%d %H:%M:%S"),
                        next_due=next_due.strftime("%Y-%m-%d %H:%M:%S"),
                        source="scheduler",
                        meta={"template": row.template.key},
                    )
                    row.update_preview(window_minutes, global_mode, meeting_mode, dnd)

        self.refresh_dashboard()
        self.load_next_table()

    def load_next_table(self):
        rows_sorted = []
        for row in self.rows:
            if row.next_due is not None and row.is_enabled():
                rows_sorted.append(row)
        rows_sorted.sort(key=lambda r: r.next_due or datetime.max)

        self.next_table.setRowCount(0)
        global_mode = self.global_mode_combo.currentText()
        meeting_mode = self.meeting_mode_cb.isChecked()
        dnd = self.dnd_active()
        for row in rows_sorted:
            r = self.next_table.rowCount()
            self.next_table.insertRow(r)
            effective_mode = row.effective_mode(global_mode, meeting_mode, dnd)
            status = "Enabled" if row.is_enabled() and effective_mode != "Off" else "Muted"
            values = [
                row.template.category,
                row.template.name,
                effective_mode,
                row.next_due.strftime("%Y-%m-%d %H:%M:%S") if row.next_due else "--",
                status,
            ]
            for c, value in enumerate(values):
                self.next_table.setItem(r, c, QTableWidgetItem(str(value)))

    def clear_logs(self):
        res = QMessageBox.question(
            self,
            "Clear logs",
            "Delete all logs from the database?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if res != QMessageBox.StandardButton.Yes:
            return
        cur = self.db.cursor()
        cur.execute("DELETE FROM logs")
        self.db.commit()
        self.load_logs_table()
        self.logs_summary.setText("Logs loaded: 0")

    def export_logs_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export logs", "logs.csv", "CSV Files (*.csv)")
        if not path:
            return
        rows = self._fetch_logs()
        with open(path, "w", encoding="utf-8") as f:
            f.write("ts,event,category,name,mode,detail,due_at,response_at,next_due,meta_json")
            for row in rows:
                vals = [row["ts"], row["event"], row["category"], row["name"], row["mode"], row["detail"], row["due_at"], row["response_at"], row["next_due"], row["meta_json"]]
                escaped = []
                for v in vals:
                    s = "" if v is None else str(v)
                    s = s.replace('"', '""')
                    escaped.append(f'"{s}"')
                f.write(",".join(escaped) + "")
        self.tray.showMessage(APP_TITLE, f"Exported to {path}", QSystemTrayIcon.MessageIcon.Information, 2500)

    def export_logs_jsonl(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export logs", "logs.jsonl", "JSONL Files (*.jsonl)")
        if not path:
            return
        rows = self._fetch_logs()
        with open(path, "w", encoding="utf-8") as f:
            for row in rows:
                obj = {
                    "ts": row["ts"],
                    "event": row["event"],
                    "category": row["category"],
                    "name": row["name"],
                    "mode": row["mode"],
                    "detail": row["detail"],
                    "due_at": row["due_at"],
                    "response_at": row["response_at"],
                    "next_due": row["next_due"],
                    "meta": json.loads(row["meta_json"]) if row["meta_json"] else {},
                }
                f.write(json.dumps(obj, ensure_ascii=False) + "")
        self.tray.showMessage(APP_TITLE, f"Exported to {path}", QSystemTrayIcon.MessageIcon.Information, 2500)

    def reset_all_state(self):
        res = QMessageBox.question(
            self,
            "Reset state",
            "Reset all reminder schedules, logs, and settings?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if res != QMessageBox.StandardButton.Yes:
            return

        cur = self.db.cursor()
        cur.execute("DELETE FROM settings")
        cur.execute("DELETE FROM logs")
        self.db.commit()

        self.start_time_edit.setTime(QTime(9, 0))
        self.end_time_edit.setTime(QTime(18, 0))
        self.global_mode_combo.setCurrentText("Toast")
        self.meeting_mode_cb.setChecked(False)
        self.short_breaks_spin.setValue(6)
        self.long_breaks_spin.setValue(2)
        self.snooze_minutes_spin.setValue(10)
        self.auto_dismiss_spin.setValue(2)
        self.startup_cb.setChecked(False)
        self.tray_close_cb.setChecked(True)
        self.autosave_cb.setChecked(True)
        self.app_icon_edit.setText("")
        self.session_dnd_until = None

        for row in self.rows:
            row.reset_runtime()
            row.enable_cb.setChecked(True)
            row.mode_combo.setCurrentText("Inherit")
            if hasattr(row, "interval_spin"):
                row.interval_spin.setValue(row.template.default_interval or 20)
            if hasattr(row, "min_spin"):
                row.min_spin.setValue(row.template.default_min or 20)
            if hasattr(row, "max_spin"):
                row.max_spin.setValue(row.template.default_max or 45)
            if hasattr(row, "goal_spin"):
                row.goal_spin.setValue(row.template.default_goal or 8)

        self.load_logs_table()
        self.rebuild_schedules()
        self.save_config()
        self.refresh_dashboard()
        self.apply_icons()
        self.tray.showMessage(APP_TITLE, "State reset.", QSystemTrayIcon.MessageIcon.Information, 1800)


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    window = ReminderApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()