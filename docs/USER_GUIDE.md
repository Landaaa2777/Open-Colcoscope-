# Guía de uso — Open Colposcope (v0.2.0-ui)

> **Prototipo educativo — no validado para diagnóstico clínico.**
> En esta etapa (F1–F3) se usa solo con maniquíes, objetivos de prueba y material educativo
> existente. Nunca con pacientes. Ver [PRIVACY.md](PRIVACY.md).

## 1. Requisitos

- Windows 10 u 11 de 64 bits.
- Python 3.11 o superior **de 64 bits** (python.org). Durante la instalación, marca
  "Add python.exe to PATH".
- Un colposcopio USB que funcione como cámara UVC (p. ej. Goldcare GC 3000E). Comprobación
  rápida: debe verse en la app **Cámara** de Windows sin el software del fabricante y sin el
  dongle conectado.

## 2. Instalación

En PowerShell, dentro de la carpeta del proyecto:

```powershell
py -3 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -e .
```

**Equipo sin Internet:** en otro equipo Windows con conexión, ejecuta `pip download -d wheels .`
dentro del proyecto y copia la carpeta del proyecto (con `wheels`) en una memoria USB. En el
equipo del sitio: `pip install --no-index --find-links wheels -e .`

El instalador para Windows (PyInstaller) llegará en F4.

## 3. Abrir la aplicación

| Forma | Comando | Cuándo usarla |
|---|---|---|
| Normal | `colpo-ui` | Uso diario. No abre ventana de consola. |
| Con consola | `python -m colpo.ui` | Si algo falla al arrancar: los mensajes aparecen en la consola. |
| Acceso directo | Crea un acceso directo a `…\.venv\Scripts\colpo-ui.exe` | Para abrirla con doble clic. |

Opciones:

| Opción | Efecto |
|---|---|
| `--lang en` | Abre en inglés (por defecto, español o el último idioma usado). |
| `--data-dir D:\Capturas` | Guarda en otra carpeta (por defecto `%USERPROFILE%\OpenColposcope`). |
| `--source demo.avi` | Añade un video como "cámara" de demostración (para practicar sin colposcopio). |

Para crear un video de demostración: `python examples\synthetic_video.py demo.avi --frames 1800`.

