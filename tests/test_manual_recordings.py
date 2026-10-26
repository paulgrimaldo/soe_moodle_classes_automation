from datetime import date

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from academic_automation.core.config import Settings
from academic_automation.core.errors import Conflict
from academic_automation.core.schemas import ManualSessionCreate, RecordingLinks
from academic_automation.database.models import AcademicSession, ProcessingJob, Recording, TranscriptArtifact
from academic_automation.services.catalog import recording_sync_result, sync_recordings
from academic_automation.services.manual_recordings import create_manual_session, link_recordings
from test_foundation import module

URLS = ['https://youtu.be/22PANKY-2Fg', 'https://www.youtube.com/watch?v=wqH05pvQnQ4&t=1s']


def request(number=4, urls=URLS):
    return ManualSessionCreate(number=number, class_date=date(2024, 6, 8), youtube_urls=urls)


def test_manual_create_is_idempotent_and_preserves_identity_assignment_and_order(db, tmp_path):
    m = module(db)
    settings = Settings(data_dir=tmp_path)
    result = create_manual_session(db, settings, m.id, request())
    repeated = create_manual_session(db, settings, m.id, request())
    assert result['session_id'] == repeated['session_id'] and not repeated['changed']
    s = db.get(AcademicSession, result['session_id'])
    assert (s.number, s.week, s.class_in_week) == (4, 2, 2)
    assert s.manual_assignment and s.recordings_manual and s.resource_key.startswith('manual:')
    assert s.discovery_status == 'VIDEO_IDENTIFIED' and not s.selected and not m.enabled
    assert db.scalar(select(func.count()).select_from(AcademicSession)) == 1
    assert [(r.position, r.video_id) for r in db.scalars(select(Recording).order_by(Recording.position))] == [
        (1, '22PANKY-2Fg'), (2, 'wqH05pvQnQ4')]
    assert db.scalar(select(func.count()).select_from(ProcessingJob)) == 1


@pytest.mark.parametrize('urls', [[], ['https://example.com/watch?v=22PANKY-2Fg'],
    [URLS[0], 'https://youtube.com/embed/22PANKY-2Fg'], URLS * 5])
def test_invalid_or_duplicate_links_rejected(urls):
    with pytest.raises(ValidationError):
        RecordingLinks(youtube_urls=urls)


def test_manual_resolution_survives_ambiguous_sync_and_duplicate_resources(db, tmp_path):
    m = module(db)
    item = {'resource_key': 'resource-4', 'resource_url': 'moodle', 'title': 'Semana 4',
            'date': date(2024, 6, 8), 'discovery_error': 'MOODLE_MULTIPLE_VIDEOS',
            'video_candidates': [{'video_id': '22PANKY-2Fg'}, {'video_id': 'wqH05pvQnQ4'}]}
    sync_recordings(db, m, [item])
    sid = db.scalar(select(AcademicSession.id))
    result = link_recordings(db, Settings(data_dir=tmp_path), sid, RecordingLinks(youtube_urls=URLS))
    assert result['changed']
    sync_recordings(db, m, [item])
    s = db.get(AcademicSession, sid)
    assert s.discovery_status == 'VIDEO_IDENTIFIED' and s.error_code is None
    assert not recording_sync_result([item], 0).get('reviews')
    # Historical courses sometimes expose each part under another activity.
    duplicates = [dict(item, resource_key=f'alias-{i}', discovery_error=None,
                       video_id=identifier, url=f'https://youtu.be/{identifier}')
                  for i, identifier in enumerate(['22PANKY-2Fg', 'wqH05pvQnQ4'])]
    assert sync_recordings(db, m, duplicates) == 0
    assert db.scalar(select(func.count()).select_from(AcademicSession)) == 1


def test_manual_created_session_matches_ambiguous_resource_without_duplicate(db, tmp_path):
    m = module(db)
    result = create_manual_session(db, Settings(data_dir=tmp_path), m.id, request())
    item = {'resource_key': 'new-moodle-resource', 'resource_url': 'moodle', 'title': 'Semana 4',
            'date': date(2024, 6, 8), 'discovery_error': 'MOODLE_MULTIPLE_VIDEOS',
            'video_candidates': [{'video_id': '22PANKY-2Fg'}, {'video_id': 'wqH05pvQnQ4'}]}
    assert sync_recordings(db, m, [item]) == 0
    assert not recording_sync_result([item], 0).get('reviews')
    assert db.scalar(select(func.count()).select_from(AcademicSession)) == 1
    assert db.get(AcademicSession, result['session_id']).number == 4


