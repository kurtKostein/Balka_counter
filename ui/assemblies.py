from nicegui import ui

from calculations import resolve_type_id
from database import Assembly, AssemblyType, Session
from ui.registry import refresh, register


@ui.refreshable
def assemblies_table():
    with Session() as s:
        asm = s.query(Assembly).order_by(Assembly.name).all()
        rows = [{
            'id': a.id, 'name': a.name,
            'type': a.asm_type.name if a.asm_type else '—',
            'plan': a.planned_qty,
            'done': a.assembled_qty, 'remaining': a.remaining,
        } for a in asm]

    columns = [
        {'name': 'name', 'label': 'Сборка', 'field': 'name', 'align': 'left'},
        {'name': 'type', 'label': 'Тип', 'field': 'type', 'align': 'left'},
        {'name': 'plan', 'label': 'План', 'field': 'plan'},
        {'name': 'done', 'label': 'Собрано', 'field': 'done'},
        {'name': 'remaining', 'label': 'Осталось', 'field': 'remaining'},
    ]
    table = ui.table(columns=columns, rows=rows, row_key='id').classes('w-full')
    table.on('rowClick', lambda e: edit_assembly_dialog(e.args[1]['id']))
    ui.label('Клик по строке — редактировать').classes('text-xs text-gray-500')


register('assemblies', assemblies_table.refresh)


def edit_assembly_dialog(asm_id=None):
    with Session() as s:
        a = s.get(Assembly, asm_id) if asm_id else None
        name_val = a.name if a else ''
        plan_val = a.planned_qty if a else 1
        done_val = a.assembled_qty if a else 0
        type_val = a.type_id if a else None
        type_opts = {t.id: t.name
                     for t in s.query(AssemblyType).order_by(
                         AssemblyType.name)}

    with ui.dialog() as dialog, ui.card():
        ui.label('Редактировать сборку' if asm_id else 'Новая сборка')
        name = ui.input('Название', value=name_val)
        plan = ui.number('План (шт.)', value=plan_val, min=0, format='%d')
        done = ui.number('Собрано (шт.)', value=done_val, min=0, format='%d')
        sel_type = ui.select(type_opts, label='Тип (необязательно)',
                             value=type_val).classes('w-full')

        def save():
            new_name = (name.value or '').strip()
            p_val = int(plan.value or 0)
            d_val = int(done.value or 0)
            # --- валидация ---
            if not new_name:
                ui.notify('Название не может быть пустым', type='negative')
                return
            if p_val < 0 or d_val < 0:
                ui.notify('Количество не может быть отрицательным',
                          type='negative')
                return
            if d_val > p_val:
                ui.notify('«Собрано» не может превышать план', type='negative')
                return
            with Session() as s:
                dup = s.query(Assembly).filter(
                    Assembly.name == new_name,
                    Assembly.id != (asm_id or 0)).first()
                if dup:
                    ui.notify(f'Сборка «{new_name}» уже существует',
                              type='negative')
                    return
                a = s.get(Assembly, asm_id) if asm_id else Assembly()
                a.name = new_name
                a.planned_qty = p_val
                a.assembled_qty = d_val
                a.type_id = resolve_type_id(s, sel_type.value)
                if not asm_id:
                    s.add(a)
                s.commit()
            dialog.close()
            assemblies_table.refresh()
            refresh('parts', 'bom')

        with ui.row():
            ui.button('Сохранить', on_click=save)
            if asm_id:
                ui.button('Удалить', on_click=lambda: confirm_delete_assembly(
                    asm_id, dialog)).props('flat color=negative')
            ui.button('Отмена', on_click=dialog.close).props('flat')
    dialog.open()


