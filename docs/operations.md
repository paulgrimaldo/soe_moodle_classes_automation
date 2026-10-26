# Operación y API

## Procesos

La API no ejecuta tareas largas en la solicitud HTTP. Persiste un `ProcessingJob`, devuelve 202 e ID, y el worker del host reclama trabajos. No se usan `BackgroundTasks`, Redis ni Celery.

El worker inicial ejecuta un trabajo a la vez. Esto respeta el máximo de un navegador Moodle, dos descargas y un Codex. Los adaptadores además tienen semáforos de dos descargas y un Codex; no se necesita aumentar paralelismo para ocho clases por módulo. El bloqueo de archivo permite solo un worker por directorio de datos. Las llamadas Notion se espacian y sus lecturas paginan.

SQLite usa WAL, claves foráneas y `busy_timeout`. Una restricción parcial impide dos trabajos activos para la misma sesión, incluso si llegan solicitudes de procesamiento y publicación al mismo tiempo. Un catálogo repetido tampoco se encola dos veces mientras está activo. Trabajos finalizados pueden volver a solicitarse: los servicios comprueban artefactos y hashes antes de repetir efectos.

Mantenga `.env`, `data/` y los volúmenes n8n fuera del control de versiones. Respalde SQLite con su API de backup o con el worker detenido; no copie únicamente el archivo principal mientras WAL está activo. Conserve también los artefactos y el volumen n8n cifrado junto con su clave en un lugar privado.

## Recuperación

Al obtener el lock exclusivo, el worker recupera trabajos `RUNNING`. Los anteriores a Notion vuelven a cola y reutilizan transcripciones válidas. Una generación interrumpida tiene nuevo directorio de intento. Una escritura Notion o reconciliación interrumpida pasa a `REVIEW_REQUIRED`, sin repetir efectos remotos inciertos.

Los fallos temporales reconocidos usan 15, 30 y 60 minutos de espera entre un máximo predeterminado de cuatro intentos. Configure `ACADEMIC_RETRY_BASE_SECONDS` y `ACADEMIC_MAX_ATTEMPTS`. Autenticación expirada, permisos, respuestas académicas inválidas y conflictos requieren intervención. Los errores desconocidos no se reintentan automáticamente.

