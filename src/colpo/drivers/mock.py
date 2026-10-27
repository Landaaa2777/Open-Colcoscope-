"""Driver simulado: **ejemplo de referencia para escribir un driver nuevo**.

Si vas a añadir soporte para otro dispositivo, copia este archivo y sustituye
la parte "simulada" por la comunicación real con tu equipo. Todo lo demás
(fotos, video, metadatos, marca de agua, UI) ya lo hace el núcleo.

Este driver:

- entrega video sintético (barras de color y número de frame, sin personas);
- puede simular una cámara **ocupada**, **inexistente** o que se **desconecta**;
- por defecto no anuncia dispositivos; ``colpo-ui --demo`` (o la variable de
  entorno ``COLPO_MOCK_DEVICES=2``) hace que aparezcan cámaras simuladas.

Reglas que cumple (y que tu driver también debe cumplir, ver docs/DRIVER_GUIDE.md):
no importa PySide6, no escribe archivos, no usa la red y no contiene nada del
software ni del dongle de ningún fabricante.
"""

from __future__ import annotations

import os
import time
from typing import Any, ClassVar

import numpy as np

from colpo.devices import DeviceInfo
from colpo.drivers.base import SOURCE_SIMULATED, Capabilities, base_metadata
from colpo.drivers.errors import (
    CameraBusy,
    CameraDisconnected,
    CameraNotFound,
    FormatNotSupported,
)
from colpo.errors import CameraNotOpenError
from colpo.synthetic import make_frame

DEMO_ENV = "COLPO_MOCK_DEVICES"
_UNSET: Any = object()


