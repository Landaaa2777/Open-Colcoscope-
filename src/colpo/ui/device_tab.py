"""Pestaña de dispositivo: vista previa en vivo de *un* dispositivo abierto.

Cada pestaña tiene su propio hilo de captura (:class:`colpo.live.LiveCapture`),
así que abrir un segundo dispositivo no bloquea al primero. La pestaña no
conoce drivers concretos: recibe una función que crea la ``CaptureCamera``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from colpo.capture import CaptureCamera
from colpo.devices import DeviceInfo
from colpo.frame import Frame
from colpo.live import (
    FILE_BACKEND,
    Captured,
    Failed,
    LiveCapture,
    LiveEvent,
    Opened,
    RecordingChanged,
    Stopped,
)
from colpo.session import CaptureSession
from colpo.ui.i18n import Translator

_PREVIEW_STYLE = "background: #111; color: #BBB;"
_RECORDING_STYLE = "color: #C62828; font-weight: bold;"


@dataclass(frozen=True)
class DeviceChoice:
    """Un dispositivo detectado y el driver que lo maneja (dato de presentación)."""

    driver: str
    device: DeviceInfo

    @property
    def key(self) -> tuple[object, ...]:
        """Identidad para evitar abrir el mismo dispositivo en dos pestañas."""
        d = self.device
        return (self.driver, d.backend, d.index, d.path)

    @property
    def tag(self) -> str:
        """Sufijo corto para los nombres de archivo (``uvc0``, ``mock1``...)."""
        if self.device.backend == FILE_BACKEND:
            return "demo"
        return f"{self.driver}{self.device.index}"

    def label(self, translator: Translator) -> str:
        if self.device.backend == FILE_BACKEND:
            return translator.tr("device.demo", name=self.device.name)
        return f"{self.device.index} — {self.device.name}"


def frame_to_pixmap(frame: Frame) -> QPixmap:
    """Convierte un frame BGR del núcleo en ``QPixmap`` (sin OpenCV)."""
    image = frame.image
    height, width = image.shape[:2]
    data = image.tobytes()
    # .copy(): la QImage pasa a ser dueña de sus datos. Sin ella, Qt puede compartir
    # el buffer de ``data`` (memoria de Python) después de que se libere.
    qimage = QImage(data, width, height, image.strides[0], QImage.Format.Format_BGR888).copy()
    return QPixmap.fromImage(qimage)


def _format_elapsed(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes:02d}:{secs:02d}"


class _EventBridge(QObject):
    """Lleva eventos del hilo de adquisición al hilo de la UI (conexión en cola)."""

    event = Signal(int, object)


class DeviceTab(QWidget):
    """Vista de un dispositivo. Estados: ``idle``, ``connecting``, ``streaming``."""

    def __init__(
        self,
        translator: Translator,
        session: CaptureSession,
        open_camera: Callable[[DeviceChoice], CaptureCamera],
        on_event: Callable[[DeviceTab, LiveEvent], None],
    ) -> None:
        super().__init__()
        self._translator = translator
        self._session = session
        self._open_camera = open_camera
        self._on_event = on_event
        self.choice: DeviceChoice | None = None
        self.state = "idle"
        self.recording = False
        self.last_sequence = -1
        self._live: LiveCapture | None = None
        self._generation = 0
        self._bridge = _EventBridge(self)  # con padre: su vida la gestiona Qt
        self._bridge.event.connect(self._on_live_event)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.preview_label = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(480, 270)
        self.preview_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.preview_label.setStyleSheet(_PREVIEW_STYLE)
        layout.addWidget(self.preview_label, 1)
        info = QHBoxLayout()
        self.stream_label = QLabel()
        self.recording_label = QLabel()
        self.recording_label.setStyleSheet(_RECORDING_STYLE)
        info.addWidget(self.stream_label)
        info.addStretch(1)
        info.addWidget(self.recording_label)
        layout.addLayout(info)
        self.retranslate()

    # --------------------------------------------------------------- control
    @property
    def streaming(self) -> bool:
        return self.state == "streaming"

    def start(self, choice: DeviceChoice) -> None:
        """Abre ``choice`` en esta pestaña; si había otro dispositivo, lo cierra antes."""
        self.stop()
        self.choice = choice
        self._generation += 1
        self.last_sequence = -1
        self._live = LiveCapture(
            partial(self._open_camera, choice),
            self._session,
            on_event=partial(self._bridge.event.emit, self._generation),
            tag=choice.tag,
        )
        self.state = "connecting"
        self._live.start()
        self.retranslate()

    def stop(self) -> None:
        """Cierra el dispositivo (si se grababa, el video se guarda)."""
        live, self._live = self._live, None
        if live is not None:
            live.stop()
        self.state = "idle"
        self.recording = False
        self.retranslate()

    def take_photo(self) -> None:
        if self._live is not None and self.streaming:
            self._live.request_photo()

    def toggle_recording(self) -> None:
        if self._live is None or not self.streaming:
            return
        if self.recording:
            self._live.request_stop_video()
        else:
            self._live.request_start_video()

    # ---------------------------------------------------------------- eventos
    def _on_live_event(self, generation: int, event: LiveEvent) -> None:
        current = generation == self._generation
        if isinstance(event, Opened) and current:
            self.state = "streaming"
        elif isinstance(event, RecordingChanged) and current:
            self.recording = event.recording
        elif isinstance(event, Stopped) and current:
            if self._live is not None:
                self._live.stop()
                self._live = None
            self.state = "idle"
            self.recording = False
        elif not isinstance(event, (Captured, Failed)):
            return  # estado de una conexión anterior de esta pestaña
        self.retranslate()
        self._on_event(self, event)

    # ------------------------------------------------------------ presentación
    def refresh(self, paint: bool) -> None:
        """Actualiza estado y, si ``paint``, la imagen (solo la pestaña visible)."""
        live = self._live
        if live is None or not self.streaming:
            return
        status = live.status()
        if status is not None:
            t = self._translator.tr
            self.stream_label.setText(
                t("status.stream", width=status.width, height=status.height, fps=status.fps)
            )
            if status.recording:
                self.recording_label.setText(
                    t("status.recording", elapsed=_format_elapsed(status.recording_elapsed_s))
                )
        if not paint:
            return
        frame = live.latest_frame()
        if frame is not None and frame.sequence != self.last_sequence:
            self.last_sequence = frame.sequence
            self.preview_label.setPixmap(
                frame_to_pixmap(frame).scaled(
                    self.preview_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def title(self) -> str:
        if self.choice is None:
            return self._translator.tr("tab.empty")
        prefix = "● " if self.recording else ""
        return prefix + self.choice.label(self._translator)

    def retranslate(self) -> None:
        t = self._translator.tr
        self.recording_label.setVisible(self.recording)
        if self.streaming:
            return
        self.preview_label.clear()
        self.preview_label.setText(
            t("tab.connecting") if self.state == "connecting" else t("tab.idle")
        )
        self.stream_label.setText(t("status.no_stream"))
