"""Drivers de cámara: contrato, errores de dominio, registro y perfiles.

- :mod:`colpo.drivers.base` — contrato ``CameraDriver`` y ``Capabilities``.
- :mod:`colpo.drivers.errors` — ``CameraNotFound``, ``CameraBusy``, ``CameraDisconnected``,
  ``FormatNotSupported``.
- :mod:`colpo.drivers.registry` — descubrimiento por *entry points* ``colpo.drivers``.
- :mod:`colpo.drivers.profiles` — perfiles JSON por VID:PID.
- :mod:`colpo.drivers.uvc` — driver UVC (OpenCV), vía principal.
- :mod:`colpo.drivers.mock` — driver simulado, ejemplo de referencia.

Guía para escribir un driver: docs/DRIVER_GUIDE.md.
"""

from colpo.drivers.base import CameraDriver, Capabilities
from colpo.drivers.errors import (
    CameraBusy,
    CameraDisconnected,
    CameraNotFound,
    DriverContractError,
    DriverError,
    FormatNotSupported,
)

__all__ = [
    "CameraBusy",
    "CameraDisconnected",
    "CameraDriver",
    "CameraNotFound",
    "Capabilities",
    "DriverContractError",
    "DriverError",
    "FormatNotSupported",
]
