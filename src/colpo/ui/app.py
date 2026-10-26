"""Aplicación de escritorio Open Colposcope (F2).

Esta capa solo presenta y recoge acciones: la captura, el guardado y los
metadatos viven en el núcleo (:mod:`colpo.live`, :mod:`colpo.session`). La UI
no importa OpenCV.

Ejecutar: ``colpo-ui`` o ``python -m colpo.ui.app``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from functools import partial
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from colpo import __version__, storage
from colpo.capture import Frame, UVCCamera
from colpo.devices import DeviceInfo, available_backends, list_devices
from colpo.errors import (
    BackendUnavailableError,
    ColpoError,
    DeviceDisconnectedError,
    DeviceOpenError,
    DiskFullError,
    MetadataError,
    NotesRejectedError,
    RecordingError,
    SnapshotError,
)
from colpo.live import (
    FILE_BACKEND,
    Captured,
    Failed,
    LiveCapture,
    LiveEvent,
    Opened,
    RecordingChanged,
    Stopped,
    camera_for_device,
)
from colpo.metadata import IFCPC_STAGES
from colpo.session import CaptureSession
from colpo.ui.i18n import DEFAULT_LANGUAGE, LANGUAGES, Translator

PREVIEW_INTERVAL_MS = 15  # sondeo del último frame (> 60 Hz: no se pierde ninguno a 30 FPS)

_BANNER_STYLE = (
    "#disclaimerBanner { background: #FFF3CD; color: #5C4400; border: 1px solid #E0A800;"
    " padding: 6px; font-weight: bold; }"
)
_ERROR_STYLE = "#errorPanel { background: #FDECEA; border: 1px solid #E57373; }"
_ERROR_TEXT_STYLE = "color: #611A15;"
_PREVIEW_STYLE = "background: #111; color: #BBB;"
_RECORDING_STYLE = "color: #C62828; font-weight: bold;"
_NOTES_WARNING_STYLE = "color: #B71C1C;"


def error_message_key(error: ColpoError, action: str) -> str:
    """Clave de traducción del mensaje principal para un error del núcleo."""
    if isinstance(error, DiskFullError) or storage.is_disk_full_error(error):
        return "error.disk_full"
    if isinstance(error, DeviceDisconnectedError):
        return "error.camera_disconnected"
    if isinstance(error, DeviceOpenError) or action == "open":
        return "error.camera_busy"
    if isinstance(error, BackendUnavailableError):
        return "error.backend"
    if isinstance(error, MetadataError):
        return "error.metadata"
    if isinstance(error, RecordingError) or action.startswith("video"):
        return "error.recording_failed"
    if isinstance(error, SnapshotError) or action == "photo":
        return "error.photo_failed"
    return "error.generic"


def frame_to_pixmap(frame: Frame) -> QPixmap:
    """Convierte un frame BGR del núcleo en ``QPixmap`` (sin OpenCV)."""
    image = frame.image
    height, width = image.shape[:2]
    data = image.tobytes()  # se mantiene vivo hasta que QPixmap copia los datos
    qimage = QImage(data, width, height, image.strides[0], QImage.Format.Format_BGR888)
    return QPixmap.fromImage(qimage)


def _format_elapsed(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes:02d}:{secs:02d}"


class _EventBridge(QObject):
    """Lleva eventos del hilo de adquisición al hilo de la UI (conexión en cola)."""

    event = Signal(int, object)


class MainWindow(QMainWindow):
    """Ventana principal.

    Args:
        data_dir: carpeta de datos (por defecto ``~/OpenColposcope``).
        list_devices_fn: enumeración de cámaras del núcleo (inyectable en pruebas).
        camera_factory: crea la ``UVCCamera`` de un dispositivo (inyectable en pruebas).
        settings: preferencias de la UI (idioma, API, última cámara).
        language: idioma inicial; si no, el guardado; si no, español.
        demo_source: video que se ofrece como "cámara" de demostración.
        session: sesión de captura (por defecto, una nueva en ``data_dir``).
    """

    def __init__(
        self,
        *,
        data_dir: Path | None = None,
        list_devices_fn: Callable[[str], list[DeviceInfo]] = list_devices,
        camera_factory: Callable[[DeviceInfo], UVCCamera] = camera_for_device,
        settings: QSettings | None = None,
        language: str | None = None,
        demo_source: Path | None = None,
        session: CaptureSession | None = None,
    ) -> None:
        super().__init__()
        self._settings = settings or QSettings("OpenColposcope", "OpenColposcope")
        initial = language or str(self._settings.value("language", DEFAULT_LANGUAGE))
        self.translator = Translator(initial if initial in LANGUAGES else DEFAULT_LANGUAGE)
        self._list_devices = list_devices_fn
        self._camera_factory = camera_factory
        self._demo_source = demo_source
        self.session = session or CaptureSession(data_dir or storage.default_data_dir())

        self._devices: list[DeviceInfo] = []
        self._live: LiveCapture | None = None
        self._generation = 0
        self._state = "disconnected"  # disconnected | connecting | streaming
        self._recording = False
        self._connected_name = ""
        self._last_sequence = -1
        self._error: tuple[str, str] | None = None
        self._last_capture: tuple[str, dict[str, object]] | None = None
        self._notes_reasons: tuple[str, ...] = ()

        self._bridge = _EventBridge()
        self._bridge.event.connect(self._on_live_event)

        self._build_ui()
        self.refresh_devices()
        self._retranslate()
        self._update_controls()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_preview)
        self._timer.start(PREVIEW_INTERVAL_MS)

    # ------------------------------------------------------------- interfaz
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)

        self.banner_label = QLabel(objectName="disclaimerBanner")
        self.banner_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.banner_label.setWordWrap(True)
        self.banner_label.setStyleSheet(_BANNER_STYLE)
        root.addWidget(self.banner_label)

        self.error_panel = QFrame(objectName="errorPanel")
        self.error_panel.setStyleSheet(_ERROR_STYLE)
        error_layout = QHBoxLayout(self.error_panel)
        self.error_label = QLabel(wordWrap=True)
        self.error_label.setStyleSheet(_ERROR_TEXT_STYLE)
        self.error_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.error_close_button = QToolButton(text="\u2715")  # ✕
        self.error_close_button.clicked.connect(self.dismiss_error)
        error_layout.addWidget(self.error_label, 1)
        error_layout.addWidget(self.error_close_button, 0, Qt.AlignmentFlag.AlignTop)
        self.error_panel.hide()
        root.addWidget(self.error_panel)

        top = QHBoxLayout()
        self.camera_label = QLabel()
        self.camera_combo = QComboBox()
        self.camera_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.api_label = QLabel()
        self.backend_combo = QComboBox()
        for backend in ("auto", *available_backends()):
            self.backend_combo.addItem(backend, backend)
        saved_backend = self.backend_combo.findData(str(self._settings.value("backend", "auto")))
        self.backend_combo.setCurrentIndex(max(0, saved_backend))
        self.refresh_button = QPushButton()
        self.connect_button = QPushButton()
        self.language_label = QLabel()
        self.language_combo = QComboBox()
        for code, name in LANGUAGES.items():
            self.language_combo.addItem(name, code)
        self.language_combo.setCurrentIndex(self.language_combo.findData(self.translator.language))
        for widget in (
            self.camera_label,
            self.camera_combo,
            self.api_label,
            self.backend_combo,
            self.refresh_button,
            self.connect_button,
        ):
            top.addWidget(widget)
        top.addSpacing(24)
        top.addWidget(self.language_label)
        top.addWidget(self.language_combo)
        root.addLayout(top)

        body = QHBoxLayout()
        left = QVBoxLayout()
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(640, 360)
        self.preview_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.preview_label.setStyleSheet(_PREVIEW_STYLE)
        left.addWidget(self.preview_label, 1)
        info_row = QHBoxLayout()
        self.stream_label = QLabel()
        self.recording_label = QLabel()
        self.recording_label.setStyleSheet(_RECORDING_STYLE)
        info_row.addWidget(self.stream_label)
        info_row.addStretch(1)
        info_row.addWidget(self.recording_label)
        left.addLayout(info_row)
        body.addLayout(left, 1)

        panel = QWidget()
        panel.setFixedWidth(320)
        side = QVBoxLayout(panel)
        side.setContentsMargins(0, 0, 0, 0)
        self.study_group = QGroupBox()
        study_layout = QVBoxLayout(self.study_group)
        self.study_label = QLabel()
        self.study_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.new_study_button = QPushButton()
        study_layout.addWidget(self.study_label)
        study_layout.addWidget(self.new_study_button)
        side.addWidget(self.study_group)

        self.stage_label = QLabel()
        self.stage_combo = QComboBox()
        for code in IFCPC_STAGES:
            self.stage_combo.addItem(code, code)
        self.stage_combo.setCurrentIndex(self.stage_combo.findData(self.session.stage))
        side.addWidget(self.stage_label)
        side.addWidget(self.stage_combo)

        self.notes_label = QLabel()
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setMaximumHeight(110)
        self.notes_warning = QLabel(wordWrap=True)
        self.notes_warning.setStyleSheet(_NOTES_WARNING_STYLE)
        self.notes_warning.hide()
        side.addWidget(self.notes_label)
        side.addWidget(self.notes_edit)
        side.addWidget(self.notes_warning)

        self.photo_button = QPushButton()
        self.record_button = QPushButton()
        for button in (self.photo_button, self.record_button):
            button.setMinimumHeight(44)
            side.addWidget(button)

        self.last_capture_title = QLabel()
        self.last_capture_label = QLabel(wordWrap=True)
        self.open_folder_button = QPushButton()
        side.addSpacing(8)
        side.addWidget(self.last_capture_title)
        side.addWidget(self.last_capture_label)
        side.addWidget(self.open_folder_button)
        side.addStretch(1)
        body.addWidget(panel)
        root.addLayout(body, 1)
        self.setCentralWidget(central)

        self.refresh_button.clicked.connect(self.refresh_devices)
        self.backend_combo.currentIndexChanged.connect(self._on_backend_changed)
        self.connect_button.clicked.connect(self.toggle_connection)
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        self.new_study_button.clicked.connect(self.new_study)
        self.stage_combo.currentIndexChanged.connect(self._on_stage_changed)
        self.notes_edit.textChanged.connect(self._on_notes_changed)
        self.photo_button.clicked.connect(self.take_photo)
        self.record_button.clicked.connect(self.toggle_recording)
        self.open_folder_button.clicked.connect(self._open_study_folder)
        # Atajos globales: funcionan aunque el foco esté en las notas (y con pedales
        # USB que emulan teclas).
        for key, slot in (("F8", self.take_photo), ("F9", self.toggle_recording)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(slot)

    def _retranslate(self) -> None:
        t = self.translator.tr
        self.setWindowTitle(t("app.title"))
        self.banner_label.setText(t("banner.disclaimer"))
        self.camera_label.setText(t("camera.label"))
        self.api_label.setText(t("camera.api"))
        self.refresh_button.setText(t("camera.refresh"))
        self.refresh_button.setToolTip(t("camera.refresh_tip"))
        self.language_label.setText(t("language.label"))
        self.study_group.setTitle(t("study.group"))
        self.new_study_button.setText(t("study.new"))
        self.stage_label.setText(t("stage.label"))
        for row, code in enumerate(IFCPC_STAGES):
            self.stage_combo.setItemText(row, t(f"stage.{code}"))
        self.notes_label.setText(t("notes.label"))
        self.notes_edit.setPlaceholderText(t("notes.placeholder"))
        self.photo_button.setText(t("capture.photo"))
        self.last_capture_title.setText(t("capture.last"))
        self.open_folder_button.setText(t("capture.open_folder"))
        self.error_close_button.setToolTip(t("error.close"))
        self._fill_camera_combo()
        self._render_study()
        self._render_notes_warning()
        self._render_error()
        self._render_last_capture()
        self._update_controls()

    def _update_controls(self) -> None:
        t = self.translator.tr
        streaming = self._state == "streaming"
        idle = self._state == "disconnected"
        has_device = self._selected_device() is not None
        for widget in (self.camera_combo, self.backend_combo, self.refresh_button):
            widget.setEnabled(idle)
        if self._state == "connecting":
            self.connect_button.setText(t("camera.connecting"))
        else:
            self.connect_button.setText(t("camera.connect" if idle else "camera.disconnect"))
        self.connect_button.setEnabled(self._state != "connecting" and (has_device or not idle))
        self.photo_button.setEnabled(streaming)
        self.record_button.setEnabled(streaming)
        self.record_button.setText(
            t("capture.record_stop" if self._recording else "capture.record_start")
        )
        self.new_study_button.setEnabled(not self._recording)
        self.recording_label.setVisible(self._recording)
        if not streaming:
            self.preview_label.clear()
            self.preview_label.setText(t("preview.placeholder"))
            self.stream_label.setText(t("status.no_stream"))

    # ------------------------------------------------------------ cámaras
    def refresh_devices(self) -> None:
        """Vuelve a enumerar las cámaras con la API seleccionada."""
        backend = self.backend_combo.currentData() or "auto"
        try:
            devices = list(self._list_devices(backend))
        except ColpoError as exc:
            devices = []
            self.show_error(exc, "enumerate")
        if self._demo_source is not None:
            devices.append(
                DeviceInfo(
                    index=0,
                    name=self._demo_source.name,
                    backend=FILE_BACKEND,
                    path=str(self._demo_source),
                )
            )
        self._devices = devices
        self._fill_camera_combo()
        self._update_controls()

    def _fill_camera_combo(self) -> None:
        t = self.translator.tr
        previous = self._selected_device()
        wanted = previous.name if previous else str(self._settings.value("last_device", ""))
        self.camera_combo.blockSignals(True)
        self.camera_combo.clear()
        for position, device in enumerate(self._devices):
            if device.backend == FILE_BACKEND:
                text = t("camera.demo", name=device.name)
            else:
                text = f"{device.index} — {device.name}"
            self.camera_combo.addItem(text, position)
            self.camera_combo.setItemData(
                position,
                t(
                    "camera.tooltip",
                    index=device.index,
                    vid_pid=device.vid_pid,
                    backend=device.backend,
                ),
                Qt.ItemDataRole.ToolTipRole,
            )
        if not self._devices:
            self.camera_combo.addItem(t("camera.none_found"), None)
        else:
            names = [d.name for d in self._devices]
            self.camera_combo.setCurrentIndex(names.index(wanted) if wanted in names else 0)
        self.camera_combo.blockSignals(False)

    def _selected_device(self) -> DeviceInfo | None:
        if not hasattr(self, "camera_combo"):
            return None
        position = self.camera_combo.currentData()
        if position is None or not 0 <= position < len(self._devices):
            return None
        return self._devices[position]

    def toggle_connection(self) -> None:
        if self._state == "disconnected":
            self.connect_camera()
        else:
            self.disconnect_camera()

    def connect_camera(self) -> None:
        device = self._selected_device()
        if device is None or self._state != "disconnected":
            return
        self.dismiss_error()
        self._generation += 1
        factory = self._camera_factory
        self._live = LiveCapture(
            lambda: factory(device),
            self.session,
            on_event=partial(self._bridge.event.emit, self._generation),
        )
        self._state = "connecting"
        self._connected_name = device.name
        self._last_sequence = -1
        self._settings.setValue("last_device", device.name)
        self._live.start()
        self._update_controls()

    def disconnect_camera(self) -> None:
        """Detiene la captura en vivo (si se grababa, el video se guarda)."""
        live, self._live = self._live, None
        if live is not None:
            live.stop()
        self._state = "disconnected"
        self._recording = False
        self._update_controls()

    # ------------------------------------------------------------- eventos
    def _on_live_event(self, generation: int, event: LiveEvent) -> None:
        current = generation == self._generation
        t = self.translator.tr
        if isinstance(event, Captured):
            result = event.result
            if result.metadata.tipo == "foto":
                self._last_capture = ("capture.photo_saved", {"name": result.media_path.name})
            else:
                self._last_capture = (
                    "capture.video_saved",
                    {"name": result.media_path.name, "codec": result.codec or "?"},
                )
                if result.frames_dropped:
                    self.statusBar().showMessage(
                        t("capture.frames_dropped", count=result.frames_dropped), 10000
                    )
            self._render_last_capture()
        elif isinstance(event, Failed):
            self.show_error(event.error, event.action)
        elif not current:
            return  # eventos de estado de una conexión anterior
        elif isinstance(event, Opened):
            self._state = "streaming"
            self.statusBar().showMessage(t("camera.connected", name=self._connected_name), 5000)
        elif isinstance(event, RecordingChanged):
            self._recording = event.recording
        elif isinstance(event, Stopped):
            if self._live is not None:
                self._live.stop()
                self._live = None
                self.statusBar().showMessage(t("camera.disconnected"), 5000)
            self._state = "disconnected"
            self._recording = False
        self._update_controls()

    def _refresh_preview(self) -> None:
        live = self._live
        if live is None or self._state != "streaming":
            return
        frame = live.latest_frame()
        if frame is not None and frame.sequence != self._last_sequence:
            self._last_sequence = frame.sequence
            self.preview_label.setPixmap(
                frame_to_pixmap(frame).scaled(
                    self.preview_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        status = live.status()
        if status is not None:
            self.stream_label.setText(
                self.translator.tr(
                    "status.stream", width=status.width, height=status.height, fps=status.fps
                )
            )
            if status.recording:
                self.recording_label.setText(
                    self.translator.tr(
                        "status.recording", elapsed=_format_elapsed(status.recording_elapsed_s)
                    )
                )

    # ------------------------------------------------------------- acciones
    def take_photo(self) -> None:
        if self._live is None or self._state != "streaming":
            return
        if self._notes_reasons:
            self.statusBar().showMessage(self.translator.tr("capture.notes_skipped"), 8000)
        self._live.request_photo()

    def toggle_recording(self) -> None:
        if self._live is None or self._state != "streaming":
            return
        if self._recording:
            self._live.request_stop_video()
        else:
            if self._notes_reasons:
                self.statusBar().showMessage(self.translator.tr("capture.notes_skipped"), 8000)
            self._live.request_start_video()

    def new_study(self) -> None:
        try:
            study_id = self.session.new_study()
        except ColpoError as exc:
            self.show_error(exc, "study")
            return
        self._last_capture = None
        self._render_study()
        self._render_last_capture()
        self.statusBar().showMessage(self.translator.tr("study.new_done", id=study_id), 5000)

    def _open_study_folder(self) -> None:
        folder = self.session.study_dir
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _on_backend_changed(self) -> None:
        self._settings.setValue("backend", self.backend_combo.currentData())
        self.refresh_devices()

    def _on_stage_changed(self) -> None:
        code = self.stage_combo.currentData()
        if code:
            self.session.stage = code

    def _on_notes_changed(self) -> None:
        try:
            self.session.set_notes(self.notes_edit.toPlainText())
            self._notes_reasons = ()
        except NotesRejectedError as exc:
            self._notes_reasons = exc.reasons
        self._render_notes_warning()

    def _on_language_changed(self) -> None:
        code = self.language_combo.currentData()
        if code and code != self.translator.language:
            self.translator.set_language(code)
            self._settings.setValue("language", code)
            self._retranslate()

    def set_language(self, code: str) -> None:
        """Cambia el idioma en caliente (equivale a usar el selector)."""
        self.language_combo.setCurrentIndex(self.language_combo.findData(code))

    # -------------------------------------------------------------- errores
    def show_error(self, error: ColpoError, action: str) -> None:
        self._error = (error_message_key(error, action), str(error))
        self._render_error()

    def dismiss_error(self) -> None:
        self._error = None
        self._render_error()

    def _render_error(self) -> None:
        if self._error is None:
            self.error_panel.hide()
            return
        key, detail = self._error
        t = self.translator.tr
        self.error_label.setText(f"{t(key)}\n{t('error.detail', detail=detail)}")
        self.error_panel.show()

    def _render_study(self) -> None:
        t = self.translator.tr
        self.study_label.setText(t("study.id", id=self.session.study_id))
        self.open_folder_button.setToolTip(t("capture.folder_tip", path=self.session.study_dir))

    def _render_notes_warning(self) -> None:
        if not self._notes_reasons:
            self.notes_warning.hide()
            return
        t = self.translator.tr
        reasons = ", ".join(t(f"notes.reason.{code}") for code in self._notes_reasons)
        self.notes_warning.setText(t("notes.rejected", reasons=reasons))
        self.notes_warning.show()

    def _render_last_capture(self) -> None:
        t = self.translator.tr
        if self._last_capture is None:
            self.last_capture_label.setText(t("capture.none"))
        else:
            key, params = self._last_capture
            self.last_capture_label.setText(t(key, **params))
        self._render_study()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (API de Qt)
        self._timer.stop()
        self.disconnect_camera()
        self._settings.sync()
        super().closeEvent(event)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="colpo-ui",
        description="Open Colposcope: interfaz de captura (prototipo educativo, no diagnóstico).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--lang", choices=tuple(LANGUAGES), help="idioma inicial (es o en)")
    parser.add_argument(
        "--data-dir", type=Path, help="carpeta de datos (por defecto ~/OpenColposcope)"
    )
    parser.add_argument(
        "--source", type=Path, help="video de demostración que se ofrece como cámara"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setApplicationName("Open Colposcope")
    app.setApplicationVersion(__version__)
    window = MainWindow(data_dir=args.data_dir, language=args.lang, demo_source=args.source)
    window.resize(1200, 760)
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    sys.exit(main())
