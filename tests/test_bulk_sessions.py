from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import select

from academic_automation.database.models import AcademicModule, AcademicSession, ProcessingJob, Recording, TranscriptArtifact
from test_api import client_for

ADMIN = {'Authorization': 'Bearer admin-test'}
PATH = '/modules/559/sessions/bulk'


@pytest.fixture
def bulk_api(tmp_path):
    app, client = client_for(tmp_path)
    with client:
        with app.state.sessions() as db:
            db.add(AcademicModule(id=559, program='MIA', cohort='V1E4', module_number=14, name='MLOps'))
            db.commit()
            for n, vid in [(1, '22PANKY-2Fg'), (2, 'wqH05pvQnQ4')]:
                db.add(AcademicSession(id=f's{n}', module_id=559, resource_key=f'r{n}', title=f'Clase {n}',
                    class_date=date(2026, 10, n), number=n, week=1, class_in_week=n, discovery_status='VIDEO_IDENTIFIED'))
            db.commit()
            for n, vid in [(1, '22PANKY-2Fg'), (2, 'wqH05pvQnQ4')]:
                db.add(Recording(session_id=f's{n}', position=1, video_id=vid, url=f'https://youtu.be/{vid}', resource_url='r'))
            db.commit()
        yield app, client


def request(operation='process', **kwargs):
    return dict(operation=operation, session_ids=['s1', 's2'], request_id=str(uuid4()), **kwargs)


def jobs(app, kind=None):
    with app.state.sessions() as db:
        query = select(ProcessingJob)
        if kind:
            query = query.where(ProcessingJob.kind == kind)
        return list(db.scalars(query))


def ready(app, processing='PROCESSED', publication='PENDING'):
    with app.state.sessions() as db:
        for n in (1, 2):
            s = db.get(AcademicSession, f's{n}')
            s.transcript_status, s.processing_status, s.publication_status = 'TRANSCRIPT_READY', processing, publication
            if processing == 'PROCESSED':
                s.output_path, s.content_hash = f'notes-{n}.md', f'hash-{n}'
            db.add(TranscriptArtifact(session_id=s.id, txt_path=f'{n}.txt', vtt_path=f'{n}.vtt', txt_hash='x', vtt_hash='y'))
        db.commit()


def test_bulk_preview_does_not_write_and_dispatch_queues_one_manual_job_per_session(bulk_api):
    app, client = bulk_api
    preview = client.post(PATH+'/preview', headers=ADMIN, json={'session_ids': ['s2', 's1']})
    assert preview.status_code == 200
    assert preview.json()['homogeneous']
    assert preview.json()['operations']['process']['compatible']
    assert not preview.json()['operations']['reprocess']['compatible']
    assert not jobs(app)
    response = client.post(PATH, headers=ADMIN, json=request())
    assert response.status_code == 202, response.text
    result = response.json()
    assert [j['session_id'] for j in result['jobs']] == ['s1', 's2']
    assert all(j['status'] == 'QUEUED' and not j['automatic'] for j in result['jobs'])
    assert len(jobs(app, 'process')) == 2
    assert db_states(app) == [('TRANSCRIPT_PENDING', 'PENDING', False), ('TRANSCRIPT_PENDING', 'PENDING', False)]


def db_states(app):
    with app.state.sessions() as db:
        return [(s.transcript_status, s.processing_status, s.selected) for s in db.scalars(select(AcademicSession).order_by(AcademicSession.id))]


