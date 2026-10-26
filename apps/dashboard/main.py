from datetime import datetime

import httpx
import pandas as pd
import streamlit as st

from academic_automation.core.config import Settings
from academic_automation.core.markdown_math import math_for_preview
from apps.dashboard.manual_recordings import ERRORS, create_session_form, link_recordings_form
from apps.dashboard.bulk_sessions import render_bulk_operations
from apps.dashboard.academic_review import ERRORS as REVIEW_ERRORS, render_academic_review

settings = Settings()
st.set_page_config(page_title="Automatización académica", layout="wide")
st.title("Automatización académica DCC / MIA")


def api(method, path, **kwargs):
    try:
        response = httpx.request(method, settings.api_url.rstrip("/") + path, timeout=30,
            headers={"Authorization": f"Bearer {settings.admin_token.get_secret_value()}"}, **kwargs)
        if response.is_error:
            try:
                detail = response.json().get("detail", "Error de API")
            except ValueError:
                detail = "Respuesta inválida de API"
            if isinstance(detail, str):
                detail = REVIEW_ERRORS.get(detail, ERRORS.get(detail, detail))
            elif isinstance(detail, dict) and detail.get("code") == "BULK_INCOMPATIBLE":
                detail = detail["message"] + " " + " ".join(detail["issues"])
            elif isinstance(detail, dict) and detail.get("code") == "ACADEMIC_REVIEW_VALIDATION_FAILED":
                detail = "La salida sigue sin pasar la validación: " + detail["validation"]["reason"]
            st.error(f"{response.status_code}: {detail}")
            return None
        return response.json()
    except httpx.HTTPError:
        st.error("Backend no disponible. Inicie la API y compruebe ACADEMIC_API_URL.")
        return None


def action(path, label):
    result = api("POST", path)
    if result:
        st.success(f"{label}: trabajo {result.get('id', 'aceptado')}")


view = st.sidebar.radio("Vista", ["General", "Módulos", "Sesiones", "Apuntes", "Historial"])
if st.sidebar.button("Actualizar"):
    st.rerun()
st.sidebar.caption("El dashboard usa la API; el worker ejecuta las operaciones en el host.")

if view == "General":
    stats = api("GET", "/stats")
    if stats:
        names = {"modules": "Módulos descubiertos", "enabled": "Módulos habilitados", "sessions": "Sesiones disponibles",
                 "processed": "Procesadas", "published": "Publicadas", "pending": "Trabajos pendientes", "failed": "Fallidos / revisión"}
        columns = st.columns(4)
        for index, (key, title) in enumerate(names.items()):
            columns[index % 4].metric(title, stats[key])
        st.write("Última sincronización:", stats["last_sync"] or "Pendiente")
    if st.button("Sincronizar catálogo"):
        action("/sync/catalog", "Catálogo solicitado")
    if st.button("Descubrir grabaciones de módulos habilitados"):
        jobs = api("POST", "/sync/recordings")
        if jobs:
            st.success("Descubrimiento solicitado. Trabajos: " + ", ".join(job["id"] for job in jobs))
            st.caption("Consulte Historial y, cuando terminen, abra Sesiones para el módulo correspondiente.")
        elif jobs is not None:
            st.info("No hay módulos habilitados. Abra Módulos, seleccione uno, marque Habilitar automatización "
                    "y pulse Guardar preferencias. También puede usar Sincronizar grabaciones del módulo "
                    "para una consulta individual.")
    if st.button("Procesar sesiones autorizadas pendientes"):
        api("POST", "/processing/dispatch")

