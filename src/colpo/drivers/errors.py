"""Excepciones del dominio de drivers.

Heredan de las excepciones del núcleo para que el código existente (CLI, UI,
``LiveCapture``) las trate sin cambios: ``CameraNotFound`` y ``CameraBusy``
son errores de apertura, ``CameraDisconnected`` es una desconexión.
"""

from __future__ import annotations

from colpo.errors import ColpoError, DeviceDisconnectedError, DeviceOpenError


class DriverError(ColpoError):
    """Base de los errores que un driver puede lanzar."""


class CameraNotFound(DriverError, DeviceOpenError):
    """El dispositivo no existe (desenchufado, índice o archivo inexistente)."""


class CameraBusy(DriverError, DeviceOpenError):
    """El dispositivo existe pero no se puede usar (otra aplicación, permisos)."""


class CameraDisconnected(DriverError, DeviceDisconnectedError):
    """El dispositivo dejó de entregar frames durante el uso."""


class FormatNotSupported(DriverError, DeviceOpenError):
    """El formato pedido (resolución, FPS, formato de pixel) no está disponible."""


class DriverContractError(ColpoError):
    """Una clase no cumple el contrato ``CameraDriver`` (se detecta al registrarla)."""
