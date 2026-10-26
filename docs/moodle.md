# Moodle: sesión e inspección

El 17/10/2026 se inspeccionaron el catálogo, la sección de sesiones síncronas del curso 559 y el recurso 32389 desde Chrome autenticado. Se observaron tarjetas con el prefijo de cohorte repetido y enlaces cuyo texto incluye `Nombre del curso`; el parser reconoce ambos formatos y conserva el nombre completo frente al truncado. Se verificaron las etiquetas accesibles del filtro de agrupación, los enlaces de sección y el reproductor multimedia Moodle. Tras reiniciar el worker se verificó una sincronización real: tres sesiones y tres videos identificados, además de una segunda sincronización sin duplicados.

```bash
uv run academic moodle-login
```

Se abre Chromium visible. Introduzca sus credenciales y resuelva cualquier MFA o CAPTCHA personalmente. Al terminar, pulse Enter en la terminal. El programa vuelve al catálogo, comprueba que no redirija a login ni exista un campo de contraseña y guarda `data/private/moodle-state.json` con permisos 0600. El directorio `data/` tiene 0700. No se almacenan contraseñas en SQLite ni se muestran cookies.

Para renovar una sesión expirada, ejecute el mismo comando. El lock del navegador impide hacerlo a la vez que una sincronización. Un error `MOODLE_SESSION_EXPIRED` o `MOODLE_LOGIN_REQUIRED` requiere intervención; no se intenta adivinar contraseñas ni superar restricciones.

```bash
uv run academic moodle-inspect
uv run academic moodle-inspect --url 'https://soe.uagrm.edu.bo/virtual/course/view.php?id=559'
```

El inspector muestra títulos, rutas de enlaces y metadatos de cursos, sin valores de formularios ni parámetros sensibles. Para inspección visual más completa puede usar las herramientas de desarrollo de Chromium durante `moodle-login`.

Para diagnosticar sin esperar al backoff de un trabajo, ejecute `uv run academic moodle-inspect` en otra terminal desde el proyecto. Hace una sola lectura supervisada, utilizando la sesión guardada y el código actual. No procesa clases ni escribe en Notion. El navegador del worker y el inspector comparten un bloqueo; `MOODLE_BROWSER_BUSY` significa que debe esperar a que termine la lectura en curso.

Cada ejecución actualizada escribe `data/private/moodle-progress.json` con permisos 0600 antes de las operaciones. Contiene revisión del cliente (`recordings-9`), PID, hora UTC, operación y código de error, sin URL, cookies ni mensajes originales de Playwright. Este registro no depende de poder leer el DOM. Permite distinguir un proceso antiguo de un timeout de navegación (`MOODLE_NAVIGATION_TIMEOUT`), espera de página o extracción de enlaces. Si la inspección falla con un error conocido, el CLI muestra JSON con el código y la ruta del diagnóstico, y devuelve código de salida 1.

El catálogo espera primero `[data-region="myoverview"][data-init="true"]`, observado en el DOM autenticado. Este atributo indica que Moodle inicializó los manejadores del bloque: `DOMContentLoaded` por sí solo no garantiza que el desplegable responda. La opción `Todos` se consulta incluso cuando el menú está cerrado y no se pulsa si ya tiene `aria-current="true"`. Esta espera solo afecta al catálogo, no a las páginas de recursos.

Después espera la aparición de enlaces de curso cargados mediante JavaScript. Si falla la inicialización, el filtro o el reconocimiento de cursos, guarda `data/private/moodle-catalog-inspection.json` con permisos 0600: contiene la operación que falló, textos de enlaces de curso, sus IDs y resultados del parser. No contiene HTML bruto, cookies, valores de formularios ni parámetros de URL distintos del ID de curso. El archivo permite revisar una nueva variante del DOM sin exportar la sesión autenticada.

