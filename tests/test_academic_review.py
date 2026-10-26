import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from academic_automation.academic.processor import load_skill
from academic_automation.core.schemas import CodexInput
from academic_automation.core.security import digest
from academic_automation.database.models import AcademicModule, AcademicSession, ProcessingJob, TranscriptArtifact, uid
from test_academic import model_output
from test_api import client_for

ADMIN = {'Authorization': 'Bearer admin-test'}
URL = '/sessions/review-session/academic-review'


@pytest.fixture
def rejected_api(tmp_path, monkeypatch):
    from datetime import date
    path = Path('~/.agents/skills/academic-transcription-to-notion').expanduser()
    if not path.is_dir():
        pytest.skip('Requires installed academic validators')
    skill, skill_hash = load_skill(path)
    app, client = client_for(tmp_path)
    app.state.settings.skill_path = path
    app.state.settings.prepare()
    job_id = uid()
    work = app.state.settings.workdir('processed', job_id+'-1')
    source = tmp_path/'transcripts'/'review-session'
    source.mkdir(parents=True)
    txt, vtt = source/'source.txt', source/'source.vtt'
    txt.write_text('Partición de datos para entrenamiento, validación y prueba.')
    vtt.write_text('WEBVTT\n')
    request = CodexInput(request_id=job_id+'-1', program='DCC', module_id=356, module_title='Ciencia de datos',
                         number=4, week=4, class_in_week=1, transcript_file=txt)
    raw = model_output(request_id=request.request_id, number=4)
    raw['classes'][0]['markdown'] += '\nSe comparan particiones de datos 80/20 y 60/20/20.\n'
    (work/'request.json').write_text(request.model_dump_json())
    (work/'response.json').write_text(json.dumps(raw, ensure_ascii=False))
    original = (work/'response.json').read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('Review must never invoke Codex or Notion')
    monkeypatch.setattr('academic_automation.academic.processor.CodexAcademicProcessor.process', forbidden)
    monkeypatch.setattr('academic_automation.notion.client.NotionClient.__init__', forbidden)
    with client:
        with app.state.sessions() as db:
            db.add(AcademicModule(id=356, program='DCC', cohort='V1E1', module_number=10, name='Ciencia de datos'))
            db.commit()
            db.add(AcademicSession(id='review-session', module_id=356, resource_key='manual:review', title='Clase 4',
                class_date=date(2025, 9, 13), number=4, week=4, class_in_week=1, discovery_status='VIDEO_IDENTIFIED',
                transcript_status='TRANSCRIPT_READY', processing_status='REVIEW_REQUIRED', error_code='CODEX_OUTPUT_INVALID'))
            db.commit()
            db.add(TranscriptArtifact(session_id='review-session', txt_path=str(txt), vtt_path=str(vtt),
                txt_hash=digest(txt.read_bytes()), vtt_hash=digest(vtt.read_bytes())))
            db.add(ProcessingJob(id=job_id, kind='reprocess', active_key='session:review-session',
                module_id=356, session_id='review-session', attempts=1, status='REVIEW_REQUIRED', stage='codex',
                error_code='CODEX_OUTPUT_INVALID', skill_hash=skill_hash, skill_version='1.0', result={'validation': {
                'stage':'academic_lint','reason':'Se detectó contenido administrativo o una fecha en la salida.'}}))
            db.commit()
        yield app, client, work, raw, original, job_id


def preview(client):
    response = client.get(URL, headers=ADMIN)
    assert response.status_code == 200, response.text
    return response.json()


def approval(p, **changes):
    return {'source_job_id':p['source_job_id'], 'expected_review_token':p['review_token'],
        'request_id':str(uuid4()), 'acknowledge':True, 'reason':'La proporción es contenido académico, no una fecha.',
        'approved_finding_ids':[f['id'] for f in p['findings']], **changes}


