"""MockDriver: cámaras simuladas para probar la UI y el hilo de captura sin hardware.

Se enchufa a los puntos de inyección existentes del núcleo (``list_devices`` y la
``capture_factory`` de ``UVCCamera``), sin cambiar ningún contrato de F1.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from colpo import DeviceInfo, UVCCamera
from conftest import FakeCapture


class MockCapture(FakeCapture):
    """``FakeCapture`` que entrega frames al ritmo de una cámara real."""

    def read(self):
        time.sleep(1 / self.props_fps)
        return super().read()

    @property
    def props_fps(self) -> float:
        import cv2

        return self.props.get(cv2.CAP_PROP_FPS) or 30.0


class MockDriver:
    """Lista de cámaras simuladas + fábrica de ``UVCCamera`` que las "abre".

    Args:
        names: nombres de los dispositivos simulados (índices 0, 1, ...).
        busy: la cámara no se puede abrir (ocupada por otra app o inexistente).
        fail_after: la cámara deja de entregar frames tras N lecturas (desconexión).
        writer_factory: escritor de video alternativo (p. ej. uno que falla).
    """

    def __init__(
        self,
        *,
        names: tuple[str, ...] = ("GOLDCARE GC 3000E (simulada)", "Webcam integrada (simulada)"),
        size: tuple[int, int] = (320, 240),
        fps: float = 30.0,
        busy: bool = False,
        fail_after: int | None = None,
        writer_factory: Callable[..., object] | None = None,
    ) -> None:
        self.names = names
        self.size = size
        self.fps = fps
        self.busy = busy
        self.fail_after = fail_after
        self.writer_factory = writer_factory
        self.opened: list[MockCapture] = []

    def list_devices(self, backend: str = "auto") -> list[DeviceInfo]:
        return [
            DeviceInfo(index=i, name=name, backend="auto", vendor_id=0x1234, product_id=0x5678 + i)
            for i, name in enumerate(self.names)
        ]

    def camera_factory(self, device: DeviceInfo) -> UVCCamera:
        def capture_factory(*_args: object) -> MockCapture:
            capture = MockCapture(
                opened=not self.busy, fail_after=self.fail_after, size=self.size, fps=self.fps
            )
            self.opened.append(capture)
            return capture

        kwargs: dict[str, object] = {
            "capture_factory": capture_factory,
            "warmup_frames": 0,
            "max_read_failures": 2,
        }
        if self.writer_factory is not None:
            kwargs["writer_factory"] = self.writer_factory
        return UVCCamera(index=device.index, backend=device.backend, **kwargs)
