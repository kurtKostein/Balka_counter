from nicegui import ui

from database import Assembly, BOMItem, Part, Session
from pages.registry import refresh, register


@ui.refreshable
def bom_section():
    with Session() as s:
        assemblies = s.query(Assembly).order_by(Assembly.name).all()
        rows = []
        for a in assemblies:
            items = sorted(s.query(BOMItem).filter_by(assembly_id=a.id).all(),
                           key=lambda it: it.part.name)
            comp = ', '.join(f'{it.part.name} {it.qty_per_assembly}шт.'
                             for it in items) or '—'
            asm_label = (f'{a.name} · {a.asm_type.name}'
                         if a.asm_type else a.name)
            rows.append({'asm_id': a.id, 'assembly': asm_label,
                         'parts': comp})

    if not rows:
        ui.label('Сначала добавьте сборки на вкладке «Сборки».').classes(
            'text-gray-500')
        return

    columns = [
        {'name': 'assembly', 'label': 'Сборка', 'field': 'assembly',
         'align': 'left'},
        {'name': 'parts', 'label': 'Детали', 'field': 'parts',
         'align': 'left'},
    ]
    table = ui.table(columns=columns, rows=rows,
                     row_key='asm_id').classes('w-full')
    table.on('rowClick',
             lambda e: edit_assembly_bom_dialog(e.args[1]['asm_id']))
    ui.label('Клик по строке — редактировать состав').classes(
        'text-xs text-gray-500')


register('bom', bom_section.refresh)


def edit_assembly_bom_dialog(asm_id):
    """Диалог редактирования состава сборки: весь список деталей внутри."""
    with Session() as s:
        a = s.get(Assembly, asm_id)
        if not a:
            return
        asm_name = a.name
        part_opts = {p.id: p.name
                     for p in s.query(Part).order_by(Part.name).all()}

    if not part_opts:
        ui.notify('Сначала добавьте детали на вкладке «Детали»',
                  type='warning')
        return

    with ui.dialog() as dialog, ui.card():
        ui.label(f'Состав сборки «{asm_name}»').classes('text-lg font-bold')

        @ui.refreshable
        def items_list():
            with Session() as s:
                items = sorted(
                    s.query(BOMItem).filter_by(assembly_id=asm_id).all(),
                    key=lambda it: it.part.name)
            if not items:
                ui.label('Состав пуст — добавьте детали ниже.').classes(
                    'text-gray-500')
            for it in items:
                with ui.row().classes('items-center w-full'):
                    ui.label(it.part.name).classes('w-48')
                    qty = ui.number(value=it.qty_per_assembly, min=1,
                                    format='%d').classes('w-24')

                    def save_qty(_, item_id=it.id, q=qty):
                        if q.value is None or int(q.value) < 1:
                            ui.notify('Количество должно быть не меньше 1',
                                      type='negative')
                        else:
                            with Session() as s:
                                item = s.get(BOMItem, item_id)
                                if item:
                                    item.qty_per_assembly = int(q.value)
                                    s.commit()
                            ui.notify('Количество сохранено',
                                      type='positive')
                        items_list.refresh()
                        refresh('parts')

                    qty.on('change', save_qty)
                    ui.button(icon='delete',
                              on_click=lambda _, i=it.id: del_item(i)
                              ).props('flat dense color=negative')

        def del_item(item_id):
            with Session() as s:
                it = s.get(BOMItem, item_id)
                if it:
                    s.delete(it)
                    s.commit()
            items_list.refresh()
            refresh('parts')

        items_list()

        def add():
            # --- валидация ---
            if sel.value is None:
                ui.notify('Выберите деталь', type='warning')
                return
            if qty_new.value is None or int(qty_new.value) < 1:
                ui.notify('Количество должно быть не меньше 1',
                          type='negative')
                return
            with Session() as s:
                existing = s.query(BOMItem).filter_by(
                    assembly_id=asm_id, part_id=sel.value).first()
                if existing:
                    existing.qty_per_assembly = int(qty_new.value)
                    ui.notify('Деталь уже в составе — количество обновлено',
                              type='positive')
                else:
                    s.add(BOMItem(assembly_id=asm_id, part_id=sel.value,
                                  qty_per_assembly=int(qty_new.value)))
                    ui.notify('Деталь добавлена в состав', type='positive')
                s.commit()
            items_list.refresh()
            refresh('parts')

        with ui.row().classes('items-center w-full'):
            sel = ui.select(part_opts, label='Деталь').classes('grow')
            qty_new = ui.number('Кол-во', value=1, min=1,
                                format='%d').classes('w-24')
            ui.button('Добавить', on_click=add).props('dense')
        ui.button('Готово', on_click=dialog.close).props('flat')

    def refresh_on_close(e):
        if not e.value:
            bom_section.refresh()

    dialog.on_value_change(refresh_on_close)
    dialog.open()
