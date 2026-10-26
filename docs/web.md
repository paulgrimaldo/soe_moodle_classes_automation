# Biblioteca web DCC / MIA

El visor usa VitePress. Los apuntes publicados se guardan en `content/`, una carpeta versionable por Git. La configuración, componentes y estilos están en `web/`. El sitio construido se guarda en `web/.vitepress/dist/`, excluido de Git.

## Exportar y consultar

Desde la raíz del repositorio:

```bash
uv run academic export-web --program DCC
npm ci
npm run web:check
npm run web:dev
```

Antes de la primera exportación, complete **Módulos → Número de módulo para web → Guardar preferencias** para cada módulo con apuntes. Es un entero positivo asignado manualmente. La tabla distingue **Número Moodle** y **Número para web**; sincronizar el catálogo conserva el número manual. Para borrarlo, marque **Borrar número para web al guardar** y guarde las preferencias.

Esta función requiere la migración `d7a02cb94e61` (`uv run alembic upgrade head`) y reiniciar API y dashboard para cargar el código nuevo. El arranque habitual `bash scripts/start-host.sh` aplica las migraciones. La columna `export_number` comienza vacía: no se rellena a partir del ID, de Moodle ni de Notion.

Abra la dirección local que imprime VitePress. `web:dev` escucha en `127.0.0.1`; no necesita tener la API, el worker o Streamlit ejecutándose. Para incorporar clases nuevas, repita la exportación y reinicie VitePress para recargar su menú.

El comando usa la base SQLite y `data_dir` de la configuración habitual. Solo lee apuntes; no ejecuta Codex, descargas ni operaciones de Notion. El interruptor de publicación de Notion es independiente de esta exportación. Preparar archivos localmente no publica la web.

Para MIA, ejecute `uv run academic export-web --program MIA`. Ambos programas pueden convivir: exportar uno conserva los archivos del otro. `--output <carpeta>` permite generar un snapshot alternativo; el visor incluido lee específicamente `content/`.

## Apuntes históricos de Notion (MIA 7–13)

Los apuntes publicados con la skill manual pueden incorporarse sin descargar videos ni ejecutar Codex. El archivo `config/mia-notion-import.json` fija los IDs de módulo, cohorte y páginas de Notion verificados, y las correcciones de sintaxis Mermaid revisadas. No contiene credenciales. La conexión usa `ACADEMIC_NOTION_TOKEN` y requiere acceso de lectura a las páginas; no depende de `ACADEMIC_PUBLICATION_ENABLED`.

Capture primero fuera del proyecto, revise la propuesta y aplique exactamente esa captura:

```bash
uv run academic notion-capture --mapping config/mia-notion-import.json --output /private/tmp/mia-capture
uv run academic import-notion --snapshot /private/tmp/mia-capture/snapshot.json
uv run academic import-notion --snapshot /private/tmp/mia-capture/snapshot.json --apply
uv run academic export-web --program MIA
npm run web:check
```

Use un directorio nuevo para cada captura completa. Una captura interrumpida puede retomarse con el mismo comando: solo reutiliza semanas terminadas si su edición remota sigue siendo la misma. No sobrescribe un `snapshot.json` ya terminado. La captura recorre los bloques y sus descendientes, con paginación, y comprueba que la semana no haya cambiado mientras se lee. Todos los accesos remotos del capturador son GET.

`import-notion` funciona sin conexión y por defecto solo muestra cobertura, revisiones previstas y números web pendientes. `--apply` guarda fuentes y revisiones bajo `data/imported/notion/revisions/`; un registro atómico `registry.json` selecciona las revisiones vigentes. Este almacenamiento es definitivo y privado, está excluido de Git y debe incluirse en los backups de `data/`. Las capturas de trabajo en `/private/tmp` son temporales. No se modifica SQLite ni se crean sesiones, trabajos, transcripciones o asociaciones de propiedad de bloques Notion. No necesita migraciones de base de datos.

Cada paquete conserva los bloques originales, hashes, límites de clase, versión del conversor y correcciones locales aplicadas. Reimportar el mismo contenido no crea otra revisión; una modificación crea un paquete nuevo y conserva el anterior. Una captura parcial no elimina semanas anteriores. La desaparición de una clase de una semana ya importada, el reemplazo de su página o una coincidencia con apuntes locales generan un conflicto. El exportador también comprueba los conflictos si posteriormente se procesa esa clase desde Moodle; no selecciona silenciosamente una fuente.