`MOODLE_CATALOG_READY_TIMEOUT` indica inicialización pendiente y admite reintento con backoff; `MOODLE_CATALOG_FILTER_TIMEOUT` requiere revisar los controles; `MOODLE_CATALOG_DOM_REQUIRES_INSPECTION` indica que no aparecieron enlaces o no se reconocieron módulos. El diagnóstico distingue `catalog_ready`, `catalog_filter_state`, `catalog_filter_open`, `catalog_filter_select` y `catalog_courses`. El timeout histórico `MOODLE_TIMEOUT` no conservaba esa distinción, por lo que no permite confirmar retrospectivamente cuál de esos pasos falló.

Configure `config/moodle-selectors.json` solo después de observar el DOM:

| Campo | Uso |
| --- | --- |
| `catalog_container` | Contenedor único del listado, si hace falta limitar enlaces |
| `catalog_next` | Botón de siguiente página, si el catálogo está paginado |
| `catalog_ready_selector` | Marcador de inicialización JavaScript exclusivo del catálogo |
| `catalog_grouping_label` | Etiqueta observada del desplegable de agrupación |
| `catalog_all_courses_label` | Etiqueta observada de la opción de todos los cursos |
| `recordings_section` | Contenedor único de Sesiones Síncronas, si hace falta limitar recursos |
| `ready_selector` | Espera opcional en todas las páginas Moodle; no colocar aquí un marcador exclusivo del catálogo |

Un selector CSS vacío significa extracción genérica. Las etiquetas de agrupación configuradas corresponden a `Menú desplegable de agrupación` y `Mostrar todos los cursos excepto los cursos archivados`, observadas en la cuenta real; se selecciona esa opción para incluir cursos pasados y futuros frente al filtro inicial `En progreso`. Los cursos eliminados de la vista/archivados tienen una opción separada en Moodle y no forman parte de ese filtro. Si el catálogo pagina mediante botones sin enlaces, configure `catalog_next` tras inspección; en la vista inspeccionada, el tamaño de página mostraba `Todos`. **La completitud del catálogo extraído automáticamente necesita validación tras reiniciar el worker.** No se interpreta un catálogo sin coincidencias como una sincronización vacía exitosa.

El módulo 559 utiliza el formato de mosaicos: la página inicial enlaza a `SESIONES SÍNCRONAS` mediante `course/view.php?id=559&section=2`, y los recursos aparecen al abrir esa sección. El adaptador obtiene ese enlace de la página; no fija el número de sección. Solo sigue enlaces del mismo curso y origen, deduplica los repetidos y detiene la sincronización si encuentra varias secciones candidatas distintas. También admite cursos que muestran directamente sus grabaciones. Espera los enlaces cargados mediante JavaScript antes de extraerlos.

Los recursos se reconocen por `Grabaciones de sesiones síncronas - dd/mm/aaaa`. También se admite el formato histórico observado el 20/10/2026 en el curso DCC 195: `Grabación de sesión síncrona - SEMANA 1 (23/03/24)` y `Grabación de sesión síncrona - ENCUENTRO 3 (20/04/24)`, con singular/plural y variantes sin tilde. Desde `recordings-8`, la preposición «de» es opcional: se reconoce también `Grabación sesión síncrona - 13/06/2026`, observado en DCC 505. La misma regla se usa para esperar los enlaces del navegador y extraer sus metadatos. Los años de dos dígitos se interpretan explícitamente en 2000–2099; las fechas inexistentes se descartan. SEMANA/ENCUENTRO se conservan en el título, pero la secuencia sigue calculándose por fecha y clave estable, sin adoptar esos números como identidad ni asignación automática. El reconocimiento de las grabaciones de esos cursos se verificó con sus diagnósticos guardados; los videos y la completitud de cada curso requieren una nueva sincronización real.

