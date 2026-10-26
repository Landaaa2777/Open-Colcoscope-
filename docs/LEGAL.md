# Aspectos legales

> **No es asesoría legal.** Resume las decisiones del proyecto y los puntos que cada
> institución debe revisar con su asesoría en su jurisdicción.

## 1. Licencias del proyecto

| Contenido | Licencia | Archivo |
|---|---|---|
| Código fuente (`src/`, `tests/`, `examples/`, configuración) | **Apache License 2.0** | [`LICENSE`](../LICENSE) |
| Documentación (`docs/`, `README.md`) | **Creative Commons Atribución 4.0 Internacional (CC BY 4.0)** | [`docs/LICENSE-CC-BY-4.0.txt`](LICENSE-CC-BY-4.0.txt) |

- Apache-2.0 permite el uso, la modificación y la redistribución (también institucional),
  incluye una licencia de patentes de los contribuidores y exige conservar los avisos de
  licencia.
- CC BY 4.0 permite reutilizar y adaptar la documentación (por ejemplo, en materiales de curso)
  citando la fuente.
- Las contribuciones se aceptan bajo las mismas licencias (*inbound = outbound*). En F5 se
  formalizará con DCO (`Signed-off-by`).

## 2. Dependencias de terceros

| Componente | Licencia | Observaciones |
|---|---|---|
| OpenCV (`opencv-python-headless`) | Apache-2.0 | La rueda incluye FFmpeg (LGPL). |
| PySide6 / Qt 6 (`PySide6-Essentials`) | LGPL-3.0 | Enlace dinámico; el paquete de F4 incluirá los avisos y permitirá sustituir las librerías Qt. |
| NumPy | BSD-3-Clause | — |
| cv2-enumerate-cameras | MIT | Enumeración de cámaras. |
| pytest, ruff (solo desarrollo) | MIT | No se distribuyen. |

El SBOM y los avisos completos se generan en F4.

## 3. Uso previsto y estatus regulatorio

- Uso previsto: **educativo**. No está destinado al diagnóstico, tratamiento, cribado ni a la
  toma de decisiones clínicas.
- No es un dispositivo médico registrado ni certificado. En Perú, los dispositivos médicos
  (incluido el software con finalidad médica) los regula la Ley N.° 29459 y su autoridad
  (DIGEMID); este proyecto **no** busca ese registro (ver [RISKS.md §3](RISKS.md#3-riesgos-regulatorios-y-de-seguridad-del-paciente)).
- El software no incorpora funciones de diagnóstico, medición ni apoyo a la decisión.

## 4. Interoperabilidad, dongle y software del fabricante

- La captura usa exclusivamente el estándar público **USB Video Class** y el controlador
  genérico del sistema operativo.
- El proyecto **no** instala, ejecuta, modifica, decompila ni redistribuye el software o
  firmware del fabricante.
- El proyecto **no** emula, elude ni analiza el dongle de licencia. Razones y procedimiento:
  [RISKS.md §5](RISKS.md#5-por-qué-no-se-emula-el-dongle).
- Las marcas citadas (p. ej. GOLDCARE) pertenecen a sus titulares y se mencionan solo para
  identificar equipos compatibles (uso nominativo). El proyecto no está afiliado ni avalado
  por ningún fabricante.

## 5. Datos personales y ética

- Sitio piloto en Perú: **Ley N.° 29733**, Ley de Protección de Datos Personales, y su
  reglamento vigente. Condiciones de uso por fases: [PRIVACY.md](PRIVACY.md).
- F1–F3: sin pacientes. Desde F4: solo con aprobación del comité de ética institucional,
  consentimiento informado y anonimización obligatoria.

## 6. Seguridad eléctrica

Conectar un PC no médico a un equipo médico en el entorno del paciente puede requerir medidas
de la norma IEC 60601-1 (sistemas electromédicos). Antes de cualquier uso con pacientes (F4+),
consulta a ingeniería biomédica (ver [RISKS.md](RISKS.md) R3).

## 7. Garantía y responsabilidad

El software se entrega "TAL CUAL", **sin garantías** de ningún tipo, según las secciones 7 y 8
de la licencia Apache-2.0. Cada institución es responsable de su uso.
