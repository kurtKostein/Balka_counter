from nicegui import ui
from sqlalchemy import (create_engine, String, Integer, Float, ForeignKey,
                        UniqueConstraint)
from sqlalchemy.orm import (declarative_base, relationship, sessionmaker,
                            Mapped, mapped_column)

# ---------- База данных ----------
Base = declarative_base()
engine = create_engine("sqlite:///assemblies.db")
Session = sessionmaker(bind=engine)


class Part(Base):
    __tablename__ = "parts"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    made_qty: Mapped[int] = mapped_column(Integer, default=0)   # изготовлено
    price: Mapped[float] = mapped_column(Float, default=0.0)    # цена за штуку


class Assembly(Base):
    __tablename__ = "assemblies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    planned_qty: Mapped[int] = mapped_column(Integer, default=1)
    assembled_qty: Mapped[int] = mapped_column(Integer, default=0)  # собрано
    items = relationship("BOMItem", cascade="all, delete-orphan",
                         backref="assembly")

    @property
    def remaining(self):                      # осталось собрать
        return max(0, self.planned_qty - self.assembled_qty)


class BOMItem(Base):
    __tablename__ = "bom_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    assembly_id: Mapped[int] = mapped_column(ForeignKey("assemblies.id"))
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"))
    qty_per_assembly: Mapped[int] = mapped_column(Integer, default=1)
    part = relationship("Part")
    __table_args__ = (UniqueConstraint("assembly_id", "part_id"),)


Base.metadata.create_all(engine)


# ---------- Расчёты ----------
def part_demand(session, part):
    """Полная потребность в детали по плану всех сборок."""
    rows = session.query(BOMItem).filter_by(part_id=part.id).all()
    return sum(r.qty_per_assembly * r.assembly.planned_qty for r in rows)


def part_demand_remaining(session, part):
    """Потребность только на ещё не собранные сборки."""
    rows = session.query(BOMItem).filter_by(part_id=part.id).all()
    return sum(r.qty_per_assembly * r.assembly.remaining for r in rows)


def part_to_make(session, part):
    """Сколько деталей ещё осталось изготовить."""
    return max(0, part_demand_remaining(session, part) - part.made_qty)


def part_in_assembled(session, part):
    """Сколько деталей ушло в уже собранные (отправленные) сборки."""
    rows = session.query(BOMItem).filter_by(part_id=part.id).all()
    return sum(r.qty_per_assembly * r.assembly.assembled_qty for r in rows)


def part_total_made(session, part):
    """Всего изготовлено: на складе + израсходовано в собранных сборках."""
    return part.made_qty + part_in_assembled(session, part)


def assembly_unit_cost(session, assembly):
    """Стоимость одной сборки = сумма (цена детали × кол-во на сборку)."""
    items = session.query(BOMItem).filter_by(assembly_id=assembly.id).all()
    return sum(i.qty_per_assembly * i.part.price for i in items)


# ---------- UI: вкладка «Детали» ----------
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
            'price': f'{p.price:,.2f}',
            'sum_need': f'{p.price * part_demand(s, p):,.2f}',
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
        {'name': 'price', 'label': 'Цена, ₽/шт', 'field': 'price'},
        {'name': 'sum_need', 'label': 'Сумма по плану, ₽', 'field': 'sum_need'},
        {'name': 'status', 'label': 'Статус', 'field': 'status'},
    ]
    table = ui.table(columns=columns, rows=rows, row_key='id').classes('w-full')
    table.on('rowClick', lambda e: edit_part_dialog(e.args[1]['id']))
    ui.label('Клик по строке — редактировать').classes('text-xs text-gray-500')


def edit_part_dialog(part_id=None):
    with Session() as s:
        part = s.get(Part, part_id) if part_id else None
        name_val = part.name if part else ''
        made_val = part.made_qty if part else 0
        price_val = part.price if part else 0.0

    with ui.dialog() as dialog, ui.card():
        ui.label('Редактировать деталь' if part_id else 'Новая деталь')
        name = ui.input('Название', value=name_val)
        made = ui.number('На складе (шт.)', value=made_val, min=0, format='%d')
        price = ui.number('Цена за штуку, ₽', value=price_val, min=0,
                          step=0.01, format='%.2f')

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
            if price.value is None or float(price.value) < 0:
                ui.notify('Цена не может быть отрицательной', type='negative')
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
                p.price = round(float(price.value or 0), 2)
                if not part_id:
                    s.add(p)
                s.commit()
            dialog.close()
            parts_table.refresh()
            assemblies_table.refresh()
            bom_section.refresh()

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
            bom_section.refresh()
            ui.notify(f'Деталь «{name}» удалена', type='positive')

        with ui.row():
            ui.button('Да, удалить', on_click=do_delete).props('color=negative')
            ui.button('Отмена', on_click=d.close).props('flat')
    d.open()


# ---------- UI: вкладка «Сборки» ----------
@ui.refreshable
def assemblies_table():
    with Session() as s:
        asm = s.query(Assembly).order_by(Assembly.name).all()
        rows = [{
            'id': a.id, 'name': a.name, 'plan': a.planned_qty,
            'done': a.assembled_qty, 'remaining': a.remaining,
            'unit_cost': f'{assembly_unit_cost(s, a):,.2f}',
            'plan_cost': f'{assembly_unit_cost(s, a) * a.planned_qty:,.2f}',
        } for a in asm]

    columns = [
        {'name': 'name', 'label': 'Сборка', 'field': 'name', 'align': 'left'},
        {'name': 'plan', 'label': 'План', 'field': 'plan'},
        {'name': 'done', 'label': 'Собрано', 'field': 'done'},
        {'name': 'remaining', 'label': 'Осталось', 'field': 'remaining'},
        {'name': 'unit_cost', 'label': 'Цена сборки, ₽', 'field': 'unit_cost'},
        {'name': 'plan_cost', 'label': 'Сумма по плану, ₽', 'field': 'plan_cost'},
    ]
    table = ui.table(columns=columns, rows=rows, row_key='id').classes('w-full')
    table.on('rowClick', lambda e: edit_assembly_dialog(e.args[1]['id']))
    ui.label('Клик по строке — редактировать').classes('text-xs text-gray-500')