class MockDriver:
    """Cámara simulada que cumple el contrato ``CameraDriver``."""

    # --- 1. Identidad -------------------------------------------------------
    # ``name`` es la clave en el registro y en pyproject.toml:
    #   [project.entry-points."colpo.drivers"]
    #   mock = "colpo.drivers.mock:MockDriver"
    name: ClassVar[str] = "mock"
    # Texto que la UI muestra como cabecera de grupo en el selector.
    display_name: ClassVar[str] = "Simulado (demostración)"

    # --- 2. Lo que el "hardware" sabe hacer --------------------------------
    # Un driver real obtendría esto del dispositivo o de su documentación.
    MODES: ClassVar[dict[tuple[int, int], tuple[float, ...]]] = {
        (640, 480): (30.0, 15.0),
        (320, 240): (30.0,),
    }
    PIXEL_FORMAT: ClassVar[str] = "BGR3"

    # --- 3. Ajustes de simulación (las pruebas crean subclases que los cambian)
    device_count: ClassVar[int | None] = None  # None: leer COLPO_MOCK_DEVICES
    simulate_busy: ClassVar[bool] = False
    simulate_not_found: ClassVar[bool] = False
    disconnect_after: ClassVar[int | None] = None  # nº de frames antes de "desconectarse"
    realtime: ClassVar[bool] = True  # esperar entre frames como una cámara real

    def __init__(
        self,
        device: DeviceInfo | None = None,
        *,
        resolution: tuple[int, int] = (640, 480),
        fps: float = 30.0,
        busy: bool = _UNSET,
        not_found: bool = _UNSET,
        disconnect_after: int | None = _UNSET,
        realtime: bool = _UNSET,
    ) -> None:
        # El constructor NO abre el dispositivo: solo guarda la configuración.
        cls = type(self)
        self._device = device or DeviceInfo(
            index=0, name="Cámara simulada 1", backend="mock", driver=cls.name
        )
        self._resolution = (int(resolution[0]), int(resolution[1]))
        self._fps = float(fps)
        self._busy = cls.simulate_busy if busy is _UNSET else busy
        self._not_found = cls.simulate_not_found if not_found is _UNSET else not_found
        self._disconnect_after = (
            cls.disconnect_after if disconnect_after is _UNSET else disconnect_after
        )
        self._realtime = cls.realtime if realtime is _UNSET else realtime
        self._open = False
        self._connected = False
        self._count = 0
        self._next_due = 0.0

    # --- 4. Descubrimiento y construcción (métodos de clase) ----------------
    @classmethod
    def discover(cls, **options: Any) -> list[DeviceInfo]:
        """Dispositivos visibles. Un driver real preguntaría al SO o al SDK."""
        count = cls.device_count
        if count is None:
            try:
                count = int(os.environ.get(DEMO_ENV, "0") or 0)
            except ValueError:
                count = 0
        return [
            DeviceInfo(index=i, name=f"Cámara simulada {i + 1}", backend="mock", driver=cls.name)
            for i in range(max(0, count))
        ]

    @classmethod
    def probe(cls, device_info: DeviceInfo) -> bool:
        """¿Puedo manejar este dispositivo? Debe ser rápido y no abrir nada."""
        return device_info.driver == cls.name

    @classmethod
    def for_device(cls, device_info: DeviceInfo, **options: Any) -> MockDriver:
        """Crea una instancia sin abrirla. Las opciones desconocidas se ignoran."""
        return cls(
            device_info,
            resolution=options.get("resolution", (640, 480)),
            fps=options.get("fps", 30.0),
        )

    # --- 5. Ciclo de vida ----------------------------------------------------
    def open(self) -> None:
        """Abre el dispositivo o lanza el error de dominio que corresponda."""
        if self._open:
            return
        if self._not_found:
            raise CameraNotFound(f"No se encontró '{self._device.name}' (simulado).")
        if self._busy:
            raise CameraBusy(f"'{self._device.name}' está en uso por otra aplicación (simulado).")
        supported = self.MODES.get(self._resolution)
        if supported is None or self._fps not in supported:
            w, h = self._resolution
            raise FormatNotSupported(f"Modo no soportado: {w}x{h} a {self._fps:g} FPS.")
        self._open = True
        self._connected = True
        self._count = 0
        self._next_due = time.monotonic()

    def close(self) -> None:
        """Libera el dispositivo. Idempotente: cerrar dos veces no es un error."""
        self._open = False
        self._connected = False

    def read_frame(self) -> np.ndarray:
        """Devuelve un frame nuevo (``uint8`` BGR, alto x ancho x 3)."""
        if not self._open:
            raise CameraNotOpenError("La cámara simulada no está abierta.")
        if self._disconnect_after is not None and self._count >= self._disconnect_after:
            self._connected = False
            raise CameraDisconnected(f"'{self._device.name}' se desconectó (simulado).")
        if self._realtime:  # un dispositivo real bloquea hasta tener el siguiente frame
            delay = self._next_due - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self._next_due = max(self._next_due, time.monotonic()) + 1.0 / self._fps
        frame = make_frame(self._count, *self._resolution)
        self._count += 1
        return frame

    # --- 6. Descripción ------------------------------------------------------
    def capabilities(self) -> Capabilities:
        return Capabilities(
            resoluciones_soportadas=tuple(self.MODES),
            fps_por_resolucion=self.MODES,
            formatos_pixel=(self.PIXEL_FORMAT,),
            tiene_control_zoom=False,
            tiene_control_brillo=False,
            tiene_control_balance_blancos=False,
            es_uvc=False,
            notas="Cámara simulada con video sintético (sin hardware).",
        )

    def metadata(self) -> dict[str, Any]:
        # Nunca incluir números de serie, rutas del sistema ni datos de personas.
        return base_metadata(
            self.name,
            self._device,
            es_uvc=False,
            fuente=SOURCE_SIMULATED,
            backend="mock",
            fps_nominal=self._fps,
            formato_pixel=self.PIXEL_FORMAT,
            resolucion=self._resolution if self._open else None,
        )

    def is_connected(self) -> bool:
        return self._open and self._connected

    def __repr__(self) -> str:
        return f"MockDriver({self._device.name!r}, {'abierta' if self._open else 'cerrada'})"
