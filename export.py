import os
from datetime import datetime

from nicegui import ui, run

from calculations import (part_demand, part_demand_remaining, part_to_make,
                          part_in_assembled, part_total_made)
from database import Assembly, BOMItem, Part, Session

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
        asm_rows = [['Сборка', 'Тип', 'План', 'Собрано', 'Осталось']]
        for a in asm:
            asm_rows.append([a.name,
                             a.asm_type.name if a.asm_type else '',
                             a.planned_qty, a.assembled_qty, a.remaining])

        bom_rows = [['Сборка', 'Тип', 'Деталь', 'Кол-во на сборку',
                     'Всего по плану']]
        for a in asm:
            for it in s.query(BOMItem).filter_by(assembly_id=a.id).all():
                bom_rows.append([a.name,
                                 a.asm_type.name if a.asm_type else '',
                                 it.part.name, it.qty_per_assembly,
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