def confirm_delete_assembly(asm_id, parent_dialog=None):
    with Session() as s:
        a = s.get(Assembly, asm_id)
        name = a.name if a else ''

    with ui.dialog() as d, ui.card():
        ui.label(f'Удалить сборку «{name}»?')
        ui.label('Её состав (спецификация) тоже удалится.').classes(
            'text-negative')

        def do_delete():
            with Session() as s:
                a = s.get(Assembly, asm_id)   # BOMItem удалятся каскадом
                if a:
                    s.delete(a)
                s.commit()
            d.close()
            if parent_dialog:
                parent_dialog.close()
            assemblies_table.refresh()
            refresh('parts', 'bom')
            ui.notify(f'Сборка «{name}» удалена', type='positive')

        with ui.row():
            ui.button('Да, удалить', on_click=do_delete).props('color=negative')
            ui.button('Отмена', on_click=d.close).props('flat')
    d.open()


def manage_types_dialog():
    with ui.dialog() as dialog, ui.card():
        ui.label('Типы сборок').classes('text-lg font-bold')

        @ui.refreshable
        def types_list():
            with Session() as s:
                types = s.query(AssemblyType).order_by(AssemblyType.name).all()
            if not types:
                ui.label('Типов пока нет — добавьте ниже.').classes(
                    'text-gray-500')
            for t in types:
                with ui.row().classes('items-center w-full'):
                    inp = ui.input(value=t.name).classes('grow')

                    def rename(_, tid=t.id, i=inp):
                        new_name = (i.value or '').strip()
                        if not new_name:
                            ui.notify('Название не может быть пустым',
                                      type='negative')
                            return
                        with Session() as s:
                            dup = s.query(AssemblyType).filter(
                                AssemblyType.name == new_name,
                                AssemblyType.id != tid).first()
                            if dup:
                                ui.notify(f'Тип «{new_name}» уже существует',
                                          type='negative')
                                return
                            t = s.get(AssemblyType, tid)
                            if t:
                                t.name = new_name
                                s.commit()
                        ui.notify('Тип переименован', type='positive')
                        types_list.refresh()
                        refresh('assemblies', 'bom')

                    inp.on('change', rename)
                    ui.button(icon='delete',
                              on_click=lambda _, tid=t.id: ask_delete(tid)
                              ).props('flat dense color=negative')

        def ask_delete(tid):
            with Session() as s:
                t = s.get(AssemblyType, tid)
                tname = t.name if t else ''
                used = s.query(Assembly).filter_by(type_id=tid).count()

            with ui.dialog() as d, ui.card():
                ui.label(f'Удалить тип «{tname}»?')
                if used:
                    ui.label(f'Тип назначен {used} сборк(ам) — '
                             'у сборок он просто пропадёт.').classes(
                        'text-negative')

                def do_delete():
                    with Session() as s:
                        s.query(Assembly).filter_by(type_id=tid).update(
                            {'type_id': None})
                        t = s.get(AssemblyType, tid)
                        if t:
                            s.delete(t)
                        s.commit()
                    d.close()
                    types_list.refresh()
                    refresh('assemblies', 'bom')
                    ui.notify(f'Тип «{tname}» удалён', type='positive')

                with ui.row():
                    ui.button('Да, удалить', on_click=do_delete).props(
                        'color=negative')
                    ui.button('Отмена', on_click=d.close).props('flat')
            d.open()

        types_list()

        new_type = ui.input('Новый тип').classes('w-full')

        def add_type():
            name = (new_type.value or '').strip()
            if not name:
                ui.notify('Введите название типа', type='warning')
                return
            with Session() as s:
                if s.query(AssemblyType).filter_by(name=name).first():
                    ui.notify(f'Тип «{name}» уже существует', type='negative')
                    return
                s.add(AssemblyType(name=name))
                s.commit()
            new_type.value = ''
            types_list.refresh()
            ui.notify(f'Тип «{name}» добавлен', type='positive')

        with ui.row():
            ui.button('Добавить', on_click=add_type).props('dense')
            ui.button('Готово', on_click=dialog.close).props('flat')
    dialog.open()
