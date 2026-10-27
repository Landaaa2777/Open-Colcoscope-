"""Enumeración multiplataforma de cámaras UVC.

OpenCV abre cámaras por índice, pero no expone su nombre ni su VID:PID. Para
poder identificar el colposcopio (y en F3 aplicarle un perfil) usamos
``cv2-enumerate-cameras``, que consulta la API nativa de cada SO (DirectShow o
Media Foundation en Windows, V4L2 en Linux, AVFoundation en macOS) y devuelve
los índices en el mismo orden que usa OpenCV para ese backend.

Si esa librería no está disponible o falla, se recurre a probar índices con
OpenCV: más lento y sin nombres ni VID:PID, pero suficiente para capturar.

Este módulo no escribe nada en disco ni accede a la red.
"""

from __future__ import annotations

import logging
import platform
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import cv2

from colpo.errors import BackendUnavailableError

log = logging.getLogger(__name__)

# Nombre de backend (CLI/configuración) -> constante de OpenCV.
_BACKENDS: dict[str, int] = {
    "any": cv2.CAP_ANY,
    "dshow": cv2.CAP_DSHOW,
    "msmf": cv2.CAP_MSMF,
    "v4l2": cv2.CAP_V4L2,
    "avfoundation": cv2.CAP_AVFOUNDATION,
}

_PLATFORM_BACKENDS: dict[str, tuple[str, ...]] = {
    "Windows": ("dshow", "msmf", "any"),
    "Linux": ("v4l2", "any"),
    "Darwin": ("avfoundation", "any"),
}

# Índices que se prueban cuando no hay enumeración nativa.
DEFAULT_PROBE_LIMIT = 8


def available_backends(system: str | None = None) -> tuple[str, ...]:
    """Backends válidos para el SO actual (o el indicado), el preferido primero."""
    return _PLATFORM_BACKENDS.get(system or platform.system(), ("any",))


def default_backend(system: str | None = None) -> str:
    """Backend predeterminado del SO.

    En Windows se prefiere DirectShow: abre las cámaras UVC más rápido que
    Media Foundation en OpenCV y respeta mejor la petición de MJPG/resolución.
    Se puede cambiar con ``--backend msmf`` si un equipo concreto lo requiere.
    """
    return available_backends(system)[0]


def resolve_backend(name: str) -> tuple[str, int]:
    """Convierte ``"auto"``/``"dshow"``/... en ``(nombre, constante OpenCV)``."""
    key = name.lower()
    if key == "auto":
        key = default_backend()
    if key not in available_backends():
        valid = ", ".join(("auto", *available_backends()))
        raise BackendUnavailableError(
            f"El backend '{name}' no está disponible en {platform.system()}. "
            f"Opciones válidas: {valid}."
        )
    return key, _BACKENDS[key]


@dataclass(frozen=True)
class DeviceInfo:
    """Cámara detectada.

    ``index`` es el valor que se pasa a ``UVCCamera(index=..., backend=...)``
    con el mismo ``backend``. ``path`` es la ruta del SO (puede contener
    identificadores de instancia del equipo: no se muestra por defecto).
    """

    index: int
    name: str
    backend: str
    vendor_id: int | None = None
    product_id: int | None = None
    path: str | None = None
    # Nombre del driver que lo descubrió (``"uvc"``, ``"mock"``...). ``None`` en
    # enumeraciones directas del SO (F1/F2), que el driver UVC acepta.
    driver: str | None = None

    @property
    def vid_pid(self) -> str:
        """``"VVVV:PPPP"`` en hexadecimal, o ``"????:????"`` si se desconoce."""
        if self.vendor_id is None or self.product_id is None:
            return "????:????"
        return f"{self.vendor_id:04X}:{self.product_id:04X}"


def _enumerate_native(api: int, backend: str) -> list[DeviceInfo]:
    from cv2_enumerate_cameras import enumerate_cameras

    return [
        DeviceInfo(
            index=int(cam.index),
            name=str(cam.name or f"Cámara {cam.index}"),
            backend=backend,
            vendor_id=cam.vid,
            product_id=cam.pid,
            path=cam.path,
        )
        for cam in enumerate_cameras(api)
    ]


def _enumerate_by_probing(
    api: int,
    backend: str,
    limit: int,
    capture_factory: Callable[..., cv2.VideoCapture],
) -> list[DeviceInfo]:
    found: list[DeviceInfo] = []
    for index in range(limit):
        cap = capture_factory(index, api)
        try:
            if cap.isOpened():
                found.append(DeviceInfo(index=index, name=f"Cámara {index}", backend=backend))
        finally:
            cap.release()
    return found


def list_devices(
    backend: str = "auto",
    *,
    probe_limit: int = DEFAULT_PROBE_LIMIT,
    capture_factory: Callable[..., cv2.VideoCapture] = cv2.VideoCapture,
) -> list[DeviceInfo]:
    """Lista las cámaras visibles para ``backend``.

    Nunca lanza por fallos de la enumeración nativa: registra el motivo y
    recurre al sondeo de índices. Sí lanza :class:`BackendUnavailableError`
    si el backend no existe en esta plataforma.
    """
    name, api = resolve_backend(backend)
    if name != "any":
        try:
            return _enumerate_native(api, name)
        except Exception as exc:  # librería ausente o fallo de la API del SO
            log.warning("Enumeración nativa no disponible (%s); se sondean índices.", exc)
    return _enumerate_by_probing(api, name, probe_limit, capture_factory)


def find_device(devices: Iterable[DeviceInfo], index: int) -> DeviceInfo | None:
    """Devuelve el dispositivo con ese índice, si fue enumerado."""
    return next((d for d in devices if d.index == index), None)
