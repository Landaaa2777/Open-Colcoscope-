# Open Colposcope

Software **open-source, multiplataforma y offline-first** para capturar imágenes y video de
colposcopios USB mediante el estándar **USB Video Class (UVC)**, sin depender del software
propietario ni de su dongle de licencia. Finalidad educativa y de bien público, pensado para
contextos con recursos limitados.

> ⚠️ **Prototipo educativo. NO es un producto médico validado** y no debe usarse para
> diagnóstico, tratamiento ni decisiones clínicas.
>
> 🔒 Sin red, sin telemetría, sin cuentas. El software no solicita ni guarda datos
> identificatorios de pacientes. Ver [docs/PRIVACY.md](docs/PRIVACY.md).
>
> 🚫 Este proyecto **no** emula, elude ni analiza dongles o mecanismos de licencia.
> Ver [docs/RISKS.md §5](docs/RISKS.md#5-por-qué-no-se-emula-el-dongle).

## Estado

- **F0 — Descubrimiento: cerrada.** Goldcare GC 3000E confirmado como UVC en Windows 10.
- **F1 — Captura UVC: entregada la parte F1.a** (`UVCCamera` + CLI `colpo` + pruebas con
  video sintético). Pendiente F1.b (metadatos *sidecar*) y la prueba manual con el GC 3000E.
  Ver [docs/ROADMAP.md](docs/ROADMAP.md).

## Inicio rápido (Windows 10/11 x64)

```powershell
py -3 -m venv .venv
.venv\Scripts\activate
pip install -e .
colpo list
colpo preview --index 0
colpo record --index 0 --out test.mp4 --duration 5
```

Sin colposcopio: `python examples\synthetic_video.py demo.avi` y luego
`colpo preview --source demo.avi`. Detalles y limitaciones: [docs/CAPTURE.md](docs/CAPTURE.md).

## Desarrollo

```powershell
pip install -e ".[dev]"
ruff check . ; ruff format --check .
pytest
```

Las pruebas no necesitan hardware: usan video sintético y una cámara simulada.

## Documentación

| Documento | Contenido |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Objetivos, no-objetivos, actores, casos de uso, componentes, HAL, flujo de captura, archivos y metadatos. |
| [docs/CAPTURE.md](docs/CAPTURE.md) | Captura UVC de F1: comandos, comportamiento, limitaciones, protocolo con el GC 3000E. |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Fases F0–F5 con entregables, estado y criterios de aceptación. |
| [docs/RISKS.md](docs/RISKS.md) | Riesgos técnicos, legales, regulatorios y de privacidad. |
| [docs/PRIVACY.md](docs/PRIVACY.md) | Privacidad por diseño, hora exacta vs. identidad, condiciones para F4 (Ley 29733). |
| [docs/LEGAL.md](docs/LEGAL.md) | Licencias, dependencias, uso previsto, interoperabilidad. |
| [docs/HARDWARE.md](docs/HARDWARE.md) | Matriz de compatibilidad de hardware. |
| [docs/STACK.md](docs/STACK.md) | Stack confirmado y alternativas evaluadas. |

## Licencia

- Código: [Apache License 2.0](LICENSE).
- Documentación: [Creative Commons Atribución 4.0 Internacional (CC BY 4.0)](docs/LICENSE-CC-BY-4.0.txt).

## Contribuir

Las guías de contribución llegarán en F5. Mientras tanto, la forma más útil de ayudar es
probar un colposcopio con `colpo list --probe` y reportarlo siguiendo
[docs/HARDWARE.md](docs/HARDWARE.md). **Nunca** compartas imágenes de pacientes.
