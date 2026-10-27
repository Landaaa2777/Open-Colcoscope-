"""Captura en vivo en un hilo propio, sin dependencias de Qt.

:class:`LiveCapture` es el único dueño de una :class:`~colpo.capture.CaptureCamera`
mientras está activa: abre la cámara, lee frames continuamente y ejecuta en su
propio hilo los comandos de foto y video que le pide la UI. Así la interfaz
nunca se bloquea esperando a la cámara y la cámara nunca se usa desde dos hilos.

La UI lee el último frame con :meth:`LiveCapture.latest_frame` (el más reciente
gana; nunca se acumulan frames) y recibe los eventos (:class:`Opened`,
:class:`Captured`, :class:`Failed`, :class:`RecordingChanged`, :class:`Stopped`)
mediante el callback ``on_event``, invocado desde el hilo de adquisición.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from colpo.capture import CaptureCamera
from colpo.devices import DeviceInfo
from colpo.drivers.registry import DriverRegistry, default_registry
from colpo.errors import ColpoError, EndOfStreamError, FrameReadError, RecordingError
from colpo.frame import Frame, StreamInfo
from colpo.session import CaptureResult, CaptureSession

log = logging.getLogger(__name__)

FILE_BACKEND = "file"


def open_capture(
    driver_name: str,
    device: DeviceInfo,
    *,
    registry: DriverRegistry | None = None,
    **options: object,
) -> CaptureCamera:
    """Crea (sin abrir) la cámara de captura para un dispositivo y su driver.

    Funciona con cualquier driver registrado: el núcleo añade foto, video y
    metadatos encima del driver.
    """
    driver = (registry or default_registry()).create(driver_name, device, **options)
    return CaptureCamera(driver)


def camera_for_device(device: DeviceInfo) -> CaptureCamera:
    """Compatibilidad F2: cámara UVC o archivo de demostración para ``device``."""
    if device.backend == FILE_BACKEND and not device.path:
        raise ValueError("Un dispositivo de archivo necesita 'path'.")
    return open_capture("uvc", device)


# --------------------------------------------------------------------- eventos
@dataclass(frozen=True)
class Opened:
    info: StreamInfo


@dataclass(frozen=True)
class Captured:
    result: CaptureResult


@dataclass(frozen=True)
class Failed:
    """``action``: ``open``, ``read``, ``photo``, ``video_start``, ``video_stop``, ``close``."""

    error: ColpoError
    action: str


@dataclass(frozen=True)
class RecordingChanged:
    recording: bool


@dataclass(frozen=True)
class Stopped:
    pass


LiveEvent = Opened | Captured | Failed | RecordingChanged | Stopped


@dataclass(frozen=True)
class LiveStatus:
    width: int
    height: int
    fps: float
    sequence: int
    recording: bool
    recording_elapsed_s: float


class LiveCapture:
    """Hilo de adquisición para una cámara.

    Args:
        camera_factory: crea la cámara (se llama dentro del hilo, porque abrir
            puede tardar varios segundos con algunos drivers).
        session: sesión donde se guardan fotos y videos.
        on_event: recibe los eventos, desde el hilo de adquisición.
        space_check_interval: cada cuántos segundos se comprueba el espacio
            libre mientras se graba.
        tag: identificador corto del dispositivo para los nombres de archivo
            (p. ej. ``uvc0``), útil con varias cámaras abiertas a la vez.
    """

    _FPS_WINDOW = 30

    def __init__(
        self,
        camera_factory: Callable[[], CaptureCamera],
        session: CaptureSession,
        *,
        on_event: Callable[[LiveEvent], None] | None = None,
        space_check_interval: float = 2.0,
        tag: str | None = None,
    ) -> None:
        self._camera_factory = camera_factory
        self._session = session
        self._on_event = on_event or (lambda _event: None)
        self._space_check_interval = space_check_interval
        self._tag = tag
        self._commands: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._latest: Frame | None = None
        self._status: LiveStatus | None = None
        self._times: deque[float] = deque(maxlen=self._FPS_WINDOW)
        self._recording_since: float | None = None

    # ------------------------------------------------------------- control
    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("LiveCapture ya se inició.")
        self._thread = threading.Thread(target=self._run, name="colpo-live", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 15.0) -> None:
        """Detiene el hilo; si se estaba grabando, el video se cierra y se guarda."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def request_photo(self) -> None:
        self._commands.put("photo")

    def request_start_video(self) -> None:
        self._commands.put("video_start")

    def request_stop_video(self) -> None:
        self._commands.put("video_stop")

    def latest_frame(self) -> Frame | None:
        return self._latest

    def status(self) -> LiveStatus | None:
        return self._status

    # ---------------------------------------------------------------- hilo
    def _emit(self, event: LiveEvent) -> None:
        try:
            self._on_event(event)
        except Exception:  # un fallo de la UI no debe matar la adquisición
            log.exception("Error en el manejador de eventos de la UI")

    def _run(self) -> None:
        try:
            camera = self._camera_factory()
            info = camera.open()
        except ColpoError as exc:
            self._emit(Failed(exc, "open"))
            self._emit(Stopped())
            return
        except Exception as exc:  # no dejar la UI esperando si algo inesperado falla
            log.exception("Error inesperado al abrir la cámara")
            self._emit(Failed(ColpoError(f"Error inesperado al abrir la cámara: {exc}"), "open"))
            self._emit(Stopped())
            return
        self._emit(Opened(info))

        started = time.monotonic()
        next_space_check = 0.0
        try:
            while not self._stop.is_set():
                self._process_commands(camera)
                try:
                    frame = camera.read()
                except RecordingError as exc:
                    # El escritor de video falló: se intenta cerrar lo grabado y se sigue.
                    self._finish_video(camera, exc)
                    continue
                except FrameReadError as exc:
                    if not isinstance(exc, EndOfStreamError):
                        self._emit(Failed(exc, "read"))
                    break
                if camera.is_file_source:  # demostración: reproducir a velocidad real
                    time.sleep(max(0.0, started + frame.timestamp - time.monotonic()))
                self._publish(frame)
                if self._session.is_recording_on(camera) and time.monotonic() >= next_space_check:
                    next_space_check = time.monotonic() + self._space_check_interval
                    try:
                        self._session.check_recording_space()
                    except ColpoError as exc:
                        self._finish_video(camera, exc)
        finally:
            if self._session.is_recording_on(camera):
                self._finish_video(camera, None)
            try:
                camera.close()
            except ColpoError as exc:
                self._emit(Failed(exc, "close"))
            self._status = None
            self._emit(Stopped())

    def _publish(self, frame: Frame) -> None:
        self._latest = frame
        self._times.append(frame.timestamp)
        fps = 0.0
        if len(self._times) > 1 and self._times[-1] > self._times[0]:
            fps = (len(self._times) - 1) / (self._times[-1] - self._times[0])
        recording = self._recording_since is not None
        self._status = LiveStatus(
            width=frame.width,
            height=frame.height,
            fps=fps,
            sequence=frame.sequence,
            recording=recording,
            recording_elapsed_s=(
                time.monotonic() - self._recording_since if self._recording_since else 0.0
            ),
        )

    def _current_fps(self) -> float | None:
        return self._status.fps if self._status and self._status.fps > 0 else None

    def _process_commands(self, camera: CaptureCamera) -> None:
        while True:
            try:
                command = self._commands.get_nowait()
            except queue.Empty:
                return
            if command == "photo":
                try:
                    result = self._session.take_photo(
                        camera, fps=self._current_fps(), tag=self._tag
                    )
                    self._emit(Captured(result))
                except ColpoError as exc:
                    self._emit(Failed(exc, "photo"))
            elif command == "video_start" and not self._session.is_recording_on(camera):
                try:
                    self._session.start_video(camera, fps=self._current_fps(), tag=self._tag)
                except ColpoError as exc:
                    self._emit(Failed(exc, "video_start"))
                else:
                    self._recording_since = time.monotonic()
                    self._emit(RecordingChanged(True))
            elif command == "video_stop" and self._session.is_recording_on(camera):
                self._finish_video(camera, None)

    def _finish_video(self, camera: CaptureCamera, reason: ColpoError | None) -> None:
        """Cierra la grabación (si la hay) y avisa con un único error si algo falló.

        Si el cierre falla, se informa ese error (incluye la ruta del archivo
        parcial); si no, se informa ``reason`` (p. ej. disco casi lleno).
        """
        self._recording_since = None
        error = reason
        if self._session.is_recording_on(camera):
            try:
                self._emit(Captured(self._session.stop_video(camera)))
            except ColpoError as exc:
                error = exc
        if error is not None:
            self._emit(Failed(error, "video_stop"))
        self._emit(RecordingChanged(False))
