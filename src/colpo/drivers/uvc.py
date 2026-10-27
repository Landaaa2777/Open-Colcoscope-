"""Driver UVC (vía principal del proyecto): cámaras USB Video Class leídas con OpenCV.

El colposcopio se lee con el controlador genérico del sistema operativo
(DirectShow/Media Foundation en Windows, V4L2 en Linux), sin software ni dongle
del fabricante. :class:`UVCCamera` también acepta un archivo de video como
fuente (``source=``), útil para demostraciones y pruebas.

Este driver solo abre, lee y describe el dispositivo. La foto, el video y los
metadatos los gestiona :class:`colpo.capture.CaptureCamera`.
"""

from __future__ import annotations

import logging
import os
import platform
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

import cv2
import numpy as np

from colpo.devices import DeviceInfo, available_backends, list_devices, resolve_backend
from colpo.drivers.base import (
    SOURCE_CAMERA,
    SOURCE_FILE,
    Capabilities,
    base_metadata,
)
from colpo.drivers.errors import (
    CameraBusy,
    CameraDisconnected,
    CameraNotFound,
    FormatNotSupported,
)
from colpo.drivers.profiles import DeviceProfile, find_profile
from colpo.errors import CameraNotOpenError, EndOfStreamError
from colpo.frame import FALLBACK_FPS, StreamInfo, decode_fourcc, is_valid_fps

log = logging.getLogger(__name__)

FILE_BACKEND = "file"