La numeración web sigue siendo manual: complete `export_number` en Módulos y respete el mapeo revisado. El importador informa de valores vacíos y rechaza un número ya asignado que difiera del mapeo; nunca lo rellena ni lo cambia. Los títulos históricos “Clase 1/2” se interpretan dentro de su semana y el encabezado exportado usa el número global correcto. Una clase ausente conserva su posición vacía. No se usan timestamps de Notion como fechas académicas: la web muestra **Fecha de clase no disponible** cuando no hay evidencia.

Los objetivos de sesión anteriores a su encabezado acompañan a esa clase. El contenido previo de alcance semanal se conserva en una página de contexto enlazada desde las clases, el índice y el menú. Las fórmulas se convierten desde ecuaciones nativas, las tablas conservan sus celdas y los callouts se presentan como citas. Los bloques no soportados se rechazan para revisión. Las correcciones Mermaid se aplican exclusivamente a los IDs y hashes especificados; si la fuente cambia, se requiere revisar la corrección. No se escribe la corrección en Notion.

Para verificar una exportación alternativa: `node scripts/check-web.mjs /private/tmp/mi-exportacion`. También comprueba hashes, descargas y diagramas de las páginas de contexto.

## Qué se exporta

Cada sesión debe tener estado `PROCESSED`, una revisión guardada y asignación válida de semana/clase. Se omiten sesiones excluidas y módulos que requieren revisión. El campo `enabled` controla la automatización del módulo y no su inclusión en la biblioteca. Una sesión en procesamiento, fallida o en revisión se omite hasta recuperar el estado `PROCESSED`.

En MIA también se incluyen las revisiones históricas verificadas del registro privado. No necesitan una sesión Moodle. Los módulos con revisión pendiente siguen omitiéndose y los números web se validan también para módulos que solo tengan apuntes importados. Las páginas públicas reciben únicamente Markdown y metadatos de lectura; las capturas originales y los metadatos privados de importación no se copian.

Dentro de cada cohorte, el orden, las etiquetas de módulo, los índices y los encabezados de la web usan exclusivamente `export_number`. Los números deben ser únicos dentro del mismo programa y cohorte, incluidos los módulos todavía sin apuntes. Se permiten números iguales en otros programas/cohortes. Los módulos sin sesiones exportables pueden tener el campo vacío.

Si un módulo con apuntes exportables no tiene número, hay duplicados o se guardó un valor inválido fuera de la API, el comando devuelve `WEB_EXPORT_NUMBERING_INVALID` con `issues`: ID, nombre, cohorte y motivo de cada módulo afectado. La exportación se detiene antes de modificar el snapshot existente. No se usa el número de Moodle como alternativa. Después de corregir los valores, vuelva a exportar para actualizar la biblioteca; cambiar el número no altera las URLs ni las descargas originales.

El exportador obtiene `output_path` y `content_hash` de la sesión. Comprueba la ubicación y el hash mediante el mismo servicio que sirve los apuntes al dashboard. Una inconsistencia detiene la exportación antes de modificar los archivos del snapshot. No recorre indiscriminadamente `data/processed/`: los intentos antiguos no generan clases duplicadas.

Las rutas usan el ID estable del módulo y la posición académica, por ejemplo:

```text
content/
  index.md                              # Portada mantenida a mano
  .export-dcc.json                       # Archivos administrados y sus hashes
  dcc/
    catalog.json                        # Módulos y sesiones en orden académico
    index.md                            # Índice del programa
    modulo-532/
      index.md                          # Índice del módulo
      semana-02.md                      # Apunte con frontmatter y navegación
  public/
    library.svg                         # Identidad del visor
    notes/dcc/modulo-532/semana-02.md     # Descarga del Markdown original
```

MIA usa `semana-01-clase-01.md` y `semana-01-clase-02.md`. Un cambio de título no cambia la URL; una reasignación de semana/clase sí puede cambiarla. La navegación anterior/siguiente recorre las sesiones disponibles del mismo módulo.

Se exportan título, fecha, revisión e identidad académica. Los archivos auxiliares de procesamiento, transcripciones, rutas locales, tokens y metadatos privados del paquete no se copian. La descarga conserva el Markdown original; la página normaliza los delimitadores matemáticos `\(...\)` y `\[...\]` para su visualización. Las fórmulas se construyen con MathJax y Mermaid se carga cuando se muestra un diagrama. El visor permite ampliarlo y consultar su fuente; si un diagrama no se puede dibujar, muestra su código sin impedir leer el apunte.

