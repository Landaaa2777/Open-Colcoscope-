# Stack tecnológico (ADR-0001)

| Campo | Valor |
|---|---|
| Estado | **Aceptado** al cierre de F0 (2026-10) |
| Contexto | [ARCHITECTURE.md](ARCHITECTURE.md), [RISKS.md](RISKS.md) |

## 1. Criterios de decisión (en orden de peso)

1. **Captura UVC fiable** en Windows, Linux y macOS con los controladores genéricos del SO.
2. **Offline y sin telemetría**: ninguna dependencia que requiera red o cuentas.
3. **Rendimiento en equipos modestos** (ARCHITECTURE.md §9).
4. **Facilidad para contribuir**: lenguaje y librerías conocidos por docentes, estudiantes de
   ingeniería biomédica e investigadores.
5. **Licencias compatibles** con distribución abierta y con uso institucional.
6. **Empaquetado offline** razonable (instalador o versión portable).

## 2. Decisión

**Confirmado en F0:** Python 3.11+, OpenCV, PySide6, `pyusb` solo lectura (solo para
diagnóstico; **no** es necesario para capturar por UVC) y PyInstaller para Windows 10/11 x64.
La vía de captura principal es UVC + OpenCV (ARCHITECTURE.md §6.0).

| Capa | Elección | Motivo principal |
|---|---|---|
| Lenguaje | **Python ≥ 3.11**, 64 bits (CI en 3.11 y 3.13) | Comunidad amplia en ciencia/medicina; prototipado rápido; buenas librerías de imagen. |
| Captura | **OpenCV** (`opencv-python-headless`) sobre V4L2 / MSMF / DirectShow / AVFoundation | Madura, multiplataforma, ya trae los backends del SO; Apache-2.0. |
| Enumeración de dispositivos | **`cv2-enumerate-cameras`** (MIT): DirectShow/MSMF en Windows, V4L2 en Linux, AVFoundation en macOS, con los mismos índices que OpenCV; sondeo de índices como respaldo | OpenCV solo expone índices; necesitamos nombre y VID:PID para identificar el colposcopio y aplicar perfiles. Aislado en `colpo/devices.py` para poder sustituirlo. |
| Introspección USB | **`pyusb` + libusb**, solo lectura, para `diagnose` (F1.b/F3). **No** es dependencia de la captura | Lectura de descriptores sin reclamar la interfaz de video. |
| UVC avanzado | **libuvc** (opcional, F3) | Controles UVC y *still trigger* cuando el SO no los expone; no predeterminado (requiere cambiar controlador). |
| GUI | **PySide6 (Qt 6)**, paquete `PySide6-Essentials` | Video fluido, HiDPI, accesibilidad, i18n (Qt Linguist), LGPL, binding oficial de Qt. En F1 solo se usa para la ventana de vista previa. |
| Video (grabación) | OpenCV `VideoWriter`: `.mp4` → en Windows, H.264 vía el codificador de Media Foundation incluido en el SO; si no está disponible, MPEG-4 Part 2 (`mp4v`). `.avi`/`.mkv` → MJPEG. Evaluar **PyAV** (FFmpeg) para *passthrough* MJPEG sin recodificar | `.mp4` es el formato pedido para F1 y se reproduce en cualquier equipo; MJPEG da más calidad con menos CPU. H.264 no viene en las ruedas de OpenCV. |
| Metadatos | JSON *sidecar* + **JSON Schema** (validación con `jsonschema` o `pydantic`) | Legible por humanos, versionable, fácil de auditar. |
| Índice | **SQLite** (stdlib `sqlite3`) | Sin servidor; reconstruible desde los sidecars. |
| Configuración | Preferencias de usuario en `QSettings` (registro de Windows); perfiles de dispositivo en **JSON** dentro del paquete | JSON: sin dependencias nuevas (no hace falta PyYAML), validable, legible. |
| Drivers | Contrato `typing.Protocol` + **entry points** `colpo.drivers` (`importlib.metadata`) | Mecanismo estándar de Python para plugins: sin importar rutas arbitrarias ni descargar nada. |
| Pruebas | `pytest`, `pytest-qt`, backend `replay`, `hypothesis` (opcional) | Probar sin hardware. |
| Calidad | `ruff`, `mypy`, `pre-commit` | Estándar actual, rápido. |
| Empaquetado | **PyInstaller para Windows 10/11 x64** (prioritario); AppImage/macOS solo si hay demanda | Ver tabla §3.7. |
| i18n | **Catálogos JSON** planos (`src/colpo/ui/i18n/es.json`, `en.json`) con un `Translator` propio (decidido en F2) | Sin paso de compilación (`lrelease`), fáciles de editar y revisar, cambio de idioma en caliente trivial, verificables en CI (mismas claves y marcadores). Contras: sin plurales automáticos ni Qt Linguist; migrable si crece el número de idiomas. |
| Documentación | Markdown en `docs/` (+ MkDocs opcional, compilado offline) | Baja barrera de entrada. |

