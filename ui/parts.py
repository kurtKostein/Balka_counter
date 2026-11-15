from nicegui import ui

from calculations import (part_demand, part_demand_remaining, part_to_make,
                          part_in_assembled, part_total_made)
from database import BOMItem, Part, Session
from ui.registry import refresh, register


@ui.refreshable
def parts_table():
    with Session() as s:
        parts = s.query(Part).order_by(Part.name).all()
        rows = [{
            'id': p.id,
            'name': p.name,
            'demand': part_demand(s, p),
            'demand_rem': part_demand_remaining(s, p),
            'made': p.made_qty,
            'in_asm': part_in_assembled(s, p),
            'total_made': part_total_made(s, p),
            'to_make': part_to_make(s, p),
            'status': 'Готово' if part_to_make(s, p) == 0 else 'В работе',
        } for p in parts]

    columns = [
        {'name': 'name', 'label': 'Деталь', 'field': 'name', 'align': 'left'},
        {'name': 'demand', 'label': 'Нужно всего', 'field': 'demand'},
        {'name': 'demand_rem', 'label': 'На несобранные', 'field': 'demand_rem'},
        {'name': 'made', 'label': 'На складе', 'field': 'made'},
        {'name': 'in_asm', 'label': 'В сборках', 'field': 'in_asm'},
        {'name': 'total_made', 'label': 'Изготовлено всего',
         'field': 'total_made'},
        {'name': 'to_make', 'label': 'Осталось', 'field': 'to_make'},
        {'name': 'status', 'label': 'Статус', 'field': 'status'},
    ]
    table = ui.table(columns=columns, rows=rows, row_key='id').classes('w-full')
    table.on('rowClick', lambda e: edit_part_dialog(e.args[1]['id']))
    ui.label('Клик по строке — редактировать').classes('text-xs text-gray-500')


register('parts', parts_table.refresh)


def edit_part_dialog(part_id=None):
    with Session() as s:
        part = s.get(Part, part_id) if part_id else None
        name_val = part.name if part else ''
        made_val = part.made_qty if part else 0

    with ui.dialog() as dialog, ui.card():
        ui.label('Редактировать деталь' if part_id else 'Новая деталь')
        name = ui.input('Название', value=name_val)
        made = ui.number('На складе (шт.)', value=made_val, min=0, format='%d')

        def save():
            new_name = (name.value or '').strip()
            # --- валидация ---
            if not new_name:
                ui.notify('Название не может быть пустым', type='negative')
                return
            if made.value is None or int(made.value) < 0:
                ui.notify('«На складе» не может быть отрицательным',
                          type='negative')
                return
            with Session() as s:
                dup = s.query(Part).filter(Part.name == new_name,
                                           Part.id != (part_id or 0)).first()
                if dup:
                    ui.notify(f'Деталь «{new_name}» уже существует',
                              type='negative')
                    return
                p = s.get(Part, part_id) if part_id else Part()
                p.name = new_name
                p.made_qty = int(made.value or 0)
                if not part_id:
                    s.add(p)
                s.commit()
            dialog.close()
            parts_table.refresh()
            refresh('assemblies', 'bom')

        with ui.row():
            ui.button('Сохранить', on_click=save)
            if part_id:
                ui.button('Удалить', on_click=lambda: confirm_delete_part(
                    part_id, dialog)).props('flat color=negative')
            ui.button('Отмена', on_click=dialog.close).props('flat')
    dialog.open()


def confirm_delete_part(part_id, parent_dialog=None):
    with Session() as s:
        part = s.get(Part, part_id)
        name = part.name if part else ''
        used_in = s.query(BOMItem).filter_by(part_id=part_id).count()

    with ui.dialog() as d, ui.card():
        ui.label(f'Удалить деталь «{name}»?')
        if used_in:
            ui.label(f'Она входит в {used_in} сборк(и). '
                     'Записи состава тоже удалятся.').classes('text-negative')

        def do_delete():
            with Session() as s:
                s.query(BOMItem).filter_by(part_id=part_id).delete()
                p = s.get(Part, part_id)
                if p:
                    s.delete(p)
                s.commit()
            d.close()
            if parent_dialog:
                parent_dialog.close()
            parts_table.refresh()
            refresh('bom')
            ui.notify(f'Деталь «{name}» удалена', type='positive')

        with ui.row():
            ui.button('Да, удалить', on_click=do_delete).props('color=negative')
            ui.button('Отмена', on_click=d.close).props('flat')
    d.open()