Se guarda la ruta e ID Moodle como identidad estable. En el recurso 32389 se verificó un reproductor Moodle Video.js con `data-setup-lazy`, cuyo JSON contiene `sources[].src`. El adaptador lee ese atributo, los enlaces y las fuentes multimedia/iframes sin reproducir el video ni esperar a que YouTube genere su iframe. Los videos se normalizan desde embed, watch, youtu.be y youtube-nocookie. Si hay varios videos en un recurso, se detiene para revisión; no se escoge uno arbitrariamente. Un recurso sin video identificable puede registrarse como `DISCOVERED` para otra sincronización.

Ante `MOODLE_MULTIPLE_VIDEOS`, se guarda `data/private/moodle-videos-ID-inspection.json` con permiso 0600. Identifica el recurso, fecha, ruta final tras la navegación y videos distintos, indicando si se encontraron en la URL final (`page`), iframe/video/source (`media`), configuración del reproductor (`player`) o enlaces (`links`). Las URLs YouTube se normalizan sin parámetros adicionales; no se guarda HTML bruto, cookies ni configuración completa del reproductor. El mismo video en varios formatos no produce un conflicto. La ubicación de recursos dentro de las semanas no es por sí misma un error; el conflicto significa varios IDs dentro del recurso abierto, cuya selección aún necesita inspección.

Para obtener esa evidencia sin crear sesiones ni iniciar transcripciones/Codex/Notion, ejecute desde el host:

```bash
uv run academic moodle-recordings-inspect --module-id 197
```

El comando carga la sesión guardada, comparte el bloqueo de navegador y usa el código actual sin reiniciar los servicios. Muestra solo el resumen y la ruta del informe; devuelve código 1 ante conflicto y 0 si la extracción termina. Una extracción exitosa mediante este comando no sincroniza SQLite: después debe solicitar la sincronización normal. `MOODLE_MULTIPLE_VIDEOS` no se resuelve eligiendo automáticamente el primer video ni descartando enlaces sin verificar su procedencia.

## Recursos descartados confirmados

`config/moodle-ignored-resources.json` registra excepciones explícitas por ID de curso y clave estable de recurso, con un motivo obligatorio. `ACADEMIC_MOODLE_IGNORED_RESOURCES_FILE` permite usar otro archivo. El cliente `recordings-9` filtra esos recursos antes de abrir sus páginas o identificar sus videos; un recurso descartado no vuelve a crear una sesión en sincronizaciones futuras. La excepción solo afecta al curso indicado y no se aplica automáticamente a otros videos cortos.

El recurso `/virtual/mod/page/view.php:23759` de MIA 378 (23/10/2025, video `QVTbkmfPYbk`) fue confirmado por el usuario como un fragmento de unos diez segundos que no corresponde a una clase. Se conserva su motivo en la configuración y se retiró su sesión local con backup y auditoría; las ocho clases válidas mantienen sus IDs y ocupan las cuatro semanas MIA en orden cronológico.

Una configuración JSON inválida detiene el descubrimiento con `MOODLE_IGNORED_RESOURCES_CONFIG_INVALID`. Un archivo ausente equivale a ninguna excepción; si todos los recursos reconocidos están descartados explícitamente, se devuelve un descubrimiento vacío válido. Modificar este archivo no borra por sí solo sesiones existentes: cualquier retiro de datos ya importados necesita revisar sus artefactos y referencias. Después de actualizar el código hay que reiniciar el worker para que cargue `recordings-9`; el CLI `academic sync-recordings` carga código nuevo en cada ejecución.

## Clases divididas en partes

Una clase confirmada con varias partes se conserva como **una sesión académica**, con varias filas `recordings` ordenadas por `position`. El recurso Moodle conserva su identidad, la secuencia académica cuenta la clase una sola vez y Codex produce un único apunte. No se crean clases ni páginas Notion por parte.

La excepción se registra en `data/private/moodle-recording-parts.json` (0600), usando el ID de curso y la clave estable del recurso. La siguiente configuración fue confirmada por el usuario para el curso 197; el orden es explícito, no alfabético ni derivado del orden de los candidatos:

```json
{
  "197": {
    "/virtual/mod/page/view.php:11143": ["6dP-ykbwEIg", "_W__qxvQA_4"]
  }
}
```

