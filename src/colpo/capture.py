"""Núcleo de captura: foto, video y medición de FPS sobre cualquier driver.

:class:`CaptureCamera` envuelve un :class:`~colpo.drivers.base.CameraDriver`
(el UVC de OpenCV, el simulado o uno de terceros) y añade lo que los drivers no
hacen por regla: marcas de tiempo, foto PNG atómica, grabación de video con
ritmo constante en un hilo propio y transformación opcional de frames (marca de
agua). Así un driver nuevo obtiene todo esto sin escribir una línea de E/S.

Modelo de uso: síncrono y de un solo hilo para la lectura. Quien usa la clase
llama a :meth:`CaptureCamera.read` en bucle; si hay una grabación en curso,
cada frame leído se entrega a un hilo escritor con cola acotada. La clase no es
*thread-safe* (ver :class:`colpo.live.LiveCapture` para uso desde la UI).

Compatibilidad: ``UVCCamera``, ``Frame``, ``StreamInfo``, ``nominal_fps`` y
``decode_fourcc`` se siguen pudiendo importar desde este módulo.
"""

from __future__ import annotations

import contextlib
import logging
import os
import platform
import queue
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from colpo.drivers.base import SOURCE_FILE, CameraDriver, Capabilities
from colpo.drivers.uvc import UVCCamera
from colpo.errors import (
    CameraNotOpenError,
    ColpoError,
    FrameReadError,
    RecordingError,
    SnapshotError,
    UnsupportedFormatError,
)
from colpo.frame import (
    FALLBACK_FPS,
    MAX_FPS,
    MIN_FPS,
    Frame,
    StreamInfo,
    decode_fourcc,
    is_valid_fps,
    nominal_fps,
)

__all__ = [
    "FALLBACK_FPS",
    "SNAPSHOT_EXTENSIONS",
    "VIDEO_CODECS",
    "CaptureCamera",
    "Frame",
    "RecordingStats",
    "StreamInfo",
    "UVCCamera",
    "decode_fourcc",
    "nominal_fps",
    "open_video_writer",
    "video_codec_candidates",
]

log = logging.getLogger(__name__)

FrameTransform = Callable[[np.ndarray], np.ndarray]

# Extensión -> FOURCC disponible en cualquier plataforma (respaldo garantizado).
VIDEO_CODECS: dict[str, str] = {".mp4": "mp4v", ".avi": "MJPG", ".mkv": "MJPG"}
# H.264 no viene en las ruedas de OpenCV (licencias/patentes), pero Windows 10/11
# trae un codificador H.264 propio en Media Foundation: se intenta primero allí.
H264_FOURCC = "H264"
SNAPSHOT_EXTENSIONS: tuple[str, ...] = (".png",)


def video_codec_candidates(suffix: str, system: str | None = None) -> tuple[str, ...]:
    """Códecs a intentar, en orden, para una extensión de video.

    ``.mp4`` en Windows: H.264 (Media Foundation) y, si no está disponible
    (p. ej. ediciones "N" sin Media Feature Pack), ``mp4v``. En el resto de
    casos, solo el códec de :data:`VIDEO_CODECS`.
    """
    fallback = VIDEO_CODECS[suffix.lower()]
    if suffix.lower() == ".mp4" and (system or platform.system()) == "Windows":
        return (H264_FOURCC, fallback)
    return (fallback,)


def open_video_writer(path: str, fourcc: int, fps: float, size: tuple[int, int]) -> cv2.VideoWriter:
    """``writer_factory`` predeterminado: usa Media Foundation para H.264 en Windows."""
    if fourcc == cv2.VideoWriter_fourcc(*H264_FOURCC) and platform.system() == "Windows":
        return cv2.VideoWriter(path, cv2.CAP_MSMF, fourcc, fps, size)
    return cv2.VideoWriter(path, fourcc, fps, size)


