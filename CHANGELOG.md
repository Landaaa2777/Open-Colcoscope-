# Changelog

Todos los cambios relevantes de Open Colposcope se documentan en este archivo.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/). Las etiquetas
de versión usan un sufijo de fase (`-ui`); la versión del paquete Python es la parte numérica
(PEP 440 no admite el sufijo).

## [Unreleased]

## [v0.3.0-drivers] - 2026-10-27

Fase F3: ecosistema de drivers y multi-dispositivo.

### Added

- Paquete `colpo.drivers`:
  - `base.py`: contrato `CameraDriver` (`discover`, `probe`, `for_device`, `open`, `close`,
    `read_frame`, `capabilities`, `metadata`, `is_connected`) y `Capabilities`.
  - `errors.py`: `CameraNotFound`, `CameraBusy`, `CameraDisconnected`, `FormatNotSupported`.
  - `registry.py`: descubrimiento por *entry points* `colpo.drivers` (solo paquetes
    instalados) y registro manual; `list_drivers`, `probe_all`, `create`, `describe`.
  - `profiles/`: perfiles JSON por VID:PID con validación; perfil del Goldcare GC 3000E
    (VID:PID pendiente, sin aplicar hasta completarlo).
  - `uvc.py`: driver UVC (OpenCV). `mock.py`: driver simulado y ejemplo comentado.
- `CaptureCamera` (núcleo): foto, video, FPS y marca de agua sobre **cualquier** driver.
- UI: selector agrupado por driver con VID:PID y capacidades; una pestaña por dispositivo
  (vista dual sin bloqueo); cambio de dispositivo en caliente; no se abre dos veces el mismo.
- Preferencias: marca de agua "Uso educativo" para foto **y video**, desactivada por defecto
  y guardada en la configuración del usuario.
- `colpo drivers` (CLI) y `colpo-ui --demo` (cámaras simuladas).
- Suite de contrato `tests/test_driver_contract.py` (con modo hardware
  `COLPO_CONTRACT_HARDWARE=1`), `tests/test_registry.py`.
- `docs/DRIVER_GUIDE.md`, `docs/NON_UVC.md`.

### Changed

- **Incompatible:** `UVCCamera` es ahora un driver puro: `read_frame()` devuelve `ndarray`;
  la foto, el video y `measure_fps` se usan a través de `CaptureCamera`
  (`CaptureCamera.for_index(0)`, `CaptureCamera.for_source("demo.avi")`). Exigido por el
  contrato de driver (los drivers no escriben archivos). `colpo.UVCCamera` se sigue exportando.
- Nombres de archivo con el dispositivo: `foto_AAAAMMDD-HHMMSS_<driver><índice>.png`.
- `CaptureSession` admite varias cámaras grabando a la vez.
- Generador sintético movido a `colpo.synthetic` (el script de `examples/` lo reutiliza).

### Fixed

- Cierre abrupto de PySide al salir de la app (la ventana se destruye antes de desmontar Qt).

### Security

- Sin red, sin telemetría, sin datos de paciente. Los drivers no pueden escribir archivos ni
  importar red/UI (verificado por la suite). Política clean-room reafirmada.

## [v0.2.0-ui] - 2026-10-26

Fase F2: interfaz gráfica de escritorio sobre el motor de captura de F1.

### Added

- Aplicación de escritorio PySide6 `colpo-ui` (también `python -m colpo.ui.app`):
  selector de cámara (índice y nombre) y de API, vista previa en vivo, resolución y FPS
  reales, botones **Foto** (F8) e **Iniciar/Detener grabación** (F9), selector de etapa
  IFCPC, notas opcionales, banner permanente "Prototipo educativo — no validado para
  diagnóstico clínico" y panel de errores.
- Internacionalización con catálogos JSON (`src/colpo/ui/i18n/es.json`, `en.json`);
  español por defecto; cambio de idioma en caliente y recordado entre sesiones.
- Metadatos por captura (`colpo.metadata`): JSON junto a cada foto/video con lista cerrada de
  campos `id_estudio`, `timestamp` (hora exacta al segundo), `etapa_ifcpc`, `resolucion`,
  `fps`, `tipo`, `sha256`, `notas`.
- Filtro de notas: se rechazan (y no se guardan) notas que parecen contener DNI, teléfonos,
  fechas, correos o palabras como "nombre".
- `colpo.session.CaptureSession`: estudio con seudónimo aleatorio, foto y video con
  metadatos, comprobación de espacio libre.
- `colpo.live.LiveCapture`: hilo de adquisición sin Qt, dueño exclusivo de la cámara; la
  grabación se detiene y se guarda sola si el disco se llena o la cámara se desconecta.
- `colpo.storage`: carpeta de datos `%USERPROFILE%\OpenColposcope` (fuera de OneDrive) y
  nombres de archivo con hora exacta.
- `colpo.watermark`: gancho de marca de agua, **desactivado** y sin control en la UI (F3+).
- Errores `DiskFullError`, `MetadataError` y `NotesRejectedError`.
- Pruebas: `tests/test_ui_smoke.py` (offscreen, `MockDriver`), `test_live.py`,
  `test_session.py`, `test_metadata.py`; verificación de que la UI no importa OpenCV ni NumPy
  y de que los catálogos ES/EN tienen las mismas claves.
- `docs/USER_GUIDE.md`.

### Changed

- Grabación `.mp4`: en Windows se intenta primero H.264 (codificador de Media Foundation
  incluido en Windows) y, si no está disponible, `mp4v`. El códec usado se informa en
  `RecordingStats.codec`. El contrato público de `UVCCamera` no cambia.
- Versión del paquete: 0.2.0.

### Security

- Sin cambios en la política: sin red, sin telemetría, sin actualizaciones automáticas, sin
  datos de paciente, sin EXIF, sin audio.

## [v0.1.0] - 2026-10-26

Fases F0 (descubrimiento) y F1.a (captura UVC).

### Added

- Documentación de arquitectura, roadmap, riesgos, privacidad, aspectos legales, stack y
  matriz de hardware.
- `UVCCamera`: apertura por índice o archivo, resolución y FPS reales, foto PNG atómica,
  grabación con ritmo constante en hilo propio, errores explícitos.
- CLI `colpo` (`list`, `preview`, `record`, `snapshot`), video sintético y pruebas sin hardware.
- Licencias Apache-2.0 (código) y CC BY 4.0 (documentación).