En transcripciones, `YOUTUBE_AUTH_REQUIRED` indica una solicitud de inicio de sesión o un fallo al acceder a las cookies; los mensajes informativos `Extracting cookies` y `Extracted … cookies` no son errores. Si YouTube no ofrece subtítulos para el idioma solicitado (`es-orig` por defecto), el resultado es `SUBTITLES_NOT_AVAILABLE_YET` y admite reintentos. Esto también puede significar que el video no tiene subtítulos; el reintento no los genera. Para comprobar los idiomas disponibles use `yt-dlp --cookies-from-browser chrome --skip-download --list-subs 'URL_DEL_VIDEO'` ([opciones oficiales](https://github.com/yt-dlp/yt-dlp#subtitle-options)). Un fallo HTTP temporal conserva `YOUTUBE_TRANSIENT_ERROR`, aunque el script añada después su mensaje genérico de que no pudo obtener subtítulos.

En Historial, `RETRY_WAIT` significa que el trabajo sigue activo y espera hasta `available_at`; las fechas se muestran en UTC. Pedir otra sincronización del mismo catálogo devuelve el trabajo activo sin adelantar el backoff. Después de cambiar el código o los selectores, detenga `scripts/start-host.sh` con Ctrl+C y vuelva a iniciarlo para cargar los cambios: el trabajo pendiente se conserva y el worker lo reclama cuando corresponde. Los errores de trabajos anteriores permanecen como historial, aunque una ejecución posterior termine correctamente.

La transcripción, el procesamiento y la publicación tienen estados independientes. Un fallo Codex conserva TXT y VTT; un fallo Notion conserva el Markdown. Un reprocesamiento conserva revisiones anteriores y deja la nueva publicación pendiente. `FAILED` y `REVIEW_REQUIRED` no destruyen artefactos. `DISCOVERED` sin video no puede procesarse hasta otra sincronización que identifique el iframe.

En clases divididas, el adaptador reutiliza el script Bash original para cada video, en orden y con concurrencia conservadora. Conserva TXT/VTT originales y logs en `data/transcripts/SESION/parts/VIDEO_ID/`. Después crea `combined/transcript.txt`, con marcas `PARTE N DE TOTAL`, y un VTT derivado. El VTT derivado desplaza los tiempos según el final de los subtítulos de la parte anterior; no representa una duración verificada del video. Los VTT originales conservan los tiempos de cada video. El manifiesto registra IDs, orden, rutas y hashes de las fuentes y del contenido combinado, y se guarda atómicamente después de cada parte.

Si falla la parte 2, el siguiente intento conserva la parte 1 válida y descarga solo la pendiente. No se envía una clase incompleta a Codex. Un archivo original modificado o un manifiesto con otro orden bloquean el procesamiento, incluso durante un reprocesamiento. La fuente combinada también está sujeta al límite de longitud de Codex y nunca se trunca. Una clase con varias partes mantiene un solo `TranscriptArtifact`, una generación y una sección Notion.

La desactivación impide despachar nuevos trabajos automáticos y cancela los que todavía no comenzaron. Un trabajo que ya está ejecutándose puede terminar; no se mata un proceso a mitad de una escritura. El procesamiento explícito desde el dashboard sigue siendo una acción administrativa permitida.

## Endpoints

Autenticación: `Authorization: Bearer ...`. El token administrador habilita todas las operaciones; el token n8n puede consultar, sincronizar, despachar sesiones ya autorizadas y consumir eventos. n8n no puede cambiar preferencias, vincular páginas ni publicar explícitamente.

| Método | Ruta | Función |
| --- | --- | --- |
| GET | `/health` | Salud pública y consulta DB |
| GET | `/stats` | Contadores y última sincronización |
| POST | `/sync/catalog` | Encolar descubrimiento del catálogo |
| POST | `/sync/modules/{id}` | Encolar grabaciones del ID Moodle |
| POST | `/sync/recordings` | Encolar módulos habilitados |
| GET | `/modules`, `/modules/{id}` | Catálogo persistido |
| PATCH | `/modules/{id}` | Activación, modo y autorización automática |
| GET | `/modules/{id}/sessions` | Grabaciones disponibles y estados |
| POST | `/modules/{id}/sessions/manual` | Crear sesión faltante con fecha, número y videos ordenados; administrador |
| PUT | `/sessions/{id}/recordings` | Vincular uno o varios videos, con prioridad manual; administrador |
| GET | `/sessions/{id}/notes` | Última revisión Markdown guardada y metadatos; solo administrador |
| GET | `/sessions/{id}/academic-review` | Previsualizar respuesta rechazada, fuente y hallazgos; administrador |
| POST | `/sessions/{id}/academic-review/validate` | Validar una corrección Markdown sin guardarla ni ejecutar Codex; administrador |
| POST | `/sessions/{id}/academic-review/approve` | Confirmar revisión y guardar paquete auditado sin Codex ni Notion; administrador |
| PATCH | `/sessions/{id}` | Selección, exclusión y corrección/propuesta |
| POST | `/sessions/{id}/process` | Transcripción + Codex, reutilizando resultados |
| POST | `/sessions/{id}/retry` | Reintentar la etapa pendiente recuperable |
| POST | `/sessions/{id}/reprocess` | Nueva generación Codex, conservando TXT/VTT |
| POST | `/sessions/{id}/publish` | Publicar o actualizar una sección |
| POST | `/modules/{id}/sessions/bulk/preview` | Consultar compatibilidad de la selección por lote; administrador |
| POST | `/modules/{id}/sessions/bulk` | Encolar atómicamente una operación por cada clase seleccionada; administrador |
| POST | `/processing/dispatch` | Encolar sesiones elegibles aún pendientes |
| GET | `/jobs`, `/jobs/{id}` | Historial y logs de etapa |
| POST | `/notion/modules/{id}/link` | Validar/asociar módulo o semana |
| POST | `/modules/{id}/reconcile` | Confirmar propuesta y encolar traslado |
| GET | `/sessions/{id}/notion/review` | Consultar bloques para revisar conflicto |
| POST | `/sessions/{id}/notion/resolve` | Adoptar IDs revisados, autorizando sustitución posterior |
| POST | `/monitor/events` | Fallos/revisiones o pendientes >3 h aún no reportados |

Las respuestas de trabajos incluyen estado, intentos, etapa, fechas, modelo explícito si existe, versión/hash de skill y resultado con URL Notion cuando hay publicación. `GET /jobs?status=FAILED` filtra; el límite máximo es 500.

`ALL` procesa grabaciones disponibles y futuras. `NEW_ONLY` fija su marca al cambiar al modo y la conserva al sincronizar o desactivar/reactivar el módulo. Para reiniciar la marca, cambie primero a otro modo y después a `NEW_ONLY`. `MANUAL` usa las clases seleccionadas. En todos los casos se respeta exclusión, habilitación y revisión del módulo. La acción individual **Procesar** es una autorización explícita independiente de la selección automática.

Sincronizar el catálogo no descubre sesiones ni habilita módulos. Para una primera consulta, abra **Módulos**, seleccione el módulo y pulse **Sincronizar grabaciones del módulo**: esta acción explícita también funciona con la automatización desactivada. Consulte el trabajo `recordings` en **Historial** y después abra **Sesiones**. Para usar el descubrimiento general, marque **Habilitar automatización** y pulse **Guardar preferencias** para cada módulo elegido; deje `MANUAL` si desea seleccionar las clases individualmente. El botón general informa cuando no hay módulos habilitados y muestra los IDs de los trabajos cuando se encolan.

En **Sesiones**, la columna **Selección** de la tabla controla la elegibilidad de los despachos en modo `MANUAL` y debe guardarse. Los botones individuales **Procesar**, **Reintentar**, **Reprocesar Codex** y **Publicar / actualizar Notion** usan exclusivamente el selector **Sesión para una acción** situado debajo de la tabla. Este selector exige una elección explícita, conserva el ID estable del destino y muestra fecha, semana, clase y estados antes de los botones. No se elige la primera clase automáticamente. El mensaje de trabajo solicitado también identifica número y fecha. Después de que el worker termine, pulse **Actualizar** para volver a consultar los estados.

En Módulos, el formulario Notion precarga la URL persistida de la página del módulo y muestra **Abrir módulo en Notion**. Volver al panel consulta los vínculos de SQLite mediante la API; cada módulo conserva sus propios campos y un módulo sin vínculo abre el campo vacío.

## Operaciones por lote

La vista **Sesiones** incluye **Operaciones por lote** debajo de las acciones individuales. Su selector es independiente del selector individual y de la columna Selección que autoriza el modo MANUAL: ninguna de las preferencias existentes se modifica al usarlo. Seleccione de una a ocho sesiones del módulo; se muestran sus estados y los motivos por los que una operación está deshabilitada. Solo se incluyen sesiones reales, nunca posiciones aún no descubiertas.

Las sesiones elegidas deben tener exactamente el mismo estado en las cuatro dimensiones: descubrimiento, transcripción, procesamiento Codex y publicación Notion. Todas deben estar identificadas, tener videos, una asignación académica válida y no estar excluidas. Se bloquea el lote si el módulo tiene revisión pendiente, una sincronización/reconciliación activa o alguna clase seleccionada tiene trabajos en cola, ejecutándose o esperando reintento. Otras clases del módulo pueden tener trabajos de procesamiento/publicación; el worker conserva su concurrencia habitual.

| Operación | Compatibilidad adicional |
| --- | --- |
| Procesar lote | Transcripción `TRANSCRIPT_PENDING`, `TRANSCRIPT_READY` o `FAILED`; Codex `PENDING` o `FAILED`; Notion `PENDING`. Descarga cuando hace falta y genera apuntes. |
| Procesar / reprocesar Codex en lote | Transcripción `TRANSCRIPT_READY` con artefacto registrado; Codex `PENDING`, `FAILED` o `PROCESSED`; Notion `PENDING`, `FAILED` o `PUBLISHED`. Reutiliza TXT/VTT y fuerza una generación. |
| Publicar / actualizar Notion en lote | Transcripción `TRANSCRIPT_READY`, Codex `PROCESSED`, Markdown y hash registrados; Notion `PENDING`, `FAILED` o `PUBLISHED`; publicación global habilitada. |

`REVIEW_REQUIRED`, `PROCESSING` y `PUBLISHING` no se omiten ni se resuelven en lote. La validez de archivos y los conflictos remotos se vuelven a comprobar durante cada trabajo mediante el pipeline existente. El botón de publicar constituye autorización explícita para las clases elegidas; procesar/Codex se encolan como acciones manuales (`automatic=false`) y no publican automáticamente.

El preview recibe `{"session_ids":["UUID-1","UUID-2"]}` y devuelve `homogeneous`, estados y `operations` con `compatible`/`issues` para cada acción. Solo consulta SQLite. El envío agrega `operation` (`process`, `reprocess` o `publish`) y un `request_id` UUID. El backend vuelve a validar bajo `BEGIN IMMEDIATE` y persiste todos los trabajos en una sola transacción; si falla la selección o una escritura, no agrega ninguno. Una selección incompatible devuelve 409 con razones, entradas inválidas 422 y un módulo inexistente 404. Los endpoints requieren administrador; n8n no tiene acceso.

Una respuesta 202 devuelve `batch_id` y los trabajos individuales con ID y sesión. El registro terminal `bulk_dispatch` del Historial certifica únicamente el **encolado**, no que las clases hayan terminado. Sus `result.job_ids` permiten seguir cada trabajo. El worker ejecuta los trabajos ordinarios; un fallo posterior en uno no deshace ni cancela los demás. Se pueden consultar los estados actuales en Historial y Sesiones.

El `request_id` se conserva como comprobante en SQLite. Reenviar exactamente el mismo ID, módulo, selección y operación devuelve los mismos trabajos, incluso después de que terminen. Reutilizar el ID para otra petición se rechaza; para una operación nueva, genere otro UUID. No hay cambios de esquema ni un scheduler adicional. Reinicie la API y recargue el dashboard para disponer de la función; las acciones individuales no cambian.

## Vincular grabaciones manualmente

En Sesiones se puede completar una clase existente o crear una posición aún no descubierta, incluso en módulos deshabilitados. Consulte el [flujo de vinculación manual](moodle.md#vinculación-manual-desde-el-dashboard). Las dos operaciones son locales y rápidas; no encolan descargas, Codex ni Notion. Devuelven `session_id`, `changed`, `created`, `video_ids` ordenados y `audit_job_id` cuando hubo cambios. Repetir la misma asociación es idempotente.

El cuerpo de `PUT /sessions/{id}/recordings` es `{"youtube_urls":["https://youtu.be/22PANKY-2Fg","https://youtu.be/wqH05pvQnQ4"]}`. El POST agrega `number` (1..8), `class_date` (ISO) y `title` opcional. La respuesta 409 identifica posiciones ocupadas (`SESSION_SLOT_OCCUPIED`), videos de otra sesión (`VIDEO_LINKED_TO_OTHER_SESSION`), trabajos activos (`MODULE_HAS_ACTIVE_JOBS`) o material previo que impide cambiar fuentes (`MANUAL_RECORDINGS_ARTIFACTS_EXIST`). URLs inválidas, repetidas o listas fuera de 1..8 devuelven 422. No se aceptan rutas de archivos. La fecha y asignación de una sesión existente se corrigen por el PATCH habitual.

La marca `recordings_manual` pertenece a la sesión; el orden sigue en `recordings.position`. Un `BEGIN IMMEDIATE` serializa la asociación con los reclamos del worker. La auditoría terminal `manual_recordings` conserva los IDs anteriores/nuevos sin poder ser reclamada como trabajo. Transcripciones y artefactos parciales existentes bloquean cambios de fuentes; sus hashes y manifiestos siguen verificándose durante el procesamiento.

## Leer los apuntes en el dashboard

Abra **Apuntes**, seleccione el módulo y elija **Clase para leer**. La vista muestra fecha, semana/clase y revisión, ofrece **Vista previa**, **Markdown** y **Descargar Markdown**. Lee únicamente archivos existentes, sin ejecutar Codex ni publicar en Notion. Si hay un reprocesamiento en curso o fallido, sigue disponible la última revisión guardada y se muestra el estado actual. Si no hay revisiones, indica que primero debe procesarse una clase.

`GET /sessions/{id}/notes` exige el token administrador y no acepta una ruta suministrada por el cliente. El backend resuelve la ruta asociada en SQLite, restringe la lectura a Markdown dentro de `data/processed/` o `data/reconciled/`, incluyendo la comprobación del destino de enlaces simbólicos, limita la lectura a 5 MB y verifica el hash persistido. La respuesta no expone rutas del host. Los errores distinguen ausencia de apuntes/archivo (404), modificación o artefacto inválido (409) y tamaño excesivo (413).

La vista previa no habilita HTML arbitrario. Tablas, encabezados, código y fórmulas utilizan el renderizador Markdown de Streamlit; los delimitadores matemáticos `\[...\]` y `\(...\)` se adaptan solo para la presentación, sin alterar el Markdown original ni su descarga. Mermaid se conserva como código fuente, sin ejecutar scripts de diagramas ni cargar un renderizador externo. Después de instalar esta actualización, reinicie la API y recargue el dashboard para disponer de la nueva ruta.

## Revisar una salida rechazada de Codex

Cuando el procesamiento esté en `REVIEW_REQUIRED` y su última generación tenga `CODEX_OUTPUT_INVALID`, abra **Sesiones**, elija la clase en **Sesión para una acción** y use **Previsualizar y aprobar salida rechazada de Codex**. La revisión muestra la respuesta guardada aunque todavía no exista un paquete publicable en Apuntes. También funciona con rechazos anteriores a esta función si se conservan `request.json`, `response.json` y las transcripciones originales válidas.

1. Lea **Vista previa de la salida** y **Hallazgos y líneas**. Se muestran el diagnóstico original, la validación actual y cada coincidencia administrativa con campo, línea y contexto. **JSON original** y **Transcripción original** permiten contrastar el contenido.
2. Si hace falta una corrección, edite **Markdown para revisión** y pulse **Validar cambios sin Codex**. La edición permanece en la sesión del dashboard hasta aprobar; no modifica archivos originales. No se puede aprobar mientras haya cambios sin validar.
3. Si las coincidencias son falsos positivos académicos —por ejemplo, una proporción `60/20/20` identificada como fecha— confirme expresamente que revisó todos los hallazgos mostrados. La aprobación exceptúa únicamente esas coincidencias exactas. Si hay contenido administrativo real, elimínelo en el editor y vuelva a validar.
4. Escriba **Motivo de la aprobación** y pulse **Aprobar y guardar apuntes sin reprocesar**. El estado Codex pasa a `PROCESSED`, aumenta la revisión y el documento aparece en **Apuntes**. Publicar o actualizar Notion se solicita por separado. Un conflicto Notion pendiente se conserva.

La revisión usa los validadores de la skill instalada y no modifica su instalación. Contrato, identidad, secciones académicas, código, Mermaid, emojis y fórmulas mantienen sus comprobaciones. Un resultado `needs_review` no se promueve desde esta pantalla; JSON incompleto o inválido puede inspeccionarse pero necesita una salida estructurada válida. El editor permite corregir el Markdown, no reconstruir la identidad o el contrato JSON.

Los archivos de revisión se guardan en un directorio nuevo `data/processed/review-<solicitud>-<id>/`, con originales, respuesta revisada y `bundle/notes.md`. El trabajo fallido permanece en Historial y se agrega un trabajo terminal `academic_review` con motivo, hallazgos aprobados, hashes, trabajo de origen y revisión anterior. La lectura y validación no escriben archivos ni estados. La aprobación comprueba transcripciones/hashes y usa una transacción SQLite; bloquea trabajos activos del módulo y revisiones obsoletas. Si cambia el contenido, la asignación o la skill desde el preview, actualice y revise de nuevo.

Los POST reciben `source_job_id`, `expected_review_token` devueltos por el GET y `markdown` opcional. Aprobar agrega un UUID `request_id`, `acknowledge: true`, `reason` (mínimo ocho caracteres) y los `approved_finding_ids` exactos. Repetir la misma solicitud devuelve el comprobante existente; cambiarla exige otro UUID. n8n no puede usar estos endpoints. No se necesita migración nueva: reinicie la API y recargue Streamlit; si usa el lanzador conjunto, reinícielo cuando hayan terminado los trabajos activos.

## n8n

Los JSON importables contienen un disparador manual, un horario y una llamada HTTP. Toda la elegibilidad, deduplicación y recuperación reside en Python.

| Workflow | Intervalo inicial | Endpoint |
| --- | --- | --- |
| Catalog Discovery | Cada 6 horas | `/sync/catalog` |
| Recording Discovery | Cada hora | `/sync/recordings` |
| Academic Processing | Cada 30 minutos | `/processing/dispatch` |
| Error Monitoring | Cada hora | `/monitor/events` |

Compose inyecta `BACKEND_URL=http://host.docker.internal:8000` y `N8N_BACKEND_TOKEN`, que debe coincidir con `ACADEMIC_N8N_TOKEN`. El configurador local crea esa correspondencia. `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` permite las expresiones `$env`; use solo workflows de confianza en esta instancia personal. No se monta el directorio del host ni sus cookies.

Error Monitoring devuelve eventos deduplicados por trabajo, estado e intento; aparecen en la salida del nodo y el historial del backend. No envía mensajes externos. Puede añadir un canal propio posteriormente. La entrega actual es consumo único: si n8n pierde la respuesta después de consumirla, el evento no vuelve a emitirse; el fallo sigue visible en `/jobs` y en el dashboard. No se promete entrega garantizada de notificaciones.

Se validó sintaxis JSON y estructura de los workflows, además de `docker compose config`. La importación y programación en una instancia n8n real quedan por validar.

Referencia: [cambios de configuración n8n 2.0](https://docs.n8n.io/2-0-breaking-changes/).
