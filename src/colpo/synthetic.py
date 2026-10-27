"""Imágenes sintéticas (sin personas) para demostraciones, pruebas y el driver simulado.

Cada frame tiene barras de color, un círculo en movimiento y, en la franja
superior, su número codificado en bloques blanco/negro (resistente a la
compresión), para verificar que no se pierden ni se desordenan frames.
"""

from __future__ import annotations

import cv2
import numpy as np

CODE_BITS = 16
BLOCK = 16
MIN_WIDTH = CODE_BITS * BLOCK

# BGR: blanco, amarillo, cian, verde, magenta, rojo, azul, negro.
_BARS = (
    (255, 255, 255),
    (0, 255, 255),
    (255, 255, 0),
    (0, 255, 0),
    (255, 0, 255),
    (0, 0, 255),
    (255, 0, 0),
    (0, 0, 0),
)


def make_frame(index: int, width: int = 640, height: int = 480) -> np.ndarray:
    """Devuelve el frame ``index`` (BGR, uint8)."""
    if width < MIN_WIDTH or height < 4 * BLOCK:
        raise ValueError(f"Tamaño mínimo: {MIN_WIDTH}x{4 * BLOCK}")
    image = np.zeros((height, width, 3), np.uint8)
    bar_width = -(-width // len(_BARS))
    for i, color in enumerate(_BARS):
        image[:, i * bar_width : (i + 1) * bar_width] = color

    radius = max(8, height // 8)
    x = radius + (index * 7) % max(1, width - 2 * radius)
    cv2.circle(image, (x, height // 2), radius, (40, 40, 200), thickness=-1)
    cv2.putText(
        image,
        f"SINTETICO {index:05d}",
        (8, height - 12),
        cv2.FONT_HERSHEY_SIMPLEX,
        max(0.4, height / 600),
        (128, 128, 128),
        2,
        cv2.LINE_AA,
    )
    _encode_index(image, index)
    return image


def _encode_index(image: np.ndarray, index: int) -> None:
    image[: 2 * BLOCK, :] = 0
    for bit in range(CODE_BITS):
        if (index >> bit) & 1:
            image[: 2 * BLOCK, bit * BLOCK : (bit + 1) * BLOCK] = 255


def decode_index(image: np.ndarray) -> int:
    """Lee el número de frame codificado por :func:`make_frame`."""
    value = 0
    margin = BLOCK // 4
    for bit in range(CODE_BITS):
        cell = image[margin : 2 * BLOCK - margin, bit * BLOCK + margin : (bit + 1) * BLOCK - margin]
        if float(cell.mean()) > 127:
            value |= 1 << bit
    return value
