# Decisiones de implementación

1. **Un backend especializado y una cola SQLite.** La carga inicial de ocho clases por módulo no justifica un servicio de colas adicional. La API escribe trabajos; un worker exclusivo permite recuperación sin leases distribuidos. Las restricciones DB siguen protegiendo contra solicitudes concurrentes.

2. **Identidad separada de posición.** El módulo usa ID Moodle. La sesión usa UUID y clave única de recurso Moodle; el video tiene unicidad propia. Número, semana y clase son asignaciones revisables. Una publicación tardía no mueve contenido generado o publicado silenciosamente.

3. **Dimensiones independientes.** La sesión conserva estado de descubrimiento, transcripción, generación y publicación. La cola conserva el estado del intento. Esto permite conservar un TXT disponible y reintentar solo Codex o Notion.

4. **Contrato real de skill y extensión explícita.** La skill instalada exige semanas completas MIA. El requisito del producto exige procesamiento por clase. Se usa su código de validación/exportación y se documenta `single-class-v1`; no se modifica la instalación global ni se finge que acepta solicitudes semanales incompletas por su interfaz original.

5. **Codex produce datos; Python publica.** El modelo recibe el texto completo, reglas y esquema por stdin, sin credenciales de servicio. CLI usa sandbox de lectura, herramientas shell deshabilitadas y configuración MCP vacía. El backend valida y guarda antes de publicar.

6. **Publicación por secciones, con intervención ante incertidumbre.** Notion carece de transacciones de sección. Se persiste intención antes de mutar y se bloquea tras interrupciones o resultados inciertos. Se guardan IDs y hashes recursivos. La revisión manual de una escritura parcial es preferible a duplicar contenido mediante un reintento ciego.

7. **API Notion 2026-03-11.** La inserción `position.start` hace posible publicar Clase 1 antes de Clase 2 sin reemplazar ni mover la segunda. Los divisores son bloques nativos con propiedad separada de las clases.

8. **Adaptación mínima del script original.** Se mantiene el script Bash suministrado, su normalización, Chrome y es-orig. Se añade solo un destino opcional de diagnóstico, porque el original enviaba errores de yt-dlp a `/dev/null`. El adaptador limita el script a un video/worker, retiene VTT y TXT y sanitiza el log.

9. **Inspección Moodle antes de selectores específicos.** Solo se asumen elementos HTML estándar. La paginación, disponibilidad de históricos y recursos modales deben verificarse con una sesión real. El archivo de selectores empieza vacío y no contiene selectores institucionales inventados.

10. **Publicación deshabilitada inicialmente.** Requiere interruptor global y acción explícita o autorización automática por módulo. Las pruebas no contactan cuentas externas. Vincular un destino es una operación distinta de publicar contenido.

11. **Concurrencia conservadora.** Un worker serial constituye el valor inicial. Los límites por adaptador impiden exceder dos descargas y un Codex si más adelante se amplía el despachador. Los locks de archivo protegen el navegador y el worker en macOS.

12. **Revisión de rigor diferenciada de lint.** Se validan estructura, contrato y patrones de contenido prohibido mediante la skill. Ni los tests ni el hash certifican profundidad académica, fidelidad ni sintaxis completa de Mermaid.

13. **Vinculación manual de grabaciones como decisión persistida.** Ante estructuras históricas de Moodle, el administrador puede completar una sesión existente o crear una faltante con número, fecha y uno o varios videos ordenados. `recordings_manual` preserva sus fuentes frente a futuros descubrimientos; las sesiones nuevas usan UUID y clave `manual:UUID`, con asignación reservada independientemente de su identidad. La sincronización deduplica videos de sesiones manuales, también cuando sus partes aparecen en actividades distintas. Una asociación no descarga ni publica; mantiene selección y autorización separadas. Los cambios de fuentes se bloquean ante artefactos o trabajos activos, conservando su procedencia y auditoría. No se implementa reemplazo destructivo ni fusión automática de sesiones ya existentes.

14. **Lotes especializados sin cambiar la ejecución individual.** La selección por lote es independiente de las preferencias de automatización. Un servicio central valida igualdad de los cuatro estados y requisitos por operación, tanto en el preview como al enviar. El envío usa una transacción SQLite y crea trabajos ordinarios por clase; conserva límites de concurrencia, recuperación y validaciones del worker. Un trabajo terminal `bulk_dispatch` funciona como comprobante e identificador idempotente de la solicitud sin introducir tablas ni servicios nuevos. La atomicidad se aplica al encolado; cada clase se ejecuta y puede fallar por separado. Procesar o reprocesar en lote no otorga autorización para publicar.

15. **Revisión humana de respuestas guardadas.** Una salida `CODEX_OUTPUT_INVALID` conserva valor editorial y puede revisarse sin otra generación. El servicio comparte validación/exportación con el procesador y permite editar únicamente Markdown o aprobar coincidencias exactas del filtro administrativo. Usa una instancia aislada del validador instalado para esas excepciones; contrato, identidad, estructura y matemáticas siguen siendo obligatorios. Un token liga la aprobación a archivos, fuentes y estado vistos; un UUID hace idempotente la confirmación. La operación guarda un paquete nuevo y un trabajo terminal `academic_review` en una transacción local, conservando el fallo y los artefactos originales. Los conflictos de publicación mantienen su propia dimensión. No añade tablas ni escritura remota.
