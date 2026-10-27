"""Sesión de captura: estudio anónimo, etapa IFCPC, notas, fotos y videos con metadatos.

Une :class:`~colpo.capture.UVCCamera` (F1, sin cambios de contrato) con el
almacenamiento y los metadatos. Toda la lógica de guardado vive aquí; la UI solo
llama a estos métodos.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from colpo import storage
from colpo.capture import CaptureCamera
from colpo.errors import (
    ColpoError,
    DiskFullError,
    MetadataError,
    NotesRejectedError,
    RecordingError,
    SnapshotError,
)
from colpo.frame import Frame, is_valid_fps, nominal_fps
from colpo.metadata import (
    DEFAULT_STAGE,
    IFCPC_STAGES,
    CaptureMetadata,
    capture_timestamp,
    clean_notes,
    new_study_id,
    sha256_file,
    write_sidecar,
)
from colpo.watermark import WATERMARK_DISABLED, WatermarkOptions, apply_watermark


@dataclass(frozen=True)
class CaptureResult:
    """Una captura guardada: archivo, su JSON y los metadatos escritos."""

    media_path: Path
    metadata_path: Path
    metadata: CaptureMetadata
    codec: str | None = None
    frames_dropped: int = 0


@dataclass(frozen=True)
class _PendingVideo:
    path: Path
    timestamp: str
    study_id: str
    stage: str
    notes: str | None
    width: int
    height: int


class CaptureSession:
    """Estado de captura compartido entre la UI y los hilos de adquisición.

    Una sesión puede alimentarse de **varias cámaras a la vez** (p. ej. el
    colposcopio y una capturadora externa): cada una puede tener su propia
    grabación en curso, y ``tag`` distingue sus archivos (``foto_<hora>_uvc0.png``).

    Las propiedades ``stage``, ``notes`` y ``watermark`` se pueden cambiar desde
    el hilo de la UI mientras se captura: son asignaciones atómicas de valores
    inmutables. Los métodos que reciben ``camera`` deben llamarse desde el hilo
    que es dueño de esa cámara (ver :class:`colpo.live.LiveCapture`).
    """

    def __init__(
        self,
        data_dir: str | Path,
        *,
        watermark: WatermarkOptions = WATERMARK_DISABLED,
        now: Callable[[], datetime] = datetime.now,
        free_bytes: Callable[[Path], int] = storage.free_bytes,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.watermark = watermark
        self._now = now
        self._free_bytes = free_bytes
        self._study_id = new_study_id()
        self._stage = DEFAULT_STAGE
        self._notes: str | None = None
        self._videos: dict[int, _PendingVideo] = {}

    # -------------------------------------------------------------- estado
    @property
    def study_id(self) -> str:
        return self._study_id

    @property
    def study_dir(self) -> Path:
        return self.data_dir / self._study_id

    def new_study(self) -> str:
        """Empieza un estudio nuevo con otro seudónimo aleatorio."""
        if self.is_recording:
            raise RecordingError("Detenga las grabaciones antes de empezar un estudio nuevo.")
        self._study_id = new_study_id()
        return self._study_id

    @property
    def stage(self) -> str:
        return self._stage

    @stage.setter
    def stage(self, value: str) -> None:
        if value not in IFCPC_STAGES:
            raise MetadataError(f"Etapa IFCPC no válida: {value!r}")
        self._stage = value

    @property
    def notes(self) -> str | None:
        return self._notes

    def set_notes(self, text: str | None) -> str | None:
        """Valida y guarda las notas para las próximas capturas.

        Si se rechazan (:class:`NotesRejectedError`), las notas quedan vacías: nunca
        se guarda texto sospechoso de contener datos de la paciente.
        """
        try:
            self._notes = clean_notes(text)
        except NotesRejectedError:
            self._notes = None
            raise
        return self._notes

    @property
    def is_recording(self) -> bool:
        """``True`` si alguna cámara está grabando para esta sesión."""
        return bool(self._videos)

    def is_recording_on(self, camera: CaptureCamera) -> bool:
        return id(camera) in self._videos

    # --------------------------------------------------------------- fotos
    def take_photo(
        self, camera: CaptureCamera, *, fps: float | None = None, tag: str | None = None
    ) -> CaptureResult:
        """Guarda el último frame mostrado como PNG + JSON en la carpeta del estudio.

        Si la marca de agua está activada, se aplica a la foto guardada (no al
        frame en memoria ni a la vista previa).

        Raises:
            DiskFullError, SnapshotError, MetadataError, CameraNotOpenError.
        """
        frame = camera.last_frame or camera.read()
        self._ensure_space(storage.MIN_FREE_PHOTO_BYTES)
        timestamp = capture_timestamp(self._now())
        # Cada cámara usa su ``tag``: dos cámaras en el mismo segundo no comparten nombre.
        path = storage.capture_path(self.study_dir, "foto", timestamp, ".png", tag=tag)

        image = apply_watermark(frame.image, self.watermark)
        if image is not frame.image:
            frame = Frame(image=image, timestamp=frame.timestamp, sequence=frame.sequence)
        try:
            camera.snapshot(path, frame=frame)
        except SnapshotError as exc:
            self._raise_if_disk_full(exc)
            raise

        metadata = CaptureMetadata(
            id_estudio=self._study_id,
            timestamp=timestamp,
            etapa_ifcpc=self._stage,
            ancho=frame.width,
            alto=frame.height,
            fps=self._photo_fps(camera, fps),
            tipo="foto",
            sha256=sha256_file(path),
            notas=self._notes,
        )
        return CaptureResult(path, self._write_metadata(path, metadata), metadata)

    # --------------------------------------------------------------- video
    def start_video(
        self, camera: CaptureCamera, *, fps: float | None = None, tag: str | None = None
    ) -> Path:
        """Empieza a grabar un MP4 de ``camera`` en la carpeta del estudio.

        La etapa, las notas y la marca de agua que se aplican son las vigentes
        **al iniciar**. ``fps`` (p. ej. los medidos en vivo) se redondea a la tasa
        estándar cercana.
        """
        if self.is_recording_on(camera):
            raise RecordingError("Esta cámara ya está grabando.")
        self._ensure_space(storage.MIN_FREE_VIDEO_START_BYTES)
        timestamp = capture_timestamp(self._now())
        path = storage.capture_path(self.study_dir, "video", timestamp, ".mp4", tag=tag)
        record_fps = nominal_fps(fps) if fps is not None and is_valid_fps(fps) else None
        watermark = self.watermark
        transform = (lambda image: apply_watermark(image, watermark)) if watermark.enabled else None
        camera.start_recording(path, fps=record_fps, frame_transform=transform)
        info = camera.stream_info
        self._videos[id(camera)] = _PendingVideo(
            path=path,
            timestamp=timestamp,
            study_id=self._study_id,
            stage=self._stage,
            notes=self._notes,
            width=info.width,
            height=info.height,
        )
        return path

    def stop_video(self, camera: CaptureCamera) -> CaptureResult:
        """Cierra el video de ``camera``, calcula su SHA-256 y escribe el JSON.

        Raises:
            RecordingError: no había grabación o falló el cierre (``DiskFullError``
                si la causa fue falta de espacio).
        """
        pending = self._videos.pop(id(camera), None)
        if pending is None:
            raise RecordingError("No hay ninguna grabación en curso.")
        try:
            stats = camera.stop_recording()
        except RecordingError as exc:
            self._raise_if_disk_full(exc)
            raise

        metadata = CaptureMetadata(
            id_estudio=pending.study_id,
            timestamp=pending.timestamp,
            etapa_ifcpc=pending.stage,
            ancho=pending.width,
            alto=pending.height,
            fps=stats.fps,
            tipo="video",
            sha256=sha256_file(stats.path),
            notas=pending.notes,
        )
        return CaptureResult(
            stats.path,
            self._write_metadata(stats.path, metadata),
            metadata,
            codec=stats.codec,
            frames_dropped=stats.frames_dropped,
        )

    def check_recording_space(self) -> None:
        """Lanza :class:`DiskFullError` si el espacio libre no permite seguir grabando."""
        self._ensure_space(storage.MIN_FREE_VIDEO_CONTINUE_BYTES)

    # ------------------------------------------------------------ internos
    def _ensure_space(self, required: int) -> None:
        available = self._free_bytes(self.data_dir)
        if available < required:
            raise DiskFullError(
                f"Espacio insuficiente en disco: quedan {available // storage.MB} MB y se "
                f"necesitan al menos {required // storage.MB} MB."
            )

    @staticmethod
    def _raise_if_disk_full(exc: ColpoError) -> None:
        if storage.is_disk_full_error(exc):
            raise DiskFullError(f"Disco lleno: {exc}") from exc

    def _write_metadata(self, media_path: Path, metadata: CaptureMetadata) -> Path:
        try:
            return write_sidecar(media_path, metadata)
        except OSError as exc:
            if storage.is_disk_full_error(exc):
                raise DiskFullError(f"Disco lleno al escribir los metadatos: {exc}") from exc
            raise MetadataError(f"No se pudieron escribir los metadatos: {exc}") from exc

    @staticmethod
    def _photo_fps(camera: CaptureCamera, fps: float | None) -> float:
        for candidate in (fps, camera.measured_fps, camera.stream_info.fps_reported):
            if candidate is not None and is_valid_fps(candidate):
                return candidate
        return 0.0
