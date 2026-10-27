"""Ventana mínima de vista previa (herramienta de F1; la GUI completa llega en F2).

Teclas: ``S`` o ``Espacio`` guarda una foto PNG, ``R`` inicia/detiene una
grabación MP4, ``Q`` o ``Esc`` cierra. La lectura ocurre en el hilo de la UI
(suficiente para depurar); en F2 se moverá a un hilo de adquisición.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QImage, QKeyEvent, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow

from colpo.capture import CaptureCamera, Frame, RecordingStats
from colpo.errors import ColpoError, EndOfStreamError

WINDOW_TITLE = "Open Colposcope - vista previa (uso educativo, no diagnóstico)"


@dataclass
class PreviewResult:
    """Lo ocurrido durante la vista previa (para la CLI y las pruebas)."""

    frames_shown: int = 0
    snapshots: list[Path] = field(default_factory=list)
    recordings: list[RecordingStats] = field(default_factory=list)
    error: ColpoError | None = None
    end_of_stream: bool = False


def frame_to_qimage(frame: Frame) -> QImage:
    """Convierte un frame BGR en una ``QImage`` independiente del buffer de NumPy."""
    image = frame.image
    height, width = image.shape[:2]
    qimage = QImage(image.tobytes(), width, height, image.strides[0], QImage.Format.Format_BGR888)
    return qimage.copy()


def _timestamped_name(prefix: str, sequence: int, suffix: str) -> str:
    # Hora local exacta al segundo; sin datos de paciente.
    return f"{prefix}_{datetime.now():%Y%m%d-%H%M%S}_{sequence:06d}{suffix}"


class PreviewWindow(QMainWindow):
    def __init__(
        self,
        camera: CaptureCamera,
        out_dir: Path,
        result: PreviewResult,
        max_frames: int | None = None,
    ) -> None:
        super().__init__()
        self._camera = camera
        self._out_dir = out_dir
        self._result = result
        self._max_frames = max_frames
        self._times: deque[float] = deque(maxlen=30)

        self.setWindowTitle(WINDOW_TITLE)
        self._label = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self._label.setMinimumSize(320, 180)
        self.setCentralWidget(self._label)
        info = camera.stream_info
        self.resize(min(info.width, 1280), min(info.height, 720) + 30)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        interval = 0
        if camera.is_file_source and info.fps_reported > 0:
            interval = int(1000 / info.fps_reported)
        self._timer.start(interval)

    def _tick(self) -> None:
        try:
            frame = self._camera.read()
        except EndOfStreamError:
            self._result.end_of_stream = True
            self._timer.stop()
            self.statusBar().showMessage("Fin del video de origen. Pulse Q para salir.")
            if self._max_frames is not None:
                self.close()
            return
        except ColpoError as exc:
            self._result.error = exc
            self.close()
            return

        pixmap = QPixmap.fromImage(frame_to_qimage(frame))
        self._label.setPixmap(
            pixmap.scaled(
                self._label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self._result.frames_shown += 1
        self._times.append(time.monotonic())
        self._update_status(frame)
        if self._max_frames is not None and self._result.frames_shown >= self._max_frames:
            self.close()

    def _update_status(self, frame: Frame) -> None:
        if self._result.error is not None:
            return
        info = self._camera.stream_info
        fps = 0.0
        if len(self._times) > 1:
            fps = (len(self._times) - 1) / (self._times[-1] - self._times[0])
        rec = "  ● GRABANDO" if self._camera.is_recording else ""
        self.statusBar().showMessage(
            f"{frame.width}x{frame.height} {info.fourcc or '?'}  {fps:4.1f} FPS  "
            f"frame {frame.sequence}{rec}   [S] foto  [R] grabar  [Q] salir"
        )

    def take_snapshot(self) -> None:
        frame = self._camera.last_frame
        if frame is None:
            return
        path = self._out_dir / _timestamped_name("foto", frame.sequence, ".png")
        try:
            self._camera.snapshot(path, frame=frame)
        except ColpoError as exc:
            self.statusBar().showMessage(f"Error al guardar la foto: {exc}")
            return
        self._result.snapshots.append(path)
        self.statusBar().showMessage(f"Foto guardada: {path}", 3000)

    def toggle_recording(self) -> None:
        try:
            if self._camera.is_recording:
                stats = self._camera.stop_recording()
                self._result.recordings.append(stats)
                self.statusBar().showMessage(
                    f"Video guardado: {stats.path} ({stats.duration_s:.1f} s)", 3000
                )
            else:
                sequence = self._camera.last_frame.sequence if self._camera.last_frame else 0
                path = self._out_dir / _timestamped_name("video", sequence, ".mp4")
                self._camera.start_recording(path)
        except ColpoError as exc:
            self.statusBar().showMessage(f"Error de grabación: {exc}")

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (API de Qt)
        key = event.key()
        if key in (Qt.Key.Key_S, Qt.Key.Key_Space):
            self.take_snapshot()
        elif key == Qt.Key.Key_R:
            self.toggle_recording()
        elif key in (Qt.Key.Key_Q, Qt.Key.Key_Escape):
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (API de Qt)
        self._timer.stop()
        if self._camera.is_recording:
            try:
                self._result.recordings.append(self._camera.stop_recording())
            except ColpoError as exc:
                self._result.error = exc
        super().closeEvent(event)


def run_preview(
    camera: CaptureCamera, *, out_dir: Path, max_frames: int | None = None
) -> PreviewResult:
    """Muestra la vista previa de una cámara ya abierta hasta que se cierre la ventana.

    ``max_frames`` cierra la ventana automáticamente (pruebas).
    """
    app = QApplication.instance() or QApplication([])
    result = PreviewResult()
    window = PreviewWindow(camera, out_dir, result, max_frames=max_frames)
    window.show()
    app.exec()
    return result
