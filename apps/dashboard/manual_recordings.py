"""Manual recording forms; persistence and validation belong to the API."""
from datetime import date

import streamlit as st


ERRORS = {
    "MODULE_HAS_ACTIVE_JOBS": "Espere a que terminen los trabajos pendientes de este módulo.",
    "MANUAL_RECORDINGS_ARTIFACTS_EXIST": "Esta sesión ya tiene archivos descargados, apuntes o una publicación. "
        "Se conservan sus videos y el material existente; no se permite sustituir ni reordenar sus partes.",
    "VIDEO_LINKED_TO_OTHER_SESSION": "Uno de los videos ya está vinculado a otra sesión. Revise la clase elegida.",
    "SESSION_SLOT_OCCUPIED": "Esa posición ya tiene una sesión. Elíjala en Sesión para una acción y vincule allí sus grabaciones.",
    "MODULE_RECONCILIATION_REQUIRED": "Resuelva la revisión de asignaciones del módulo antes de crear otra sesión.",
}


def urls_from_text(value):
    return [line.strip() for line in value.splitlines() if line.strip()]


def saved(result):
    st.session_state["manual_recordings_notice"] = (
        "Grabaciones vinculadas. Elija la sesión y pulse Procesar cuando desee descargar y generar sus apuntes."
        if result["changed"] else "El vínculo ya estaba guardado; no se realizaron cambios."
    )
    st.rerun()


def create_session_form(api, module, sessions):
    occupied = {session["number"] for session in sessions}
    available = [number for number in range(1, 9) if number not in occupied]
    with st.expander("Crear sesión y vincular grabaciones"):
        st.caption("Use esta opción si Moodle no descubre la clase. Para una sesión que ya aparece en la tabla, "
                   "elíjala en Sesión para una acción y use Vincular grabaciones manualmente.")
        if not available:
            st.info("Las ocho posiciones ya tienen una sesión. Puede vincular videos a una sesión existente.")
            return
        with st.form(f"create_manual_session_{module['id']}"):
            number = st.selectbox("Número de sesión", available, index=None, placeholder="Elija la sesión")
            class_date = st.date_input("Fecha de la clase", value=date.today(), key=f"manual_date_{module['id']}")
            title = st.text_input("Título de la sesión (opcional)")
            links = st.text_area("Enlaces YouTube de la nueva sesión, uno por línea y en orden")
            st.caption("Una línea = un video. Si la clase está dividida, pegue primero la parte 1, después la parte 2, etc. "
                       "Se guardará una sola sesión. Guardar no descarga ni publica contenido.")
            if st.form_submit_button("Crear sesión con grabaciones"):
                if number is None or not urls_from_text(links):
                    st.warning("Elija una sesión e indique al menos un enlace de YouTube.")
                else:
                    result = api("POST", f"/modules/{module['id']}/sessions/manual", json={
                        "number": number, "class_date": class_date.isoformat(), "title": title,
                        "youtube_urls": urls_from_text(links)})
                    if result:
                        saved(result)


def link_recordings_form(api, session):
    with st.expander("Vincular grabaciones manualmente"):
        if session.get("recordings_manual"):
            st.info("El vínculo manual tiene prioridad sobre el descubrimiento de Moodle.")
        links = "\n".join(part["url"] for part in session.get("recordings", []))
        # Compatibility with previously returned single-recording sessions.
        links = links or session.get("youtube_url") or ""
        with st.form(f"manual_recordings_{session['id']}"):
            text = st.text_area("Enlaces YouTube de esta sesión, uno por línea y en orden", value=links)
            st.caption("Pegue una o varias partes de esta misma clase en su orden de reproducción. "
                       "El vínculo manual se conserva al sincronizar. Si ya hay archivos descargados o apuntes, "
                       "sus videos y orden no pueden cambiarse.")
            if st.form_submit_button("Guardar vínculo manual"):
                if not urls_from_text(text):
                    st.warning("Indique al menos un enlace de YouTube.")
                else:
                    result = api("PUT", f"/sessions/{session['id']}/recordings", json={"youtube_urls": urls_from_text(text)})
                    if result:
                        saved(result)
