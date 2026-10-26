#!/usr/bin/env bash
# yt_transcripts.sh — Descarga concurrente de subtitulos/transcripciones con yt-dlp
# Transforma y limpia VTT a TXT con numeracion secuencial (ej. clase8.txt, clase9.txt)

set -euo pipefail

WORKERS=3
LANG_CODE="es-orig"
OUTPUT_DIR="."
FILE_PATH=""
FROM_NUM=1
PREFIX="clase"
KEEP_VTT=false
declare -a URLS=()

usage() {
    cat << 'EOF'
Uso:
  yt-transcripts [opciones] [URL ...]
  yt-transcripts -f links.txt --from 8 [-w 4] [-l es-orig] [-o ./salida]
  cat links.txt | yt-transcripts --from 5

Opciones:
  --from N                 Numero de clase inicial para nombrar los archivos (por defecto: 1)
                           Ejemplo: --from 8 genera clase8.txt, clase9.txt, etc.
  --prefix TEXTO           Prefijo del nombre de archivo (por defecto: "clase")
                           Ejemplo: --prefix sesion genera sesion8.txt, etc.
  -f, --file ARCHIVO       Archivo de texto con URLs o rutas de archivos (una por linea)
  -w, --workers N          Numero de descargas/conversiones en paralelo (por defecto: 3)
  -l, --lang CODIGO        Codigo de idioma del subtitulo (por defecto: es-orig)
  -o, --output-dir RUTA    Directorio destino de guardado (por defecto: directorio actual)
  --keep-vtt               Conserva el archivo .vtt original ademas del .txt limpio
  -h, --help               Muestra este mensaje de ayuda

Ejemplos:
  yt-transcripts --from 8 -f links.txt
  yt-transcripts --from 14 "https://www.youtube.com/watch?v=..."
  yt-transcripts --from 8 -w 4 -f links.txt -o ./transcripts
EOF
    exit 0
}

# Subproceso worker invocado internamente para ejecucion en paralelo
if [[ "${1:-}" == "--_worker" ]]; then
    NUM="$2"
    TARGET="$3"
    OUT_DIR="$4"
    LANG="$5"
    PREF="$6"
    KEEP="$7"

    DEST_TXT="${OUT_DIR%/}/${PREF}${NUM}.txt"
    DEST_VTT="${OUT_DIR%/}/${PREF}${NUM}.vtt"
    TMP_BASE="${OUT_DIR%/}/.tmp_${PREF}${NUM}_$$"

    # Si el target es un archivo VTT local existente, solo limpiarlo a TXT
    if [[ -f "$TARGET" && "$TARGET" =~ \.vtt$ ]]; then
        python3 -c '
import sys, re

vtt_path = sys.argv[1]
txt_path = sys.argv[2]

try:
    with open(vtt_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    blocks = content.strip().split("\n\n")
    cleaned_lines = []

    for block in blocks:
        lines = block.strip().split("\n")
        if not lines:
            continue
        if any(lines[0].startswith(h) for h in ["WEBVTT", "Kind:", "Language:", "NOTE", "STYLE"]):
            continue

        text_lines = []
        for l in lines:
            if "-->" in l:
                continue
            cleaned = re.sub(r"<[^>]+>", "", l).strip()
            cleaned = (cleaned.replace("&nbsp;", " ")
                              .replace("&amp;", "&")
                              .replace("&quot;", "\"")
                              .replace("&#39;", "\x27")
                              .replace("&lt;", "<")
                              .replace("&gt;", ">"))
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            if cleaned:
                text_lines.append(cleaned)

        for t in text_lines:
            if not cleaned_lines or cleaned_lines[-1] != t:
                if cleaned_lines and t.startswith(cleaned_lines[-1]):
                    cleaned_lines[-1] = t
                elif cleaned_lines and cleaned_lines[-1].startswith(t):
                    pass
                else:
                    cleaned_lines.append(t)

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(cleaned_lines) + "\n")
    print(f"[COMPLETADO] {vtt_path} -> {txt_path} ({len(cleaned_lines)} lineas)")
except Exception as e:
    sys.stderr.write(f"[ERROR] Error al limpiar {vtt_path}: {e}\n")
    sys.exit(1)
' "$TARGET" "$DEST_TXT"
        exit 0
    fi

    # Descarga de subtitulos mediante yt-dlp
    set +e
    yt-dlp \
        --js-runtimes node \
        --remote-components ejs:github \
        --cookies-from-browser chrome \
        --skip-download \
        --write-subs \
        --write-auto-subs \
        --sub-langs "$LANG" \
        -o "${TMP_BASE}.%(ext)s" \
        "$TARGET" > "${ACADEMIC_YTDLP_LOG:-/dev/null}" 2>&1
    STATUS=$?
    set -e

    VTT_FOUND=$(ls "${TMP_BASE}"*.vtt 2>/dev/null | head -n 1 || true)

    if [[ -n "$VTT_FOUND" && -f "$VTT_FOUND" ]]; then
        python3 -c '
import sys, re

vtt_path = sys.argv[1]
txt_path = sys.argv[2]

