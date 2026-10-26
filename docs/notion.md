# Notion: destino, publicación y conflictos

Cree una conexión de Notion y comparta con ella las páginas existentes de sus módulos. Configure `ACADEMIC_NOTION_TOKEN` en `.env`; no lo introduzca en SQLite ni lo entregue al proceso Codex.

La conexión MCP de un cliente como Codex no autentica automáticamente al servicio FastAPI. En este proyecto, Codex genera el Markdown y el backend publica mediante la API REST, conservando en SQLite los IDs de bloques y hashes para gestionar duplicados y conflictos. El proceso Codex automático tiene MCP y Apps deshabilitados. Un publicador mediante MCP necesitaría un adaptador y autenticación propios; no está implementado. Por tanto, `NOTION_TOKEN_MISSING` se resuelve configurando `ACADEMIC_NOTION_TOKEN` para el backend, aunque el cliente interactivo ya tenga Notion conectado.

El token se obtiene en la configuración de una conexión interna de Notion. Comparta con esa conexión la página del módulo desde su menú `••• → Add connections`, guarde el token únicamente en `.env` y reinicie API y worker. Después valide/vincule el destino desde el dashboard. No pegue el token en conversaciones ni en el campo de URL/ID de página.

Vincule cada módulo desde el dashboard mediante el ID o URL de su página. La vinculación valida acceso y persiste el destino; no publica contenido. Se puede vincular una semana existente indicando su número, siempre que pertenezca al módulo vinculado. Si faltan asociaciones, se permite búsqueda exacta de título bajo `ACADEMIC_NOTION_DCC_ROOT` o `ACADEMIC_NOTION_MIA_ROOT`. No se crean raíces ni módulos alternativos. Cero o varias coincidencias requieren intervención.

Para autorizar escrituras, cambie `ACADEMIC_PUBLICATION_ENABLED=true` y reinicie API y worker. Después pulse **Publicar / actualizar Notion**. Para publicación desatendida, habilite además la casilla de autorización `auto_publish` del módulo. La configuración inicial no autoriza publicaciones y la implementación no publicó contenido real durante las pruebas.

## Estructura

DCC tiene hasta ocho páginas Semana, cada una con una clase. MIA tiene hasta cuatro páginas Semana; contiene encabezados Clase 1 y Clase 2 y un divisor nativo. Las semanas se crean al publicar su primer contenido y se reutilizan por ID. No se crean páginas por clase ni se sustituye una página completa.

El resolvedor valida que las páginas asociadas sigan accesibles y bajo el módulo correcto. Ante ambigüedad se detiene. Un encabezado de clase existente sin asociación de bloques también bloquea la publicación para impedir duplicarlo.

Se utiliza la API `2026-03-11`, que permite insertar al inicio mediante `position`. Esto resuelve la llegada posterior de Clase 1. Una actualización reemplaza exclusivamente los IDs de bloques de su clase. Se conserva la otra sección, incluso cuando contiene ediciones manuales. Si se intenta actualizar la sección editada, se detecta un conflicto por hash.

Se inspeccionan bloques descendientes, incluidas filas de tablas. Una inserción entre bloques propios, un bloque eliminado o un cambio de contenido/estilo detiene la actualización. Los hashes excluyen metadatos administrativos de Notion. Los IDs y el divisor semanal se guardan en SQLite.

La idempotencia compara el hash de los bloques convertidos, además de comprobar la integridad del Markdown original. Esto permite aplicar una corrección del conversor al pulsar **Publicar / actualizar Notion**, aunque la fuente académica no cambie. Las filas antiguas que guardaban solo el hash de fuente se actualizan en esa publicación explícita; no requiere migrar el esquema ni regenerar apuntes. Se verifica el hash remoto antes de sustituir los bloques y se conserva la otra clase de la semana.

Notion no ofrece una transacción atómica ni una comparación condicional para toda la sección. El servicio persiste intención antes de escribir. Una interrupción, una respuesta de escritura incierta o un conflicto exige revisión; no se reintenta a ciegas una creación ni un append. Existe una ventana inevitable si un humano edita exactamente durante la escritura: evite editar esa sección mientras se publica.

## Resolver un conflicto

`NOTION_EXTERNAL_EDIT_CONFLICT` significa que los bloques de esta clase ya no producen el hash guardado en la publicación. No depende de que la aplicación de Notion esté abierta: la comparación se hace contra el servicio remoto. El mensaje por sí solo no identifica quién cambió el contenido ni permite descartar un falso positivo del comparador. Reintentar o reprocesar con Codex no resuelve esa diferencia.

Antes de aceptar una nueva base, capture evidencia sin modificar la página:

```bash
uv run academic notion-inspect --session-id UUID_DE_LA_SESION
```

El UUID figura en el detalle del trabajo. No requiere reiniciar servicios. El comando consulta solamente la sección administrada y sus descendientes; guarda los bloques, orden, IDs y hashes en `data/private/notion-inspections/` con permiso `0600`. La consola muestra únicamente estado, contadores y ruta del diagnóstico. No cambia bloques, hashes ni trabajos. El archivo contiene apuntes privados y debe revisarse localmente. Cada captura tiene un nombre diferente para conservar evidencia. Un error de red o permisos se informa sin imprimir el token.

Las publicaciones existentes conservan solo el hash remoto, no una copia histórica de los bloques; por ello esta captura permite inspeccionar el estado actual, pero no promete un diff exacto contra una versión histórica inexistente. No se restablecen hashes automáticamente.