## Actualizar y corregir

Reprocesar desde el dashboard guarda una revisión nueva. Después vuelva a ejecutar `export-web`. La misma sesión actualiza su archivo; Git conserva las versiones publicadas cuando se confirman los cambios.

Los archivos generados no son un lugar para editar permanentemente los apuntes. Si se modificó uno localmente, el exportador devuelve `WEB_EXPORT_LOCAL_CHANGES` sin sobrescribirlo. Conserve primero esa corrección y aplíquela en el flujo de origen. Para descartar expresamente las ediciones de copias generadas:

```bash
uv run academic export-web --program DCC --overwrite
```

Incluso con `--overwrite`, el exportador rechaza colisiones con archivos que no administra. Si una sesión deja de ser exportable o cambia de posición, retira únicamente sus archivos registrados en el manifiesto; conserva archivos ajenos y el otro programa. Mantenga los manifiestos en Git junto con los Markdown y catálogos.

Las ediciones hechas directamente en Notion no se sincronizan hacia esta biblioteca. La fuente para la web es la revisión local guardada por el proyecto.

## Validación y construcción

Requiere Node.js 22.12 o superior. Las versiones resueltas quedan fijadas en `package-lock.json`.

Se mantienen overrides de `vite` y `@xmldom/xmldom` para usar versiones corregidas de las dependencias transitivas de VitePress/MathJax. Al actualizar VitePress, compruebe si siguen siendo necesarios y repita construcción y auditoría.

```bash
npm run web:check
npm run web:build
npm run web:preview
```

`web:check` compara hashes de todos los archivos administrados y descargas, y analiza los bloques Mermaid con el parser real. El build verifica enlaces Markdown y construye las fórmulas, páginas y búsqueda local. Los archivos descargables no se incluyen como páginas ni como resultados duplicados de búsqueda.

Para comprobar el despliegue bajo una subruta:

```bash
WEB_BASE=/soe-academic-automation/ npm run web:build
WEB_BASE=/soe-academic-automation/ npm run web:preview
```

La vista previa de VitePress 1.6 escucha en todas las interfaces; úsela solo para la verificación local y deténgala al terminar. El servidor de desarrollo sí queda restringido a `127.0.0.1` mediante el script incluido.

## GitHub Pages

El workflow `.github/workflows/academic-pages.yml` instala dependencias desde el lock, verifica el snapshot, construye el sitio y despliega el artefacto estático. El build de GitHub no accede a la base de datos del Mac: usa solamente el contenido exportado y confirmado en Git.

1. Configure el remoto GitHub del repositorio y su rama de publicación `main` (ajuste el workflow si usa otra).
2. En GitHub, abra **Settings → Pages → Build and deployment → Source → GitHub Actions**.
3. Confirme y suba `content/` con sus manifiestos, `web/`, los archivos npm, `scripts/check-web.mjs` y el workflow. Confirme también el exportador y su documentación en el proyecto.
4. Los pushes a `main` que cambien esos archivos despliegan el sitio. También puede iniciar el workflow manualmente.

`actions/configure-pages` proporciona automáticamente la subruta del repositorio o dominio personalizado. La exportación y el push siguen siendo pasos explícitos; no se añade publicación automática al worker.

