import os
from datetime import datetime

from nicegui import ui, run
from sqlalchemy import (create_engine, String, Integer, ForeignKey,
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
    made_qty: Mapped[int] = mapped_column(Integer, default=0)   # на складе


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
        } for a in asm]

    columns = [
        {'name': 'name', 'label': 'Сборка', 'field': 'name', 'align': 'left'},
        {'name': 'plan', 'label': 'План', 'field': 'plan'},
        {'name': 'done', 'label': 'Собрано', 'field': 'done'},
        {'name': 'remaining', 'label': 'Осталось', 'field': 'remaining'},
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
        rows = []
        for a in assemblies:
            items = sorted(s.query(BOMItem).filter_by(assembly_id=a.id).all(),
                           key=lambda it: it.part.name)
            comp = ', '.join(f'{it.part.name} {it.qty_per_assembly}шт.'
                             for it in items) or '—'
            rows.append({'asm_id': a.id, 'assembly': a.name,
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
                        bom_section.refresh()
                        parts_table.refresh()

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
            bom_section.refresh()
            parts_table.refresh()

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
            bom_section.refresh()
            parts_table.refresh()

        with ui.row().classes('items-center w-full'):
            sel = ui.select(part_opts, label='Деталь').classes('grow')
            qty_new = ui.number('Кол-во', value=1, min=1,
                                format='%d').classes('w-24')
            ui.button('Добавить', on_click=add).props('dense')
        ui.button('Готово', on_click=dialog.close).props('flat')
    dialog.open()


# ---------- Экспорт в Google Таблицы ----------
# Требуется: pip install gspread google-auth
# И файл сервисного аккаунта credentials.json рядом с app.py
CREDENTIALS_FILE = os.getenv('GOOGLE_CREDENTIALS', 'credentials.json')
SPREADSHEET_NAME = os.getenv('GOOGLE_SHEET_NAME', 'Учёт сборок и деталей')
SHARE_WITH = os.getenv('GOOGLE_SHARE_EMAIL', '')   # ваш gmail для доступа


def build_export_data():
    """Готовит три набора строк: Детали, Сборки, Состав сборок."""
    with Session() as s:
        parts = s.query(Part).order_by(Part.name).all()
        parts_rows = [['Деталь', 'Нужно всего', 'На несобранные', 'На складе',
                       'В сборках', 'Изготовлено всего', 'Осталось', 'Статус']]
        for p in parts:
            parts_rows.append([
                p.name, part_demand(s, p), part_demand_remaining(s, p),
                p.made_qty, part_in_assembled(s, p), part_total_made(s, p),
                part_to_make(s, p),
                'Готово' if part_to_make(s, p) == 0 else 'В работе',
            ])

        asm = s.query(Assembly).order_by(Assembly.name).all()
        asm_rows = [['Сборка', 'План', 'Собрано', 'Осталось']]
        for a in asm:
            asm_rows.append([a.name, a.planned_qty, a.assembled_qty,
                             a.remaining])

        bom_rows = [['Сборка', 'Деталь', 'Кол-во на сборку', 'Всего по плану']]
        for a in asm:
            for it in s.query(BOMItem).filter_by(assembly_id=a.id).all():
                bom_rows.append([a.name, it.part.name, it.qty_per_assembly,
                                 it.qty_per_assembly * a.planned_qty])

    return {'Детали': parts_rows, 'Сборки': asm_rows,
            'Состав сборок': bom_rows}


def export_to_google_sheets():
    """Выгружает все таблицы в Google Таблицы. Возвращает ссылку."""
    import gspread
    from google.oauth2.service_account import Credentials

    if not os.path.exists(CREDENTIALS_FILE):
        raise FileNotFoundError(
            f'Не найден файл ключа «{CREDENTIALS_FILE}». '
            'Создайте сервисный аккаунт в Google Cloud и скачайте JSON.')

    scopes = ['https://www.googleapis.com/auth/spreadsheets',
              'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE,
                                                  scopes=scopes)
    client = gspread.authorize(creds)

    try:
        sh = client.open(SPREADSHEET_NAME)
    except gspread.SpreadsheetNotFound:
        sh = client.create(SPREADSHEET_NAME)
        if SHARE_WITH:
            sh.share(SHARE_WITH, perm_type='user', role='writer')

    data = build_export_data()
    for title, rows in data.items():
        try:
            ws = sh.worksheet(title)
            ws.clear()
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=title, rows=max(len(rows) + 10, 50),
                                  cols=max(len(rows[0]) + 2, 10))
        ws.update(values=rows, range_name='A1')
        ws.format('1:1', {'textFormat': {'bold': True}})

    # убираем пустой лист «Sheet1», если он остался от создания
    for ws in sh.worksheets():
        if ws.title not in data and ws.row_count and not ws.get_all_values():
            sh.del_worksheet(ws)

    stamp = datetime.now().strftime('%d.%m.%Y %H:%M')
    return sh.url, stamp


async def do_export():
    n = ui.notification('Выгружаю в Google Таблицы…', spinner=True,
                        timeout=None)
    try:
        url, stamp = await run.io_bound(export_to_google_sheets)
    except Exception as e:
        n.dismiss()
        ui.notify(f'Ошибка экспорта: {e}', type='negative',
                  multi_line=True, close_button='OK')
        return
    n.dismiss()
    ui.notify(f'Готово! Выгружено {stamp}', type='positive')
    with ui.dialog() as d, ui.card():
        ui.label('Данные выгружены в Google Таблицы').classes('font-bold')
        ui.link('Открыть таблицу', url, new_tab=True)
        ui.button('Закрыть', on_click=d.close).props('flat')
    d.open()


# ---------- Сборка интерфейса ----------
@ui.page('/')
def main_page():
    with ui.row().classes('items-center w-full justify-between'):
        ui.label('Учёт сборок и деталей').classes('text-2xl font-bold')
        ui.button('Выгрузить в Google Таблицы', icon='cloud_upload',
                  on_click=do_export).props('color=green')
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
