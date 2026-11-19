"""Тесты расчётной логики потребности деталей (calculations.py).

Используют временную базу SQLite — реальная assemblies.db не трогается.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from calculations import (part_demand, part_demand_remaining,
                          part_in_assembled, part_to_make, part_total_made,
                          parts_stats)
from database import Assembly, BOMItem, Base, Part


@pytest.fixture()
def session_factory(tmp_path):
    """Отдельная временная SQLite-база для каждого теста."""
    engine = create_engine(f'sqlite:///{tmp_path}/test.db')
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def seed(session_factory, parts, assemblies, bom):
    """parts: [(name, made_qty)], assemblies: [(name, planned, assembled)],
    bom: [(assembly_name, part_name, qty_per_assembly)]."""
    with session_factory() as s:
        part_objs = {}
        for name, made_qty in parts:
            p = Part(name=name, made_qty=made_qty)
            s.add(p)
            part_objs[name] = p
        asm_objs = {}
        for name, planned, assembled in assemblies:
            a = Assembly(name=name, planned_qty=planned,
                         assembled_qty=assembled)
            s.add(a)
            asm_objs[name] = a
        s.flush()
        for asm_name, part_name, qty in bom:
            s.add(BOMItem(assembly_id=asm_objs[asm_name].id,
                          part_id=part_objs[part_name].id,
                          qty_per_assembly=qty))
        s.commit()


def get_part(session_factory, name):
    with session_factory() as s:
        return s.query(Part).filter_by(name=name).one()


def test_part_in_two_assemblies(session_factory):
    # Деталь «Вал» входит и в «Привод», и в «Редуктор».
    seed(
        session_factory,
        parts=[('Вал', 5)],
        assemblies=[('Привод', 2, 1), ('Редуктор', 3, 0)],
        bom=[('Привод', 'Вал', 2), ('Редуктор', 'Вал', 3)],
    )
    part = get_part(session_factory, 'Вал')

    # Полная потребность: 2*2 + 3*3 = 13.
    assert part_demand(session_factory(), part) == 13
    # На несобранные: 1*2 + 3*3 = 11.
    assert part_demand_remaining(session_factory(), part) == 11
    # В собранных: 1*2 + 0*3 = 2.
    assert part_in_assembled(session_factory(), part) == 2
    # Всего изготовлено: 5 + 2 = 7.
    assert part_total_made(session_factory(), part) == 7
    # Осталось изготовить: 11 - 5 = 6.
    assert part_to_make(session_factory(), part) == 6


def test_full_scenario_from_spec(session_factory):
    # planned=5, assembled=2, qty_per_assembly=4, made=3.
    seed(
        session_factory,
        parts=[('Вал', 3)],
        assemblies=[('Привод', 5, 2)],
        bom=[('Привод', 'Вал', 4)],
    )
    part = get_part(session_factory, 'Вал')

    assert part_demand(session_factory(), part) == 20          # 4*5
    assert part_demand_remaining(session_factory(), part) == 12  # 4*3
    assert part_in_assembled(session_factory(), part) == 8     # 4*2
    assert part_total_made(session_factory(), part) == 11      # 3+8
    assert part_to_make(session_factory(), part) == 9          # 12-3


def test_all_assemblies_completed(session_factory):
    seed(
        session_factory,
        parts=[('Вал', 10)],
        assemblies=[('Привод', 4, 4)],
        bom=[('Привод', 'Вал', 2)],
    )
    part = get_part(session_factory, 'Вал')

    assert part_demand_remaining(session_factory(), part) == 0
    assert part_to_make(session_factory(), part) == 0
    assert part_in_assembled(session_factory(), part) == 8
    assert part_in_assembled(session_factory(), part) == \
        part_demand(session_factory(), part)
    # Всего изготовлено: на складе + ушедшее в собранные.
    assert part_total_made(session_factory(), part) == 18      # 10+8


def test_stock_exceeds_remaining_demand(session_factory):
    # Потребность на несобранные 8, на складе 20 — изготавливать нечего.
    seed(
        session_factory,
        parts=[('Вал', 20)],
        assemblies=[('Привод', 2, 0)],
        bom=[('Привод', 'Вал', 4)],
    )
    part = get_part(session_factory, 'Вал')

    assert part_to_make(session_factory(), part) == 0


def test_part_not_in_any_assembly(session_factory):
    seed(
        session_factory,
        parts=[('Вал', 7), ('Шестерня', 3)],
        assemblies=[('Привод', 2, 1)],
        bom=[('Привод', 'Шестерня', 2)],
    )
    part = get_part(session_factory, 'Вал')

    assert part_demand(session_factory(), part) == 0
    assert part_demand_remaining(session_factory(), part) == 0
    assert part_in_assembled(session_factory(), part) == 0
    assert part_to_make(session_factory(), part) == 0
    # Изготовлено всего равно складскому остатку.
    assert part_total_made(session_factory(), part) == 7


def test_same_part_summed_across_assemblies(session_factory):
    # «Вал» в трёх сборках с разными планами и расходами на сборку.
    seed(
        session_factory,
        parts=[('Вал', 4)],
        assemblies=[('Привод', 3, 1), ('Редуктор', 2, 2), ('Насос', 4, 0)],
        bom=[('Привод', 'Вал', 1), ('Редуктор', 'Вал', 2),
             ('Насос', 'Вал', 5)],
    )
    part = get_part(session_factory, 'Вал')

    # Полная: 3*1 + 2*2 + 4*5 = 27.
    assert part_demand(session_factory(), part) == 27
    # Несобранные: 2*1 + 0*2 + 4*5 = 22.
    assert part_demand_remaining(session_factory(), part) == 22
    # Собранные: 1*1 + 2*2 + 0*5 = 5.
    assert part_in_assembled(session_factory(), part) == 5
    # Всего изготовлено: 4 + 5 = 9.
    assert part_total_made(session_factory(), part) == 9
    # Осталось изготовить: 22 - 4 = 18.
    assert part_to_make(session_factory(), part) == 18


def test_parts_stats_matches_individual_functions(session_factory):
    # parts_stats (одним запросом) должен давать те же числа и статус,
    # что и пофункциональные расчёты — включая деталь без состава.
    seed(
        session_factory,
        parts=[('Вал', 4), ('Шестерня', 10), ('Лишняя', 0)],
        assemblies=[('Привод', 3, 1), ('Редуктор', 2, 2), ('Насос', 4, 0)],
        bom=[('Привод', 'Вал', 1), ('Редуктор', 'Вал', 2),
             ('Насос', 'Вал', 5), ('Привод', 'Шестерня', 2)],
    )
    with session_factory() as s:
        parts = s.query(Part).order_by(Part.name).all()
        stats = parts_stats(s, parts)
        for p in parts:
            st = stats[p.id]
            to_make = part_to_make(s, p)
            assert st['demand'] == part_demand(s, p)
            assert st['demand_rem'] == part_demand_remaining(s, p)
            assert st['in_asm'] == part_in_assembled(s, p)
            assert st['total_made'] == part_total_made(s, p)
            assert st['to_make'] == to_make
            assert st['status'] == ('Готово' if to_make == 0
                                    else 'В работе')


def test_parts_stats_empty_input(session_factory):
    assert parts_stats(session_factory(), []) == {}
