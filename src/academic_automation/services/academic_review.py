"""Review a saved Codex response locally. No model calls or Notion writes."""

import copy
import json
import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select, text

from academic_automation.academic.output import CodexOutputError, export_academic_response, validate_academic_response
from academic_automation.academic.processor import load_skill
from academic_automation.core.errors import Conflict, StageError
from academic_automation.core.schemas import CodexInput
from academic_automation.core.security import digest
from academic_automation.database.models import (
    AcademicModule, AcademicSession, ExecutionLog, ProcessingJob, Recording, TranscriptArtifact, now, uid,
)
from academic_automation.services.manual_recordings import module_idle
from academic_automation.transcripts.multipart import atomic_text, load_manifest, verify_entry

MAX_RESPONSE_BYTES = 5_000_000


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def latest_generation(db, session_id):
    return db.scalar(select(ProcessingJob).where(ProcessingJob.session_id == session_id,
        ProcessingJob.kind.in_(['process', 'reprocess'])).order_by(ProcessingJob.created_at.desc(), ProcessingJob.id.desc()).limit(1))


def review_available(session, job):
    return bool(session.processing_status == 'REVIEW_REQUIRED' and job and job.status == 'REVIEW_REQUIRED'
                and job.error_code == 'CODEX_OUTPUT_INVALID')


def read_private(settings, path, limit):
    path = Path(path).resolve()
    if not path.is_relative_to(settings.data_dir.resolve()):
        raise Conflict('ACADEMIC_REVIEW_PATH_INVALID')
    try:
        with path.open('rb') as source:
            data = source.read(limit + 1)
    except OSError:
        raise Conflict('ACADEMIC_REVIEW_FILE_MISSING') from None
    if len(data) > limit:
        raise Conflict('ACADEMIC_REVIEW_FILE_TOO_LARGE')
    return data


@dataclass
class ReviewContext:
    session: AcademicSession
    module: AcademicModule
    job: ProcessingJob
    request: CodexInput
    request_bytes: bytes
    response_bytes: bytes
    response_text: str
    raw: Any
    transcript: str
    skill: Any
    skill_hash: str
    token: str

    def skill_request(self):
        return {'schema_version':'1.0', 'request_id':self.request.request_id, 'mode':'automatic',
            'program':self.request.program, 'module_id':f'moodle-{self.module.id}',
            'module_title':self.request.module_title, 'week':self.request.week,
            'notion':{'parent_page_id':None,'week_page_id':None},
            'classes':[{'class_number':self.request.number,'transcript_file':str(self.request.transcript_file)}]}


