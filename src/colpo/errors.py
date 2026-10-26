"""Jerarquía de errores explícitos de Open Colposcope.

Todas las excepciones propias heredan de :class:`ColpoError`, de modo que la CLI
(y en F2 la GUI) pueden capturarlas en un único punto y mostrar un mensaje
comprensible, sin trazas de Python, mientras que los errores de programación
(``TypeError``, ``ValueError``...) siguen propagándose normalmente.
"""


class ColpoError(Exception):
    """Error base de la aplicación."""


class BackendUnavailableError(ColpoError):
    """El backend de captura solicitado no existe en esta plataforma."""


class DeviceOpenError(ColpoError):
    """No se pudo abrir la cámara o la fuente de video."""


class CameraNotOpenError(ColpoError):
    """Se intentó operar sobre una cámara que no está abierta."""


class FrameReadError(ColpoError):
    """No se pudo leer un frame."""


class DeviceDisconnectedError(FrameReadError):
    """La cámara dejó de entregar frames (probablemente se desconectó)."""


class EndOfStreamError(FrameReadError):
    """La fuente de archivo llegó a su final."""


class UnsupportedFormatError(ColpoError):
    """Extensión o formato de archivo no soportado."""


class SnapshotError(ColpoError):
    """Falló el guardado de una imagen fija."""


class RecordingError(ColpoError):
    """Falló el inicio, la escritura o el cierre de una grabación."""
