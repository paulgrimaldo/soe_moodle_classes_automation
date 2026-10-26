"""Human review of rejected notes, independently of Codex and publication."""

import json
from uuid import uuid4

import streamlit as st

from academic_automation.core.markdown_math import math_for_preview
from academic_automation.core.security import digest


ERRORS = {
    'ACADEMIC_REVIEW_CHANGED': 'La salida cambió desde que la abrió. Pulse Actualizar y revise de nuevo.',
    'ACADEMIC_REVIEW_ASSIGNMENT_CHANGED': 'La asignación de clase cambió respecto de esta generación. Revise la asignación antes de recuperar la salida.',
    'ACADEMIC_REVIEW_SOURCE_CHANGED': 'La transcripción o sus archivos no coinciden con los originales registrados.',
    'ACADEMIC_REVIEW_FINDINGS_CHANGED': 'Los hallazgos cambiaron. Valide el texto actual y vuelva a revisarlos.',
    'ACADEMIC_REVIEW_NOT_AVAILABLE': 'Ya no hay una salida CODEX_OUTPUT_INVALID pendiente para esta sesión. Actualice los estados.',
    'ACADEMIC_REVIEW_FILE_MISSING': 'Faltan archivos originales de esta generación; no se puede recuperarla desde esta revisión.',
    'ACADEMIC_REVIEW_FILE_INVALID': 'Un archivo original no contiene texto o contrato UTF-8 válido.',
    'ACADEMIC_REVIEW_FILE_TOO_LARGE': 'El archivo supera el tamaño permitido para la revisión.',
    'ACADEMIC_REVIEW_PATH_INVALID': 'La ubicación del archivo no pertenece a los artefactos permitidos.',
    'ACADEMIC_REVIEW_NOT_EDITABLE': 'La respuesta no contiene un Markdown editable dentro del contrato esperado.',
    'ACADEMIC_REVIEW_REQUEST_CHANGED': 'Esta confirmación ya se usó con otro contenido. Actualice la revisión.',
}


def render_academic_review(api, session):
    if not session.get('academic_review_available'):
        return
    with st.expander('Previsualizar y aprobar salida rechazada de Codex', expanded=True):
        initial = api('GET', f"/sessions/{session['id']}/academic-review")
        if initial is None:
            return
        base = f"academic_review_{initial['source_job_id']}_{initial['review_token']}"
        report_key = base+'_draft'
        review = st.session_state.get(report_key, initial)
        st.caption(f"Sesión {session['number']} · Trabajo {initial['source_job_id']} · "
                   f"Modelo: {initial['model'] or 'no registrado'}")
        st.info('Esta es una salida pendiente de revisión. Validar y aprobar reutilizan los archivos guardados; '
                'no ejecutan Codex ni publican en Notion.')
        if initial.get('stored_diagnostic'):
            diagnosis = initial['stored_diagnostic']
            st.write('Observación original:', diagnosis.get('reason', 'Salida académica inválida.'))
        preview, located, editor, original, source = st.tabs([
            'Vista previa de la salida', 'Hallazgos y líneas', 'Editar Markdown', 'JSON original', 'Transcripción original'])
        with editor:
            if initial['markdown'] is not None:
                markdown = st.text_area('Markdown para revisión', value=initial['markdown'], height=420, key=base+'_editor')
            else:
                markdown = None
                st.warning('La respuesta no contiene un Markdown editable. Consulte JSON original y el diagnóstico; '
                           'un contrato inválido no puede aprobarse mediante excepciones del lint.')
            if st.button('Validar cambios sin Codex', key=base+'_validate', disabled=markdown is None):
                checked = api('POST', f"/sessions/{session['id']}/academic-review/validate", json={
                    'source_job_id':initial['source_job_id'], 'expected_review_token':initial['review_token'],
                    'markdown':markdown})
                if checked:
                    st.session_state[report_key] = checked
                    st.rerun()
        with preview:
            if markdown is not None:
                st.markdown(math_for_preview(markdown), unsafe_allow_html=False)
            else:
                st.info('No hay Markdown para previsualizar.')
        with located:
            validation = review['validation']
            if validation['passed']:
                st.success('El documento pasa la validación automática.')
            else:
                st.warning(f"{validation.get('stage', 'validación')}: {validation.get('reason', 'Salida inválida.')}")
                if validation.get('issues'):
                    st.json(validation['issues'])
            for finding in review['findings']:
                st.write('Campo:', finding['field'], '· Línea:', finding['line'], '· Coincidencia:', finding['match'])
                st.code(finding['excerpt'], language='markdown')
            if not review['findings'] and not validation['passed']:
                st.caption('Este rechazo no corresponde a una coincidencia del filtro administrativo.')
        with original:
            st.code(initial['raw_response'], language='json')
        with source:
            st.text(initial['transcript'])
        current_validated = markdown == review['markdown']
        if not current_validated:
            st.info('Hay cambios sin validar. Pulse Validar cambios sin Codex antes de aprobar.')
        if review['approval_blocker']:
            st.error('La aprobación está bloqueada: '+review['approval_blocker']['reason'])
        findings_key = digest(json.dumps({'findings':[f['id'] for f in review['findings']],
                                         'markdown_hash':digest(review['markdown'] or '')}))
        label = ('He revisado el contenido y confirmo que todos los hallazgos mostrados son falsos positivos académicos'
                 if review['findings'] else 'He revisado el contenido y apruebo guardar estos apuntes')
        acknowledge = st.checkbox(label, key=base+'_ack_'+findings_key)
        reason = st.text_area('Motivo de la aprobación', key=base+'_reason_'+findings_key,
                              placeholder='Explique por qué el contenido es válido o qué corrigió.')
        disabled = not (review['can_approve'] and current_validated and acknowledge and len(reason.strip()) >= 8)
        if st.button('Aprobar y guardar apuntes sin reprocesar', key=base+'_approve', disabled=disabled):
            payload = {'source_job_id':initial['source_job_id'], 'expected_review_token':initial['review_token'],
                'markdown':markdown, 'approved_finding_ids':[f['id'] for f in review['findings']] if acknowledge else [],
                'reason':reason, 'acknowledge':True}
            pending_key = base+'_request_'+digest(json.dumps(payload, sort_keys=True))
            payload['request_id'] = st.session_state.setdefault(pending_key, str(uuid4()))
            result = api('POST', f"/sessions/{session['id']}/academic-review/approve", json=payload)
            if result:
                st.session_state.pop(pending_key, None)
                st.session_state['academic_review_notice'] = (
                    f"Apuntes de sesión {session['number']} guardados. Puede leerlos en Apuntes. "
                    f"Auditoría: {result['audit_job_id']}. La publicación se solicita por separado.")
                st.rerun()
