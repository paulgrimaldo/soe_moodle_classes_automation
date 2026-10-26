from sqlalchemy import select

from academic_automation.core.errors import Conflict
from academic_automation.database.models import AcademicModule, AcademicSession, NotionSection, Recording, now


def assignment(program: str, number: int) -> tuple[int, int]:
    if program not in {"DCC", "MIA"} or not 1 <= number <= 8:
        raise ValueError("Asignación académica fuera de rango")
    return (number, 1) if program == "DCC" else ((number + 1) // 2, (number - 1) % 2 + 1)


def authorized(module: AcademicModule, session: AcademicSession) -> bool:
    if not module.enabled or module.review_required or session.excluded or session.week is None:
        return False
    if module.mode == "ALL":
        return True
    if module.mode == "NEW_ONLY":
        return module.activated_at is not None and session.discovered_at > module.activated_at
    return session.selected


def reconcile(db, module: AcademicModule) -> list[dict]:
    sessions = list(db.scalars(select(AcademicSession).where(AcademicSession.module_id == module.id)
                              .order_by(AcademicSession.class_date, AcademicSession.resource_key)))
    if len(sessions) > 8:
        module.review_required = True
        db.commit()  # Keep discovery evidence and the review flag even though this sync stops.
        raise Conflict("MORE_THAN_EIGHT_SESSIONS")
    # Explicit overrides reserve their slot; remaining sessions occupy chronological free slots.
    reserved = {s.number for s in sessions if s.manual_assignment}
    free = iter(n for n in range(1, 9) if n not in reserved)
    proposal = []
    for session in sessions:
        number = session.number if session.manual_assignment else next(free)
        week, cls = assignment(module.program, number)
        proposal.append({"id": session.id, "number": number, "week": week, "class_in_week": cls})
    changed = [p for p in proposal if (s := db.get(AcademicSession, p["id"]))
               and (s.number, s.week, s.class_in_week) != (p["number"], p["week"], p["class_in_week"])]
    published = any(db.scalar(select(NotionSection).where(NotionSection.session_id == p["id"]))
                    for p in changed)
    # Once generated, a number is also embedded in the Markdown. Never silently invalidate it.
    generated = any(db.get(AcademicSession, p["id"]).output_path for p in changed)
    if published or generated:
        module.review_required = True
        module.proposed_assignments = proposal
    else:
        for p in proposal:
            s = db.get(AcademicSession, p["id"])
            s.number, s.week, s.class_in_week = p["number"], p["week"], p["class_in_week"]
        module.review_required, module.proposed_assignments = False, None
    return proposal


def sync_catalog(db, courses: list[dict]) -> int:
    for course in courses:
        module = db.get(AcademicModule, course["moodle_course_id"])
        if module is None:
            module = AcademicModule(id=course["moodle_course_id"], enabled=False)
            db.add(module)
        for field in ("program", "cohort", "module_number", "name"):
            setattr(module, field, course[field if field != "name" else "module_name"])
        module.last_catalog_sync = now()
    db.commit()
    return len(courses)


def sync_recordings(db, module: AcademicModule, items: list[dict], *, commit=True) -> int:
    count = 0
    for item in items:
        item.pop("manual_override", None)
        session = db.scalar(select(AcademicSession).where(AcademicSession.module_id == module.id,
                                                       AcademicSession.resource_key == item["resource_key"]))
        if session and session.recordings_manual:
            item["manual_override"] = True
            continue
        videos = item.get("videos") or ([{"video_id": item["video_id"], "url": item["url"]}]
                                         if item.get("video_id") else [])
        candidates = videos or item.get("video_candidates", [])
        candidate_ids = {video["video_id"] for video in candidates}
        owners = list(db.scalars(select(Recording).where(Recording.video_id.in_(candidate_ids)))) if candidate_ids else []
        owner_ids = {part.session_id for part in owners}
        if session is None and len(owner_ids) == 1 and {part.video_id for part in owners} == candidate_ids:
            owner = db.get(AcademicSession, next(iter(owner_ids)))
            if owner.module_id == module.id and owner.recordings_manual:
                item["manual_override"] = True
                continue
        ids = [video["video_id"] for video in videos]
        if len(ids) != len(set(ids)) or len(ids) > 8:
            raise Conflict("INVALID_RECORDING_PARTS")
        existing = list(db.scalars(select(Recording).where(Recording.video_id.in_(ids)))) if ids else []
        foreign = [part for part in existing if session is None or part.session_id != session.id]
        if foreign:
            owners = {part.session_id for part in foreign}
            if any(db.get(AcademicSession, sid).module_id != module.id for sid in owners):
                raise Conflict("VIDEO_LINKED_TO_OTHER_MODULE")
            if len(owners) == 1:
                original_parts = list(db.scalars(select(Recording).where(Recording.session_id == next(iter(owners)))
                                                 .order_by(Recording.position)))
                if [part.video_id for part in original_parts] == ids and len(foreign) == len(ids):
                    continue  # Duplicate link to the same complete recording, not a new class.
            raise Conflict("VIDEO_LINKED_TO_OTHER_SESSION")
        if session is None:
            session = AcademicSession(module_id=module.id, resource_key=item["resource_key"],
                                      title=item["title"], class_date=item["date"])
            db.add(session)
            db.flush()
            count += 1
        elif not session.manual_assignment:
            session.title, session.class_date = item["title"], item["date"]
        if item.get("discovery_error"):
            session.discovery_status = "REVIEW_REQUIRED"
            session.error_code = item["discovery_error"]
        if videos:
            old = list(db.scalars(select(Recording).where(Recording.session_id == session.id).order_by(Recording.position)))
            if old and [part.video_id for part in old] != ids:
                raise Conflict("RECORDING_VIDEO_CHANGED")
            if not old:
                for position, video in enumerate(videos, 1):
                    db.add(Recording(session_id=session.id, position=position, video_id=video["video_id"],
                                     url=video["url"], resource_url=item["resource_url"]))
            session.discovery_status = "VIDEO_IDENTIFIED"
            if session.error_code in {"MOODLE_MULTIPLE_VIDEOS", "RECORDING_REQUIRES_REVIEW"}:
                session.error_code = None
    db.flush()
    reconcile(db, module)
    module.last_recording_sync = now()
    if commit:
        db.commit()
    else:
        db.flush()
    return count


def recording_sync_result(items, count):
    result = {"recordings_found": len(items), "new_sessions": count,
              "videos_identified": sum(len(item["videos"]) if item.get("videos") else bool(item.get("video_id")) for item in items)}
    reviews = [{"resource_key": item["resource_key"], "title": item["title"],
                "date": item["date"].isoformat(), "candidates": item["video_candidates"]}
               for item in items if item.get("discovery_error") and not item.get("manual_override")]
    if reviews:
        result["reviews"] = reviews
    return result
