from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from academic_automation.database.models import AcademicProgram


def make_engine(url: str):
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")

    return engine


def factory(engine):
    return sessionmaker(engine, expire_on_commit=False)


def seed(db) -> None:
    for code, name, weeks, classes in [("DCC", "Doctorado", 8, 1), ("MIA", "Maestría IA", 4, 2)]:
        if db.get(AcademicProgram, code) is None:
            db.add(AcademicProgram(code=code, name=name, weeks=weeks, classes_per_week=classes))
    db.commit()