## 3. Alternativas evaluadas

### 3.1 Lenguaje / plataforma

| Opción | Ventajas | Desventajas | Veredicto |
|---|---|---|---|
| **Python 3.11+** | Accesible para la comunidad objetivo; OpenCV/Qt maduros; rápido de iterar. | Empaquetado pesado; GIL (mitigado: la captura y codificación ocurren en C/C++). | ✅ **Elegido** |
| C++ / Qt | Máximo rendimiento; paquetes más pequeños. | Barrera de contribución alta; ciclo más lento. | Reserva si el rendimiento falla en F1. |
| Rust (+ `nokhwa`, egui/Slint) | Seguridad de memoria; binario único pequeño. | Ecosistema de captura/GUI menos maduro; menos contribuidores en el dominio. | ❌ Por ahora. |
| Web / PWA (`getUserMedia`) | Sin instalación en Chromium; multiplataforma. | Control limitado de formatos/controles UVC; almacenamiento local restringido; depende del navegador. | ❌ Útil como demo futura. |
| Electron / Tauri | UI web, empaquetado conocido. | Electron pesado; misma limitación de captura que la web salvo módulos nativos. | ❌ |

### 3.2 Captura de video

| Opción | Ventajas | Desventajas | Veredicto |
|---|---|---|---|
| **OpenCV `VideoCapture`** | Multiplataforma; usa controladores del SO; amplia documentación. | No lista formatos ni nombres; control de propiedades irregular por backend. | ✅ **Predeterminado** |
| Qt Multimedia (`QCamera`) | Enumeración de formatos y nombres; integra con la GUI. | Acopla captura a Qt (núcleo headless más difícil); comportamiento variable entre versiones. | 🟡 Backend alternativo en F3. |
| PyAV / FFmpeg | Control fino de formatos; *passthrough* MJPEG; contenedores MKV. | Enumeración por SO poco amigable; licencias FFmpeg (LGPL/GPL según compilación). | 🟡 Para grabación; evaluar en F1. |
| GStreamer (PyGObject) | Muy potente en Linux; pipelines flexibles. | Empaquetado difícil en Windows/macOS. | ❌ Salvo variante solo-Linux. |
| libuvc (+ libusb) | Acceso UVC completo en espacio de usuario. | Requiere desvincular/reemplazar controlador del SO; frágil en Windows. | 🟡 Opcional, F3. |
| APIs nativas directas (Media Foundation, AVFoundation, V4L2) | Control total. | Tres implementaciones a mantener. | ❌ Solo para enumeración mínima. |

### 3.3 Interfaz gráfica

| Opción | Ventajas | Desventajas | Veredicto |
|---|---|---|---|
| **PySide6** | Binding oficial de Qt; LGPL; video fluido; accesibilidad e i18n maduras; HiDPI. | Paquete grande (~100+ MB); requiere Windows 10+ 64 bits / macOS reciente. | ✅ **Elegido** |
| PyQt6 | API casi idéntica. | GPL/comercial: más restrictiva para adopción institucional. | ❌ |
| Tkinter | En la biblioteca estándar; muy ligero; funciona en equipos antiguos. | Vista previa de video menos eficiente; aspecto anticuado; accesibilidad e i18n limitadas. | 🟡 **Plan B** si F0 revela parque con SO antiguos. |
| Kivy | Táctil; multiplataforma incluso móvil. | Aspecto no nativo; accesibilidad limitada. | ❌ |
| Dear PyGui | Rápido (GPU). | Requiere GPU/drivers razonables; accesibilidad débil. | ❌ |
| NiceGUI / Flet (UI web local) | UI moderna. | Servidor local + navegador: superficie de red innecesaria para un software "sin red". | ❌ |

### 3.4 Formato de imagen fija

