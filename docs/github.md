# Primer commit y push a GitHub

El repositorio usa `main`. Se versionan el código, las migraciones, los tests,
la documentación, los workflows y ambos locks (`uv.lock` y `package-lock.json`).
También se incluye `content/`: contiene los apuntes exportados y sus descargas,
además de los manifiestos necesarios para verificar sus hashes.

`.gitignore` excluye `.env`, `data/` salvo su `.gitkeep`, sesiones autenticadas,
bases SQLite, dependencias, builds, cachés, logs y archivos locales de credenciales.
Los identificadores de páginas Notion en `config/mia-notion-import.json` son
configuración del proyecto; el token de acceso permanece en `.env`.

## Verificar antes del commit

```bash
uv sync --locked
uv run pytest -q
uv run ruff check --select F .
bash -n scripts/start-host.sh scripts/yt_transcripts.sh
npm ci
npm run web:check
npm run web:build
git diff --cached --stat
git status --short
```

La comprobación Ruff anterior cubre Pyflakes, el alcance usado en las
verificaciones existentes. La comprobación amplia `uv run ruff check .` tiene
incidencias previas de estilo y otras reglas; no debe interpretarse como aprobada.
Las pruebas que necesitan la skill académica instalada se omiten cuando no está
disponible. Las pruebas de servicios externos usan simulaciones.

## Crear el commit y conectar el remoto

Cree un repositorio vacío en GitHub, sin README, licencia ni `.gitignore`
automáticos. Sustituya `OWNER` por su usuario u organización en estos comandos:

```bash
git add .
git diff --cached --stat
git commit -m "Initial commit: academic automation and DCC/MIA library"
git remote add origin git@github.com:OWNER/soe-academic-automation.git
git remote -v
git push -u origin main
```

Si usa HTTPS, sustituya la URL SSH por la URL HTTPS del repositorio.

El workflow existente de GitHub Pages se ejecuta al subir a `main` cambios de
la biblioteca. Configure Pages antes del push si desea desplegarla; consulte
la [guía web](web.md#github-pages). El snapshot académico se incluye en el
commit y será visible para quienes tengan acceso al repositorio. Revise la
visibilidad del repositorio y del sitio según el acceso deseado a los apuntes.
