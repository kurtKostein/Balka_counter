"""Тесты ограничений целостности схемы (CHECK и внешние ключи).

Недопустимые значения должны отклоняться базой данных, даже если их
записывают напрямую через SQLAlchemy, минуя проверки UI. Используют
временную базу SQLite — реальная assemblies.db не трогается.
"""

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from database import Assembly, BOMItem, Base, Part


@pytest.fixture()
def session_factory(tmp_path):
    """Отдельная временная SQLite-база для каждого теста,
    с включённой поддержкой внешних ключей (как в database.py)."""
    engine = create_engine(f'sqlite:///{tmp_path}/test.db')

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def commit_and_expect_integrity_error(session_factory, obj):
    with session_factory() as s:
        s.add(obj)
        with pytest.raises(IntegrityError):
            s.commit()


def test_part_negative_made_qty_rejected(session_factory):
    commit_and_expect_integrity_error(session_factory,
                                      Part(name='Вал', made_qty=-1))


def test_assembly_negative_planned_qty_rejected(session_factory):
    commit_and_expect_integrity_error(
        session_factory, Assembly(name='Привод', planned_qty=-1))


def test_assembly_negative_assembled_qty_rejected(session_factory):
    commit_and_expect_integrity_error(
        session_factory, Assembly(name='Привод', planned_qty=1,
                                  assembled_qty=-1))


def test_assembly_assembled_exceeds_planned_rejected(session_factory):
    commit_and_expect_integrity_error(
        session_factory, Assembly(name='Привод', planned_qty=3,
                                  assembled_qty=5))


def test_bom_zero_qty_per_assembly_rejected(session_factory):
    with session_factory() as s:
        part = Part(name='Вал', made_qty=0)
        asm = Assembly(name='Привод', planned_qty=1)
        s.add_all([part, asm])
        s.flush()
        s.add(BOMItem(assembly_id=asm.id, part_id=part.id,
                      qty_per_assembly=0))
        with pytest.raises(IntegrityError):
            s.commit()


def test_bom_negative_qty_per_assembly_rejected(session_factory):
    with session_factory() as s:
        part = Part(name='Вал', made_qty=0)
        asm = Assembly(name='Привод', planned_qty=1)
        s.add_all([part, asm])
        s.flush()
        s.add(BOMItem(assembly_id=asm.id, part_id=part.id,
                      qty_per_assembly=-2))
        with pytest.raises(IntegrityError):
            s.commit()


def test_bom_references_missing_part_rejected(session_factory):
    with session_factory() as s:
        asm = Assembly(name='Привод', planned_qty=1)
        s.add(asm)
        s.flush()
        s.add(BOMItem(assembly_id=asm.id, part_id=999,
                      qty_per_assembly=1))
        with pytest.raises(IntegrityError):
            s.commit()


def test_bom_references_missing_assembly_rejected(session_factory):
    with session_factory() as s:
        part = Part(name='Вал', made_qty=0)
        s.add(part)
        s.flush()
        s.add(BOMItem(assembly_id=999, part_id=part.id,
                      qty_per_assembly=1))
        with pytest.raises(IntegrityError):
            s.commit()


def test_boundary_values_accepted(session_factory):
    # made_qty=0, assembled == planned, qty_per_assembly=1 — допустимы.
    with session_factory() as s:
        part = Part(name='Вал', made_qty=0)
        asm = Assembly(name='Привод', planned_qty=2, assembled_qty=2)
        s.add_all([part, asm])
        s.flush()
        s.add(BOMItem(assembly_id=asm.id, part_id=part.id,
                      qty_per_assembly=1))
        s.commit()

    with session_factory() as s:
        assert s.query(Part).one().made_qty == 0
        assert s.query(Assembly).one().assembled_qty == 2
        assert s.query(BOMItem).one().qty_per_assembly == 1