1. Abra la semana en Notion y el detalle del trabajo en el dashboard.
2. En Sesiones, use **Revisar conflicto o publicación interrumpida** para consultar bloques y su asociación actual.
3. Conserve manualmente el contenido deseado en Notion y elimine allí cualquier duplicado parcial. El servicio no adivina qué parte conservar tras una escritura incierta.
4. Indique los IDs contiguos que pertenecen exclusivamente a esa clase, en orden, y autorice explícitamente la próxima sustitución. No se aceptan IDs pertenecientes a otra clase administrada.
5. Solicite publicar de nuevo. No se sobrescriben modificaciones externas por el mero hecho de reintentar un trabajo.

Si la escritura de creación de una semana perdió la respuesta antes de asociarla, busque la página creada y vincúlela manualmente; el resolvedor no repetirá ese trabajo automáticamente. Las reconciliaciones parcialmente ejecutadas requieren revisar páginas, asociaciones y propuesta antes de repetirlas.

## Página eliminada y creada de nuevo

Una página nueva tiene otro ID aunque tenga el mismo título. SQLite conserva el ID publicado anteriormente; después de eliminarla pueden aparecer `NOTION_PAGE_IN_TRASH` o `NOTION_OBJECT_UNAVAILABLE`. Este último también puede indicar pérdida de acceso de la conexión, por lo que no se descartan asociaciones automáticamente ante un 404.

En **Módulos → Recuperar vínculo de una página eliminada**, seleccione la página anterior, indique la URL nueva y confirme que desea sustituir las asociaciones locales. Comparta primero la página nueva con la conexión de Notion. Si reemplazó una semana, la nueva página debe depender directamente de la página del módulo ya vinculada. Si reemplazó el módulo completo, seleccione **Página del módulo**: también se archivan los vínculos de sus semanas anteriores.

La recuperación valida el acceso al destino nuevo y que el anterior ya no esté disponible o esté en la papelera. Rechaza páginas asignadas a otro destino, una página anterior todavía accesible, permisos/red inválidos y módulos con trabajos activos. La sustitución local es atómica y se registra en Historial como `notion_relink`, incluyendo los antiguos IDs de página/bloques y hashes. No modifica ni borra contenido remoto. Se conservan sesiones, transcripciones, Markdown y revisiones; la publicación vuelve a `PENDING` en las sesiones afectadas y las demás semanas se conservan si solo se reemplaza una.

Después solicite **Publicar / actualizar Notion** desde Sesiones. No necesita volver a descargar ni ejecutar Codex. Los títulos de clase ajenos en la página nueva siguen sujetos al control contra duplicados. API administrativa: `GET /notion/modules/{id}/pages` y `POST /notion/modules/{id}/relink`, con `page_id`, `week`, `previous_page_id` y `acknowledge_replacement: true`. Repetir la misma recuperación aplicada es idempotente.

## Conversión de contenido

Encabezados, párrafos, énfasis, enlaces HTTP(S), listas, citas/callouts, tablas y divisores usan bloques nativos. Las listas anidadas se aplanan conservando el orden y el texto; las tablas largas se dividen con encabezado repetido. Fórmulas de bloque `$$...$$` o `\[...\]` usan bloques de ecuación nativos. Las fórmulas `$...$` o `\(...\)` dentro de párrafos, encabezados, listas y celdas usan rich text de tipo `equation`, preservando el énfasis. No se reinterpretan fórmulas dentro de código ni precios como `$5 ... $10`. Imágenes Markdown se conservan como descripción y URL, sin descargar contenido externo.

El parser reconoce las fórmulas antes de que CommonMark elimine las barras de los delimitadores. Se comprueban cierre de delimitadores explícitos, llaves balanceadas, expresión no vacía y límite de 1000 caracteres. Un fallo solicita revisión antes de escribir en Notion; una fórmula extensa no se trunca ni se degrada silenciosamente a texto. Estas comprobaciones son estructurales: no certifican el significado matemático ni todos los comandos de KaTeX. Las mismas comprobaciones se aplican a nuevas salidas de Codex antes de exportarlas. El prompt exige variables, supuestos, interpretación y límites, y ejemplos/derivaciones cuando estén justificados por la clase.

La vista **Apuntes** adapta los delimitadores de presentación para Streamlit, conservando intactos el archivo original, los fragmentos de código y la descarga. Una corrección del formato no modifica la transcripción ni inventa una nueva derivación académica.

Mermaid se conserva como código `plain text` con leyenda Mermaid; no se presume renderizado nativo. HTML y lenguajes desconocidos conservan su fuente en código. Los textos se dividen en segmentos para respetar los límites de Notion; se limitan tamaño, bloques y descendientes por solicitud. Solicitudes demasiado grandes requieren revisión, sin truncar contenido.

Se limita el ritmo a aproximadamente 2.5 solicitudes/segundo. Los 429/529 respetan `Retry-After`; solo las lecturas y eliminaciones reintentan errores de servidor. Una escritura con resultado incierto pasa a revisión.

Referencias: [cambios de la API 2026-03-11](https://developers.notion.com/guides/get-started/upgrade-guide-2026-03-11), [ecuaciones inline de Notion](https://developers.notion.com/reference/rich-text#equation), [bloques de ecuación](https://developers.notion.com/reference/block#equation), [límites y reintentos de Notion](https://developers.notion.com/reference/request-limits).