def test_preview_locates_false_positive_and_does_not_mutate(rejected_api):
    app, client, work, raw, original, job_id = rejected_api
    p = preview(client)
    assert p['source_job_id'] == job_id and p['can_approve']
    assert p['findings'][0]['match'] == '60/20/20'
    assert p['findings'][0]['field'] == 'classes.0.markdown'
    assert str(p['findings'][0]['line'])+':' in p['findings'][0]['excerpt']
    assert p['markdown'] == raw['classes'][0]['markdown']
    assert (work/'response.json').read_bytes() == original
    with app.state.sessions() as db:
        assert db.get(AcademicSession, 'review-session').processing_status == 'REVIEW_REQUIRED'
        assert len(list(db.scalars(select(ProcessingJob)))) == 1


def test_explicit_false_positive_approval_preserves_text_and_creates_audited_bundle(rejected_api):
    app, client, work, raw, original, job_id = rejected_api
    p = preview(client)
    payload = approval(p)
    response = client.post(URL+'/approve', headers=ADMIN, json=payload)
    assert response.status_code == 200, response.text
    repeat = client.post(URL+'/approve', headers=ADMIN, json=payload)
    assert repeat.status_code == 200 and not repeat.json()['changed']
    with app.state.sessions() as db:
        session = db.get(AcademicSession, 'review-session')
        assert session.processing_status == 'PROCESSED' and session.error_code is None
        assert session.transcript_status == 'TRANSCRIPT_READY' and session.publication_status == 'PENDING'
        notes = Path(session.output_path)
        assert '60/20/20' in notes.read_text()
        metadata = json.loads((notes.parent/'metadata.json').read_text())
        assert metadata['validation']['academic_lint'] == 'human_approved_false_positives'
        assert metadata['human_review']['source_job_id'] == job_id
        assert db.get(ProcessingJob, job_id).status == 'REVIEW_REQUIRED'
        assert db.get(ProcessingJob, response.json()['audit_job_id']).kind == 'academic_review'
        assert len(list(db.scalars(select(ProcessingJob)))) == 2
    assert (work/'response.json').read_bytes() == original
    skill, _ = load_skill(app.state.settings.skill_path)
    with pytest.raises(skill.Failure):
        skill.validate_result({'request_id':job_id+'-1','classes':[{'class_number':4}]}, raw)
    assert client.get('/sessions/review-session/notes', headers=ADMIN).status_code == 200


def test_edit_then_validate_and_approve_without_exceptions(rejected_api):
    app, client, work, raw, original, job_id = rejected_api
    p = preview(client)
    markdown = p['markdown'].replace('60/20/20', '60 % / 20 % / 20 %')
    draft = {'source_job_id':p['source_job_id'], 'expected_review_token':p['review_token'], 'markdown':markdown}
    checked = client.post(URL+'/validate', headers=ADMIN, json=draft)
    assert checked.status_code == 200 and checked.json()['validation']['passed']
    response = client.post(URL+'/approve', headers=ADMIN, json=approval(p, markdown=markdown, approved_finding_ids=[]))
    assert response.status_code == 200, response.text
    notes = client.get('/sessions/review-session/notes', headers=ADMIN).json()
    assert '60 % / 20 % / 20 %' in notes['markdown'] and notes['revision'] == 1
    assert (work/'response.json').read_bytes() == original


def test_approval_needs_explicit_exact_findings_and_is_atomic_when_invalid(rejected_api):
    app, client, work, raw, original, job_id = rejected_api
    p = preview(client)
    response = client.post(URL+'/approve', headers=ADMIN, json=approval(p, approved_finding_ids=[]))
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'ACADEMIC_REVIEW_VALIDATION_FAILED'
    bad = approval(p, approved_finding_ids=['a'*64])
    assert client.post(URL+'/approve', headers=ADMIN, json=bad).status_code == 409
    with app.state.sessions() as db:
        assert db.get(AcademicSession, 'review-session').output_path is None
        assert len(list(db.scalars(select(ProcessingJob)))) == 1


