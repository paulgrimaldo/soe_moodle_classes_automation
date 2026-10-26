# Plan provisional: recuperar apuntes históricos de MIA desde Notion

Fecha del plan: 23 de octubre de 2026. Estado: implementado y aplicado; cierre de verificación el 25 de octubre de 2026. La implementación y los resultados definitivos se describen en [la guía web](web.md#recuperacion-historica-mia-y-cierre-del-25-de-octubre-de-2026). Las fases siguientes conservan la propuesta original como referencia; permanecen pendientes de localizar cuatro clases.

## Objetivo y alcance

Recuperar los apuntes que se generaron con la skill manual y se publicaron directamente en Notion, incorporarlos como fuentes locales verificables y exportarlos con la biblioteca web existente. La recuperación conserva el contenido académico; no vuelve a generar apuntes con Codex ni necesita descargar transcripciones.

El alcance confirmado por el usuario es módulos 7–13, ambos incluidos. Los módulos 1–6 y el módulo 14 continúan con el procesamiento actual y no se incluyen en esta recuperación.

Se propone una importación histórica explícita y repetible. Una sincronización bidireccional permanente queda fuera de este alcance.

## Evidencia local

La consulta de SQLite fue de solo lectura. Los módulos históricos existen en `academic_modules`, pero no tienen sesiones ni páginas vinculadas en este proyecto:

| Número de Moodle como referencia provisional | ID estable | Módulo |
| --- | --- | --- |
| 7 | 416 | Data Visualization and Visual Analytics |
| 8 | 426 | Machine Learning and Deep Learning |
| 9 | 449 | Data Mining |
| 10 | 497 | Natural Language Processing, Text Analytics and Search |
| 11 | 510 | Taller de Tesis 1 |
| 12 | 529 | Practicing Data Science |
| 13 | 545 | Generative Models and Computer Vision |

Los siete módulos tienen `export_number` vacío. La correspondencia con los números académicos debe comprobarse: ya existen diferencias entre el número Moodle y el número manual en otros módulos MIA.

El cliente REST de Notion y una credencial están configurados. No está configurada la raíz MIA; esto no impide leer una página conocida, pero obliga a resolver los destinos históricos mediante IDs, enlaces existentes o descubrimiento acotado. La presencia de la credencial no demuestra acceso a las páginas históricas.

El exportador actual consulta exclusivamente `AcademicSession` con estado `PROCESSED`, revisión y ruta de apuntes. `read_notes` solo permite archivos bajo `data/processed/` o `data/reconciled/`. No existe un importador general de Notion: `notion-inspect` requiere secciones previamente administradas por este proyecto.

La skill instalada prescribe una página semanal con dos clases en MIA. Es una referencia para el piloto, no evidencia de que todas las páginas antiguas cumplan ese formato.

## Diseño propuesto

```text
Páginas históricas de Notion
          ↓ captura de solo lectura
Snapshot privado + inventario de módulo / semana / clase
          ↓ conversión y validación
Markdown por clase + procedencia + revisión local
          ↓ selección explícita de fuentes
Exportador web → content/mia/ → VitePress
```

La recomendación provisional es registrar los apuntes importados como fuentes históricas independientes, con vínculo opcional a una sesión existente. Actualmente no hay sesiones en estos módulos. Crear sesiones ficticias con recursos o fechas inventados para satisfacer el exportador introduciría inconsistencias en la sincronización de Moodle.

Un adaptador entregaría al exportador un formato común para apuntes locales e importados. Se mantendrían el catálogo público, las URLs por ID de módulo/semana/clase, las descargas y los manifiestos existentes. La elección final del modelo se cerrará después del piloto; no se propone convertir todo el sistema en una sincronización genérica de documentos.

Datos mínimos de procedencia: identificador de importación, ID estable de módulo/programa/cohorte, semana, clase dentro de la semana, número global de sesión, título, fecha académica si se conoce, ID/URL de página Notion, límites o IDs de bloques de la clase, fecha de captura, última edición remota observada, hash de fuente, hash del Markdown, versión del conversor y revisión local.

No se crearán registros en `NotionSection` por leer contenido: esa tabla representa bloques administrados para futuras escrituras. Importar apuntes no debe autorizar al publicador a sustituir las páginas antiguas.

## Fase 1: inventario y correspondencia

1. Resolver las páginas de módulo mediante referencias existentes o enlaces conocidos, y verificar programa/cohorte y acceso real.
2. Enumerar semanas y clases; producir una matriz de cobertura con páginas ausentes, duplicadas o ambiguas.
3. Confirmar los números académicos manuales de los módulos 7–13.
4. Identificar fechas y recursos académicos solo cuando haya evidencia. La fecha de creación/edición de Notion no sustituye a la fecha de clase.
5. Revisar si existen artefactos originales de la skill ya localizados. Si aparecen, compararlos con Notion para detectar ediciones posteriores antes de elegir la fuente.

Entregable: inventario revisable; todavía sin incorporar contenido a la biblioteca ni cambiar estados de sesiones.

## Fase 2: piloto de una semana

Elegir una semana representativa con dos clases, fórmulas, tablas y Mermaid. Capturar el contenido y su estructura en una ubicación privada y conservar los datos originales para repetir la conversión sin volver a consultar Notion.

La API oficial ofrece `GET /v1/pages/{page_id}/markdown`; se evaluará primero con la versión ya usada por el proyecto. No se presupone que su Markdown se pueda compilar directamente con VitePress. La API de bloques se usará para identificar límites de clases y recuperar o diagnosticar estructuras no convertidas.

Validar explícitamente respuestas truncadas, bloques desconocidos y páginas hijas: una referencia a una subpágina no equivale a haber recuperado su contenido. La recuperación debe preservar la posición de los bloques al completar subárboles.

Separar las clases por estructura y encabezados confirmados, no por cualquier divisor `---`. MIA tiene semanas 1–4, clases 1–2 y número global `(semana - 1) * 2 + clase`. Si una página no permite esa separación, conservar la evidencia y marcarla para revisión, sin inventar ni duplicar contenido compartido.

Convertir etiquetas propias de Notion, callouts, listas anidadas, tablas, ecuaciones inline y de bloque a representaciones compatibles. Conservar el código Mermaid. Identificar imágenes o adjuntos con URLs temporales y definir su copia estable antes de publicar. Revisar enlaces internos, rutas `file://` y etiquetas que VitePress pudiera interpretar como componentes; no enviar contenido privado o marcado sin normalizar al sitio.

Entregable: comparación de Notion y las dos clases resultantes, vista previa local y listado de pérdidas o decisiones pendientes. No se reescribe ni enriquece el texto durante la migración.

## Fase 3: incorporación local e integración del exportador

Después del piloto, implementar el registro de procedencia y el adaptador mínimo necesario. Un directorio privado dedicado, por ejemplo `data/imported/notion/`, contendrá las capturas y revisiones; el acceso al Markdown deberá tener controles de ruta, tamaño y hash equivalentes a los apuntes actuales.

Separar captura/conversión de aplicación: primero generar una propuesta o `dry-run`; luego incorporar exactamente esa captura validada, con backup y auditoría local. Un cambio remoto posterior exige otra captura y una revisión nueva.

Definir una identidad académica única por programa, cohorte, ID de módulo, semana y clase. Si aparece también un apunte del flujo actual, presentar el conflicto y requerir una selección explícita. No elegir silenciosamente por fecha ni generar dos páginas para la misma clase. La integración debe cubrir las validaciones de numeración, no solo añadir archivos al final del exportador.

La importación no crea trabajos de descarga, generación ni publicación; tampoco simula una transcripción completada. Una fecha académica desconocida se muestra como no disponible, con los cambios mínimos necesarios en el catálogo y encabezado web.

La misma fuente y versión de conversor no generan nuevas revisiones al repetir la operación. Un cambio de fuente o conversión genera un diff y una revisión nueva, conservando la anterior. Una captura parcial o un error de permisos no elimina apuntes previamente importados. La convivencia futura con sesiones Moodle debe resolver coincidencias por identidad académica, sin crear recursos sintéticos que luego dupliquen sesiones.

## Fase 4: recuperación por módulo

Aplicar el proceso módulo a módulo y registrar cuántas páginas y clases se encontraron, importaron o dejaron pendientes. Como referencia, siete módulos completos representarían 28 semanas y 56 clases; el inventario determinará la cobertura real, incluyendo posibles semanas parciales.

Conservar las fuentes locales existentes y la exportación DCC. No interpretar el estado incompleto de un módulo como permiso para inventar contenido. El exportador solo usará revisiones importadas que hayan superado las comprobaciones.

## Fase 5: verificación y exportación

- Probar separación de clases y fidelidad de tablas, fórmulas, código y Mermaid con capturas representativas.
- Comprobar idempotencia, actualización de revisiones, conflictos con fuentes locales y ausencia de borrado ante lecturas parciales.
- Verificar que importar no realiza escrituras remotas ni crea asociaciones de propiedad de bloques o trabajos automáticos.
- Comprobar convivencia con un descubrimiento posterior de Moodle y estabilidad de URLs.
- Ejecutar `web:check`, construcción con subruta y revisión visual de páginas representativas y sus descargas.
- Comprobar que solo los artefactos destinados a la web pasan a `content/`; las capturas privadas y metadatos internos permanecen fuera de Git.

La exportación y el despliegue siguen siendo operaciones explícitas. El objetivo se cumple cuando las clases recuperadas están accesibles en la web en el orden académico correcto, con procedencia local verificable y sin duplicados.

## Complejidad y decisiones abiertas

Complejidad provisional: media. La lectura reutiliza infraestructura existente; el mayor trabajo está en la fidelidad de conversión, la división de clases y la integración de apuntes sin sesiones locales. No se fija una estimación de implementación hasta inspeccionar el piloto.

Pendientes: páginas históricas accesibles, correspondencia de numeración, formato real de las semanas, disponibilidad de fechas y adjuntos, y resolución del contenido compartido entre clases. El primer hito recomendado es un inventario de solo lectura y un piloto, antes de implementar la recuperación masiva.

## Referencias

- Código: `src/academic_automation/notion/client.py`, `notion/inspection.py`, `services/artifacts.py`, `services/web_export.py`, `database/models.py`.
- Documentación local: `docs/notion.md`, `docs/web.md`, `docs/codex.md`.
- [Notion: recuperar una página como Markdown](https://developers.notion.com/reference/retrieve-page-markdown).
- [Notion: formato Markdown, tipos soportados, truncamiento y archivos](https://developers.notion.com/guides/data-apis/working-with-markdown-content).
