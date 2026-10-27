"""Tipos de frame y utilidades de FPS compartidos por drivers y núcleo de captura."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

FALLBACK_FPS = 30.0
MIN_FPS, MAX_FPS = 1.0, 240.0
_NOMINAL_RATES = (5.0, 10.0, 15.0, 20.0, 24.0, 25.0, 30.0, 50.0, 60.0)


def is_valid_fps(value: float | None) -> bool:
    """``True`` si ``value`` es un FPS plausible (1-240)."""
    return value is not None and MIN_FPS <= value <= MAX_FPS


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
    driver y pueden ser 0/"" si no lo informa; los FPS reales se obtienen con
    :meth:`colpo.capture.CaptureCamera.measure_fps`.
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