@pytest.mark.parametrize('damage', ['response', 'source', 'assignment', 'new_job'])
def test_stale_review_cannot_approve_changed_material(rejected_api, damage):
    app, client, work, raw, original, job_id = rejected_api
    p = preview(client)
    if damage == 'response':
        (work/'response.json').write_bytes(original+b'\n')
    elif damage == 'source':
        with app.state.sessions() as db:
            artifact = db.scalar(select(TranscriptArtifact))
            Path(artifact.txt_path).write_text('Changed source')
    else:
        with app.state.sessions() as db:
            if damage == 'assignment':
                db.get(AcademicSession, 'review-session').number = 3
            else:
                db.add(ProcessingJob(kind='reprocess', active_key='session:review-session', module_id=356,
                                     session_id='review-session', status='QUEUED'))
            db.commit()
    assert client.post(URL+'/approve', headers=ADMIN, json=approval(p)).status_code == 409
    with app.state.sessions() as db:
        assert db.get(AcademicSession, 'review-session').processing_status == 'REVIEW_REQUIRED'


@pytest.mark.parametrize('damage', ['identity', 'sections', 'emoji', 'math'])
def test_human_lint_exception_cannot_bypass_other_validators(rejected_api, damage):
    app, client, work, raw, original, job_id = rejected_api
    if damage == 'identity':
        raw['request_id'] = 'another-request'
    elif damage == 'sections':
        raw['classes'][0]['markdown'] = '# Clase 4: Fundamentos\n60/20/20'
    elif damage == 'emoji':
        raw['classes'][0]['markdown'] += '\n\U0001f600\n'
    else:
        raw['classes'][0]['markdown'] += '\n$$\nx^{2\n$$\n'
    (work/'response.json').write_text(json.dumps(raw))
    p = preview(client)
    assert not p['can_approve']
    assert client.post(URL+'/approve', headers=ADMIN, json=approval(p)).status_code == 409


def test_review_auth_and_no_arbitrary_file_access(rejected_api, tmp_path):
    app, client, work, raw, original, job_id = rejected_api
    assert client.get(URL).status_code == 401
    assert client.get(URL, headers={'Authorization':'Bearer n8n-test'}).status_code == 403
    p = preview(client)
    assert client.post(URL+'/approve', headers={'Authorization':'Bearer n8n-test'}, json=approval(p)).status_code == 403
    assert client.post(URL+'/approve', headers=ADMIN, json=approval(p, acknowledge=False)).status_code == 422
    (work/'response.json').unlink()
    outside = tmp_path.parent/(str(uuid4())+'.json')
    outside.write_text(json.dumps(raw))
    try:
        (work/'response.json').symlink_to(outside)
        assert client.get(URL, headers=ADMIN).status_code == 409
    finally:
        outside.unlink()


@pytest.mark.parametrize('edit', [False, True])
def test_dashboard_reviews_real_saved_output_without_running_external_services(rejected_api, monkeypatch, edit):
    from urllib.parse import urlsplit
    from streamlit.testing.v1 import AppTest

    backend, client, work, raw, original, job_id = rejected_api
    mutations = []

    def request(method, url, **kwargs):
        path = urlsplit(url).path
        kwargs.pop('timeout', None)
        kwargs['headers'] = ADMIN
        if method != 'GET':
            mutations.append(path)
            assert path in {URL+'/validate', URL+'/approve'}
        return client.request(method, path, **kwargs)

    monkeypatch.setattr('httpx.request', request)
    app = AppTest.from_file(Path(__file__).resolve().parents[1]/'apps/dashboard/main.py').run()
    app.sidebar.radio[0].set_value('Sesiones').run()
    next(box for box in app.selectbox if box.label == 'Sesión para una acción').select_index(0).run()
    assert not app.exception
    assert any('60/20/20' in block.value for block in app.code)
    button_label = 'Aprobar y guardar apuntes sin reprocesar'
    assert next(button for button in app.button if button.label == button_label).disabled
    if edit:
        field = next(field for field in app.text_area if field.label == 'Markdown para revisión')
        field.set_value(field.value.replace('60/20/20', '60 % / 20 % / 20 %')).run()
        assert next(button for button in app.button if button.label == button_label).disabled
        next(button for button in app.button if button.label == 'Validar cambios sin Codex').click().run()
        assert any('pasa la validación' in message.value for message in app.success)
    next(box for box in app.checkbox if box.label.startswith('He revisado el contenido')).check()
    next(field for field in app.text_area if field.label == 'Motivo de la aprobación').set_value('Revisé la proporción académica.')
    app.run()
    assert not next(button for button in app.button if button.label == button_label).disabled
    next(button for button in app.button if button.label == button_label).click().run()
    assert not app.exception
    assert any('guardados' in message.value for message in app.success)
    assert not any(button.label == button_label for button in app.button)
    assert mutations == ([URL+'/validate', URL+'/approve'] if edit else [URL+'/approve'])
    with backend.state.sessions() as db:
        session = db.get(AcademicSession, 'review-session')
        assert session.processing_status == 'PROCESSED' and session.revision == 1
        assert ('60 % / 20 % / 20 %' if edit else '60/20/20') in Path(session.output_path).read_text()
    assert (work/'response.json').read_bytes() == original


