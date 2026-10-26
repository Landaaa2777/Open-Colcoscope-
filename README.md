# Open Colposcope (nombre provisional)

Software **open-source, multiplataforma y offline-first** para capturar imágenes y video de
colposcopios USB mediante el estándar **USB Video Class (UVC)**, sin depender del software
propietario ni de su dongle de licencia. Finalidad educativa y de bien público, pensado para
contextos con recursos limitados.

> ⚠️ **Prototipo educativo. NO es un producto médico validado** y no debe usarse para
> diagnóstico, tratamiento ni decisiones clínicas.
>
> 🔒 Sin red, sin telemetría, sin cuentas. El software no solicita ni guarda datos
> identificatorios de pacientes.
>
> 🚫 Este proyecto **no** emula, elude ni analiza dongles o mecanismos de licencia.
> Ver [docs/RISKS.md §5](docs/RISKS.md#5-por-qué-no-se-emula-el-dongle).

## Estado

Fase **F0 — Descubrimiento**. Todavía no hay código de aplicación; solo documentación y decisiones.

## Documentación

| Documento | Contenido |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Objetivos, no-objetivos, actores, casos de uso, componentes, HAL, flujo de captura, archivos y metadatos anonimizados. |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Fases F0–F5 con entregables y criterios de aceptación. |
| [docs/RISKS.md](docs/RISKS.md) | Riesgos técnicos, legales, regulatorios y de privacidad, con mitigaciones. |
| [docs/HARDWARE.md](docs/HARDWARE.md) | Matriz de compatibilidad de hardware (plantilla). |
| [docs/STACK.md](docs/STACK.md) | Stack propuesto y alternativas evaluadas. |

## Contribuir

Las guías de contribución llegarán en F5. Mientras tanto, la forma más útil de ayudar es
probar un colposcopio con una app de cámara genérica y reportarlo siguiendo
[docs/HARDWARE.md](docs/HARDWARE.md). **Nunca** compartas imágenes de pacientes.