El cliente relee esta configuración en cada sincronización. Solo admite las partes si el conjunto completo de IDs encontrados coincide exactamente con lo configurado; videos nuevos, ausentes o configuración inconsistente provocan `MOODLE_RECORDING_PARTS_CHANGED`. Otros recursos con múltiples videos siguen requiriendo revisión. No configure partes por semejanza de fechas/títulos: confirme primero que pertenecen a la misma clase y cuál va antes.

La migración `ba91c321ab02` transforma las grabaciones anteriores en parte 1 sin cambiar IDs ni artefactos. Aplique `uv run alembic upgrade head` con los servicios detenidos, o reinicie mediante `scripts/start-host.sh`, que la ejecuta antes del arranque. El downgrade se detiene si existen sesiones con varias partes para evitar pérdida de datos. Una sincronización repetida conserva partes y sesión; un cambio posterior de videos/orden requiere revisión, especialmente si ya hay apuntes generados.

El dashboard muestra el número de partes y los enlaces ordenados al elegir la sesión para una acción. La API conserva `youtube_url` como primer enlace para compatibilidad y añade `recordings` con todos los videos y sus posiciones. El resultado de descubrimiento cuenta recursos/clases en `recordings_found` y videos físicos en `videos_identified`.

## Vinculación manual desde el dashboard

No hace falta adaptar selectores ni editar archivos de configuración para enlazar clases de cursos históricos. En **Sesiones**, seleccione el módulo:

1. Si la sesión ya aparece (también si está en `REVIEW_REQUIRED`), elíjala en **Sesión para una acción**, abra **Vincular grabaciones manualmente** y pegue uno o varios enlaces YouTube, uno por línea. El orden de las líneas es el orden de las partes. Pulse **Guardar vínculo manual**.
2. Si la sesión falta, abra **Crear sesión y vincular grabaciones**, elija una posición libre entre 1 y 8, indique la fecha real de la clase y pegue sus enlaces en orden. El título es opcional. La asignación se calcula para DCC o MIA y se reserva manualmente; crearla no renumera las demás sesiones.
3. El vínculo queda guardado en SQLite, visible como **Manual** en la tabla, con auditoría en Historial. Pulse **Procesar** para usar el pipeline habitual: un video se procesa directamente; varias partes conservan sus originales y producen una única transcripción y un único apunte de clase.

Se aceptan entre uno y ocho videos distintos por sesión; se normalizan URLs `watch`, `embed`, `youtu.be` y `youtube-nocookie`, eliminando parámetros de reproducción como `t`. No se consultan servicios externos al guardar. No se puede reutilizar un video ya asociado a otra sesión o módulo. La API exige token administrador y bloquea cambios mientras el módulo tenga trabajos activos, incluso pendientes o en espera de reintento.

La sincronización respeta los enlaces manuales de un recurso existente. Si una sesión fue creada manualmente y Moodle descubre posteriormente los mismos videos (incluso una actividad por parte), los reconoce y no crea otra sesión. Una actividad que mezcle videos de varias sesiones o incluya videos desconocidos sigue requiriendo revisión. Los fallos de navegación/autenticación o estructura de Moodle aún pueden dejar el trabajo de sincronización en revisión; no impiden procesar sesiones manuales que ya están identificadas.

Puede corregir enlaces y orden antes de descargar archivos. Cuando existen descargas completas o parciales, apuntes o publicación, el backend rechaza sustituir o reordenar videos para conservar la procedencia del material; guardar exactamente los mismos videos permite fijar como manual un vínculo existente sin invalidarlo. Cambiar fecha/semana/clase continúa usando **Corregir asignación académica** y sus controles de reconciliación. No se modifican ni publican páginas de Notion al vincular. Las selecciones y los modos `ALL`, `NEW_ONLY` y `MANUAL` mantienen su comportamiento: guardar no encola trabajo; un próximo despacho automático puede procesar la sesión si el módulo y su modo lo autorizan.