def load_context(db, settings, session_id):
    session = db.get(AcademicSession, session_id)
    if session is None:
        raise StageError('SESSION_NOT_FOUND')
    job = latest_generation(db, session_id)
    if not review_available(session, job):
        raise Conflict('ACADEMIC_REVIEW_NOT_AVAILABLE')
    module = db.get(AcademicModule, session.module_id)
    key = f'{job.id}-{job.attempts}'
    root = settings.data_dir.resolve() / 'processed'
    work = (root / key).resolve()
    if not work.is_relative_to(root):
        raise Conflict('ACADEMIC_REVIEW_PATH_INVALID')
    if any(not (work/name).resolve().is_relative_to(work) for name in ('request.json','response.json')):
        raise Conflict('ACADEMIC_REVIEW_PATH_INVALID')
    request_bytes = read_private(settings, work/'request.json', 64_000)
    response_bytes = read_private(settings, work/'response.json', MAX_RESPONSE_BYTES)
    try:
        request = CodexInput.model_validate_json(request_bytes)
        response_text = response_bytes.decode('utf-8')
    except (ValueError, UnicodeError):
        raise Conflict('ACADEMIC_REVIEW_FILE_INVALID') from None
    if (request.request_id != key or request.module_id != module.id or request.program != module.program
            or (request.number, request.week, request.class_in_week) != (session.number, session.week, session.class_in_week)):
        raise Conflict('ACADEMIC_REVIEW_ASSIGNMENT_CHANGED')
    artifact = db.scalar(select(TranscriptArtifact).where(TranscriptArtifact.session_id == session_id))
    if artifact is None or request.transcript_file.resolve() != Path(artifact.txt_path).resolve():
        raise Conflict('ACADEMIC_REVIEW_SOURCE_CHANGED')
    txt = read_private(settings, artifact.txt_path, settings.max_transcript_chars * 4 + 4)
    vtt = read_private(settings, artifact.vtt_path, 64_000_000)
    if digest(txt) != artifact.txt_hash or digest(vtt) != artifact.vtt_hash:
        raise Conflict('ACADEMIC_REVIEW_SOURCE_CHANGED')
    recordings = list(db.scalars(select(Recording).where(Recording.session_id == session_id).order_by(Recording.position)))
    if len(recordings) > 1:
        manifest = load_manifest(settings.data_dir/'transcripts'/session_id/'combined', recordings)
        if len(manifest['parts']) != len(recordings) or 'combined' not in manifest:
            raise Conflict('TRANSCRIPT_PARTS_MANIFEST_INVALID')
        for entry in [*manifest['parts'], manifest['combined']]:
            verify_entry(settings, entry)
        if (manifest['combined']['txt_hash'], manifest['combined']['vtt_hash']) != (artifact.txt_hash, artifact.vtt_hash):
            raise Conflict('ACADEMIC_REVIEW_SOURCE_CHANGED')
    try:
        transcript = txt.decode('utf-8')
    except UnicodeError:
        raise Conflict('ACADEMIC_REVIEW_SOURCE_CHANGED') from None
    if not transcript.strip() or len(transcript) > settings.max_transcript_chars:
        raise Conflict('TRANSCRIPT_EMPTY_OR_TOO_LARGE')
    try:
        raw = json.loads(response_text)
    except ValueError:
        raw = None
    skill, skill_hash = load_skill(settings.skill_path)
    snapshot = {field:getattr(session, field) for field in ('id','number','week','class_in_week','revision',
        'output_path','content_hash','processing_status','publication_status','error_code','excluded')}
    token = digest(canonical({'session':snapshot,'job':job.id,'attempt':job.attempts,
        'request':digest(request_bytes),'response':digest(response_bytes), 'txt':artifact.txt_hash,
        'vtt':artifact.vtt_hash,'skill':skill_hash,'module_review':module.review_required}))
    return ReviewContext(session, module, job, request, request_bytes, response_bytes, response_text,
                         raw, transcript, skill, skill_hash, token)


def strings(value, field=''):
    if isinstance(value, str):
        yield field, value
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from strings(item, f'{field}.{i}')
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from strings(item, f'{field}.{key}'.strip('.'))


def findings(pattern, raw):
    result = []
    for field, value in strings(raw):
        for match in pattern.finditer(value):
            line = value.count('\n', 0, match.start()) + 1
            lines = value.splitlines()
            result.append({'id':digest(canonical([field,digest(value),match.start(),match.end()])),
                'field':field,'line':line,'match':match[0], 'start':match.start(),'end':match.end(),
                'value_hash':digest(value), 'excerpt':'\n'.join(f'{i+1}: {lines[i]}'
                    for i in range(max(0,line-3), min(len(lines),line+2)))})
            if len(result) > 100:
                return result
    return result