## 4. La pantalla

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│     Prototipo educativo — no validado para diagnóstico clínico   (siempre)    │
├──────────────────────────────────────────────────────────────────────────────┤
│ (mensajes de error, con ✕ para cerrarlos; solo aparecen si hay un problema)   │
├──────────────────────────────────────────────────────────────────────────────┤
│ Cámara: [0 — GOLDCARE …   ▼] API: [auto ▼] [Actualizar] [Conectar]  Idioma: [Español ▼] │
├──────────────────────────────────────────────┬───────────────────────────────┤
│                                              │ Estudio                       │
│                                              │  ID de estudio: E-XXXXXXXX    │
│              VISTA PREVIA EN VIVO            │  [Nuevo estudio]              │
│                                              │ Etapa (IFCPC): [Basal ▼]      │
│                                              │ Notas (opcional): [         ] │
│                                              │ [ Foto (F8) ]                 │
│                                              │ [ Iniciar grabación (F9) ]    │
│                                              │ Última captura: …             │
│ 1280×720 · 30.0 FPS          ● GRABANDO 00:10│ [Abrir carpeta del estudio]   │
└──────────────────────────────────────────────┴───────────────────────────────┘
```

## 5. Flujo de captura paso a paso

1. **Prepara el equipo:** conecta el colposcopio por USB y cierra la app Cámara, el software
   del fabricante y cualquier videollamada (una cámara solo la puede usar una aplicación a la vez).
2. **Abre la app** (`colpo-ui`).
3. **Elige la cámara** en la lista *Cámara*. Cada entrada muestra `índice — nombre`; al pasar el
   ratón se ve el VID:PID. En un portátil, el índice 0 suele ser la webcam integrada: elige la
   que tenga el nombre del colposcopio. Si no aparece, pulsa **Actualizar**.
4. Pulsa **Conectar**. En unos segundos aparece la imagen y, debajo, la resolución y los FPS reales.
5. **Estudio:** cada vez que abres la app se crea un *ID de estudio* aleatorio. Pulsa
   **Nuevo estudio** cuando empieces con otro maniquí o caso de práctica.
6. **Elige la etapa** (Basal, Solución salina, Ácido acético, Lugol, Filtro verde).
7. **Notas (opcional):** escribe solo observaciones educativas. Si escribes algo que parece un
   dato personal (DNI, teléfono, fecha, correo, palabras como "nombre"), aparece un aviso en
   rojo y **esas notas no se guardan**.
8. **Foto:** pulsa **Foto** o **F8**. En *Última captura* aparece el nombre del archivo.
9. **Video:** pulsa **Iniciar grabación** o **F9**. Verás `● GRABANDO mm:ss`. Para terminar,
   pulsa **Detener grabación** o **F9** otra vez.
10. **Cambia de etapa** cuando corresponda (p. ej. tras aplicar ácido acético) y repite 8–9.
11. **Idioma:** cambia entre Español e English en cualquier momento; no se interrumpe la vista previa.
12. Pulsa **Abrir carpeta del estudio** para ver los archivos, y **Desconectar** al terminar.
    Si cierras la app mientras grabas, el video se cierra y se guarda.

## 6. Qué hace cada control

| Control | Función |
|---|---|
| Banner amarillo | Recordatorio permanente: prototipo educativo, no validado para diagnóstico. No se puede ocultar. |
| Cámara | Lista de cámaras detectadas por el sistema (índice y nombre). |
| API | Interfaz de captura de Windows: `auto` (DirectShow), `dshow` o `msmf` (Media Foundation). Cambia a `msmf` solo si la cámara no funciona con `auto`. |
| Actualizar | Vuelve a buscar cámaras (por ejemplo, después de conectar el USB). |
| Conectar / Desconectar | Inicia o detiene la vista previa en vivo. |
| Idioma | Español / English, en caliente. Se recuerda para la próxima vez. |
| Resolución · FPS | Lo que la cámara entrega realmente, medido en vivo. |
| ID de estudio / Nuevo estudio | Seudónimo aleatorio de la carpeta de capturas. No se puede cambiar mientras se graba. |
| Etapa (IFCPC) | Se guarda en el JSON de cada captura. En videos se guarda la etapa vigente al iniciar. |
| Notas | Texto educativo opcional (máx. 500 caracteres), sin datos de la paciente. |
| Foto (F8) | Guarda el último frame mostrado como PNG sin pérdida + JSON. |
| Iniciar / Detener grabación (F9) | Graba MP4 (H.264 si Windows lo ofrece; si no, MPEG-4 `mp4v`) + JSON. |
| Última captura | Archivo guardado más reciente y, en video, el códec usado. |
| Abrir carpeta del estudio | Abre el Explorador de archivos en la carpeta del estudio actual. |

F8 y F9 funcionan aunque estés escribiendo en las notas. Un pedal USB que emule esas teclas
también sirve.

## 7. Dónde se guardan los archivos

Por defecto en `%USERPROFILE%\OpenColposcope` (por ejemplo `C:\Users\docente\OpenColposcope`).
Esta carpeta está **fuera de "Documentos"** a propósito: en muchos equipos "Documentos" se
sincroniza con OneDrive y las capturas no deben salir del equipo.

```text
OpenColposcope\
└── E-ZC858XX2\                       ← un estudio
    ├── foto_20261026-150405.png       ← foto (PNG sin pérdida, sin EXIF)
    ├── foto_20261026-150405.json      ← sus metadatos
    ├── video_20261026-150412.mp4      ← video (sin audio)
    └── video_20261026-150412.json