El destino habitual de Pages es público, aunque el repositorio sea privado. Para acceso restringido, resuelva primero el alojamiento/autenticación; la publicación privada de Pages requiere una organización con Enterprise Cloud. La biblioteca no incorpora login ni control de acceso en el navegador. Referencia: [control de acceso en GitHub Pages](https://docs.github.com/en/enterprise-cloud@latest/pages/getting-started-with-github-pages/changing-the-visibility-of-your-github-pages-site).

## Verificación del 21 de octubre de 2026

- Exportadas 68 sesiones vigentes de 13 módulos DCC; siete sesiones pendientes omitidas. Segunda exportación sin cambios de archivos.
- 221 pruebas Python aprobadas, incluidas actualización de revisiones, integridad, omisiones, navegación DCC/MIA, conflictos locales, retiro de archivos administrados, symlinks y CLI. Se mantienen seis advertencias de deprecación de Starlette/Alembic anteriores a esta entrega.
- `web:check`: hashes y descargas correctos; 88 diagramas analizados con el parser real de Mermaid.
- Construcción correcta con `WEB_BASE=/soe-academic-automation/`: 84 páginas HTML y 68 descargas. Todos los enlaces y recursos locales encontrados bajo la subruta; sin páginas duplicadas para las descargas. La construcción emite un aviso de tamaño de chunks de las dependencias de visualización.
- Portada, sesión con fórmulas/diagrama y descarga respondieron HTTP 200 en preview. Servidor de desarrollo Vite verificado por HTTP en `127.0.0.1:5173`. Los servidores temporales de verificación se detuvieron.
- Ruff F sin incidencias en los archivos Python modificados. `npm audit`: cero vulnerabilidades con las versiones del lock.
- No hay navegador conectado en la sesión: queda pendiente verificar visualmente escritorio/móvil, búsqueda, cambio de tema y renderizado interactivo de los diagramas. El análisis de Mermaid comprueba sintaxis, no su disposición visual.
- No se hizo commit, push ni despliegue externo. El repositorio local no tiene remoto configurado; falta conectarlo a GitHub y habilitar Pages para ejecutar el workflow.

### Número manual para web

Se añadió `export_number` con migración `d7a02cb94e61`, edición y borrado desde Módulos, y validación previa a exportar. El selector del dashboard usa IDs estables para conservar el módulo elegido después de guardar. `module_number` conserva el valor de Moodle y las sincronizaciones no modifican el número manual.

Verificación: **236 pruebas aprobadas**, incluidas migración/rollback protegido, API administrativa, valores inválidos, sincronización, orden y etiquetas exportadas, URLs estables, errores sin modificar el snapshot, duplicados por programa/cohorte y recorrido AppTest con API real para guardar/cambiar de módulo/borrar. Ruff F sin incidencias.

La migración se ensayó sobre una copia de la base real y se aplicó después de comprobar ausencia de trabajos activos, con backup privado `before-export-number-20261022T022902912889.sqlite3`. Se conservaron todos los campos y filas anteriores de las diez tablas; integridad y claves foráneas correctas. Los 28 módulos quedaron con el campo vacío, sin adoptar automáticamente una numeración.

La exportación real se detuvo con `WEB_EXPORT_NUMBERING_INVALID` e identificó los 14 módulos DCC que requieren asignación manual. El snapshot previo se conservó; `web:check` siguió validando sus 68 sesiones y 88 diagramas. Para actualizar la web hay que completar los números y volver a exportar. No se escribió en Notion ni se reprocesaron clases como parte de este cambio.

## Recuperación histórica MIA y cierre del 25 de octubre de 2026

Se incorporaron 52 clases de 27 semanas de los módulos 7–13 al registro privado. La captura conservó los árboles completos de Notion y el conversor mantuvo las 2.139 expresiones matemáticas y los 359 bloques de código; los tres diagramas con errores requirieron cuatro correcciones de sintaxis auditadas. El contexto previo de cinco semanas se conservó en páginas separadas.

La biblioteca exportada contiene 101 clases MIA y 69 DCC, con 368 diagramas en total. Repetir la importación conserva las 27 revisiones vigentes y repetir ambas exportaciones cambia cero archivos. La última suite Python completa aprobó 291 pruebas; la construcción se verificó bajo `/soe-academic-automation/`. La revisión del HTML importado no encontró errores MathJax. Los avisos de chunks grandes y de lenguajes de código sin resaltador no impiden la construcción; esos lenguajes se muestran como texto.

Se completó la numeración web 7–14 conforme al orden de las páginas verificadas, conservando el resto de campos de los módulos. Se guardaron un backup SQLite y la auditoría de esa configuración en `data/private/backups/`. La importación en sí no modificó SQLite ni escribió en Notion. No hubo reprocesamiento de grabaciones ni adopción de propiedad de bloques remotos.

La web desactiva los atajos automáticos de emoji para conservar signos académicos como `:*` literalmente. Las fechas desconocidas se indican como tales y las clases enlazan el contexto semanal cuando existe.

La revisión final en navegador comprobó las tres páginas con Mermaid corregido (15/15, 8/8 y 5/5 diagramas renderizados), el contexto semanal y el índice de 14 módulos MIA. No aparecieron errores de diagrama ni MathJax en esas páginas. La construcción final completó en 62 segundos; la vista previa temporal se detuvo al terminar.

Pendientes de contenido: no se localizaron las clases 1, 7 y 8 del módulo 8 ni la clase 8 del módulo 9 en las páginas inspeccionadas. Se conservan sus posiciones vacías. La importación y construcción son locales; no se realizó commit, push ni despliegue externo en esta entrega.