| Opción | Ventajas | Desventajas | Veredicto |
|---|---|---|---|
| **PNG** | Sin pérdida; universal; sin EXIF por defecto. | Archivos grandes (~3–6 MB a 1080p). | ✅ **Elegido** |
| TIFF | Sin pérdida; 16 bits. | Metadatos complejos (riesgo de fuga); menos universal. | ❌ |
| JPEG | Pequeño. | Pérdida añadida a la ya existente si la cámara entrega MJPEG. | 🟡 Solo como miniatura/exportación opcional. |
| DICOM | Estándar médico; interoperable con PACS. | Complejo; campos de paciente obligatorios a gestionar con cuidado. | 🟡 Exportación futura. |

### 3.5 Formato de video

| Opción | Ventajas | Desventajas | Veredicto |
|---|---|---|---|
| **MJPEG en MKV/AVI (sin recodificar)** | CPU casi nula; sin patentes problemáticas; robusto ante cortes (con segmentos). | Archivos grandes. | ✅ **Predeterminado** |
| H.264 / H.265 | Archivos pequeños. | CPU alta en equipos modestos; patentes/licencias. | 🟡 Opcional para exportar. |
| VP9 / AV1 | Libres de regalías. | Codificación muy costosa en CPU. | 🟡 Exportación offline posterior. |
| FFV1 | Sin pérdida, libre. | Archivos enormes; CPU moderada. | ❌ Salvo investigación. |

### 3.6 Metadatos e índice

| Opción | Ventajas | Desventajas | Veredicto |
|---|---|---|---|
| **JSON sidecar + SQLite caché** | Auditable a simple vista; robusto; índice reconstruible. | Dos representaciones a mantener coherentes. | ✅ **Elegido** |
| Solo SQLite | Consultas simples. | Un archivo corrupto afecta a todo; menos transparente. | ❌ |
| Metadatos incrustados (EXIF/XMP) | Un solo archivo. | Fácil fuga de datos al compartir; difícil de auditar. | ❌ |

### 3.7 Empaquetado

| Opción | Ventajas | Desventajas | Veredicto |
|---|---|---|---|
| **PyInstaller** | Maduro; Win/macOS/Linux; modo carpeta portable. | Falsos positivos de antivirus; tamaño. | ✅ Win/macOS |
| **AppImage** | Un archivo, sin instalación, funciona offline. | Dependencia de glibc mínima. | ✅ Linux |
| Flatpak | Aislamiento; actualizaciones. | Requiere permisos de dispositivo; repositorio suele requerir red. | 🟡 Segunda opción Linux |
| Briefcase (BeeWare) | Instaladores nativos. | Menos probado con Qt+OpenCV. | 🟡 Evaluar |
| Nuitka | Binario compilado; menos falsos positivos. | Compilación lenta; complejidad. | 🟡 Si AV es un problema |
| Paquete `pip`/`pipx` | Simple para desarrolladores. | Requiere red o *wheelhouse* local. | ✅ Para contribuidores |

## 4. Dependencias y licencias (orientativo, a verificar en F0/F4)

| Dependencia | Licencia | Observaciones |
|---|---|---|
| Python | PSF | — |
| OpenCV (`opencv-python-headless`) | Apache-2.0 (las ruedas incluyen FFmpeg LGPL) | Incluir avisos. Se usa la variante *headless* para no chocar con los plugins Qt de PySide6. |
| cv2-enumerate-cameras | MIT | Enumeración de cámaras (nombre, VID:PID). |
| NumPy | BSD-3 | — |
| PySide6 / Qt 6 | LGPL-3.0 | Enlace dinámico; permitir sustitución de librerías; incluir avisos. |
| pyusb / libusb | BSD-3 / LGPL-2.1 | — |
| libuvc | BSD-3 | Opcional. |
| PyAV / FFmpeg | BSD-3 / LGPL (según compilación) | Evitar compilaciones GPL si se elige licencia permisiva. |
| jsonschema / pydantic | MIT | — |

## 5. Consecuencias

- **Positivas:** arranque rápido del desarrollo, comunidad amplia, captura estándar sin código
  propietario, núcleo testeable sin hardware.
- **Negativas:** paquetes grandes; Qt 6 excluye Windows 7/8 y 32 bits (no afecta: los sitios
  usan Windows 10/11 x64); OpenCV requiere una librería complementaria de enumeración.
- **A revisar con el GC 3000E (F1, prueba manual):** rendimiento en el equipo del sitio,
  comportamiento de DirectShow vs Media Foundation, formatos y FPS reales.