@pytest.mark.parametrize('state', ['PROCESSING', 'PROCESSED'])
def test_bulk_repeated_request_returns_same_jobs_even_after_worker_changes_state(bulk_api, state):
    app, client = bulk_api
    payload = request()
    first = client.post(PATH, headers=ADMIN, json=payload).json()
    with app.state.sessions() as db:
        db.get(AcademicSession, 's1').processing_status = state
        for job in db.scalars(select(ProcessingJob).where(ProcessingJob.kind == 'process')):
            job.status = 'RUNNING' if state == 'PROCESSING' else 'COMPLETED'
            job.result = {'markdown_file': 'new-output.md'}
        db.commit()
    second = client.post(PATH, headers=ADMIN, json=payload)
    assert second.status_code == 202
    assert not second.json()['created']
    assert [j['id'] for j in first['jobs']] == [j['id'] for j in second.json()['jobs']]
    assert len(jobs(app, 'process')) == 2
    assert client.post(PATH, headers=ADMIN, json={**payload, 'operation': 'publish'}).status_code == 409
    assert client.post(PATH, headers=ADMIN, json=request()).status_code == 409
    assert len(jobs(app, 'process')) == 2


@pytest.mark.parametrize('field,value', [('processing_status', 'FAILED'), ('transcript_status', 'TRANSCRIPT_READY'),
    ('publication_status', 'PUBLISHED'), ('discovery_status', 'REVIEW_REQUIRED'), ('excluded', True)])
def test_mixed_or_incompatible_states_reject_entire_batch(bulk_api, field, value):
    app, client = bulk_api
    with app.state.sessions() as db:
        setattr(db.get(AcademicSession, 's2'), field, value)
        db.commit()
    response = client.post(PATH, headers=ADMIN, json=request())
    assert response.status_code == 409
    assert response.json()['detail']['issues']
    assert not jobs(app)


def test_state_is_rechecked_after_preview(bulk_api):
    app, client = bulk_api
    assert client.post(PATH+'/preview', headers=ADMIN, json={'session_ids': ['s1', 's2']}).json()['operations']['process']['compatible']
    with app.state.sessions() as db:
        db.get(AcademicSession, 's2').excluded = True
        db.commit()
    assert client.post(PATH, headers=ADMIN, json=request()).status_code == 409
    assert not jobs(app)


@pytest.mark.parametrize('operation,processing,publication', [('reprocess', 'PENDING', 'PENDING'),
    ('reprocess', 'PROCESSED', 'PUBLISHED'), ('publish', 'PROCESSED', 'PENDING'), ('publish', 'PROCESSED', 'PUBLISHED')])
def test_ready_transcripts_support_codex_and_processed_classes_support_publication(bulk_api, operation, processing, publication):
    app, client = bulk_api
    app.state.settings.publication_enabled = True
    ready(app, processing, publication)
    response = client.post(PATH, headers=ADMIN, json=request(operation))
    assert response.status_code == 202, response.text
    assert len(jobs(app, operation)) == 2
    assert all(not j.automatic for j in jobs(app, operation))


def test_publication_gate_and_review_conflicts_apply_to_whole_batch(bulk_api):
    app, client = bulk_api
    ready(app)
    assert client.post(PATH, headers=ADMIN, json=request('publish')).status_code == 409
    assert not jobs(app)
    app.state.settings.publication_enabled = True
    with app.state.sessions() as db:
        for sid in ['s1', 's2']:
            db.get(AcademicSession, sid).publication_status = 'REVIEW_REQUIRED'
        db.commit()
    assert client.post(PATH, headers=ADMIN, json=request('publish')).status_code == 409
    assert not jobs(app)


def test_active_job_does_not_enqueue_other_class(bulk_api):
    app, client = bulk_api
    with app.state.sessions() as db:
        db.add(ProcessingJob(kind='publish', active_key='session:s2', module_id=559, session_id='s2'))
        db.commit()
    assert client.post(PATH, headers=ADMIN, json=request()).status_code == 409
    assert len(jobs(app)) == 1


def test_bulk_admin_auth_and_input_validation(bulk_api):
    app, client = bulk_api
    assert client.post(PATH, json=request()).status_code == 401
    assert client.post(PATH, headers={'Authorization': 'Bearer n8n-test'}, json=request()).status_code == 403
    for values in [[], ['s1', 's1'], ['s1'] * 9]:
        assert client.post(PATH, headers=ADMIN, json={**request(), 'session_ids': values}).status_code == 422
    assert client.post(PATH, headers=ADMIN, json={**request(), 'operation': 'delete'}).status_code == 422
    assert client.post(PATH, headers=ADMIN, json={**request(), 'session_ids': ['missing']}).status_code == 409
    assert client.post('/modules/532/sessions/bulk', headers=ADMIN, json=request()).status_code == 404
    assert not jobs(app)