@dataclass(frozen=True)
class RecordingStats:
    """Resumen de una grabación finalizada.

    El video se escribe a ritmo constante (``fps``): si la cámara entrega menos
    frames, se repiten (``frames_written`` > ``frames_received``); si entrega
    más, se omiten (``frames_skipped``). ``frames_dropped`` cuenta frames que
    no se pudieron encolar porque el disco/CPU no daba abasto: es pérdida real.
    """

    path: Path
    codec: str
    fps: float
    frames_received: int
    frames_written: int
    frames_skipped: int
    frames_dropped: int
    duration_s: float
    wall_time_s: float


def _atomic_write(path: Path, data: bytes) -> None:
    """Escribe en un temporal del mismo directorio, ``fsync`` y renombra."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def _fsync_file(path: Path) -> None:
    with open(path, "rb+") as fh:
        os.fsync(fh.fileno())


class _VideoRecorder:
    """Escribe frames en un hilo propio, a ritmo constante, en un archivo temporal.

    El archivo final solo aparece (por renombrado) cuando la grabación se cierra
    correctamente; si el proceso muere, queda ``.<nombre>.recording<ext>``.

    Con ``block_when_full`` (fuentes de archivo, sin tiempo real) la lectura espera
    al escritor en vez de descartar frames; con cámaras, esperar solo movería la
    pérdida al driver, así que se descarta y se cuenta.
    """

    # Máximo de repeticiones de un frame para rellenar un hueco (p. ej., un
    # bloqueo momentáneo de la cámara). Huecos mayores se comprimen.
    MAX_GAP_S = 2.0

    def __init__(
        self,
        path: Path,
        codecs: tuple[str, ...],
        fps: float,
        size: tuple[int, int],
        writer_factory: Callable[..., cv2.VideoWriter],
        queue_size: int,
        block_when_full: bool = False,
        frame_transform: Callable[[np.ndarray], np.ndarray] | None = None,
    ) -> None:
        self.path = path
        self._block_when_full = block_when_full
        self._transform = frame_transform
        self.tmp_path = path.with_name(f".{path.stem}.recording{path.suffix}")
        self.fps = fps
        self.size = size
        self._max_repeats = max(1, int(self.MAX_GAP_S * fps))

        self.codec, self._writer = self._open_first_available(codecs, writer_factory)

        self._queue: queue.Queue[tuple[np.ndarray, int] | None] = queue.Queue(maxsize=queue_size)
        self._error: BaseException | None = None
        self._t0: float | None = None
        self._slots = 0
        self.received = self.written = self.skipped = self.dropped = 0
        self._started = time.monotonic()
        self._thread = threading.Thread(target=self._run, name="colpo-recorder", daemon=True)
        self._thread.start()

    def _open_first_available(
        self, codecs: tuple[str, ...], writer_factory: Callable[..., cv2.VideoWriter]
    ) -> tuple[str, cv2.VideoWriter]:
        for codec in codecs:
            writer = writer_factory(
                str(self.tmp_path), cv2.VideoWriter_fourcc(*codec), self.fps, self.size
            )
            if writer.isOpened():
                if codec != codecs[0]:
                    log.info("Códec %s no disponible; se usa %s.", codecs[0], codec)
                return codec, writer
            writer.release()
            with contextlib.suppress(OSError):
                self.tmp_path.unlink()
        raise RecordingError(
            f"No se pudo crear el video '{self.path}' con los códecs {', '.join(codecs)}. "
            "Pruebe la extensión .avi (MJPEG). En Windows, OpenCV puede fallar con rutas "
            "que contienen caracteres no ASCII (tildes, ñ)."
        )

    def _run(self) -> None:
        try:
            while (item := self._queue.get()) is not None:
                image, repeats = item
                for _ in range(repeats):
                    self._writer.write(image)
                self.written += repeats
        except BaseException as exc:  # se re-lanza como RecordingError en submit/stop
            self._error = exc

    def submit(self, frame: Frame) -> None:
        if self._error is not None:
            raise RecordingError(f"Falló la escritura del video: {self._error}") from self._error

        if self._t0 is None:
            self._t0 = frame.timestamp
        elapsed = max(0.0, frame.timestamp - self._t0)
        # Cantidad de frames que el video debería tener tras este instante.
        target = int(elapsed * self.fps + 1e-6) + 1
        repeats = target - self._slots
        if repeats <= 0:
            self.skipped += 1
            return

        image = frame.image
        if self._transform is not None:  # p. ej. marca de agua (solo frames que se escriben)
            image = self._transform(image)
        if (image.shape[1], image.shape[0]) != self.size:
            image = cv2.resize(image, self.size, interpolation=cv2.INTER_AREA)
        item = (image, min(repeats, self._max_repeats))
        try:
            if self._block_when_full:
                self._put_blocking(item)
            else:
                self._queue.put_nowait(item)
        except queue.Full:
            # No se avanza _slots: el siguiente frame rellenará el hueco.
            self.dropped += 1
            return
        self._slots = target
        self.received += 1

    def _put_blocking(self, item: tuple[np.ndarray, int]) -> None:
        while True:
            try:
                self._queue.put(item, timeout=0.5)
                return
            except queue.Full:
                if self._error is not None or not self._thread.is_alive():
                    raise RecordingError(
                        f"Falló la escritura del video: {self._error}"
                    ) from self._error

    def stop(self) -> RecordingStats:
        while True:
            try:
                self._queue.put(None, timeout=0.5)
                break
            except queue.Full:
                if not self._thread.is_alive():
                    break
        self._thread.join()
        self._writer.release()
        wall = time.monotonic() - self._started

        if self._error is not None:
            raise RecordingError(
                f"La grabación falló: {self._error}. Archivo parcial: {self.tmp_path}"
            ) from self._error
        if self.written == 0:
            with contextlib.suppress(OSError):
                self.tmp_path.unlink()
            raise RecordingError("No se grabó ningún frame; no se creó el archivo.")
        try:
            _fsync_file(self.tmp_path)
            os.replace(self.tmp_path, self.path)
        except OSError as exc:
            raise RecordingError(
                f"No se pudo finalizar '{self.path}': {exc}. Archivo parcial: {self.tmp_path}"
            ) from exc

        return RecordingStats(
            path=self.path,
            codec=self.codec,
            fps=self.fps,
            frames_received=self.received,
            frames_written=self.written,
            frames_skipped=self.skipped,
            frames_dropped=self.dropped,
            duration_s=self.written / self.fps,
            wall_time_s=wall,
        )


class CaptureCamera:
    """Foto, video y FPS reales sobre cualquier driver que cumpla ``CameraDriver``.

    Ejemplo::

        with CaptureCamera.for_index(0) as cam:          # driver UVC
            print(cam.stream_info, cam.measure_fps())
            cam.snapshot("foto.png")
            cam.start_recording("video.mp4")
            for _ in range(150):
                cam.read()
            stats = cam.stop_recording()

    Args:
        driver: instancia de driver **sin abrir** (``UVCCamera``, ``MockDriver``...).
        writer_factory, clock: inyección para pruebas.
    """

    def __init__(
        self,
        driver: CameraDriver,
        *,
        writer_factory: Callable[..., cv2.VideoWriter] = open_video_writer,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._driver = driver
        self._writer_factory = writer_factory
        self._clock = clock
        self._info: StreamInfo | None = None
        self._pending: Frame | None = None
        self._last_frame: Frame | None = None
        self._recorder: _VideoRecorder | None = None
        self._sequence = 0
        self._is_file = False
        self._file_fps = FALLBACK_FPS
        self._measured_fps: float | None = None

    @classmethod
    def for_index(
        cls,
        index: int,
        *,
        backend: str = "auto",
        writer_factory: Callable[..., cv2.VideoWriter] = open_video_writer,
        clock: Callable[[], float] = time.monotonic,
        **driver_options: Any,
    ) -> CaptureCamera:
        """Atajo: cámara UVC por índice (``driver_options`` van a :class:`UVCCamera`)."""
        driver = UVCCamera(index=index, backend=backend, **driver_options)
        return cls(driver, writer_factory=writer_factory, clock=clock)

    @classmethod
    def for_source(
        cls,
        source: str | os.PathLike[str],
        *,
        writer_factory: Callable[..., cv2.VideoWriter] = open_video_writer,
        clock: Callable[[], float] = time.monotonic,
        **driver_options: Any,
    ) -> CaptureCamera:
        """Atajo: archivo de video como fuente (demostración y pruebas)."""
        driver = UVCCamera(source=source, **driver_options)
        return cls(driver, writer_factory=writer_factory, clock=clock)

    # ------------------------------------------------------------------ info
    @property
    def driver(self) -> CameraDriver:
        return self._driver

    @property
    def is_file_source(self) -> bool:
        return self._is_file

    @property
    def is_open(self) -> bool:
        return self._info is not None

    @property
    def is_recording(self) -> bool:
        return self._recorder is not None

    @property
    def stream_info(self) -> StreamInfo:
        self._require_open()
        assert self._info is not None
        return self._info

    @property
    def last_frame(self) -> Frame | None:
        """Último frame entregado por :meth:`read` (o ``None``)."""
        return self._last_frame

    @property
    def measured_fps(self) -> float | None:
        """FPS reales medidos con :meth:`measure_fps` (``None`` si no se midió)."""
        return self._measured_fps

    def capabilities(self) -> Capabilities:
        return self._driver.capabilities()

    def metadata(self) -> dict[str, Any]:
        return self._driver.metadata()

    def is_connected(self) -> bool:
        return self.is_open and self._driver.is_connected()

    def __repr__(self) -> str:
        state = "abierta" if self.is_open else "cerrada"
        return f"CaptureCamera({self._driver!r}, {state})"

    # -------------------------------------------------------- ciclo de vida
    def __enter__(self) -> CaptureCamera:
        self.open()
        return self

    def __exit__(self, exc_type: type[BaseException] | None, *_: object) -> None:
        if exc_type is None:
            self.close()
            return
        # Ya hay una excepción en curso: cerrar sin ocultarla.
        try:
            self.close()
        except ColpoError as exc:
            log.error("Error adicional al cerrar la cámara: %s", exc)

    def open(self) -> StreamInfo:
        """Abre el driver y lee el primer frame (para conocer el formato real).

        Raises:
            CameraNotFound, CameraBusy, FormatNotSupported (y en general
            ``DeviceOpenError``), ``BackendUnavailableError``.
        """
        if self._info is not None:
            return self._info
        self._driver.open()
        try:
            meta = self._driver.metadata()
            self._is_file = meta.get("fuente") == SOURCE_FILE
            nominal = meta.get("fps_nominal")
            self._file_fps = float(nominal) if is_valid_fps(nominal) else FALLBACK_FPS
            image = self._read_driver()
            self._info = self._build_stream_info(image)
        except BaseException:
            with contextlib.suppress(Exception):
                self._driver.close()
            raise
        self._pending = self._make_frame(image)
        return self._info

    def close(self) -> RecordingStats | None:
        """Finaliza una grabación en curso (si la hay) y cierra el driver."""
        stats = None
        try:
            if self._recorder is not None:
                stats = self.stop_recording()
        finally:
            self._driver.close()
            self._info = None
            self._pending = None
        return stats

    # --------------------------------------------------------------- frames
    def read(self) -> Frame:
        """Devuelve el siguiente :class:`Frame` y, si se está grabando, lo envía al video.

        Raises:
            CameraNotOpenError: la cámara no está abierta.
            DeviceDisconnectedError (``CameraDisconnected``): dejó de entregar frames.
            EndOfStreamError: la fuente de archivo terminó.
            FrameReadError: el driver falló o devolvió algo que no es un frame.
            RecordingError: el hilo de grabación falló.
        """
        self._require_open()
        if self._pending is not None:
            frame, self._pending = self._pending, None
        else:
            frame = self._make_frame(self._read_driver())
        self._last_frame = frame
        if self._recorder is not None:
            self._recorder.submit(frame)
        return frame

    def read_frame(self) -> np.ndarray:
        """Como :meth:`read`, pero devuelve solo la imagen (forma del contrato de driver)."""
        return self.read().image

    def measure_fps(self, frames: int = 30) -> float:
        """Mide los FPS reales leyendo ``frames`` frames (cámaras).

        Para archivos devuelve los FPS declarados por el archivo.
        """
        self._require_open()
        if self._is_file:
            self._measured_fps = self._file_fps
            return self._file_fps
        if frames < 1:
            raise ValueError("'frames' debe ser >= 1.")
        if self._pending is not None:
            self.read()  # el frame pendiente es antiguo: no sirve de referencia
        start = self.read().timestamp
        end = start
        for _ in range(frames):
            end = self.read().timestamp
        elapsed = end - start
        self._measured_fps = frames / elapsed if elapsed > 0 else 0.0
        return self._measured_fps

    # ------------------------------------------------------------ foto fija
    def snapshot(
        self, path: str | os.PathLike[str], *, frame: Frame | None = None, overwrite: bool = False
    ) -> Path:
        """Guarda un PNG sin pérdida con escritura atómica.

        Si no se pasa ``frame``, se lee uno nuevo de la cámara. Los PNG
        generados no llevan metadatos EXIF.

        Raises:
            UnsupportedFormatError: la extensión no es ``.png``.
            SnapshotError: el archivo existe (sin ``overwrite``) o no se pudo escribir.
        """
        target = Path(path)
        if target.suffix.lower() not in SNAPSHOT_EXTENSIONS:
            raise UnsupportedFormatError(
                f"Formato de imagen no soportado: '{target.suffix}'. Use .png (sin pérdida)."
            )
        if target.exists() and not overwrite:
            raise SnapshotError(f"El archivo ya existe: {target}")
        if frame is None:
            frame = self.read()

        ok, buffer = cv2.imencode(".png", frame.image)
        if not ok:
            raise SnapshotError("OpenCV no pudo codificar la imagen como PNG.")
        try:
            # imencode + escritura propia: cv2.imwrite falla en Windows con rutas no ASCII.
            _atomic_write(target, buffer.tobytes())
        except OSError as exc:
            raise SnapshotError(f"No se pudo guardar '{target}': {exc}") from exc
        return target

    # --------------------------------------------------------------- video
    def start_recording(
        self,
        path: str | os.PathLike[str],
        *,
        fps: float | None = None,
        overwrite: bool = False,
        queue_size: int = 30,
        frame_transform: FrameTransform | None = None,
    ) -> Path:
        """Empieza a grabar los frames que se lean con :meth:`read`.

        Códec: ver :func:`video_codec_candidates` (``.mp4`` intenta H.264 en
        Windows y recurre a ``mp4v``); el usado queda en ``RecordingStats.codec``.

        ``fps`` por defecto: los medidos con :meth:`measure_fps` (redondeados
        con :func:`nominal_fps`), si no los informados por el driver o el
        archivo, y si no son válidos, 30. ``queue_size`` limita los frames en
        espera de codificación (~1 s a 30 FPS; a 1080p cada frame ocupa ~6 MB).
        ``frame_transform`` se aplica a cada frame que se escribe (p. ej. marca
        de agua); no altera la vista previa ni el frame original.

        Raises:
            UnsupportedFormatError: extensión distinta de .mp4, .avi o .mkv.
            RecordingError: ya se está grabando, el archivo existe o no se puede crear.
        """
        self._require_open()
        if self._recorder is not None:
            raise RecordingError("Ya hay una grabación en curso.")
        target = Path(path)
        if target.suffix.lower() not in VIDEO_CODECS:
            valid = ", ".join(VIDEO_CODECS)
            raise UnsupportedFormatError(
                f"Formato de video no soportado: '{target.suffix}'. Use {valid}."
            )
        if target.exists() and not overwrite:
            raise RecordingError(f"El archivo ya existe: {target}")
        if fps is not None and not is_valid_fps(fps):
            raise RecordingError(f"FPS fuera de rango ({MIN_FPS:g}-{MAX_FPS:g}): {fps}")

        info = self.stream_info
        if fps is not None:
            chosen = float(fps)
        elif is_valid_fps(self._measured_fps):
            assert self._measured_fps is not None
            chosen = nominal_fps(self._measured_fps)
        elif self._is_file:
            chosen = self._file_fps
        elif is_valid_fps(info.fps_reported):
            chosen = info.fps_reported
        else:
            log.warning("FPS desconocidos; se graba a %.0f FPS.", FALLBACK_FPS)
            chosen = FALLBACK_FPS

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RecordingError(f"No se pudo crear la carpeta '{target.parent}': {exc}") from exc
        self._recorder = _VideoRecorder(
            target,
            video_codec_candidates(target.suffix),
            chosen,
            (info.width, info.height),
            self._writer_factory,
            queue_size,
            block_when_full=self._is_file,
            frame_transform=frame_transform,
        )
        return target

    def stop_recording(self) -> RecordingStats:
        """Cierra el video y lo deja con su nombre final.

        Raises:
            RecordingError: no hay grabación en curso o falló el cierre.
        """
        if self._recorder is None:
            raise RecordingError("No hay ninguna grabación en curso.")
        recorder, self._recorder = self._recorder, None
        return recorder.stop()

    # ------------------------------------------------------------- internos
    def _require_open(self) -> None:
        if self._info is None:
            raise CameraNotOpenError("La cámara no está abierta. Llame a open() primero.")

    def _read_driver(self) -> np.ndarray:
        try:
            image = self._driver.read_frame()
        except ColpoError:
            raise
        except Exception as exc:  # un driver de terceros no debe tumbar la captura
            name = getattr(self._driver, "name", type(self._driver).__name__)
            raise FrameReadError(f"Error del driver '{name}': {exc}") from exc
        if not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.size == 0:
            raise FrameReadError("El driver devolvió un frame no válido (se espera uint8 BGR).")
        if image.ndim == 2:
            image = np.repeat(image[:, :, None], 3, axis=2)
        if image.ndim != 3 or image.shape[2] != 3:
            raise FrameReadError(f"El driver devolvió un frame con forma {image.shape}.")
        return image

    def _build_stream_info(self, image: np.ndarray) -> StreamInfo:
        native = getattr(self._driver, "stream_info", None)
        if isinstance(native, StreamInfo):
            return native
        meta = self._driver.metadata()
        nominal = meta.get("fps_nominal")
        return StreamInfo(
            width=int(image.shape[1]),
            height=int(image.shape[0]),
            fps_reported=float(nominal) if is_valid_fps(nominal) else 0.0,
            fourcc=str(meta.get("formato_pixel") or ""),
            backend=str(meta.get("backend") or meta.get("driver") or ""),
            source=str(meta.get("nombre") or meta.get("driver") or ""),
        )

    def _make_frame(self, image: np.ndarray) -> Frame:
        image.flags.writeable = False
        sequence = self._sequence
        self._sequence += 1
        # Archivos: tiempo de medio; cámaras: reloj monotónico.
        timestamp = sequence / self._file_fps if self._is_file else self._clock()
        return Frame(image=image, timestamp=timestamp, sequence=sequence)
