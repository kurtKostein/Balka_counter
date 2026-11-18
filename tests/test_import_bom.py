"""Регрессионные тесты безопасности синхронизации составов сборок при импорте.

Используют временную базу SQLite — реальная assemblies.db не трогается.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import import_data
from database import Assembly, BOMItem, Base, Part


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """Временная SQLite-база; apply_import работает с ней, а не с assemblies.db."""
    engine = create_engine(f'sqlite:///{tmp_path}/test.db')
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr(import_data, 'Session', session_factory)
    return session_factory


def make_sheets(parts, assemblies, bom):
    return {
        import_data.SHEET_PARTS: [['Деталь', 'На складе'], *parts],
        import_data.SHEET_ASM: [['Сборка', 'Тип', 'План', 'Собрано'],
                                *assemblies],
        import_data.SHEET_BOM: [['Сборка', 'Деталь', 'Кол-во на сборку'],
                                *bom],
    }


def bom_of(db, asm_name):
    with db() as s:
        a = s.query(Assembly).filter_by(name=asm_name).one()
        return {it.part.name: it.qty_per_assembly for it in a.items}


def test_typo_in_bom_keeps_existing_composition(db):
    # В базе: сборка «Привод» с деталью «Вал», количество 4.
    with db() as s:
        part = Part(name='Вал', made_qty=10)
        asm = Assembly(name='Привод', planned_qty=1, assembled_qty=0)
        s.add_all([part, asm])
        s.flush()
        s.add(BOMItem(assembly_id=asm.id, part_id=part.id,
                      qty_per_assembly=4))
        s.commit()

    # В таблице: корректные листы «Детали» и «Сборки», но в составе — опечатка.
    data = make_sheets(
        parts=[['Вал', 10]],
        assemblies=[['Привод', '', 1, 0]],
        bom=[['Привод', 'Валл', 4]],
    )
    report = import_data.apply_import(data)

    # Существующий состав «Привода» должен остаться без изменений.
    assert bom_of(db, 'Привод') == {'Вал': 4}
    # В отчёте должно быть понятное предупреждение об ошибке.
    assert any('Валл' in w for w in report.warnings)
    assert report.compositions_synced == 0


def seed_drive(db):
    """База: сборка «Привод» с деталью «Вал» (кол-во 4)."""
    with db() as s:
        part = Part(name='Вал', made_qty=10)
        asm = Assembly(name='Привод', planned_qty=1, assembled_qty=0)
        s.add_all([part, asm])
        s.flush()
        s.add(BOMItem(assembly_id=asm.id, part_id=part.id,
                      qty_per_assembly=4))
        s.commit()


VALID_PARTS = [['Вал', 10]]
VALID_ASSEMBLIES = [['Привод', '', 1, 0]]


@pytest.mark.parametrize('qty', [0, -2, 'abc'])
def test_invalid_qty_keeps_existing_composition(db, qty):
    seed_drive(db)
    data = make_sheets(VALID_PARTS, VALID_ASSEMBLIES,
                       [['Привод', 'Вал', qty]])
    report = import_data.apply_import(data)

    assert bom_of(db, 'Привод') == {'Вал': 4}
    assert any('Привод' in w and 'Вал' in w for w in report.warnings)
    assert any('без изменений' in w for w in report.warnings)
    assert report.compositions_synced == 0


def test_good_and_bad_rows_same_assembly_keeps_whole_composition(db):
    # Одна корректная строка (Вал, 5) и одна с опечаткой (Валл, 1):
    # сборка не синхронизируется целиком, корректная строка тоже не применяется.
    seed_drive(db)
    data = make_sheets(VALID_PARTS, VALID_ASSEMBLIES,
                       [['Привод', 'Вал', 5], ['Привод', 'Валл', 1]])
    report = import_data.apply_import(data)

    assert bom_of(db, 'Привод') == {'Вал': 4}
    assert report.compositions_synced == 0


def test_fully_correct_import_syncs_composition(db):
    # В базе «Привод»: Вал 4, Шестерня 2. В таблице: Вал 5, Подшипник 1.
    with db() as s:
        val = Part(name='Вал', made_qty=10)
        gear = Part(name='Шестерня', made_qty=3)
        asm = Assembly(name='Привод', planned_qty=1, assembled_qty=0)
        s.add_all([val, gear, asm])
        s.flush()
        s.add_all([BOMItem(assembly_id=asm.id, part_id=val.id,
                           qty_per_assembly=4),
                   BOMItem(assembly_id=asm.id, part_id=gear.id,
                           qty_per_assembly=2)])
        s.commit()

    data = make_sheets(
        parts=[['Вал', 10], ['Шестерня', 3], ['Подшипник', 7]],
        assemblies=VALID_ASSEMBLIES,
        bom=[['Привод', 'Вал', 5], ['Привод', 'Подшипник', 1]],
    )
    report = import_data.apply_import(data)

    # обновлено (Вал 4→5), добавлено (Подшипник), удалено (Шестерня)
    assert bom_of(db, 'Привод') == {'Вал': 5, 'Подшипник': 1}
    assert report.compositions_synced == 1
    assert not report.warnings


def test_error_in_one_assembly_does_not_block_other(db):
    seed_drive(db)
    data = make_sheets(
        parts=VALID_PARTS + [['Корпус', 2]],
        assemblies=[['Привод', '', 1, 0], ['Редуктор', '', 2, 0]],
        bom=[['Привод', 'Валл', 4],          # опечатка — Привод не трогаем
             ['Редуктор', 'Корпус', 2]],    # корректно — Редуктор синхронизируем
    )
    report = import_data.apply_import(data)

    assert bom_of(db, 'Привод') == {'Вал': 4}
    assert bom_of(db, 'Редуктор') == {'Корпус': 2}
    assert report.compositions_synced == 1