def test_database_failure_rolls_back_all_jobs_and_receipt(bulk_api):
    from sqlalchemy import event
    app, client = bulk_api
    writes = []
    def fail_second(mapper, connection, target):
        if target.kind == 'process':
            writes.append(target.id)
            if len(writes) == 2:
                raise RuntimeError('simulated write failure')
    event.listen(ProcessingJob, 'before_insert', fail_second)
    try:
        with pytest.raises(RuntimeError, match='simulated write failure'):
            client.post(PATH, headers=ADMIN, json=request())
    finally:
        event.remove(ProcessingJob, 'before_insert', fail_second)
    assert len(writes) == 2
    assert not jobs(app)


@pytest.mark.parametrize('block', ['module_review', 'wrong_module', 'missing_transcript', 'assignment', 'structural_job'])
def test_batch_rejects_pending_review_missing_sources_and_other_modules(bulk_api, block):
    app, client = bulk_api
    if block == 'missing_transcript':
        with app.state.sessions() as db:
            for s in db.scalars(select(AcademicSession)):
                s.transcript_status = 'TRANSCRIPT_READY'
            db.commit()
        operation = 'reprocess'
    else:
        operation = 'process'
        with app.state.sessions() as db:
            if block == 'module_review':
                db.get(AcademicModule, 559).review_required = True
            elif block == 'wrong_module':
                db.add(AcademicModule(id=532, program='DCC', cohort='V1E1', module_number=11, name='Doctorado'))
                db.flush()
                db.get(AcademicSession, 's2').module_id = 532
            elif block == 'assignment':
                db.get(AcademicSession, 's2').week = None
            else:
                db.add(ProcessingJob(kind='recordings', active_key='recordings:559', module_id=559))
            db.commit()
    response = client.post(PATH, headers=ADMIN, json=request(operation))
    assert response.status_code == 409
    assert not jobs(app, operation)


async def test_bulk_children_use_ordinary_worker_and_preserve_each_session(db, tmp_path):
    from sqlalchemy.orm import sessionmaker
    from academic_automation.core.config import Settings
    from academic_automation.core.schemas import BulkOperation
    from academic_automation.orchestration.worker import Worker
    from academic_automation.services.bulk_sessions import enqueue_bulk
    from academic_automation.services.catalog import sync_recordings
    from test_foundation import module
    from test_moodle import recording
    from test_worker import FakeTranscript, FakeProcessor

    settings = Settings(data_dir=tmp_path)
    m = module(db)
    sync_recordings(db, m, [recording('r1', 5, '22PANKY-2Fg'), recording('r2', 9, 'wqH05pvQnQ4')])
    sessions = list(db.scalars(select(AcademicSession).order_by(AcademicSession.number)))
    payload = BulkOperation(operation='process', request_id=uuid4(), session_ids=[s.id for s in sessions])
    result = enqueue_bulk(db, settings, m.id, payload)
    adapter, processor = FakeTranscript(tmp_path), FakeProcessor(tmp_path)
    worker = Worker(settings, sessionmaker(db.get_bind()), transcripts=adapter, processor=processor)
    assert await worker.tick()
    assert await worker.tick()
    assert not await worker.tick()  # The terminal receipt is not executable work.
    db.expire_all()
    assert [db.get(ProcessingJob, j['id']).status for j in result['jobs']] == ['COMPLETED', 'COMPLETED']
    assert all(db.get(AcademicSession, s.id).processing_status == 'PROCESSED' for s in sessions)
    assert adapter.calls == processor.calls == 2
    # Same request after completion does not create another processing job.
    repeated = enqueue_bulk(db, settings, m.id, payload)
    assert not repeated['created'] and [j['id'] for j in repeated['jobs']] == [j['id'] for j in result['jobs']]
