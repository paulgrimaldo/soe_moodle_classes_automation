# Automatización académica DCC / MIA

MVP para macOS: Moodle → transcripciones → Codex CLI con la skill instalada → Markdown validado → Notion. Python ejecuta la lógica y los subprocesos en el host. n8n solo programa y consulta la API. El dashboard permite elegir módulos y clases, corregir asignaciones y revisar ejecuciones.

## Inicio

Requiere Python 3.12+, uv, Node.js, yt-dlp, Codex CLI autenticado, la skill `academic-transcription-to-notion` y Chrome con sesión YouTube. Docker Desktop es necesario solamente para n8n.

```bash
python3 scripts/configure_local.py
uv sync --python 3.12
uv run playwright install chromium
uv run alembic upgrade head
uv run academic doctor
uv run pytest -q
```

El configurador genera tokens independientes y un `.env` privado, sin mostrarlos. No reemplaza configuraciones existentes. Ajuste las rutas de la skill y del script si fuera necesario. **La publicación real queda deshabilitada por defecto.**

Autenticar Moodle e inspeccionar el catálogo antes de la primera sincronización:

```bash
uv run academic moodle-login
uv run academic moodle-inspect
```

Iniciar los tres procesos en terminales separadas desde la raíz del proyecto:

```bash
uv run uvicorn apps.api.main:app --host 0.0.0.0 --port 8000
uv run academic worker
uv run streamlit run apps/dashboard/main.py --server.address 127.0.0.1 --server.port 8501 --server.headless=true --browser.gatherUsageStats=false
```

También puede usar `bash scripts/start-host.sh`, que migra, inicia API y worker, y abre Streamlit. Dashboard: <http://localhost:8501>. OpenAPI: <http://localhost:8000/docs>. Solo `/health` es público. Al escuchar en `0.0.0.0`, la API será accesible por Docker Desktop; restrinja el acceso con el firewall de macOS y mantenga los tokens habilitados.

El dashboard se abre manualmente en <http://127.0.0.1:8501>. El arranque usa `headless` para evitar que el primer aviso de correo de Streamlit bloquee el servidor. El puerto 8000 corresponde a la API: su ruta `/` no está definida y devuelve 404; use `/health` o `/docs`.

```bash
docker compose up -d
```

n8n: <http://localhost:5678>. Cree su cuenta local e importe los cuatro JSON de `workflows/`. Se importan sin activar; pruebe el disparador manual y después publique cada workflow. No configure nodos para ejecutar Codex o yt-dlp en Docker.

## Primer recorrido

1. En **General**, solicite sincronizar el catálogo; mantenga el worker activo y consulte **Historial**.
2. En **Módulos**, habilite únicamente el módulo deseado y elija `MANUAL`, `ALL` o `NEW_ONLY`. Los nuevos módulos nacen deshabilitados.
3. Sincronice sus grabaciones. En **Sesiones**, verá ocho posiciones esperadas; las que aún no se descubrieron no se inventan en SQLite.
4. En **Sesión para una acción**, elija explícitamente una clase y pulse **Procesar**. La columna Selección de la tabla controla los despachos en modo `MANUAL` y se guarda por separado. El proceso explícito también puede ejecutarse sobre un módulo deshabilitado; la desactivación detiene la automatización.
5. Consulte **Historial**. Cuando termine, abra **Apuntes**, seleccione módulo y clase para leer la última revisión guardada, consultar el Markdown original o descargarlo. No requiere conexión con Notion. Una salida `needs_review` nunca se publica.
6. Vincule el módulo con su página existente en Notion. Vincular solo valida y persiste una asociación; no publica apuntes.
7. Cuando decida autorizar publicación, configure el token de Notion y `ACADEMIC_PUBLICATION_ENABLED=true`, reinicie API y worker, y pulse **Publicar / actualizar Notion** para la clase. Para ejecución desatendida, autorice además `auto_publish` en ese módulo desde el dashboard.
8. Reprocesar con Codex genera una revisión nueva. Publicar de nuevo actualiza solamente esa sección, conservando las demás.

MIA publica ambas clases como bloques de una misma página `Semana N`, con divisor nativo entre ellas. DCC publica una clase por semana. Nunca se crean páginas por clase. Los IDs de Moodle son las claves de módulo; las sesiones tienen UUID estable y clave de recurso independiente de su numeración.