```

Ejemplo real de JSON (generado por la app):

```json
{
  "id_estudio": "E-ZC858XX2",
  "timestamp": "2026-10-26T15:04:05-05:00",
  "etapa_ifcpc": "acido_acetico",
  "resolucion": { "ancho": 1280, "alto": 720 },
  "fps": 30.0,
  "tipo": "foto",
  "sha256": "a66e6c28bb41570e6be1573f613133186f001998714282039049b9fbebfcabd3",
  "notas": "Maniquí de práctica, ZT tipo 1"
}
```

Los campos son siempre esos ocho; no existen campos de nombre, documento ni fecha de
nacimiento. Para comprobar que un archivo no se alteró:

```powershell
(Get-FileHash .\foto_20261026-150405.png -Algorithm SHA256).Hash.ToLower()
```

El resultado debe coincidir con `sha256` del JSON.

## 8. Mensajes de error

| Mensaje | Qué hacer |
|---|---|
| No se pudo abrir la cámara (ocupada o desconectada) | Cierra la app Cámara, el software del fabricante y videollamadas. Revisa *Configuración > Privacidad y seguridad > Cámara > Permitir que las aplicaciones de escritorio accedan a la cámara*. Prueba otra API. |
| Se perdió la conexión con la cámara | Revisa el cable USB y pulsa **Conectar**. Lo grabado hasta ese momento ya está guardado. |
| Disco lleno o casi lleno | Libera espacio. Se necesitan al menos 50 MB para una foto y 500 MB para empezar un video; con menos de 200 MB, la grabación se detiene y se guarda sola. |
| La grabación falló | Vuelve a intentarlo. Si se repite, anota el "Detalle técnico" y repórtalo. |
| No se pudo guardar la foto / los metadatos | Revisa el espacio y los permisos de la carpeta de datos. |

Cada mensaje incluye un "Detalle técnico" (en español) útil para reportar problemas.

## 9. Cómo verificar que la app no usa la red

La app no tiene ningún código de red: no hay telemetría, ni actualizaciones automáticas, ni
cuentas. Puedes comprobarlo tú mismo:

1. **Modo avión:** activa el modo avión (o desconecta el cable de red) y usa la app con
   normalidad. Todo funciona igual.
2. **Monitor de recursos:** con la app abierta, ejecuta `resmon`, pestaña **Red** →
   *Procesos con actividad de red*. No debe aparecer `python.exe`, `pythonw.exe` ni `colpo-ui.exe`.
3. **PowerShell** (con la app abierta):

   ```powershell
   $ids = (Get-Process python, pythonw, colpo-ui -ErrorAction SilentlyContinue).Id
   Get-NetTCPConnection -ErrorAction SilentlyContinue | Where-Object OwningProcess -in $ids
   Get-NetUDPEndpoint  -ErrorAction SilentlyContinue | Where-Object OwningProcess -in $ids
   ```

   Ambos comandos no deben mostrar nada.
4. **Pruebas automáticas:** `pytest tests/test_no_network.py` verifica que ningún módulo
   importa librerías de red y que capturar funciona con los sockets bloqueados.

## 10. Prueba manual de aceptación (5 minutos, con el colposcopio real)

Con un maniquí u objetivo de prueba:

- [ ] La app abre con `colpo-ui` y el colposcopio aparece en la lista con su índice y nombre.
- [ ] Vista previa fluida; la barra muestra ~30 FPS a 1280×720 (o la resolución nativa).
- [ ] Foto en etapa *Basal*: aparecen el PNG y el JSON; el SHA-256 coincide (§7).
- [ ] Cambia a *Ácido acético*, graba ~10 s: el MP4 se reproduce en VLC y en la app
      Películas y TV / Reproductor multimedia de Windows; su JSON dice `acido_acetico`.
- [ ] Cambia el idioma a English y de vuelta a Español sin que se corte la vista previa.
- [ ] Desconecta el USB durante una grabación: aparece el aviso y el video se conserva.
- [ ] Ningún cierre inesperado durante los 5 minutos.

Anota los resultados (y el VID:PID que muestra la lista) en [HARDWARE.md](HARDWARE.md).

## 11. Problemas frecuentes

| Problema | Solución |
|---|---|
| `colpo-ui` no se reconoce como comando | Activa el entorno: `.venv\Scripts\activate`. |
| La lista de cámaras está vacía | Conecta el USB, espera unos segundos y pulsa **Actualizar**. Prueba la API `msmf`. |
| La imagen va lenta | Cierra otros programas; usa un puerto USB del propio equipo (no un hub). |
| El video se ve pero dice `mp4v` en vez de H.264 | Tu Windows no ofrece el codificador H.264 (p. ej. ediciones "N" sin *Media Feature Pack*). El MP4 sigue siendo válido. |
