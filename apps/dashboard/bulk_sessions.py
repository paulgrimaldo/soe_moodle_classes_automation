"""Separate selection for bulk actions; eligibility is decided by the backend."""

from uuid import uuid4

import pandas as pd
import streamlit as st


def render_bulk_operations(api, module_id, sessions):
    st.divider()
    st.subheader("Operaciones por lote")
    st.caption("Esta selección es independiente de la columna Selección del modo MANUAL y de los botones individuales. "
               "Cada clase genera su propio trabajo; el worker los ejecuta con la concurrencia habitual.")
    receipt = st.session_state.get(f"bulk_receipt_{module_id}")
    if receipt:
        st.success(f"Lote aceptado: {len(receipt['jobs'])} trabajos. Consulte Historial para seguir su ejecución.")
        st.caption(f"Identificador del lote: {receipt['batch_id']}")
        st.dataframe(pd.DataFrame([{"Sesión ID": job["session_id"], "Trabajo": job["id"],
                                   "Operación": job["kind"], "Estado al aceptar": job["status"]}
                                  for job in receipt["jobs"]]), hide_index=True, use_container_width=True)
    if not sessions:
        st.info("No hay sesiones descubiertas o creadas para este módulo.")
        return
    by_id = {session["id"]: session for session in sessions}
    selected_ids = st.multiselect("Sesiones para el lote", list(by_id), key=f"bulk_sessions_{module_id}",
        format_func=lambda sid: f"Sesión {by_id[sid]['number'] or '?'} / {by_id[sid]['class_date']} / {by_id[sid]['title']}")
    if not selected_ids:
        st.info("Seleccione las sesiones para consultar las operaciones compatibles.")
        return
    preview = api("POST", f"/modules/{module_id}/sessions/bulk/preview", json={"session_ids": selected_ids})
    if preview is None:
        return
    st.dataframe(pd.DataFrame([{"Sesión": s["number"], "Fecha": s["class_date"],
                               "Descubrimiento": s["discovery_status"], "Transcripción": s["transcript_status"],
                               "Codex": s["processing_status"], "Notion": s["publication_status"]}
                              for s in preview["sessions"]]), hide_index=True, use_container_width=True)
    if not preview["homogeneous"]:
        st.warning("El lote requiere el mismo estado de descubrimiento, transcripción, Codex y Notion en todas las sesiones.")
    st.caption("El backend vuelve a validar todo al enviar. Si alguna sesión no cumple, no se encola ninguna. "
               "Publicar / actualizar Notion en lote autoriza explícitamente la publicación de las clases seleccionadas.")
    operations = [("process", "Procesar lote"), ("reprocess", "Procesar / reprocesar Codex en lote"),
                  ("publish", "Publicar / actualizar Notion en lote")]
    for col, (operation, label) in zip(st.columns(3), operations):
        validation = preview["operations"][operation]
        with col:
            if st.button(label, key=f"bulk_{operation}_{module_id}", disabled=not validation["compatible"]):
                # Keep the UUID on network errors so retrying a request can reuse its receipt.
                request_key = f"bulk_request_{module_id}_{operation}_{','.join(sorted(selected_ids))}"
                request_id = st.session_state.setdefault(request_key, str(uuid4()))
                result = api("POST", f"/modules/{module_id}/sessions/bulk", json={
                    "session_ids": selected_ids, "operation": operation, "request_id": request_id})
                if result:
                    st.session_state[f"bulk_receipt_{module_id}"] = result
                    st.session_state.pop(request_key, None)
                    st.rerun()
            if validation["issues"]:
                st.caption(" ".join(validation["issues"]))
