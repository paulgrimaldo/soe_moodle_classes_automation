# Codex CLI y skill académica

El adaptador usa Codex CLI en macOS, con la autenticación ya instalada en el host. Se comprobó la interfaz local de `codex-cli 0.163.0` mediante `codex exec --help`; el proyecto no ejecutó una generación real durante sus pruebas.

La skill instalada se conserva íntegra. Se cargan `SKILL.md`, las reglas, el contrato y el esquema de salida. Se reutilizan sus funciones `validate_result` y `export_bundle`, incluyendo su lint académico. El hash SHA-256 de los archivos relevantes y la versión del contrato quedan registrados por trabajo.

El adaptador local aplica la extensión `text-examples-v1`: permite bloques `text` para ejemplos de configuración o salida, como `.dockerignore`, sin cambiar el Markdown guardado. Durante el lint trata esa etiqueta como `plaintext` y aplica dentro del bloque la detección de diagramas de texto del validador original. Mantiene la obligatoriedad de Mermaid, las etiquetas de diagramas prohibidas, los cierres de código y las demás comprobaciones. La extensión queda identificada en `metadata.json`. Reinicie API y worker para cargar cambios del adaptador; una salida rechazada ya guardada puede recuperarse mediante revisión sin ejecutar Codex otra vez.

## Diferencia respecto del contrato instalado

El contrato real 1.0 exige una semana completa: DCC una clase y MIA exactamente dos. Esto contradice el requisito del sistema de procesar clases individualmente. El adaptador implementa una extensión explícita `single-class-v1`: conserva el esquema de salida, el número global original, las reglas y los validadores; modifica únicamente la cardinalidad de entrada MIA a una clase por ejecución. No usa `load_request` ni el comando `run` semanal de la skill para este caso. No fabrica una segunda clase y no modifica la skill global.

Las fuentes completas se incluyen como datos JSON en el prompt; el límite configurable de 500000 caracteres rechaza el exceso, sin truncarlo. El prompt invoca explícitamente `$academic-transcription-to-notion` y proporciona reglas y textos completos, como requiere su modo automático.

Se invoca el equivalente a:

```text
codex -a never exec --ignore-user-config -c mcp_servers={} \
  -c features.shell_tool=false --sandbox read-only --ephemeral \
  --skip-git-repo-check --cd DIRECTORIO_PRIVADO \
  --output-schema output.schema.json --output-last-message response.json --json -
```

El prompt entra por stdin, sin shell. El proceso recibe solo variables de entorno necesarias para localizar Codex y su autenticación, sin tokens de Notion ni del backend. Se ignora la configuración de usuario para evitar heredar MCP y hooks; se deshabilita la herramienta shell y se impide escritura desde el modelo. El backend escribe los artefactos. El soporte exacto de flags se debe volver a comprobar al cambiar la versión instalada.

La invocación real también deshabilita búsqueda web, Apps, plugins, hooks, subagentes, automatización de navegador/computadora y otros ejecutores. Es necesario deshabilitar Apps explícitamente: las conexiones de la cuenta pueden existir aunque `mcp_servers` esté vacío. Los nombres de capacidades se contrastaron con `codex features list` de la versión instalada. No se confía solamente en una instrucción del prompt para impedir publicaciones.

No se fuerza un modelo. `ACADEMIC_CODEX_MODEL` permite escoger uno compatible con la cuenta; el valor vacío usa el predeterminado del CLI y se registra como desconocido (`null`) si no está explícito. No se usa `gpt-5.5`. Cambiar la configuración personal de modelo no afecta una ejecución con `--ignore-user-config`: seleccione explícitamente el modelo si necesita reproducibilidad.

Cada intento tiene directorio propio: `data/processed/JOB-INTENTO/`. Allí quedan request, esquema, respuesta y log sanitizado; en `bundle/`, `result.json`, `metadata.json` y `notes.md`. `needs_review` conserva JSON y metadatos, sin Markdown publicable. El publicador requiere `ready`, el hash correcto y una sesión procesada.

Se validan el request y la respuesta con Pydantic, y después la salida con la skill. El Markdown debe tener objetivo académico, seis secciones en orden, Mermaid y ausencia de emojis/avisos administrativos. El lint no certifica fidelidad conceptual, referencias ni sintaxis completa de Mermaid: esos aspectos requieren auditoría semántica.

## Diagnosticar CODEX_OUTPUT_INVALID

Este error no implica necesariamente que Codex haya fallado al ejecutarse. Un proceso con código 0 puede entregar JSON correcto que incumpla la identidad de la clase, el contrato o el lint académico. Cada rechazo conserva la respuesta original; el diagnóstico privado `validation-error.json` identifica la etapa (`response_json`, `output_schema`, `identity`, `academic_lint` o `export`). Para errores Pydantic registra campos/tipos sin copiar los valores de entrada. Para coincidencias del filtro administrativo registra campo, línea y expresión coincidente, sin volcar el documento a los logs.

El worker persiste ese diagnóstico en el resultado del trabajo y **Historial** muestra motivo y ubicaciones. Los trabajos anteriores al cambio conservan su código genérico hasta que se diagnostiquen explícitamente. No se reintenta automáticamente ni se publica una respuesta rechazada.

La skill instalada tiene un filtro mecánico que puede confundir «examen del método» con un examen asignado al alumnado. El prompt recomienda «análisis del método» para el primer significado. Esto no cambia las reglas globales ni desactiva la validación: los avisos administrativos siguen excluidos. No se sustituyen automáticamente palabras de una salida rechazada; una recuperación editorial debe verificar el contexto, preservar la respuesta original y revalidar el documento completo.

El validador/exportador compartido está en `academic/output.py`, separado de la invocación a Codex para permitir comprobar respuestas guardadas sin llamar al modelo ni a Notion. Desde **Sesiones** puede [previsualizar, corregir y aprobar una salida rechazada](operations.md#revisar-una-salida-rechazada-de-codex), conservando los originales. La nueva función registra un trabajo `academic_review`, hashes, motivo, hallazgos aceptados y paquete en un directorio nuevo; las reparaciones históricas `academic_repair` permanecen en el historial. Los falsos positivos se exceptúan por campo y coincidencia exacta únicamente durante esa revisión; no se desactiva el filtro global ni los demás validadores. El trabajo fallido original se conserva. La aprobación requiere una revisión humana del contenido y no autoriza la publicación.

## Uso manual

La ejecución interactiva original sigue disponible:

```text
codex
$academic-transcription-to-notion
```

Proporcione programa, ID y título del módulo, semana y archivos. Para MIA, el modo manual original pide ambas clases y produce el paquete semanal. Ese paquete no se importa automáticamente a las sesiones del backend; el flujo automático utiliza artefactos por clase. La publicación automática pertenece exclusivamente al backend, nunca a Codex.