Esta función incorpora la migración `c3ad19e62b04`, que conserva sesiones y artefactos existentes con la nueva marca desactivada inicialmente. Detenga los servicios y arranque `bash scripts/start-host.sh`: migra antes de iniciar API, worker y dashboard. La configuración privada de excepciones por recurso sigue siendo compatible, pero la interfaz es el flujo recomendado. No se permite bajar de esta migración cuando hay vínculos manuales para evitar perder su protección.

## Sincronización parcial y comando directo

La sincronización normal consulta todos los recursos aunque encuentre videos ambiguos sin configurar. Guarda las clases identificadas y registra las ambiguas como sesiones con descubrimiento `REVIEW_REQUIRED`, sin elegir sus videos. El trabajo queda en revisión e incluye `result.reviews`, pero las demás sesiones siguen disponibles para procesar. La asignación cronológica incluye también las sesiones pendientes para conservar sus posiciones. Siguen vigentes los controles de ambigüedad de sección, cambio de partes ya configuradas y reconciliación académica: esos fallos no se ignoran.

Los diagnósticos por recurso se conservan en `moodle-videos-CURSO-RECURSO-inspection.json` además del informe más reciente. La vista Sesiones muestra `Descubrimiento` y bloquea las acciones de una grabación pendiente de revisar; Historial explica que las demás ya están guardadas.

Para ejecutar la lectura y guardado con el código actual sin depender del worker residente:

```bash
uv run academic sync-recordings --module-id 197
```

Este comando **sí guarda sesiones en SQLite** y añade un trabajo final al historial; se diferencia de `moodle-recordings-inspect`, que solo inspecciona. Usa el mismo cliente, bloqueo Moodle, servicios de persistencia y restricciones de duplicados; rechaza módulos con trabajos activos. No habilita la automatización ni inicia descargas, Codex o publicaciones. No requiere reiniciar la API para que las sesiones guardadas aparezcan al actualizar el dashboard. Puede devolver `REVIEW_REQUIRED` junto con sesiones nuevas: eso significa que se guardaron las identificadas y quedan recursos concretos por resolver. Un fallo de red/autenticación antes de terminar la lectura no se trata como una sincronización parcial válida. Para usar la misma conducta desde el botón habitual y cargar los nuevos controles de interfaz/API, reinicie los servicios cuando corresponda.

Si no se reconocen recursos, el cliente produce `MOODLE_RECORDINGS_DOM_REQUIRES_INSPECTION`, guarda `data/private/moodle-recordings-559-inspection.json` (con el ID del curso correspondiente) con permisos 0600 y solicita revisión. El informe contiene rutas e IDs de actividades y títulos sanitizados; no contiene parámetros sensibles ni HTML bruto. Esta medida conservadora también requiere revisar módulos que legítimamente todavía no publicaron grabaciones: no se interpreta automáticamente una vista sin coincidencias como extracción válida. El resultado de un trabajo exitoso distingue `recordings_found`, `new_sessions` y `videos_identified`; cero sesiones nuevas puede significar que ya existían.

No se depende del día de la semana. Las grabaciones se ordenan por fecha y clave de recurso. Si aparece una grabación anterior, se recalcula la propuesta. Cuando afecta contenido generado o publicado, se detiene el módulo y se solicita confirmación desde el dashboard. Las posiciones todavía no descubiertas se muestran como expectativas, sin crear videos o sesiones ficticios.

No se ha asumido ningún endpoint interno de Moodle. El extractor utiliza enlaces independientes observados, incluidos los de las secciones que la interfaz abre como modal. Una sección o recurso exclusivamente modal sin enlace independiente todavía necesitará adaptación tras inspección.

Referencias: [estado de autenticación Playwright](https://playwright.dev/python/docs/auth), [inicialización del bloque de cursos Moodle](https://github.com/moodle/moodle/blob/MOODLE_405_STABLE/blocks/myoverview/amd/src/view.js).
