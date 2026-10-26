import asyncio
import inspect
import os

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from academic_automation.database.models import Base
from academic_automation.database.session import seed
from academic_automation.core.config import Settings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    # Simulated tests must not inherit account credentials or flags from the host.
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in tuple(os.environ):
        if name.startswith("ACADEMIC_"):
            monkeypatch.delenv(name)


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    # Async tests use only synchronous fixtures; no additional event loop plugin needed.
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        arguments = {name: pyfuncitem.funcargs[name] for name in pyfuncitem._fixtureinfo.argnames}
        asyncio.run(pyfuncitem.obj(**arguments))
        return True


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.sqlite3'}")
    @event.listens_for(engine, "connect")
    def fk(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as session:
        seed(session)
        yield session
    engine.dispose()