def test_cannot_claim_video_from_other_session_or_edit_during_active_job(db, tmp_path):
    m = module(db)
    settings = Settings(data_dir=tmp_path)
    one = create_manual_session(db, settings, m.id, request())
    with pytest.raises(Conflict, match='VIDEO_LINKED_TO_OTHER_SESSION'):
        create_manual_session(db, settings, m.id, request(3))
    assert db.scalar(select(func.count()).select_from(AcademicSession)) == 1
    db.add(ProcessingJob(kind='process', active_key='session:'+one['session_id'],
                         module_id=m.id, session_id=one['session_id'], status='QUEUED'))
    db.commit()
    with pytest.raises(Conflict, match='MODULE_HAS_ACTIVE_JOBS'):
        link_recordings(db, settings, one['session_id'], RecordingLinks(youtube_urls=URLS))


@pytest.mark.parametrize('material', ['transcript', 'output', 'cached_part'])
def test_material_is_preserved_when_replacing_links(db, tmp_path, material):
    m = module(db)
    settings = Settings(data_dir=tmp_path)
    one = create_manual_session(db, settings, m.id, request())
    sid = one['session_id']
    if material == 'transcript':
        db.add(TranscriptArtifact(session_id=sid, txt_path='source.txt', vtt_path='source.vtt', txt_hash='x', vtt_hash='y'))
    elif material == 'output':
        db.get(AcademicSession, sid).output_path = 'notes.md'
    else:
        (settings.workdir('transcripts', sid, 'parts') / 'manifest.json').write_text('{}')
    db.commit()
    assert not link_recordings(db, settings, sid, RecordingLinks(youtube_urls=URLS))['changed']
    with pytest.raises(Conflict, match='MANUAL_RECORDINGS_ARTIFACTS_EXIST'):
        link_recordings(db, settings, sid, RecordingLinks(youtube_urls=list(reversed(URLS))))
    assert db.scalar(select(Recording).where(Recording.session_id == sid, Recording.position == 1)).video_id == '22PANKY-2Fg'


def test_can_replace_unprocessed_links_without_leaving_old_recordings(db, tmp_path):
    m = module(db)
    settings = Settings(data_dir=tmp_path)
    one = create_manual_session(db, settings, m.id, request(urls=URLS[:1]))
    result = link_recordings(db, settings, one['session_id'], RecordingLinks(youtube_urls=list(reversed(URLS))))
    assert result['changed']
    assert [r.video_id for r in db.scalars(select(Recording).order_by(Recording.position))] == ['wqH05pvQnQ4', '22PANKY-2Fg']


def test_manual_api_auth_validation_and_existing_review_resolution(tmp_path):
    from test_api import client_for
    app, client = client_for(tmp_path)
    admin = {'Authorization': 'Bearer admin-test'}
    n8n = {'Authorization': 'Bearer n8n-test'}
    with client:
        with app.state.sessions() as db:
            m = module(db)
            sid = create_manual_session(db, app.state.settings, m.id, request())['session_id']
        payload = {'youtube_urls': URLS}
        assert client.put(f'/sessions/{sid}/recordings', json=payload).status_code == 401
        assert client.put(f'/sessions/{sid}/recordings', json=payload, headers=n8n).status_code == 403
        assert client.put('/sessions/missing/recordings', json=payload, headers=admin).status_code == 404
        assert client.put(f'/sessions/{sid}/recordings', json={'youtube_urls': ['not-youtube']}, headers=admin).status_code == 422
        result = client.put(f'/sessions/{sid}/recordings', json=payload, headers=admin)
        assert result.status_code == 200 and not result.json()['changed']
        # A different unoccupied slot can be created without Moodle or background work.
        create_payload = {'number': 2, 'class_date': '2024-06-01', 'youtube_urls': ['https://youtu.be/6dP-ykbwEIg']}
        assert client.post('/modules/559/sessions/manual', json=create_payload, headers=n8n).status_code == 403
        created = client.post('/modules/559/sessions/manual', json=create_payload, headers=admin)
        assert created.status_code == 200
        repeated = client.post('/modules/559/sessions/manual', json=create_payload, headers=admin)
        assert repeated.json()['session_id'] == created.json()['session_id'] and not repeated.json()['changed']
        sessions = client.get('/modules/559/sessions', headers=admin).json()
        assert len(sessions) == 2 and all(s['recordings_manual'] for s in sessions)
        assert all(j['status'] == 'COMPLETED' for j in client.get('/jobs', headers=admin).json())