@contextmanager
def approved_matches(skill, raw, accepted):
    """Filter only reviewed matches in this fresh in-memory skill instance.

    The installed skill and every other validator remain untouched. Identical
    strings in several fields need approval in ALL fields before being filtered.
    """
    pattern = skill.ADMINISTRATIVE
    matches = findings(pattern, raw)
    if set(accepted) - {f['id'] for f in matches}:
        raise Conflict('ACADEMIC_REVIEW_FINDINGS_CHANGED')
    groups = {}
    for f in matches:
        groups.setdefault((f['value_hash'],f['start'],f['end']), set()).add(f['id'])
    allowed = {key for key, identifiers in groups.items() if identifiers.issubset(set(accepted))}

    class ReviewedPattern:
        def finditer(self, value):
            for match in pattern.finditer(value):
                if (digest(value),match.start(),match.end()) not in allowed:
                    yield match

        def search(self, value):
            return next(self.finditer(value), None)

    skill.ADMINISTRATIVE = ReviewedPattern()
    try:
        yield
    finally:
        skill.ADMINISTRATIVE = pattern


def edited_response(context, draft):
    if draft and (draft.source_job_id != context.job.id or draft.expected_review_token != context.token):
        raise Conflict('ACADEMIC_REVIEW_CHANGED')
    raw = copy.deepcopy(context.raw)
    if draft and draft.markdown is not None:
        try:
            if not isinstance(raw['classes'][0]['markdown'], str):
                raise ValueError()
            raw['classes'][0]['markdown'] = draft.markdown
        except (KeyError, IndexError, TypeError, ValueError):
            raise Conflict('ACADEMIC_REVIEW_NOT_EDITABLE') from None
    return raw


def validation(context, raw, accepted=()):
    if raw is None:
        return {'stage':'response_json','reason':'response.json no contiene JSON válido.'}
    try:
        with approved_matches(context.skill, raw, accepted):
            validate_academic_response(context.request, context.skill_request(), raw, context.skill)
    except CodexOutputError as error:
        return error.diagnostic
    except StageError as error:
        return {'stage':'markdown','reason':error.code}
    return None


def report(context, raw):
    matches = findings(context.skill.ADMINISTRATIVE, raw)
    problem = validation(context, raw)
    blocker = validation(context, raw, [f['id'] for f in matches]) if len(matches) <= 100 else {
        'stage':'academic_lint','reason':'Hay más de 100 hallazgos; corrija el documento antes de aprobarlo.'}
    is_ready = isinstance(raw, dict) and raw.get('status') == 'ready'
    if not is_ready:
        blocker = blocker or {'stage':'status','reason':'La respuesta no está lista (ready); no puede promoverse desde esta revisión.'}
    if context.module.review_required or context.session.excluded or context.session.transcript_status != 'TRANSCRIPT_READY':
        blocker = {'stage':'session','reason':'Resuelva la asignación, exclusión o estado de transcripción antes de aprobar.'}
    try:
        markdown = raw['classes'][0]['markdown']
        if not isinstance(markdown, str):
            markdown = None
    except (KeyError, IndexError, TypeError):
        markdown = None
    return {'session_id':context.session.id, 'source_job_id':context.job.id, 'review_token':context.token,
        'number':context.session.number,'revision':context.session.revision, 'markdown':markdown,
        'raw_response':context.response_text, 'stored_diagnostic':(context.job.result or {}).get('validation'),
        'validation':{'passed':problem is None, **(problem or {})},
        'findings':matches[:100], 'can_approve':blocker is None, 'approval_blocker':blocker,
        'transcript':context.transcript,
        'model':context.job.model,'skill_version':context.job.skill_version}


def preview_review(db, settings, session_id, draft=None):
    context = load_context(db, settings, session_id)
    return report(context, edited_response(context, draft))


class AcademicReviewRejected(Conflict):
    def __init__(self, diagnostic):
        super().__init__('ACADEMIC_REVIEW_VALIDATION_FAILED')
        self.diagnostic = diagnostic


