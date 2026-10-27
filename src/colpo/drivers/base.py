"""Contrato de driver de cámara (``CameraDriver``) y descripción de capacidades.

Un **driver** sabe hablar con un tipo de dispositivo y nada más: lo encuentra,
lo abre, entrega frames y describe lo que sabe hacer. Todo lo demás (fotos,
video, metadatos de captura, marca de agua, almacenamiento) lo hace el núcleo
(:class:`colpo.capture.CaptureCamera`) para *cualquier* driver.

Reglas para todo driver:

1. No importa PySide6 ni nada de la interfaz.
2. No escribe archivos ni gestiona almacenamiento: solo devuelve frames y metadatos.
3. No usa la red.
4. No contiene software, firmware ni recursos del fabricante, ni elude
   mecanismos de licencia (dongles). Ver docs/DRIVER_GUIDE.md.

La suite ``tests/test_driver_contract.py`` verifica estas reglas.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol, runtime_checkable

import numpy as np

from colpo.devices import DeviceInfo

Resolution = tuple[int, int]

# Claves estándar de ``CameraDriver.metadata()``. Un driver puede añadir otras,
# pero nunca números de serie, rutas del sistema ni datos de personas.
METADATA_KEYS: tuple[str, ...] = (
    "driver",  # nombre del driver ("uvc", "mock"...)
    "nombre",  # nombre legible del dispositivo
    "vid_pid",  # "VVVV:PPPP" o None
    "es_uvc",  # bool
    "fuente",  # "camara" | "archivo" | "simulada"
    "backend",  # API usada ("dshow", "msmf", "v4l2", "file", "mock"...)
    "perfil",  # id del perfil aplicado o None
    "fps_nominal",  # FPS declarados por el dispositivo/archivo, o None
    "formato_pixel",  # "MJPG", "YUY2"... o None
    "resolucion",  # [ancho, alto] activa (tras open) o None
)
# Claves que un driver jamás debe incluir en ``metadata()``.
FORBIDDEN_METADATA_KEYS: frozenset[str] = frozenset(
    {"serial", "numero_serie", "serial_number", "path", "ruta", "usuario", "user", "paciente"}
)
SOURCE_CAMERA, SOURCE_FILE, SOURCE_SIMULATED = "camara", "archivo", "simulada"


@dataclass(frozen=True)
class Capabilities:
    """Lo que un dispositivo sabe hacer, según lo que el driver puede averiguar.

    Los controles usan ``None`` cuando el driver no puede saberlo (p. ej. OpenCV
    no informa de forma fiable qué controles UVC existen): la UI lo muestra como
    "desconocido" en lugar de afirmar algo falso.
    """

    resoluciones_soportadas: tuple[Resolution, ...] = ()
    fps_por_resolucion: Mapping[Resolution, tuple[float, ...]] = field(default_factory=dict)
    formatos_pixel: tuple[str, ...] = ()
    tiene_control_zoom: bool | None = None
    tiene_control_brillo: bool | None = None
    tiene_control_balance_blancos: bool | None = None
    es_uvc: bool = False
    notas: str = ""

    def __post_init__(self) -> None:
        resolutions = tuple((int(w), int(h)) for w, h in self.resoluciones_soportadas)
        object.__setattr__(self, "resoluciones_soportadas", tuple(dict.fromkeys(resolutions)))
        object.__setattr__(
            self,
            "fps_por_resolucion",
            {
                (int(w), int(h)): tuple(float(f) for f in fps)
                for (w, h), fps in self.fps_por_resolucion.items()
            },
        )
        object.__setattr__(self, "formatos_pixel", tuple(dict.fromkeys(self.formatos_pixel)))
        problems = self.problems()
        if problems:
            raise ValueError("Capabilities incoherentes: " + "; ".join(problems))

    def problems(self) -> list[str]:
        """Lista de incoherencias (vacía si todo está bien)."""
        found = []
        for w, h in self.resoluciones_soportadas:
            if w <= 0 or h <= 0:
                found.append(f"resolución no positiva {w}x{h}")
        for res, fps in self.fps_por_resolucion.items():
            if res not in self.resoluciones_soportadas:
                found.append(f"fps_por_resolucion menciona {res} que no está en la lista")
            if not fps or any(f <= 0 for f in fps):
                found.append(f"fps no válidos para {res}: {fps}")
        for fmt in self.formatos_pixel:
            if not isinstance(fmt, str) or not fmt.strip():
                found.append(f"formato de pixel no válido: {fmt!r}")
        return found

    def to_dict(self) -> dict[str, Any]:
        """Representación serializable (para la UI y diagnósticos)."""
        return {
            "resoluciones_soportadas": [list(r) for r in self.resoluciones_soportadas],
            "fps_por_resolucion": {
                f"{w}x{h}": list(fps) for (w, h), fps in self.fps_por_resolucion.items()
            },
            "formatos_pixel": list(self.formatos_pixel),
            "tiene_control_zoom": self.tiene_control_zoom,
            "tiene_control_brillo": self.tiene_control_brillo,
            "tiene_control_balance_blancos": self.tiene_control_balance_blancos,
            "es_uvc": self.es_uvc,
            "notas": self.notas,
        }


@runtime_checkable
class CameraDriver(Protocol):
    """Contrato que implementa todo driver de cámara.

    Miembros de clase (para que el registro descubra y construya drivers):

    - ``name``: identificador estable y único (``[a-z0-9_-]``), p. ej. ``"uvc"``.
    - ``discover(**options)``: dispositivos que este driver ve ahora mismo.
      Opciones desconocidas se ignoran (la UI pasa p. ej. ``backend=``).
    - ``probe(device_info)``: ``True`` si este driver puede manejar el
      dispositivo. Rápido y sin abrirlo.
    - ``for_device(device_info, **options)``: crea una instancia **sin abrirla**.

    Miembros de instancia:

    - ``open()``: abre el dispositivo. Lanza ``CameraNotFound``, ``CameraBusy``
      o ``FormatNotSupported``.
    - ``close()``: libera el dispositivo. Idempotente; nunca lanza por estar cerrado.
    - ``read_frame()``: siguiente frame como ``ndarray`` BGR ``uint8`` (alto,
      ancho, 3), **nuevo en cada llamada** (no reutilizar buffers). Bloquea como
      mucho unos segundos. Lanza ``CameraNotOpenError`` si no está abierto,
      ``CameraDisconnected`` si el dispositivo dejó de responder y
      ``EndOfStreamError`` si es un archivo que terminó.
    - ``capabilities()``: :class:`Capabilities`; válido antes y después de abrir.
    - ``metadata()``: ``dict`` serializable a JSON con :data:`METADATA_KEYS`.
    - ``is_connected()``: ``True`` si está abierto y entregando frames.
    """

    name: ClassVar[str]

    @classmethod
    def discover(cls, **options: Any) -> list[DeviceInfo]: ...

    @classmethod
    def probe(cls, device_info: DeviceInfo) -> bool: ...

    @classmethod
    def for_device(cls, device_info: DeviceInfo, **options: Any) -> CameraDriver: ...

    def open(self) -> object: ...

    def close(self) -> None: ...

    def read_frame(self) -> np.ndarray: ...

    def capabilities(self) -> Capabilities: ...

    def metadata(self) -> dict[str, Any]: ...

    def is_connected(self) -> bool: ...


DRIVER_CLASS_MEMBERS: tuple[str, ...] = ("discover", "probe", "for_device")
DRIVER_INSTANCE_MEMBERS: tuple[str, ...] = (
    "open",
    "close",
    "read_frame",
    "capabilities",
    "metadata",
    "is_connected",
)


def base_metadata(
    driver: str,
    device: DeviceInfo | None,
    *,
    es_uvc: bool,
    fuente: str,
    backend: str | None = None,
    perfil: str | None = None,
    fps_nominal: float | None = None,
    formato_pixel: str | None = None,
    resolucion: Sequence[int] | None = None,
) -> dict[str, Any]:
    """Construye el diccionario estándar de ``metadata()`` (sin rutas ni seriales)."""
    return {
        "driver": driver,
        "nombre": device.name if device else None,
        "vid_pid": device.vid_pid if device and device.vendor_id is not None else None,
        "es_uvc": es_uvc,
        "fuente": fuente,
        "backend": backend,
        "perfil": perfil,
        "fps_nominal": fps_nominal,
        "formato_pixel": formato_pixel or None,
        "resolucion": list(resolucion) if resolucion else None,
    }