elif view in {"Módulos", "Sesiones", "Apuntes"}:
    program = st.selectbox("Programa", ["Todos", "DCC", "MIA"])
    query = st.text_input("Buscar módulo")
    params = {"q": query}
    if program != "Todos":
        params["program"] = program
    modules = api("GET", "/modules", params=params) or []
    if not modules:
        st.info("No hay módulos para este filtro. Sincronice el catálogo después del login Moodle.")
        st.stop()
    modules_by_id = {module["id"]: module for module in modules}
    module_id = st.selectbox("Módulo", list(modules_by_id), format_func=lambda identifier:
        f"{modules_by_id[identifier]['program']}-{modules_by_id[identifier]['cohort']} / "
        f"{modules_by_id[identifier]['module_number']}. {modules_by_id[identifier]['name']} [{identifier}]")
    chosen = modules_by_id[module_id]
    sessions = api("GET", f"/modules/{module_id}/sessions") or []
    st.caption(f"{len(sessions)} de 8 sesiones descubiertas · "
               f"{sum(s['processing_status'] == 'PROCESSED' for s in sessions)} procesadas · "
               f"{sum(s['publication_status'] == 'PUBLISHED' for s in sessions)} publicadas")
    if view == "Apuntes":
        available = {session["id"]: session for session in sessions if session.get("output_path")}
        if not available:
            st.info("Este módulo todavía no tiene apuntes guardados. Procese una clase desde Sesiones.")
        else:
            note_id = st.selectbox("Clase para leer", list(available), key=f"notes_session_{module_id}",
                format_func=lambda sid: f"Sesión {available[sid]['number']} / {available[sid]['class_date']}")
            note = api("GET", f"/sessions/{note_id}/notes")
            if note:
                st.caption(f"Sesión {note['number']} · {note['class_date']} · Semana {note['week']} / "
                           f"Clase {note['class_in_week']} · Revisión {note['revision']}")
                if note["processing_status"] != "PROCESSED":
                    st.info("Se muestra la última revisión guardada. Estado actual de procesamiento: "
                            + note["processing_status"])
                st.download_button("Descargar Markdown", data=note["markdown"], file_name=note["filename"],
                                   mime="text/markdown", key=f"download_notes_{note_id}_{note['revision']}")
                preview, source = st.tabs(["Vista previa", "Markdown"])
                with preview:
                    st.markdown(math_for_preview(note["markdown"]), unsafe_allow_html=False)
                    if "```mermaid" in note["markdown"].lower():
                        st.caption("Los diagramas Mermaid se conservan como código fuente.")
                with source:
                    st.code(note["markdown"], language="markdown")
    elif view == "Módulos":
        st.dataframe(pd.DataFrame(modules), hide_index=True, use_container_width=True,
                     column_config={"module_number": "Número Moodle",
                                    "export_number": st.column_config.NumberColumn("Número para web", format="%d")})
        with st.form("module_preferences"):
            st.caption(f"Número importado de Moodle: {chosen['module_number']}")
            export_number = st.number_input("Número de módulo para web", min_value=1,
                value=chosen.get("export_number"), step=1, format="%d",
                key=f"export_number_{module_id}_{chosen.get('export_number')}",
                help="Número manual para mostrar y ordenar en la web. "
                     "La exportación exige números únicos por programa y cohorte; Moodle no modifica este campo.")
            clear_export_number = False
            if chosen.get("export_number") is not None:
                clear_export_number = st.checkbox("Borrar número para web al guardar",
                    key=f"clear_export_number_{module_id}_{chosen['export_number']}")
            enabled = st.checkbox("Habilitar automatización", value=chosen["enabled"])
            mode = st.selectbox("Modo", ["MANUAL", "ALL", "NEW_ONLY"], index=["MANUAL", "ALL", "NEW_ONLY"].index(chosen["mode"]))
            st.caption("NEW_ONLY fija una marca temporal al entrar al modo; sincronizar no la modifica.")
            auto_publish = st.checkbox("Autorizo publicar automáticamente el contenido generado de este módulo en Notion",
                                       value=chosen["auto_publish"])
            if st.form_submit_button("Guardar preferencias"):
                api("PATCH", f"/modules/{module_id}", json={"enabled": enabled, "mode": mode,
                    "auto_publish": auto_publish,
                    "export_number": None if clear_export_number else export_number})
                st.rerun()
        if st.button("Sincronizar grabaciones del módulo"):
            action(f"/sync/modules/{module_id}", "Sincronización solicitada")
        links = api("GET", f"/notion/modules/{module_id}/pages") or []
        module_page = next((link for link in links if link["week"] == 0), None)
        saved_destination = (module_page.get("url") or module_page["page_id"]) if module_page else ""
        if module_page:
            st.caption("Página del módulo vinculada en Notion")
            st.link_button("Abrir módulo en Notion", module_page.get("url") or
                           f"https://www.notion.so/{module_page['page_id'].replace('-', '')}")
        with st.form(f"notion_link_{module_id}"):
            destination = st.text_input("URL o ID de página existente en Notion", value=saved_destination,
                key=f"notion_destination_{module_id}_{module_page['page_id'] if module_page else 'unlinked'}")
            week = st.number_input("Semana (0 = página del módulo)", min_value=0,
                                   max_value=8 if chosen["program"] == "DCC" else 4, value=0,
                                   key=f"notion_link_week_{module_id}")
            if st.form_submit_button("Validar y vincular página"):
                result = api("POST", f"/notion/modules/{module_id}/link", json={"page_id": destination, "week": week})
                if result:
                    st.success("Página disponible y vinculada")
        with st.expander("Recuperar vínculo de una página eliminada"):
            if not links:
                st.info("No hay vínculos anteriores. Use Validar y vincular página.")
            else:
                by_id = {link["page_id"]: link for link in links}
                previous_id = st.selectbox("Página eliminada", list(by_id), key=f"relink_old_{module_id}",
                    format_func=lambda pid: ("Página del módulo" if by_id[pid]["week"] == 0
                                            else f"Semana {by_id[pid]['week']}") + f" · {pid}")
                previous = by_id[previous_id]
                st.caption("La nueva página debe estar compartida con la conexión de Notion del backend.")
                st.warning("Esta recuperación archiva las asociaciones anteriores de " +
                           ("todas las semanas del módulo." if previous["week"] == 0 else f"Semana {previous['week']}.") +
                           " Conserva transcripciones y apuntes. Después deberá solicitar publicar cada clase.")
                acknowledge = st.checkbox("Confirmo que eliminé la página anterior y autorizo sustituir sus asociaciones locales",
                                          key=f"relink_ack_{module_id}_{previous_id}")
                with st.form(f"notion_relink_{module_id}_{previous_id}"):
                    replacement = st.text_input("URL o ID de la página nueva")
                    if st.form_submit_button("Validar página nueva y recuperar vínculo", disabled=not acknowledge):
                        result = api("POST", f"/notion/modules/{module_id}/relink", json={
                            "page_id": replacement, "week": previous["week"], "previous_page_id": previous_id,
                            "acknowledge_replacement": True})
                        if result:
                            st.success("Vínculo recuperado. Los apuntes están disponibles para volver a publicar desde Sesiones. "
                                       f"Registro de auditoría: {result.get('audit_job_id') or 'ya aplicado'}")
    else:
        if notice := st.session_state.pop("academic_review_notice", None):
            st.success(notice)
        if notice := st.session_state.pop("manual_recordings_notice", None):
            st.success(notice)
        rows = []
        occupied = set()
        for s in sessions:
            occupied.add(s["number"])
            rows.append({"id": s["id"], "Sesión": s["number"], "Semana": s["week"], "Clase": s["class_in_week"],
                         "Fecha": s["class_date"], "YouTube": s["youtube_url"], "Partes": len(s.get("recordings", [])) or int(bool(s["youtube_url"])),
                         "Descubrimiento": s.get("discovery_status", ""), "Transcripción": s["transcript_status"],
                         "Vínculo": "Manual" if s.get("recordings_manual") else "Moodle",
                         "Codex": s["processing_status"], "Notion": s["publication_status"],
                         "Selección": s["selected"], "Excluida": s["excluded"]})
        for number in range(1, 9):
            if number not in occupied:
                rows.append({"id": None, "Sesión": number, "Semana": number if chosen["program"] == "DCC" else (number + 1) // 2,
                             "Clase": 1 if chosen["program"] == "DCC" else (number - 1) % 2 + 1,
                             "Fecha": None, "YouTube": None, "Transcripción": "AÚN NO DESCUBIERTA",
                             "Codex": "PENDIENTE", "Notion": "PENDIENTE", "Selección": False, "Excluida": False})
        st.caption("Las filas aún no descubiertas son posiciones esperadas; no representan grabaciones confirmadas.")
        frame = pd.DataFrame(rows).sort_values("Sesión", na_position="last")
        edited = st.data_editor(frame, hide_index=True, use_container_width=True,
            disabled=[c for c in frame.columns if c not in {"Selección", "Excluida"}],
            column_config={"id": None, "YouTube": st.column_config.LinkColumn("YouTube")})
        if st.button("Guardar selección y exclusiones"):
            for row in edited.to_dict("records"):
                if row["id"]:
                    original = next(s for s in sessions if s["id"] == row["id"])
                    if original["selected"] != row["Selección"] or original["excluded"] != row["Excluida"]:
                        api("PATCH", f"/sessions/{row['id']}", json={"selected": row["Selección"], "excluded": row["Excluida"]})
            st.rerun()
        create_session_form(api, chosen, sessions)
        if sessions:
            sessions_by_id = {session["id"]: session for session in sessions}
            selected_id = st.selectbox("Sesión para una acción", list(sessions_by_id), index=None,
                key=f"action_session_{module_id}", placeholder="Elija la clase para estos botones",
                format_func=lambda sid: f"Sesión {sessions_by_id[sid]['number'] or '?'} / "
                    f"{sessions_by_id[sid]['class_date']} / {sessions_by_id[sid]['title']}")
            st.caption("La columna Selección se usa en el modo MANUAL; los botones individuales usan "
                       "exclusivamente la clase elegida en este selector.")
            if selected_id is None:
                st.info("Elija una clase en Sesión para una acción antes de procesar, reprocesar o publicar.")
            else:
                selected = sessions_by_id[selected_id]
                link_recordings_form(api, selected)
                selected_date = datetime.fromisoformat(selected["class_date"]).strftime("%d/%m/%Y")
                st.info(f"Acciones sobre sesión {selected['number']} · {selected_date} · "
                        f"Semana {selected['week']} / Clase {selected['class_in_week']}")
                st.write("Transcripción:", selected["transcript_status"], "· Codex:", selected["processing_status"],
                         "· Notion:", selected["publication_status"])
                st.write("Error:", selected["error_code"] or "Ninguno")
                render_academic_review(api, selected)
                if len(selected.get("recordings", [])) > 1:
                    for part in selected["recordings"]:
                        st.link_button(f"YouTube · Parte {part['position']}", part["url"])
                    st.caption("Todas las partes se procesan juntas como una clase, en el orden mostrado.")
                if selected["notion_url"]:
                    st.link_button("Abrir semana en Notion", selected["notion_url"])
                if selected.get("discovery_status") == "REVIEW_REQUIRED":
                    st.warning("Esta grabación requiere revisar sus videos. Puede procesar las demás clases identificadas del módulo.")
                else:
                    cols = st.columns(4)
                    for col, (operation, label) in zip(cols, [("process", "Procesar"), ("retry", "Reintentar"),
                                                             ("reprocess", "Reprocesar Codex"), ("publish", "Publicar / actualizar Notion")]):
                        if col.button(label):
                            action(f"/sessions/{selected['id']}/{operation}", f"{label} · sesión {selected['number']} · {selected_date}")
                st.caption("Publicar / actualizar constituye autorización explícita para esta clase. El interruptor global debe estar habilitado.")
                with st.expander("Corregir asignación académica"):
                    with st.form(f"session_assignment_{selected_id}"):
                        w = st.number_input("Semana", 1, 8 if chosen["program"] == "DCC" else 4, selected["week"] or 1)
                        c = st.number_input("Clase dentro de semana", 1, 1 if chosen["program"] == "DCC" else 2,
                                            selected["class_in_week"] or 1)
                        if st.form_submit_button("Guardar corrección"):
                            api("PATCH", f"/sessions/{selected['id']}", json={"week": w, "class_in_week": c})
                            st.rerun()
                    st.caption("Si hay contenido generado o una posición ocupada se prepara una propuesta para confirmar abajo.")
                if selected["publication_status"] == "REVIEW_REQUIRED":
                    with st.expander("Revisar conflicto o publicación interrumpida"):
                        if st.button("Consultar bloques remotos"):
                            result = api("GET", f"/sessions/{selected['id']}/notion/review")
                            if result:
                                st.json(result)
                        st.caption("Revise la página en Notion y resuelva allí cualquier bloque parcial duplicado. "
                                   "Indique únicamente los IDs contiguos que pertenecen a esta clase, en orden.")
                        block_ids = st.text_area("IDs de bloques de la clase, uno por línea")
                        overwrite = st.checkbox("Revisé los bloques y autorizo que la próxima publicación sustituya este contenido")
                        if st.button("Aceptar nueva base para actualización", disabled=not overwrite):
                            api("POST", f"/sessions/{selected['id']}/notion/resolve", json={
                                "block_ids": [i.strip() for i in block_ids.splitlines() if i.strip()],
                                "acknowledge_overwrite": True})
                            st.rerun()
        render_bulk_operations(api, module_id, sessions)
    if chosen["review_required"]:
        st.warning("Módulo detenido para revisión de asignaciones.")
        if chosen["proposed_assignments"]:
            st.dataframe(pd.DataFrame(chosen["proposed_assignments"]), hide_index=True)
            approve = st.checkbox("Revisé la propuesta y autorizo renumerar los apuntes y trasladar sus secciones publicadas")
            if st.button("Confirmar reconciliación", disabled=not approve):
                action(f"/modules/{module_id}/reconcile", "Reconciliación solicitada")

