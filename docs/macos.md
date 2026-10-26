# Instalación macOS

Ejecute desde la raíz del repositorio. Mantenga el equipo despierto durante los trabajos y evite cerrar la sesión de Chrome utilizada por el script.

```bash
brew install python@3.12 uv node yt-dlp
# Codex CLI: utilice su instalación autenticada existente.
codex --version
codex exec --help
yt-dlp --version
node --version
python3 scripts/configure_local.py
uv sync --python 3.12
uv run playwright install chromium
uv run alembic upgrade head
uv run academic doctor
uv run pytest -q
```

No se necesita clave de la API OpenAI: Codex usa su autenticación del host. Si falta la skill, instálela antes del procesamiento; este proyecto no instala una copia alternativa. Por defecto se busca `~/.agents/skills/academic-transcription-to-notion`. Configure `ACADEMIC_SKILL_PATH` cuando su instalación use otra ruta.

El script original está en `scripts/yt_transcripts.sh`, con permiso de ejecución; lo necesita porque sus workers se invocan mediante `xargs`. Si lo reemplaza, conserve ese permiso con `chmod +x scripts/yt_transcripts.sh`. La única modificación de integración es una salida de diagnóstico optativa mediante `ACADEMIC_YTDLP_LOG`; su comportamiento manual predeterminado no cambia.

En sistemas con Conda, `uv sync --python /opt/homebrew/bin/python3.12` evita seleccionar un intérprete de Conda por el PATH. Un entorno virtual debe usar la misma arquitectura que las dependencias compiladas.

Si el entorno no accede a PyPI, `uv sync` no podrá instalar todo. No considere la instalación terminada hasta que ese comando, Chromium y las pruebas concluyan. Los resultados de desarrollo obtenidos mediante dependencias locales de respaldo están descritos en `verification.md`.

Arranque manual, en tres terminales:

```bash
uv run uvicorn apps.api.main:app --host 0.0.0.0 --port 8000
uv run academic worker
uv run streamlit run apps/dashboard/main.py --server.address 127.0.0.1 --server.port 8501 --server.headless=true --browser.gatherUsageStats=false
```

`0.0.0.0` permite acceso desde n8n por `host.docker.internal`; la autenticación permanece obligatoria. Sin n8n, puede limitar Uvicorn a `127.0.0.1`. No exponga SQLite ni `data/` como archivos estáticos.

Abra el dashboard en `http://127.0.0.1:8501`. `--server.headless=true` evita el aviso de correo del primer arranque y la apertura automática del navegador; no impide usar la interfaz web. Si solo ve logs de Uvicorn y no aparece el dashboard, detenga el lanzador con Ctrl+C y ejecute la versión actualizada de `bash scripts/start-host.sh`. El 404 de `http://127.0.0.1:8000/` es esperado porque esa es la API y no define una página raíz; consulte `/health` o `/docs`.

Para operación continua supervise los procesos con launchd o una terminal persistente y mantenga el equipo despierto. El worker conserva trabajos en SQLite y se recupera tras reinicios. No lance varios workers sobre la misma base de datos usando diferentes directorios de datos.