def test_manual_dcc_creates_requested_week_without_reconciling_other_classes(db, tmp_path):
    m = module(db)
    m.program = 'DCC'
    db.commit()
    one = create_manual_session(db, Settings(data_dir=tmp_path), m.id, request())
    assert (db.get(AcademicSession, one['session_id']).week, db.get(AcademicSession, one['session_id']).class_in_week) == (4, 1)
    sync_recordings(db, m, [{'resource_key': 'early', 'resource_url': 'moodle', 'title': 'Otra clase',
        'date': date(2024, 5, 18), 'video_id': '6dP-ykbwEIg', 'url': 'https://youtu.be/6dP-ykbwEIg'}])
    assert db.get(AcademicSession, one['session_id']).number == 4
    assert not m.review_required


def test_manual_migration_preserves_links_and_rejects_unprotected_downgrade(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text
    from academic_automation.database.session import make_engine, factory, seed

    monkeypatch.setenv('ACADEMIC_DATABASE_URL', f'sqlite:///{tmp_path / "migration.sqlite3"}')
    monkeypatch.setenv('ACADEMIC_DATA_DIR', str(tmp_path))
    cfg = Config('alembic.ini')
    command.upgrade(cfg, 'head')
    settings = Settings()
    engine = make_engine(settings.database_url)
    with factory(engine)() as db:
        seed(db)
        m = module(db)
        result = create_manual_session(db, settings, m.id, request())
        sid = result['session_id']
    with pytest.raises(RuntimeError, match='Manual recording links exist'):
        command.downgrade(cfg, 'ba91c321ab02')
    with engine.connect() as connection:
        assert connection.execute(text('SELECT recordings_manual FROM academic_sessions WHERE id=:id'), {'id': sid}).scalar() == 1
        assert connection.execute(text('PRAGMA foreign_key_check')).all() == []
    engine.dispose()


def test_pinning_same_published_recordings_keeps_all_artifact_states(db, tmp_path):
    m = module(db)
    settings = Settings(data_dir=tmp_path)
    result = create_manual_session(db, settings, m.id, request())
    s = db.get(AcademicSession, result['session_id'])
    s.recordings_manual = False
    s.transcript_status, s.processing_status, s.publication_status = 'TRANSCRIPT_READY', 'PROCESSED', 'PUBLISHED'
    s.output_path, s.content_hash, s.revision = 'notes.md', 'original-hash', 2
    db.commit()
    assert link_recordings(db, settings, s.id, RecordingLinks(youtube_urls=URLS))['changed']
    assert s.recordings_manual
    assert (s.transcript_status, s.processing_status, s.publication_status) == ('TRANSCRIPT_READY', 'PROCESSED', 'PUBLISHED')
    assert (s.output_path, s.content_hash, s.revision) == ('notes.md', 'original-hash', 2)


async def test_manual_multipart_runs_through_worker_without_moodle(db, tmp_path):
    from sqlalchemy.orm import sessionmaker
    from academic_automation.core.process import ProcessResult
    from academic_automation.orchestration.worker import Worker
    from academic_automation.transcripts.adapter import TranscriptAdapter
    from test_worker import FakeProcessor, run_job

    settings = Settings(data_dir=tmp_path)
    m = module(db)
    result = create_manual_session(db, settings, m.id, request())
    downloads = []

    async def runner(args, **kwargs):
        downloads.append(args[-1])
        target = kwargs['cwd']
        (target / 'clase1.txt').write_text('Contenido de '+target.name)
        (target / 'clase1.vtt').write_text('WEBVTT\n\n00:00.000 --> 00:01.000\n \nContenido\n')
        return ProcessResult(0, '', '')

    processor = FakeProcessor(tmp_path)
    worker = Worker(settings, sessionmaker(db.get_bind()), transcripts=TranscriptAdapter(settings, runner), processor=processor)
    one = await run_job(worker, db, 'process', session_id=result['session_id'], module_id=m.id)
    assert one.status == 'COMPLETED', one.error_code
    two = await run_job(worker, db, 'process', session_id=result['session_id'], module_id=m.id)
    assert two.status == 'COMPLETED' and len(downloads) == 2 and processor.calls == 1
    s = db.get(AcademicSession, result['session_id'])
    assert s.transcript_status == 'TRANSCRIPT_READY' and s.processing_status == 'PROCESSED'
    assert s.publication_status == 'PENDING'
    assert worker.moodle is None
    assert db.scalar(select(func.count()).select_from(AcademicSession)) == 1