def approve_review(db, settings, session_id, request):
    payload = request.model_dump(mode='json', exclude={'request_id'})
    payload['approved_finding_ids'] = sorted(payload['approved_finding_ids'])
    payload_hash = digest(canonical(payload))
    db.execute(text('BEGIN IMMEDIATE'))
    work = None
    committed = False
    try:
        identifier = str(request.request_id)
        previous = db.get(ProcessingJob, identifier)
        if previous is not None:
            if (previous.kind != 'academic_review' or previous.session_id != session_id
                    or previous.result.get('payload_hash') != payload_hash):
                raise Conflict('ACADEMIC_REVIEW_REQUEST_CHANGED')
            result = {'session_id':session_id,'audit_job_id':identifier,'changed':False}
            db.rollback()
            return result
        context = load_context(db, settings, session_id)
        raw = edited_response(context, request)
        module_idle(db, context.module.id)
        info = report(context, raw)
        if not info['can_approve']:
            raise AcademicReviewRejected(info['approval_blocker'])
        if set(request.approved_finding_ids) - {f['id'] for f in info['findings']}:
            raise Conflict('ACADEMIC_REVIEW_FINDINGS_CHANGED')
        problem = validation(context, raw, request.approved_finding_ids)
        if problem:
            raise AcademicReviewRejected(problem)
        root = settings.workdir('processed')
        work = root / f'review-{identifier}-{uid()}'
        work.mkdir(mode=0o700)
        atomic_text(work/'response.original.json', context.response_text)
        atomic_text(work/'response.reviewed.json', json.dumps(raw, ensure_ascii=False, indent=2))
        atomic_text(work/'request.json', context.request_bytes.decode('utf-8'))
        sources = [{'class_number':context.request.number,'file_uri':context.request.transcript_file.as_uri(),
            'sha256':digest(context.transcript),'characters':len(context.transcript),'text':context.transcript}]
        with approved_matches(context.skill, raw, request.approved_finding_ids):
            result = export_academic_response(context.request, context.skill_request(), sources, raw,
                work/'bundle', context.skill, context.skill_hash, model=context.job.model)
        metadata = result['metadata']
        if request.approved_finding_ids:
            metadata['validation']['academic_lint'] = 'human_approved_false_positives'
        metadata['human_review'] = {'audit_job_id':identifier,'source_job_id':context.job.id,
                                   'approved_finding_ids':request.approved_finding_ids}
        atomic_text(work/'bundle'/'metadata.json', json.dumps(metadata, ensure_ascii=False, indent=2))
        session = context.session
        before = {field:getattr(session,field) for field in ('output_path','content_hash','revision','publication_status','error_code')}
        session.output_path, session.content_hash = result['markdown_file'], result['content_hash']
        session.processing_status = 'PROCESSED'
        session.revision += 1
        if session.publication_status != 'REVIEW_REQUIRED':
            session.publication_status = 'PENDING'
        if session.error_code in {'CODEX_OUTPUT_INVALID','ACADEMIC_OUTPUT_REQUIRED'}:
            session.error_code = None
        accepted = [{key:f[key] for key in ('id','field','line','match')} for f in info['findings']
                    if f['id'] in request.approved_finding_ids]
        audit = ProcessingJob(id=identifier,kind='academic_review',active_key='academic_review:'+identifier,
            module_id=context.module.id,session_id=session_id,status='COMPLETED',stage='academic_review',attempts=1,
            started_at=now(),finished_at=now(),model=context.job.model,skill_hash=context.skill_hash,skill_version='1.0',
            result={'payload_hash':payload_hash,'source_job_id':context.job.id,'reason':request.reason,
                'review_token':context.token,'source_response_sha256':digest(context.response_bytes),
                'reviewed_response_sha256':digest((work/'response.reviewed.json').read_bytes()),
                'approved_findings':accepted,'previous_artifact':before,'markdown_file':session.output_path,
                'content_hash':session.content_hash,'codex_runs':0,'remote_writes':False})
        db.add(audit)
        db.flush()
        db.add(ExecutionLog(job_id=identifier,stage='academic_review',event='completed',message='ACADEMIC_REVIEW_APPROVED'))
        db.commit()
        committed = True
        return {'session_id':session_id,'audit_job_id':identifier,'changed':True}
    except Exception:
        db.rollback()
        if work is not None and not committed:
            shutil.rmtree(work)
        raise
