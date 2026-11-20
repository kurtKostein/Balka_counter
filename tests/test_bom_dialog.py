"""Регрессионный тест поведения диалога состава сборки (issue #4)."""

import asyncio

from nicegui import ui
from nicegui.testing.user_simulation import user_simulation
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Assembly, Base, BOMItem, Part
from pages import bom
from pages.registry import refreshers


def test_bom_dialog_stays_open_until_done(monkeypatch, tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path}/test.db')
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr(bom, 'Session', session_factory)
    monkeypatch.setitem(refreshers, 'parts', lambda: None)

    with session_factory() as session:
        shaft = Part(name='Вал')
        gear = Part(name='Шестерня')
        assembly = Assembly(name='Привод', planned_qty=1)
        session.add_all([shaft, gear, assembly])
        session.flush()
        session.add(BOMItem(assembly_id=assembly.id, part_id=shaft.id,
                            qty_per_assembly=2))
        session.commit()
        assembly_id = assembly.id

    def page():
        bom.bom_section()

    async def scenario():
        async with user_simulation(root=page) as user:
            await user.open('/')
            user.find(kind=ui.table).trigger(
                'rowClick', [None, {'asm_id': assembly_id}])
            await user.should_see('Состав сборки «Привод»')
            dialog = next(iter(user.find(kind=ui.dialog).elements))

            def assert_open():
                assert not dialog.is_deleted and dialog.value

            assert_open()

            quantity = next(element for element in
                            user.find(kind=ui.number).elements
                            if element.value == 2)
            quantity.value = 3
            user.find(kind=ui.number).trigger('change')
            await asyncio.sleep(0)
            assert_open()

            user.find('delete').click()
            await asyncio.sleep(0)
            assert_open()

            user.find(kind=ui.select).click()
            user.find('Шестерня').click()
            user.find('Добавить').click()
            await asyncio.sleep(0)
            assert_open()

            user.find('Готово').click()
            await asyncio.sleep(0)
            assert dialog.is_deleted or not dialog.value
            table = next(iter(user.find(kind=ui.table).elements))
            assert table.rows[0]['parts'] == 'Шестерня 1шт.'

    asyncio.run(scenario())