class UVCCamera:
    """Driver ``"uvc"``: cámara UVC (o archivo de video) mediante ``cv2.VideoCapture``.

    Args:
        index: índice de la cámara para ``backend`` (ver ``colpo list``).
        source: archivo de video a usar como fuente (excluyente con ``index``).
        backend: ``"auto"`` (DirectShow en Windows, V4L2 en Linux,
            AVFoundation en macOS), ``"msmf"``, ``"dshow"``, ``"v4l2"``...
        width, height, fps, fourcc: formato solicitado. La cámara puede
            ignorarlo; el formato real queda en :attr:`stream_info`.
        strict_format: si es ``True`` y la cámara no entrega la resolución
            pedida, ``open()`` lanza :class:`FormatNotSupported`.
        warmup_frames: frames descartados tras abrir una cámara para que la
            exposición y el balance de blancos se estabilicen.
        max_read_failures: lecturas fallidas seguidas antes de considerar que
            la cámara se desconectó.
        profile: perfil del dispositivo (ver ``colpo.drivers.profiles``).
        device: ``DeviceInfo`` del que se creó (para ``metadata()``).
        capture_factory: inyección para pruebas (por defecto ``cv2.VideoCapture``).
    """

    name: ClassVar[str] = "uvc"
    display_name: ClassVar[str] = "UVC (OpenCV)"

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
        strict_format: bool = False,
        warmup_frames: int = 5,
        max_read_failures: int = 10,
        profile: DeviceProfile | None = None,
        device: DeviceInfo | None = None,
        capture_factory: Callable[..., cv2.VideoCapture] = cv2.VideoCapture,
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
        self._strict_format = strict_format
        self._warmup_frames = max(0, warmup_frames)
        self._max_read_failures = max(1, max_read_failures)
        self._profile = profile
        self._device = device
        self._capture_factory = capture_factory

        self._cap: cv2.VideoCapture | None = None
        self._info: StreamInfo | None = None
        self._pending: np.ndarray | None = None
        self._failures = 0
        self._connected = False

    # -------------------------------------------------- contrato (de clase)
    @classmethod
    def discover(cls, **options: Any) -> list[DeviceInfo]:
        """Cámaras visibles para la API indicada (``backend=``, por defecto ``auto``)."""
        backend = str(options.get("backend") or "auto")
        devices = list_devices(backend)
        return [
            DeviceInfo(
                index=d.index,
                name=d.name,
                backend=d.backend,
                vendor_id=d.vendor_id,
                product_id=d.product_id,
                path=d.path,
                driver=cls.name,
            )
            for d in devices
        ]

    @classmethod
    def probe(cls, device_info: DeviceInfo) -> bool:
        """Acepta dispositivos enumerados por el SO y archivos de video."""
        if device_info.driver not in (None, cls.name):
            return False
        if device_info.backend == FILE_BACKEND:
            return bool(device_info.path)
        return device_info.backend in ("auto", *available_backends())

    @classmethod
    def for_device(cls, device_info: DeviceInfo, **options: Any) -> UVCCamera:
        """Crea el driver para un dispositivo, aplicando su perfil si existe.

        Opciones: ``backend`` (sustituye la API del dispositivo) y
        ``capture_factory`` (pruebas). Las desconocidas se ignoran.
        """
        factory = options.get("capture_factory", cv2.VideoCapture)
        if device_info.backend == FILE_BACKEND:
            if not device_info.path:
                raise ValueError("Un dispositivo de archivo necesita 'path'.")
            return cls(source=device_info.path, device=device_info, capture_factory=factory)

        profile = find_profile(device_info)
        requested: dict[str, Any] = {}
        if profile and profile.verified_modes:
            mode = profile.verified_modes[0]
            requested = {
                "width": mode.ancho,
                "height": mode.alto,
                "fps": mode.fps,
                "fourcc": mode.formato,
            }
        return cls(
            index=device_info.index,
            backend=str(options.get("backend") or device_info.backend),
            profile=profile,
            device=device_info,
            capture_factory=factory,
            **requested,
        )

    # --------------------------------------------------- contrato (instancia)
    def open(self) -> StreamInfo:
        """Abre la fuente, aplica el formato solicitado y lee el primer frame.

        Raises:
            CameraNotFound: el índice o el archivo no existen.
            CameraBusy: la cámara existe pero no se pudo abrir o no entrega imágenes.
            FormatNotSupported: ``strict_format`` y la resolución no coincide.
            BackendUnavailableError: el backend no existe en esta plataforma.
        """
        if self._info is not None:
            return self._info

        if self._source is not None:
            if not self._source.is_file():
                raise CameraNotFound(f"No existe el archivo de video: {self._source}")
            backend_name, label = FILE_BACKEND, str(self._source)
            cap = self._capture_factory(str(self._source))
        else:
            backend_name, api = resolve_backend(self._backend)
            label = f"index:{self._index}"
            cap = self._capture_factory(self._index, api)

        if not cap.isOpened():
            cap.release()
            raise self._open_failure(backend_name)

        self._cap = cap
        try:
            if self._source is None:
                self._apply_requested_format()
            first = self._read_first_frame()
            height, width = first.shape[:2]
            req_w, req_h = self._requested[0], self._requested[1]
            if req_w is not None and (req_w, req_h) != (width, height):
                if self._strict_format:
                    raise FormatNotSupported(
                        f"Se pidió {req_w}x{req_h} pero la cámara entrega {width}x{height}."
                    )
                log.warning(
                    "Se pidió %sx%s pero la cámara entrega %sx%s.", req_w, req_h, width, height
                )
        except BaseException:
            self._release()
            raise

        self._info = StreamInfo(
            width=int(width),
            height=int(height),
            fps_reported=float(cap.get(cv2.CAP_PROP_FPS) or 0.0),
            fourcc=decode_fourcc(cap.get(cv2.CAP_PROP_FOURCC)),
            backend=backend_name,
            source=label,
        )
        self._pending = first
        self._connected = True
        return self._info

    def close(self) -> None:
        self._release()

    def read_frame(self) -> np.ndarray:
        """Siguiente frame BGR (el primero es el leído al abrir).

        Raises:
            CameraNotOpenError, CameraDisconnected, EndOfStreamError.
        """
        if self._cap is None:
            raise CameraNotOpenError("La cámara no está abierta. Llame a open() primero.")
        if self._pending is not None:
            image, self._pending = self._pending, None
            return image
        while True:
            ok, image = self._cap.read()
            if ok and image is not None and image.size:
                self._failures = 0
                return _to_bgr(image)
            if self._source is not None:
                raise EndOfStreamError("Fin del archivo de video.")
            self._failures += 1
            if self._failures >= self._max_read_failures:
                self._connected = False
                raise CameraDisconnected(
                    f"La cámara dejó de entregar imágenes ({self._failures} lecturas fallidas "
                    "seguidas). ¿Se desconectó el cable USB?"
                )
            time.sleep(0.02)

    def capabilities(self) -> Capabilities:
        """Lo que se sabe del dispositivo: perfil + formato activo.

        OpenCV no permite listar todos los modos de una cámara UVC ni saber de
        forma fiable qué controles tiene; por eso se combinan los datos
        verificados del perfil con el formato realmente entregado.
        """
        resolutions: list[tuple[int, int]] = []
        fps_map: dict[tuple[int, int], list[float]] = {}
        formats: list[str] = []
        if self._profile:
            for mode in self._profile.verified_modes:
                res = (mode.ancho, mode.alto)
                resolutions.append(res)
                fps_map.setdefault(res, []).append(mode.fps)
                formats.append(mode.formato)
        if self._info is not None:
            res = (self._info.width, self._info.height)
            resolutions.append(res)
            fps = self._info.fps_reported
            if is_valid_fps(fps):
                fps_map.setdefault(res, []).append(fps)
            if self._info.fourcc:
                formats.append(self._info.fourcc)
        controls = self._profile.controles if self._profile else {}
        notes = ["OpenCV no lista todos los modos UVC: se muestran los del perfil y el activo."]
        if self._profile:
            notes.append(f"Perfil: {self._profile.nombre}.")
        if self._source is not None:
            notes = ["Archivo de video usado como cámara de demostración."]
        return Capabilities(
            resoluciones_soportadas=tuple(resolutions),
            fps_por_resolucion={r: tuple(dict.fromkeys(f)) for r, f in fps_map.items()},
            formatos_pixel=tuple(formats),
            tiene_control_zoom=controls.get("zoom"),
            tiene_control_brillo=controls.get("brillo"),
            tiene_control_balance_blancos=controls.get("balance_blancos"),
            es_uvc=self._source is None,
            notas=" ".join(notes),
        )

    def metadata(self) -> dict[str, Any]:
        info = self._info
        fps_nominal: float | None = None
        if info is not None and is_valid_fps(info.fps_reported):
            fps_nominal = info.fps_reported
        elif self._source is not None and info is not None:
            fps_nominal = FALLBACK_FPS
        device = self._device or DeviceInfo(
            index=self._index if self._index is not None else 0,
            name=self._source.name if self._source else f"Cámara {self._index}",
            backend=FILE_BACKEND if self._source else self._backend,
        )
        return base_metadata(
            self.name,
            device,
            es_uvc=self._source is None,
            fuente=SOURCE_FILE if self._source is not None else SOURCE_CAMERA,
            backend=info.backend if info else (FILE_BACKEND if self._source else self._backend),
            perfil=self._profile.id if self._profile else None,
            fps_nominal=fps_nominal,
            formato_pixel=info.fourcc if info else None,
            resolucion=(info.width, info.height) if info else None,
        )

    def is_connected(self) -> bool:
        return self._cap is not None and self._connected

    # -------------------------------------------- compatibilidad F1 (sin archivos)
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
    def stream_info(self) -> StreamInfo:
        if self._info is None:
            raise CameraNotOpenError("La cámara no está abierta. Llame a open() primero.")
        return self._info

    def __repr__(self) -> str:
        src = f"source={str(self._source)!r}" if self._source else f"index={self._index}"
        state = "abierta" if self.is_open else "cerrada"
        return f"UVCCamera({src}, backend={self._backend!r}, {state})"

    # ------------------------------------------------------------- internos
    def _release(self) -> None:
        if self._cap is not None:
            self._cap.release()
        self._cap = None
        self._info = None
        self._pending = None
        self._connected = False

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
                return _to_bgr(image)
            if self._source is not None:
                break
            time.sleep(0.05)
        raise CameraBusy(
            "La fuente se abrió pero no entrega imágenes. Si es una cámara, desconéctela y "
            "vuelva a conectarla, cierre otras aplicaciones que la usen o pruebe otro --backend."
        )

    def _open_failure(self, backend: str) -> CameraBusy | CameraNotFound:
        if self._source is not None:
            return CameraBusy(f"OpenCV no pudo abrir el archivo de video: {self._source}")
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
        hint += "Use 'colpo list' para ver los índices o pruebe otro --backend."
        # OpenCV no distingue "no existe" de "ocupada": se consulta la enumeración.
        try:
            known = {d.index for d in list_devices(backend)}
        except Exception:  # sin enumeración no se puede saber
            return CameraBusy(hint)
        return CameraBusy(hint) if self._index in known else CameraNotFound(hint)


def _to_bgr(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    return image
