"""Captura de imagen fija y video desde cámaras UVC mediante OpenCV.

La vía principal del proyecto es **UVC + OpenCV**: el colposcopio se lee con el
controlador genérico del sistema operativo, sin software ni dongle del
fabricante. :class:`UVCCamera` también acepta un archivo de video como fuente
(``source=``), lo que permite probar todo el flujo sin hardware.

Modelo de uso (F1): síncrono y de un solo hilo para la lectura. Quien usa la
clase llama a :meth:`UVCCamera.read_frame` en bucle; si hay una grabación en
curso, cada frame leído se entrega a un hilo escritor con cola acotada, de modo
que la codificación no bloquea la lectura. La clase no es *thread-safe*.
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

import cv2
import numpy as np

from colpo.devices import DeviceInfo, list_devices, resolve_backend
from colpo.errors import (
    CameraNotOpenError,
    ColpoError,
    DeviceDisconnectedError,
    DeviceOpenError,
    EndOfStreamError,
    RecordingError,
    SnapshotError,
    UnsupportedFormatError,
)

log = logging.getLogger(__name__)

# Extensión -> FOURCC. H.264 no se ofrece: las ruedas de OpenCV no lo incluyen
# (licencias/patentes); ver docs/CAPTURE.md.
VIDEO_CODECS: dict[str, str] = {".mp4": "mp4v", ".avi": "MJPG", ".mkv": "MJPG"}
SNAPSHOT_EXTENSIONS: tuple[str, ...] = (".png",)

FALLBACK_FPS = 30.0
_MIN_FPS, _MAX_FPS = 1.0, 240.0


def _valid_fps(value: float | None) -> bool:
    return value is not None and _MIN_FPS <= value <= _MAX_FPS


_NOMINAL_RATES = (5.0, 10.0, 15.0, 20.0, 24.0, 25.0, 30.0, 50.0, 60.0)


def nominal_fps(measured: float, tolerance: float = 0.05) -> float:
    """Redondea un FPS medido (p. ej. 29.7) a la tasa estándar cercana (30).

    Si ninguna está dentro de la tolerancia relativa, devuelve el valor medido
    con dos decimales.
    """
    closest = min(_NOMINAL_RATES, key=lambda rate: abs(measured - rate))
    if abs(measured - closest) <= closest * tolerance:
        return closest
    return round(measured, 2)


def decode_fourcc(value: float) -> str:
    """Convierte el valor numérico de ``CAP_PROP_FOURCC`` en texto (``"MJPG"``)."""
    code = int(value)
    if code <= 0:
        return ""
    text = "".join(chr((code >> (8 * i)) & 0xFF) for i in range(4))
    return text if text.isprintable() else ""


@dataclass(frozen=True)
class StreamInfo:
    """Formato real del stream abierto.

    ``width``/``height`` se miden sobre el primer frame recibido (no son lo que
    el driver dice). ``fps_reported`` y ``fourcc`` son lo que informa el
    backend y pueden ser 0/"" si no lo informa; los FPS reales se obtienen con
    :meth:`UVCCamera.measure_fps`.
    """

    width: int
    height: int
    fps_reported: float
    fourcc: str
    backend: str
    source: str


@dataclass(frozen=True, eq=False)
class Frame:
    """Un frame BGR de 8 bits. ``image`` es de solo lectura.

    ``timestamp`` está en segundos: reloj monotónico para cámaras y tiempo de
    medio (``sequence / fps``) para archivos.
    """

    image: np.ndarray
    timestamp: float
    sequence: int

    @property
    def width(self) -> int:
        return int(self.image.shape[1])

    @property
    def height(self) -> int:
        return int(self.image.shape[0])


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
        codec: str,
        fps: float,
        size: tuple[int, int],
        writer_factory: Callable[..., cv2.VideoWriter],
        queue_size: int,
        block_when_full: bool = False,
    ) -> None:
        self.path = path
        self._block_when_full = block_when_full
        self.tmp_path = path.with_name(f".{path.stem}.recording{path.suffix}")
        self.codec = codec
        self.fps = fps
        self.size = size
        self._max_repeats = max(1, int(self.MAX_GAP_S * fps))

        self._writer = writer_factory(str(self.tmp_path), cv2.VideoWriter_fourcc(*codec), fps, size)
        if not self._writer.isOpened():
            self._writer.release()
            with contextlib.suppress(OSError):
                self.tmp_path.unlink()
            raise RecordingError(
                f"No se pudo crear el video '{path}' con el códec {codec}. "
                "Pruebe la extensión .avi (MJPEG). En Windows, OpenCV puede fallar con rutas "
                "que contienen caracteres no ASCII (tildes, ñ)."
            )

        self._queue: queue.Queue[tuple[np.ndarray, int] | None] = queue.Queue(maxsize=queue_size)
        self._error: BaseException | None = None
        self._t0: float | None = None
        self._slots = 0
        self.received = self.written = self.skipped = self.dropped = 0
        self._started = time.monotonic()
        self._thread = threading.Thread(target=self._run, name="colpo-recorder", daemon=True)
        self._thread.start()

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

        image = frame.image
        if (image.shape[1], image.shape[0]) != self.size:
            image = cv2.resize(image, self.size, interpolation=cv2.INTER_AREA)

        if self._t0 is None:
            self._t0 = frame.timestamp
        elapsed = max(0.0, frame.timestamp - self._t0)
        # Cantidad de frames que el video debería tener tras este instante.
        target = int(elapsed * self.fps + 1e-6) + 1
        repeats = target - self._slots
        if repeats <= 0:
            self.skipped += 1
            return
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


class UVCCamera:
    """Cámara UVC (o archivo de video) con vista de frames, foto y grabación.

    Ejemplo::

        with UVCCamera(index=0) as cam:
            print(cam.stream_info, cam.measure_fps())
            cam.snapshot("foto.png")
            cam.start_recording("video.mp4")
            for _ in range(150):
                cam.read_frame()
            stats = cam.stop_recording()

    Args:
        index: índice de la cámara para ``backend`` (ver ``colpo list``).
        source: archivo de video a usar como fuente (excluyente con ``index``).
        backend: ``"auto"`` (DirectShow en Windows, V4L2 en Linux,
            AVFoundation en macOS), ``"msmf"``, ``"dshow"``, ``"v4l2"``...
        width, height, fps, fourcc: formato solicitado. El driver puede
            ignorarlo; el formato real queda en :attr:`stream_info`.
        warmup_frames: frames descartados tras abrir una cámara para que la
            exposición y el balance de blancos se estabilicen.
        max_read_failures: lecturas fallidas seguidas antes de considerar que
            la cámara se desconectó.
        capture_factory, writer_factory, clock: inyección para pruebas.
    """

    def __init__(
        self,
        index: int | None = None,
        *,
        source: str | os.PathLike[str] | None = None,
        backend: str = "auto",
        width: int | None = None,
        height: int | None = None,
        fps: float | None = None,
        fourcc: str | None = None,
        warmup_frames: int = 5,
        max_read_failures: int = 10,
        capture_factory: Callable[..., cv2.VideoCapture] = cv2.VideoCapture,
        writer_factory: Callable[..., cv2.VideoWriter] = cv2.VideoWriter,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if (index is None) == (source is None):
            raise ValueError("Indique exactamente uno: 'index' (cámara) o 'source' (archivo).")
        if index is not None and index < 0:
            raise ValueError("'index' debe ser >= 0.")
        if fourcc is not None and len(fourcc) != 4:
            raise ValueError("'fourcc' debe tener 4 caracteres, p. ej. 'MJPG'.")
        if (width is None) != (height is None):
            raise ValueError("Indique 'width' y 'height' juntos.")

        self._index = index
        self._source = Path(source) if source is not None else None
        self._backend = backend
        self._requested = (width, height, fps, fourcc)
        self._warmup_frames = max(0, warmup_frames)
        self._max_read_failures = max(1, max_read_failures)
        self._capture_factory = capture_factory
        self._writer_factory = writer_factory
        self._clock = clock

        self._cap: cv2.VideoCapture | None = None
        self._info: StreamInfo | None = None
        self._pending: Frame | None = None
        self._last_frame: Frame | None = None
        self._recorder: _VideoRecorder | None = None
        self._sequence = 0
        self._failures = 0
        self._file_fps = FALLBACK_FPS
        self._measured_fps: float | None = None

    # ------------------------------------------------------------------ info
    @staticmethod
    def list_devices(backend: str = "auto") -> list[DeviceInfo]:
        """Atajo de :func:`colpo.devices.list_devices`."""
        return list_devices(backend)

    @property
    def is_file_source(self) -> bool:
        return self._source is not None

    @property
    def is_open(self) -> bool:
        return self._cap is not None

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
        """Último frame entregado por :meth:`read_frame` (o ``None``)."""
        return self._last_frame

    @property
    def measured_fps(self) -> float | None:
        """FPS reales medidos con :meth:`measure_fps` (``None`` si no se midió)."""
        return self._measured_fps

    def __repr__(self) -> str:
        src = f"source={str(self._source)!r}" if self._source else f"index={self._index}"
        state = "abierta" if self.is_open else "cerrada"
        return f"UVCCamera({src}, backend={self._backend!r}, {state})"

    # -------------------------------------------------------- ciclo de vida
    def __enter__(self) -> UVCCamera:
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
        """Abre la fuente, aplica el formato solicitado y lee el primer frame.

        Raises:
            DeviceOpenError: la cámara/archivo no se puede abrir o no entrega imágenes.
            BackendUnavailableError: el backend no existe en esta plataforma.
        """
        if self._info is not None:
            return self._info

        if self._source is not None:
            if not self._source.is_file():
                raise DeviceOpenError(f"No existe el archivo de video: {self._source}")
            backend_name, label = "file", str(self._source)
            cap = self._capture_factory(str(self._source))
        else:
            backend_name, api = resolve_backend(self._backend)
            label = f"index:{self._index}"
            cap = self._capture_factory(self._index, api)

        if not cap.isOpened():
            cap.release()
            raise DeviceOpenError(self._open_failure_message(backend_name))

        self._cap = cap
        try:
            if self._source is None:
                self._apply_requested_format()
            else:
                reported = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
                self._file_fps = reported if _valid_fps(reported) else FALLBACK_FPS
            first = self._read_first_frame()
        except BaseException:
            self._release()
            raise

        height, width = first.shape[:2]
        self._info = StreamInfo(
            width=int(width),
            height=int(height),
            fps_reported=float(cap.get(cv2.CAP_PROP_FPS) or 0.0),
            fourcc=decode_fourcc(cap.get(cv2.CAP_PROP_FOURCC)),
            backend=backend_name,
            source=label,
        )
        req_w, req_h = self._requested[0], self._requested[1]
        if req_w is not None and (req_w, req_h) != (width, height):
            log.warning("Se pidió %sx%s pero la cámara entrega %sx%s.", req_w, req_h, width, height)
        self._pending = self._make_frame(first)
        return self._info

    def close(self) -> RecordingStats | None:
        """Finaliza una grabación en curso (si la hay) y libera la cámara."""
        stats = None
        try:
            if self._recorder is not None:
                stats = self.stop_recording()
        finally:
            self._release()
        return stats

    # --------------------------------------------------------------- frames
    def read_frame(self) -> Frame:
        """Devuelve el siguiente frame y, si se está grabando, lo envía al video.

        Raises:
            CameraNotOpenError: la cámara no está abierta.
            DeviceDisconnectedError: la cámara dejó de entregar frames.
            EndOfStreamError: la fuente de archivo terminó.
            RecordingError: el hilo de grabación falló.
        """
        self._require_open()
        if self._pending is not None:
            frame, self._pending = self._pending, None
        else:
            frame = self._read_next()
        self._last_frame = frame
        if self._recorder is not None:
            self._recorder.submit(frame)
        return frame

    def measure_fps(self, frames: int = 30) -> float:
        """Mide los FPS reales leyendo ``frames`` frames (cámaras).

        Para archivos devuelve los FPS declarados por el archivo.
        """
        self._require_open()
        if self._source is not None:
            self._measured_fps = self._file_fps
            return self._file_fps
        if frames < 1:
            raise ValueError("'frames' debe ser >= 1.")
        if self._pending is not None:
            self.read_frame()  # el frame pendiente es antiguo: no sirve de referencia
        start = self.read_frame().timestamp
        end = start
        for _ in range(frames):
            end = self.read_frame().timestamp
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
            frame = self.read_frame()

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
    ) -> Path:
        """Empieza a grabar los frames que se lean con :meth:`read_frame`.

        ``fps`` por defecto: los medidos con :meth:`measure_fps` (redondeados
        con :func:`nominal_fps`), si no los informados por el driver o el
        archivo, y si no son válidos, 30. ``queue_size`` limita los frames en
        espera de codificación (~1 s a 30 FPS; a 1080p cada frame ocupa ~6 MB).

        Raises:
            UnsupportedFormatError: extensión distinta de .mp4, .avi o .mkv.
            RecordingError: ya se está grabando, el archivo existe o no se puede crear.
        """
        self._require_open()
        if self._recorder is not None:
            raise RecordingError("Ya hay una grabación en curso.")
        target = Path(path)
        codec = VIDEO_CODECS.get(target.suffix.lower())
        if codec is None:
            valid = ", ".join(VIDEO_CODECS)
            raise UnsupportedFormatError(
                f"Formato de video no soportado: '{target.suffix}'. Use {valid}."
            )
        if target.exists() and not overwrite:
            raise RecordingError(f"El archivo ya existe: {target}")

        if fps is not None and not _valid_fps(fps):
            raise RecordingError(f"FPS fuera de rango ({_MIN_FPS:g}-{_MAX_FPS:g}): {fps}")

        info = self.stream_info
        if fps is not None:
            chosen = float(fps)
        elif _valid_fps(self._measured_fps):
            assert self._measured_fps is not None
            chosen = nominal_fps(self._measured_fps)
        elif self._source is not None:
            chosen = self._file_fps
        elif _valid_fps(info.fps_reported):
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
            codec,
            chosen,
            (info.width, info.height),
            self._writer_factory,
            queue_size,
            block_when_full=self._source is not None,
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
        if self._cap is None:
            raise CameraNotOpenError("La cámara no está abierta. Llame a open() primero.")

    def _release(self) -> None:
        if self._cap is not None:
            self._cap.release()
        self._cap = None
        self._info = None
        self._pending = None

    def _apply_requested_format(self) -> None:
        assert self._cap is not None
        width, height, fps, fourcc = self._requested
        # En DirectShow el FOURCC debe fijarse antes que la resolución.
        if fourcc is not None:
            self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
        if width is not None and height is not None:
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        if fps is not None:
            self._cap.set(cv2.CAP_PROP_FPS, fps)

    def _read_first_frame(self) -> np.ndarray:
        assert self._cap is not None
        if self._source is None:
            for _ in range(self._warmup_frames):
                self._cap.read()
        for _ in range(self._max_read_failures):
            ok, image = self._cap.read()
            if ok and image is not None and image.size:
                return image
            if self._source is not None:
                break
            time.sleep(0.05)
        raise DeviceOpenError(
            "La fuente se abrió pero no entrega imágenes. Si es una cámara, desconéctela y "
            "vuelva a conectarla, cierre otras aplicaciones que la usen o pruebe otro --backend."
        )

    def _read_next(self) -> Frame:
        assert self._cap is not None
        while True:
            ok, image = self._cap.read()
            if ok and image is not None and image.size:
                self._failures = 0
                return self._make_frame(image)
            if self._source is not None:
                raise EndOfStreamError("Fin del archivo de video.")
            self._failures += 1
            if self._failures >= self._max_read_failures:
                raise DeviceDisconnectedError(
                    f"La cámara dejó de entregar imágenes ({self._failures} lecturas fallidas "
                    "seguidas). ¿Se desconectó el cable USB?"
                )
            time.sleep(0.02)

    def _make_frame(self, image: np.ndarray) -> Frame:
        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        image.flags.writeable = False
        sequence = self._sequence
        self._sequence += 1
        # Archivos: tiempo de medio; cámaras: reloj monotónico.
        timestamp = sequence / self._file_fps if self._source is not None else self._clock()
        return Frame(image=image, timestamp=timestamp, sequence=sequence)

    def _open_failure_message(self, backend: str) -> str:
        if self._source is not None:
            return f"OpenCV no pudo abrir el archivo de video: {self._source}"
        hint = (
            f"No se pudo abrir la cámara con índice {self._index} (backend {backend}). "
            "Compruebe que el cable USB esté conectado y que ninguna otra aplicación "
            "(app Cámara, software del fabricante, videollamadas) la esté usando. "
        )
        if platform.system() == "Windows":
            hint += (
                "Verifique que Windows permita el acceso de aplicaciones de escritorio a la "
                "cámara (Configuración > Privacidad y seguridad > Cámara). "
            )
        elif platform.system() == "Linux":
            hint += "Verifique que su usuario pertenezca al grupo 'video'. "
        return hint + "Use 'colpo list' para ver los índices o pruebe otro --backend."