else:
    status = st.selectbox("Estado", ["Todos", "QUEUED", "RUNNING", "RETRY_WAIT", "COMPLETED", "FAILED", "REVIEW_REQUIRED", "CANCELLED"])
    jobs = api("GET", "/jobs", params={} if status == "Todos" else {"status": status}) or []
    rows = []
    for job in jobs:
        row = dict(job)
        if job["started_at"] and job["finished_at"]:
            row["duration_seconds"] = (datetime.fromisoformat(job["finished_at"]) - datetime.fromisoformat(job["started_at"])).total_seconds()
        row["notion_url"] = (job["result"] or {}).get("notion_url")
        rows.append(row)
    columns = ["created_at", "kind", "status", "error_code", "stage", "attempts",
               "available_at", "duration_seconds", "model", "skill_version", "notion_url", "id"]
    st.dataframe(pd.DataFrame(rows).reindex(columns=columns), hide_index=True, use_container_width=True)
    st.caption("RETRY_WAIT: reintento automático con espera progresiva. Las fechas del historial están en UTC.")
    if jobs:
        selected = st.selectbox("Detalle de trabajo", jobs, format_func=lambda j: f"{j['created_at']} / {j['kind']} / {j['status']} / {j['id']}")
        detail = api("GET", f"/jobs/{selected['id']}")
        if detail:
            if detail.get("error_code"):
                st.warning(f"Último error: {detail['error_code']}")
            if (detail.get("result") or {}).get("reviews"):
                st.info("La sincronización guardó las sesiones descubiertas. Solo las grabaciones indicadas en reviews "
                        "requieren revisión; las demás están disponibles en Sesiones.")
            validation = (detail.get("result") or {}).get("validation")
            if validation:
                st.info(f"Validación ({validation['stage']}): {validation['reason']}")
                if validation.get("findings"):
                    st.dataframe(pd.DataFrame(validation["findings"]), hide_index=True)
            if detail.get("status") == "RETRY_WAIT":
                st.write("Próximo intento (UTC):", detail.get("available_at"))
            st.json(detail)