try:
    with open(vtt_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    blocks = content.strip().split("\n\n")
    cleaned_lines = []

    for block in blocks:
        lines = block.strip().split("\n")
        if not lines:
            continue
        if any(lines[0].startswith(h) for h in ["WEBVTT", "Kind:", "Language:", "NOTE", "STYLE"]):
            continue

        text_lines = []
        for l in lines:
            if "-->" in l:
                continue
            cleaned = re.sub(r"<[^>]+>", "", l).strip()
            cleaned = (cleaned.replace("&nbsp;", " ")
                              .replace("&amp;", "&")
                              .replace("&quot;", "\"")
                              .replace("&#39;", "\x27")
                              .replace("&lt;", "<")
                              .replace("&gt;", ">"))
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            if cleaned:
                text_lines.append(cleaned)

        for t in text_lines:
            if not cleaned_lines or cleaned_lines[-1] != t:
                if cleaned_lines and t.startswith(cleaned_lines[-1]):
                    cleaned_lines[-1] = t
                elif cleaned_lines and cleaned_lines[-1].startswith(t):
                    pass
                else:
                    cleaned_lines.append(t)

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(cleaned_lines) + "\n")
    print(f"[COMPLETADO] {txt_path} ({len(cleaned_lines)} lineas)")
except Exception as e:
    sys.stderr.write(f"[ERROR] Error procesando {vtt_path}: {e}\n")
    sys.exit(1)
' "$VTT_FOUND" "$DEST_TXT"

        if [[ "$KEEP" == "true" ]]; then
            mv "$VTT_FOUND" "$DEST_VTT"
        fi
        rm -f "${TMP_BASE}"*
    else
        echo "[FALLIDO] No se pudo obtener subtitulo para: $TARGET (esperado: ${PREF}${NUM}.txt)" >&2
        rm -f "${TMP_BASE}"*
        exit 1
    fi
    exit 0
fi

# Verificar dependencias
if ! command -v yt-dlp >/dev/null 2>&1; then
    echo "Error: yt-dlp no se encuentra en el PATH del sistema." >&2
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 no se encuentra en el PATH del sistema." >&2
    exit 1
fi

# Parseo de argumentos principales
while [[ $# -gt 0 ]]; do
    case "$1" in
        --from)
            FROM_NUM="$2"
            shift 2
            ;;
        --prefix)
            PREFIX="$2"
            shift 2
            ;;
        -f|--file)
            FILE_PATH="$2"
            shift 2
            ;;
        -w|--workers)
            WORKERS="$2"
            shift 2
            ;;
        -l|--lang)
            LANG_CODE="$2"
            shift 2
            ;;
        -o|--output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --keep-vtt)
            KEEP_VTT=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            if [[ "$1" =~ ^https?:// ]] || [[ -f "$1" ]]; then
                URLS+=("$1")
            else
                echo "Advertencia: Argumento no reconocido ignorado: $1" >&2
            fi
            shift
            ;;
    esac
done

# Validar que FROM_NUM sea un entero positivo
if ! [[ "$FROM_NUM" =~ ^[0-9]+$ ]]; then
    echo "Error: El parametro --from debe ser un numero entero (recibido: $FROM_NUM)." >&2
    exit 1
fi

# Si se proporciono archivo, leer URLs
if [[ -n "$FILE_PATH" ]]; then
    if [[ ! -f "$FILE_PATH" ]]; then
        echo "Error: El archivo especificado no existe: $FILE_PATH" >&2
        exit 1
    fi
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="$(echo "$line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
        if [[ -n "$line" && ! "$line" =~ ^# ]]; then
            URLS+=("$line")
        fi
    done < "$FILE_PATH"
fi

# Si no hay URLs y hay entrada por tuberia (stdin)
if [[ ${#URLS[@]} -eq 0 && ! -t 0 ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="$(echo "$line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
        if [[ -n "$line" && ! "$line" =~ ^# ]]; then
            URLS+=("$line")
        fi
    done
fi

if [[ ${#URLS[@]} -eq 0 ]]; then
    echo "Error: No se proporcionaron enlaces ni archivo con URLs." >&2
    echo "Ejecuta 'yt-transcripts --help' para ver ejemplos de uso." >&2
    exit 1
fi

mkdir -p "$OUTPUT_DIR"
TOTAL=${#URLS[@]}
END_NUM=$((FROM_NUM + TOTAL - 1))

echo "=================================================="
echo "Descarga y limpieza de transcripciones (VTT -> TXT)"
echo "Total de enlaces: $TOTAL"
echo "Secuencia de clases: ${PREFIX}${FROM_NUM}.txt -> ${PREFIX}${END_NUM}.txt"
echo "Concurrencia (workers): $WORKERS"
echo "Idioma de subtitulo: $LANG_CODE"
echo "Directorio de salida: $OUTPUT_DIR"
echo "=================================================="

CURRENT_INDEX="$FROM_NUM"
JOBS_FILE=$(mktemp /tmp/yt_transcripts_jobs.XXXXXX)

for url in "${URLS[@]}"; do
    printf "%s\0%s\0%s\0%s\0%s\0%s\0" \
        "$CURRENT_INDEX" \
        "$url" \
        "$OUTPUT_DIR" \
        "$LANG_CODE" \
        "$PREFIX" \
        "$KEEP_VTT" >> "$JOBS_FILE"
    CURRENT_INDEX=$((CURRENT_INDEX + 1))
done

# Ejecucion concurrente pasando argumentos delimitados por byte nulo
xargs -0 -P "$WORKERS" -n 6 "$0" --_worker < "$JOBS_FILE"

rm -f "$JOBS_FILE"

echo "=================================================="
echo "Proceso finalizado. Archivos generados en: $OUTPUT_DIR"
echo "=================================================="