def test_review_preserves_independent_notion_conflict(rejected_api):
    app, client, work, raw, original, job_id = rejected_api
    with app.state.sessions() as db:
        session = db.get(AcademicSession, 'review-session')
        session.publication_status = 'REVIEW_REQUIRED'
        session.error_code = 'NOTION_EXTERNAL_EDIT_CONFLICT'
        db.commit()
    response = client.post(URL+'/approve', headers=ADMIN, json=approval(preview(client)))
    assert response.status_code == 200, response.text
    with app.state.sessions() as db:
        session = db.get(AcademicSession, 'review-session')
        assert session.processing_status == 'PROCESSED'
        assert session.publication_status == 'REVIEW_REQUIRED'
        assert session.error_code == 'NOTION_EXTERNAL_EDIT_CONFLICT'


def test_review_blocks_active_module_jobs(rejected_api):
    app, client, work, raw, original, job_id = rejected_api
    p = preview(client)
    with app.state.sessions() as db:
        db.add(ProcessingJob(kind='recordings', active_key='recordings:356', module_id=356, status='QUEUED'))
        db.commit()
    response = client.post(URL+'/approve', headers=ADMIN, json=approval(p))
    assert response.status_code == 409 and response.json()['detail'] == 'MODULE_HAS_ACTIVE_JOBS'
    with app.state.sessions() as db:
        assert db.get(AcademicSession, 'review-session').output_path is None


def test_failed_audit_commit_rolls_back_state_and_new_files(rejected_api, monkeypatch):
    from sqlalchemy import event

    app, client, work, raw, original, job_id = rejected_api
    p = preview(client)
    before = set(work.parent.iterdir())

    def fail(mapper, connection, target):
        if target.kind == 'academic_review':
            raise RuntimeError('Simulated persistence failure')

    event.listen(ProcessingJob, 'before_insert', fail)
    try:
        with pytest.raises(RuntimeError, match='Simulated persistence failure'):
            client.post(URL+'/approve', headers=ADMIN, json=approval(p))
    finally:
        event.remove(ProcessingJob, 'before_insert', fail)
    assert set(work.parent.iterdir()) == before
    with app.state.sessions() as db:
        session = db.get(AcademicSession, 'review-session')
        assert session.output_path is None and session.processing_status == 'REVIEW_REQUIRED'
        assert session.revision == 0
        assert len(list(db.scalars(select(ProcessingJob)))) == 1


def test_duplicate_text_requires_approval_in_every_field(rejected_api):
    app, client, work, raw, original, job_id = rejected_api
    raw['classes'][0]['topics'] = [raw['classes'][0]['markdown']]
    (work/'response.json').write_text(json.dumps(raw))
    p = preview(client)
    assert len(p['findings']) == 2 and p['can_approve']
    payload = approval(p, approved_finding_ids=[p['findings'][0]['id']])
    assert client.post(URL+'/approve', headers=ADMIN, json=payload).status_code == 409


@pytest.mark.parametrize('response_text', ['{incomplete JSON', '{}'])
def test_invalid_contract_can_be_inspected_but_not_approved(rejected_api, response_text):
    app, client, work, raw, original, job_id = rejected_api
    (work/'response.json').write_text(response_text)
    p = preview(client)
    assert p['raw_response'] == response_text and p['markdown'] is None and not p['can_approve']
    assert client.post(URL+'/approve', headers=ADMIN, json=approval(p)).status_code == 409
