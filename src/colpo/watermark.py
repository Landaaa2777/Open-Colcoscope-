"""Marca de agua opcional (gancho para F3+). **Desactivada por defecto.**

F2 no expone esta opción en la interfaz. :class:`colpo.session.CaptureSession`
la aplica a las fotos solo si se le pasa ``WatermarkOptions(enabled=True)``.
La marca de agua en video queda para F3 (requiere transformar cada frame).
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

DEFAULT_WATERMARK_TEXT = "Uso educativo - no diagnostico"


@dataclass(frozen=True)
class WatermarkOptions:
    enabled: bool = False
    text: str = DEFAULT_WATERMARK_TEXT


WATERMARK_DISABLED = WatermarkOptions()


def apply_watermark(
    image: np.ndarray, options: WatermarkOptions = WATERMARK_DISABLED
) -> np.ndarray:
    """Devuelve ``image`` sin cambios si está desactivada; si no, una copia marcada."""
    if not options.enabled:
        return image
    marked = image.copy()
    height = marked.shape[0]
    scale = max(0.5, height / 900)
    origin = (12, height - 16)
    # Contorno oscuro + texto claro: legible sobre cualquier fondo.
    cv2.putText(
        marked, options.text, origin, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 4, cv2.LINE_AA
    )
    cv2.putText(
        marked,
        options.text,
        origin,
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return marked