Una clase dividida en varios videos puede procesarse como una sola sesión después de confirmar sus partes y su orden. Se preservan los TXT/VTT por video y se genera una transcripción conjunta para un único apunte. Consulte [clases divididas en partes](docs/moodle.md#clases-divididas-en-partes); los recursos ambiguos siguen requiriendo revisión.

Para cursos cuya estructura no se descubre automáticamente, use **Sesiones → Crear sesión y vincular grabaciones**, o elija una sesión existente y abra **Vincular grabaciones manualmente**. Pegue un enlace de YouTube por línea en orden de partes y guarde. El vínculo manual se conserva al sincronizar y queda listo para **Procesar**, sin editar JSON. Consulte la [guía de vinculación manual](docs/moodle.md#vinculación-manual-desde-el-dashboard). Tras actualizar este código, reinicie con `bash scripts/start-host.sh` para aplicar la migración y cargar los formularios y endpoints nuevos.

Los apuntes generados se conservan en `data/processed/<trabajo>-<intento>/bundle/notes.md`, junto con `metadata.json`; los intentos anteriores se mantienen. Una reconciliación puede crear la revisión vigente bajo `data/reconciled/`. La vista **Apuntes** consulta la revisión asociada a la sesión mediante la API autenticada. Conserva fórmulas y bloques de código; Mermaid se muestra como código fuente.

Si Codex termina con **REVIEW_REQUIRED / CODEX_OUTPUT_INVALID**, elija la clase en **Sesiones → Sesión para una acción** y abra **Previsualizar y aprobar salida rechazada de Codex**. Puede leer los apuntes y la transcripción, localizar hallazgos por campo/línea y corregir el Markdown. Tras validar, confirme la revisión y explique la aprobación para guardar los apuntes sin ejecutar Codex otra vez. Los falsos positivos del filtro administrativo pueden aprobarse expresamente; los errores de contrato, identidad, estructura o fórmulas deben corregirse. La revisión queda auditada y publicar en Notion sigue siendo una acción aparte. Consulte el [flujo de revisión](docs/operations.md#revisar-una-salida-rechazada-de-codex).

Para consultar una **biblioteca web con Mermaid, fórmulas, búsqueda y navegación por módulo/semana**, exporte las revisiones vigentes a la carpeta versionable `content/`:

Asigne primero **Número de módulo para web** en **Módulos → Guardar preferencias**. Este valor manual controla la numeración de la biblioteca y se conserva al sincronizar Moodle. Los valores faltantes en módulos con apuntes o duplicados en la misma cohorte detienen la exportación e identifican los módulos afectados.

```bash
uv run academic export-web --program DCC
npm ci
npm run web:check
npm run web:dev
```

El visor no requiere los servicios administrativos encendidos. Exportar copia los apuntes sin mover sus originales ni escribir en Notion. La [guía de biblioteca web](docs/web.md) explica actualización, protección de ediciones locales, soporte MIA y despliegue con GitHub Actions/Pages.

En **Sesiones → Operaciones por lote**, debajo de las acciones individuales, puede seleccionar varias clases y procesarlas, generar/reprocesar sus apuntes con Codex o publicar/actualizar Notion. La selección es independiente del modo MANUAL. Todas deben compartir los cuatro estados y cumplir los requisitos de la operación; si alguna no cumple, no se encola ninguna. Cada clase conserva su propio trabajo e historial. Consulte [operaciones por lote](docs/operations.md#operaciones-por-lote).

## Componentes

| Ruta | Responsabilidad |
| --- | --- |
| `apps/api/` | API administrativa y endpoints para n8n |
| `apps/dashboard/` | General, Módulos, Sesiones, Apuntes e Historial; consume solamente la API |
| `src/academic_automation/database/` | SQLAlchemy, restricciones, SQLite WAL |
| `src/academic_automation/moodle/` | Sesión Playwright, inspección y parsers |
| `src/academic_automation/transcripts/` | Adaptador del script original, TXT/VTT, clasificación de errores |
| `src/academic_automation/academic/` | Codex y validadores de la skill instalada |
| `src/academic_automation/notion/` | Resolución de semanas, conversión y secciones con hashes |
| `src/academic_automation/orchestration/` | Cola SQLite durable y worker recuperable |
| `workflows/` | Cuatro workflows importables de n8n |
| `migrations/` | Migraciones Alembic versionadas |

## Guías y verificación

- [Instalación macOS](docs/macos.md)
- [Autenticación e inspección Moodle](docs/moodle.md)
- [Integración Codex y adaptación del contrato real](docs/codex.md)
- [Notion, autorización y conflictos](docs/notion.md)
- [Operación, API y n8n](docs/operations.md)
- [Decisiones de implementación](docs/decisions.md)
- [Resultados verificados y pendientes](docs/verification.md)
- [Biblioteca web y GitHub Pages](docs/web.md)
- [Primer commit y push a GitHub](docs/github.md)

Las pruebas usan Moodle, YouTube, Codex y Notion simulados. Las pruebas de validación contra la skill real se omiten explícitamente si no está instalada. La validación mecánica no certifica el rigor conceptual del texto ni ejecuta el parser de Mermaid.
