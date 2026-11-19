"""Тесты пересчёта складских остатков при изменении количества
готовых сборок (issue #1 «Пересчёт остатка на складе»).

apply_stock_recalc списывает детали со склада, когда «Собрано» выросло,
и возвращает на склад, когда уменьшилось. Используют временную базу
SQLite — реальная assemblies.db не трогается.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from calculations import apply_stock_recalc
from database import Assembly, BOMItem, Base, Part


@pytest.fixture()
def session_factory(tmp_path):
    """Отдельная временная SQLite-база для каждого теста."""
    engine = create_engine(f'sqlite:///{tmp_path}/test.db')
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def seed_drive(session_factory, made_qty=10, qty_per_assembly=4,
               planned=5, assembled=2):
    """Сборка «Привод» с одной деталью «Вал»; на складе «Вала» made_qty шт."""
    with session_factory() as s:
        part = Part(name='Вал', made_qty=made_qty)
        asm = Assembly(name='Привод', planned_qty=planned,
                       assembled_qty=assembled)
        s.add_all([part, asm])
        s.flush()
        s.add(BOMItem(assembly_id=asm.id, part_id=part.id,
                      qty_per_assembly=qty_per_assembly))
        s.commit()


def stock_of(session_factory, part_name):
    with session_factory() as s:
        return s.query(Part).filter_by(name=part_name).one().made_qty


def test_increase_assembled_consumes_stock(session_factory):
    # Собрали на 2 шт. больше: со склада ушло 2*4 = 8 «Валов».
    seed_drive(session_factory, made_qty=10, qty_per_assembly=4, assembled=2)
    with session_factory() as s:
        asm = s.query(Assembly).filter_by(name='Привод').one()
        assert apply_stock_recalc(s, asm, old_assembled=2,
                                  new_assembled=4) == {}
        s.commit()
    assert stock_of(session_factory, 'Вал') == 2


def test_increase_consumes_each_part_by_own_qty(session_factory):
    # Каждая деталь списывается со своей нормой на сборку.
    with session_factory() as s:
        val = Part(name='Вал', made_qty=10)
        gear = Part(name='Шестерня', made_qty=7)
        asm = Assembly(name='Привод', planned_qty=5, assembled_qty=1)
        s.add_all([val, gear, asm])
        s.flush()
        s.add_all([BOMItem(assembly_id=asm.id, part_id=val.id,
                           qty_per_assembly=4),
                   BOMItem(assembly_id=asm.id, part_id=gear.id,
                           qty_per_assembly=2)])
        s.commit()
    with session_factory() as s:
        asm = s.query(Assembly).filter_by(name='Привод').one()
        assert apply_stock_recalc(s, asm, old_assembled=1,
                                  new_assembled=3) == {}
        s.commit()
    assert stock_of(session_factory, 'Вал') == 2        # 10 - 2*4
    assert stock_of(session_factory, 'Шестерня') == 3   # 7 - 2*2


def test_decrease_assembled_returns_stock(session_factory):
    # Ошибочно отмеченные сборки убрали: детали вернулись на склад.
    seed_drive(session_factory, made_qty=5, qty_per_assembly=4, assembled=4)
    with session_factory() as s:
        asm = s.query(Assembly).filter_by(name='Привод').one()
        assert apply_stock_recalc(s, asm, old_assembled=4,
                                  new_assembled=1) == {}
        s.commit()
    assert stock_of(session_factory, 'Вал') == 17       # 5 + 3*4


def test_insufficient_stock_clamps_to_zero_and_reports(session_factory):
    # Нужно 8, на складе 5: остаток обнуляется, нехватка 3 шт. — в отчёте.
    seed_drive(session_factory, made_qty=5, qty_per_assembly=4, assembled=0)
    with session_factory() as s:
        asm = s.query(Assembly).filter_by(name='Привод').one()
        report = apply_stock_recalc(s, asm, old_assembled=0,
                                    new_assembled=2)
        s.commit()
    assert report == {'Вал': 3}
    assert stock_of(session_factory, 'Вал') == 0


def test_stock_exactly_enough_is_no_shortage(session_factory):
    # Нужно 8, на складе ровно 8: остаток 0, но нехватки нет.
    seed_drive(session_factory, made_qty=8, qty_per_assembly=4, assembled=0)
    with session_factory() as s:
        asm = s.query(Assembly).filter_by(name='Привод').one()
        assert apply_stock_recalc(s, asm, old_assembled=0,
                                  new_assembled=2) == {}
        s.commit()
    assert stock_of(session_factory, 'Вал') == 0


def test_no_change_leaves_stock(session_factory):
    seed_drive(session_factory, made_qty=10, assembled=2)
    with session_factory() as s:
        asm = s.query(Assembly).filter_by(name='Привод').one()
        assert apply_stock_recalc(s, asm, old_assembled=2,
                                  new_assembled=2) == {}
        s.commit()
    assert stock_of(session_factory, 'Вал') == 10


def test_assembly_without_composition_is_noop(session_factory):
    # Состава ещё нет — пересчитывать нечего, ошибок тоже нет,
    # сама сборка остаётся без изменений.
    with session_factory() as s:
        asm = Assembly(name='Привод', planned_qty=5, assembled_qty=0)
        s.add(asm)
        s.commit()
    with session_factory() as s:
        asm = s.query(Assembly).filter_by(name='Привод').one()
        assert apply_stock_recalc(s, asm, old_assembled=0,
                                  new_assembled=3) == {}
        s.commit()
    with session_factory() as s:
        assert s.query(Assembly).filter_by(name='Привод').one() \
                   .assembled_qty == 0
        assert s.query(BOMItem).count() == 0
