"""Open Colposcope: captura offline de colposcopios USB vía UVC.

Prototipo educativo. NO es un producto médico validado y no debe usarse para
diagnóstico, tratamiento ni decisiones clínicas.
"""

from colpo.capture import CaptureCamera, Frame, RecordingStats, StreamInfo, UVCCamera
from colpo.devices import DeviceInfo, list_devices
from colpo.errors import (
    BackendUnavailableError,
    CameraNotOpenError,
    ColpoError,
    DeviceDisconnectedError,
    DeviceOpenError,
    DiskFullError,
    EndOfStreamError,
    FrameReadError,
    MetadataError,
    NotesRejectedError,
    RecordingError,
    SnapshotError,
    UnsupportedFormatError,
)

__version__ = "0.3.0"

INTENDED_USE = "educational-not-for-diagnosis"
DISCLAIMER = (
    "Open Colposcope es un prototipo educativo. NO es un producto médico validado "
    "y no debe usarse para diagnóstico, tratamiento ni decisiones clínicas."
)

__all__ = [
    "DISCLAIMER",
    "INTENDED_USE",
    "BackendUnavailableError",
    "CameraNotOpenError",
    "CaptureCamera",
    "ColpoError",
    "DeviceDisconnectedError",
    "DeviceInfo",
    "DeviceOpenError",
    "DiskFullError",
    "EndOfStreamError",
    "Frame",
    "FrameReadError",
    "MetadataError",
    "NotesRejectedError",
    "RecordingError",
    "RecordingStats",
    "SnapshotError",
    "StreamInfo",
    "UVCCamera",
    "UnsupportedFormatError",
    "__version__",
    "list_devices",
]