def edit_assembly_dialog(asm_id=None):
    with Session() as s:
        a = s.get(Assembly, asm_id) if asm_id else None
        name_val = a.name if a else ''
        plan_val = a.planned_qty if a else 1
        done_val = a.assembled_qty if a else 0

    with ui.dialog() as dialog, ui.card():
        ui.label('Редактировать сборку' if asm_id else 'Новая сборка')
        name = ui.input('Название', value=name_val)
        plan = ui.number('План (шт.)', value=plan_val, min=0, format='%d')
        done = ui.number('Собрано (шт.)', value=done_val, min=0, format='%d')

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
                if not asm_id:
                    s.add(a)
                s.commit()
            dialog.close()
            assemblies_table.refresh()
            parts_table.refresh()
            bom_section.refresh()

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
            parts_table.refresh()
            bom_section.refresh()
            ui.notify(f'Сборка «{name}» удалена', type='positive')

        with ui.row():
            ui.button('Да, удалить', on_click=do_delete).props('color=negative')
            ui.button('Отмена', on_click=d.close).props('flat')
    d.open()


# ---------- UI: вкладка «Состав сборок» ----------
@ui.refreshable
def bom_section():
    with Session() as s:
        assemblies = s.query(Assembly).order_by(Assembly.name).all()
        parts = s.query(Part).order_by(Part.name).all()
        part_opts = {p.id: f'{p.name} — {p.price:,.2f} ₽' for p in parts}

        if not assemblies:
            ui.label('Сначала добавьте сборки на вкладке «Сборки».').classes(
                'text-gray-500')
            return

        for a in assemblies:
            unit_cost = assembly_unit_cost(s, a)
            plan_cost = unit_cost * a.planned_qty
            with ui.expansion(
                    f'{a.name}  (план {a.planned_qty})  —  '
                    f'{unit_cost:,.2f} ₽/шт').classes('w-full'):
                items = s.query(BOMItem).filter_by(assembly_id=a.id).all()
                for it in items:
                    line_sum = it.qty_per_assembly * it.part.price
                    with ui.row().classes('items-center'):
                        ui.label(f'{it.part.name}: {it.qty_per_assembly} шт. × '
                                 f'{it.part.price:,.2f} ₽ = {line_sum:,.2f} ₽')
                        ui.button(icon='delete',
                                  on_click=lambda _, i=it.id: del_item(i)
                                  ).props('flat dense color=negative')
                if items:
                    ui.separator()
                    ui.label(f'Себестоимость одной сборки: {unit_cost:,.2f} ₽'
                             ).classes('font-bold')
                    ui.label(f'На весь план ({a.planned_qty} шт.): '
                             f'{plan_cost:,.2f} ₽').classes('font-bold')
                if part_opts:
                    _add_item_row(a.id, part_opts)
                else:
                    ui.label('Нет деталей — добавьте их на вкладке '
                             '«Детали».').classes('text-gray-500')


def _add_item_row(asm_id, part_opts):
    with ui.row().classes('items-center'):
        sel = ui.select(part_opts, label='Деталь').classes('w-48')
        qty = ui.number('Кол-во', value=1, min=1, format='%d').classes('w-24')

        def add():
            # --- валидация ---
            if sel.value is None:
                ui.notify('Выберите деталь', type='warning')
                return
            if qty.value is None or int(qty.value) < 1:
                ui.notify('Количество должно быть не меньше 1', type='negative')
                return
            with Session() as s:
                existing = s.query(BOMItem).filter_by(
                    assembly_id=asm_id, part_id=sel.value).first()
                if existing:
                    existing.qty_per_assembly = int(qty.value)
                    ui.notify('Количество обновлено', type='positive')
                else:
                    s.add(BOMItem(assembly_id=asm_id, part_id=sel.value,
                                  qty_per_assembly=int(qty.value)))
                s.commit()
            bom_section.refresh()
            parts_table.refresh()

        ui.button('Добавить', on_click=add).props('dense')

def del_item(item_id):
    with Session() as s:
        it = s.get(BOMItem, item_id)
        if it:
            s.delete(it)
            s.commit()
    bom_section.refresh()
    parts_table.refresh()
    assemblies_table.refresh()


# ---------- Сборка интерфейса ----------
@ui.page('/')
def main_page():
    ui.label('Учёт сборок и деталей').classes('text-2xl font-bold')
    with ui.tabs() as tabs:
        t_parts = ui.tab('Детали')
        t_asm = ui.tab('Сборки')
        t_bom = ui.tab('Состав сборок')

    with ui.tab_panels(tabs, value=t_parts).classes('w-full'):
        with ui.tab_panel(t_parts):
            ui.button('+ Деталь', on_click=lambda: edit_part_dialog())
            parts_table()
        with ui.tab_panel(t_asm):
            ui.button('+ Сборка', on_click=lambda: edit_assembly_dialog())
            assemblies_table()
        with ui.tab_panel(t_bom):
            bom_section()


ui.run(title='Сборки и детали', reload=False)
