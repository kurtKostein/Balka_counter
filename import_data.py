import os
import time
from dataclasses import dataclass, field

from nicegui import ui, run

from calculations import resolve_type_id
from database import Assembly, BOMItem, Part, Session
from export import CREDENTIALS_FILE, SPREADSHEET_NAME
from pages.registry import refresh

SHEET_PARTS = 'Детали'
SHEET_ASM = 'Сборки'
SHEET_BOM = 'Состав сборок'


class SheetImportError(Exception):
    """Ожидаемая проблема с содержимым таблицы (показывается пользователю)."""


@dataclass
class ImportReport:
    parts_added: int = 0
    parts_updated: int = 0
    assemblies_added: int = 0
    assemblies_updated: int = 0
    compositions_synced: int = 0      # сборок, чей состав синхронизирован
    warnings: list[str] = field(default_factory=list)


def _to_int(value):
    """Число из ячейки таблицы; None, если значение не похоже на целое."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        try:
            num = float(text.replace(',', '.'))
        except ValueError:
            return None
        return int(num) if num.is_integer() else None


def _col(header, name, sheet_title):
    """Индекс колонки по заголовку первой строки."""
    try:
        return header.index(name)
    except ValueError:
        raise SheetImportError(
            f'В листе «{sheet_title}» не найдена колонка «{name}» — '
            'проверьте, что таблицу не меняли вручную.')


def _names(names, limit=10):
    """Список имён для предупреждения: «А», «Б» и ещё N."""
    shown = [f'«{n}»' for n in names[:limit]]
    if len(names) > limit:
        shown.append(f'и ещё {len(names) - limit}')
    return ', '.join(shown)


def apply_import(data):
    """Применяет к базе данные, прочитанные из трёх листов таблицы.

    Записи сопоставляются по именам: существующие обновляются, новые
    создаются. Записи, которых в таблице нет, не трогаются — о них
    предупреждение. Вся операция в одной транзакции.
    """
    report = ImportReport()
    with Session() as s:
        _import_parts(s, data.get(SHEET_PARTS) or [], report)
        sheet_asm, asm_by_name = _import_assemblies(
            s, data.get(SHEET_ASM) or [], report)
        _import_bom(s, data.get(SHEET_BOM) or [], report,
                    sheet_asm, asm_by_name)
        s.commit()
    return report


def _import_parts(s, rows, report):
    if not rows:
        report.warnings.append(f'Лист «{SHEET_PARTS}» пуст — детали '
                               'не импортированы.')
        return
    header = rows[0]
    i_name = _col(header, 'Деталь', SHEET_PARTS)
    i_made = _col(header, 'На складе', SHEET_PARTS)

    part_by_name = {p.name: p for p in s.query(Part).all()}
    in_sheet = set()
    for num, row in enumerate(rows[1:], start=2):
        name = str(row[i_name]).strip() if i_name < len(row) else ''
        if not name:
            if any(str(c).strip() for c in row):
                report.warnings.append(
                    f'«{SHEET_PARTS}» строка {num}: нет названия — '
                    'строка пропущена.')
            continue
        if name in in_sheet:
            report.warnings.append(f'Деталь «{name}» встречается в таблице '
                                   'несколько раз — учтена первая строка.')
            continue
        made = _to_int(row[i_made] if i_made < len(row) else None)
        if made is None or made < 0:
            report.warnings.append(
                f'Деталь «{name}»: «На складе» = '
                f'«{row[i_made] if i_made < len(row) else ""}» не является '
                'неотрицательным числом — строка пропущена.')
            continue
        in_sheet.add(name)
        p = part_by_name.get(name)
        if p:
            if p.made_qty != made:
                p.made_qty = made
                report.parts_updated += 1
        else:
            p = Part(name=name, made_qty=made)
            s.add(p)
            s.flush()
            part_by_name[name] = p
            report.parts_added += 1
    missing = sorted(set(part_by_name) - in_sheet)
    if missing:
        report.warnings.append(
            f'В таблице нет {_names(missing)} — эти детали в базе оставлены '
            'без изменений.')


def _import_assemblies(s, rows, report):
    if not rows:
        report.warnings.append(f'Лист «{SHEET_ASM}» пуст — сборки '
                               'не импортированы.')
        return {}, {}
    header = rows[0]
    i_name = _col(header, 'Сборка', SHEET_ASM)
    i_type = _col(header, 'Тип', SHEET_ASM)
    i_plan = _col(header, 'План', SHEET_ASM)
    i_done = _col(header, 'Собрано', SHEET_ASM)

    sheet_asm = {}
    for num, row in enumerate(rows[1:], start=2):
        def cell(i):
            return row[i] if i < len(row) else None

        name = str(cell(i_name) or '').strip()
        if not name:
            if any(str(c).strip() for c in row):
                report.warnings.append(
                    f'«{SHEET_ASM}» строка {num}: нет названия — '
                    'строка пропущена.')
            continue
        if name in sheet_asm:
            report.warnings.append(f'Сборка «{name}» встречается в таблице '
                                   'несколько раз — учтена первая строка.')
            continue
        plan, done = _to_int(cell(i_plan)), _to_int(cell(i_done))
        if plan is None or plan < 0:
            report.warnings.append(f'Сборка «{name}»: «План» не является '
                                   'неотрицательным числом — строка '
                                   'пропущена.')
            continue
        if done is None or done < 0:
            report.warnings.append(f'Сборка «{name}»: «Собрано» не является '
                                   'неотрицательным числом — строка '
                                   'пропущена.')
            continue
        if done > plan:
            report.warnings.append(f'Сборка «{name}»: «Собрано» ({done}) '
                                   f'больше плана ({plan}) — строка '
                                   'пропущена.')
            continue
        type_name = str(cell(i_type) or '').strip()
        sheet_asm[name] = (type_name, plan, done)

    asm_by_name = {a.name: a for a in s.query(Assembly).all()}
    missing = sorted(set(asm_by_name) - set(sheet_asm))
    if missing:
        report.warnings.append(
            f'В таблице нет {_names(missing)} — эти сборки в базе оставлены '
            'без изменений.')
    for name, (type_name, plan, done) in sheet_asm.items():
        a = asm_by_name.get(name)
        if a:
            type_id = resolve_type_id(s, type_name)
            if (a.planned_qty != plan or a.assembled_qty != done
                    or a.type_id != type_id):
                a.planned_qty = plan
                a.assembled_qty = done
                a.type_id = type_id
                report.assemblies_updated += 1
        else:
            a = Assembly(name=name, planned_qty=plan,
                         assembled_qty=done,
                         type_id=resolve_type_id(s, type_name))
            s.add(a)
            s.flush()
            asm_by_name[name] = a
            report.assemblies_added += 1
    # состав обрабатываем только для сборок из таблицы
    return sheet_asm, asm_by_name


def _import_bom(s, rows, report, sheet_asm, asm_by_name):
    if not rows:
        report.warnings.append(f'Лист «{SHEET_BOM}» пуст — составы сборок '
                               'не импортированы.')
        return
    header = rows[0]
    i_asm = _col(header, 'Сборка', SHEET_BOM)
    i_part = _col(header, 'Деталь', SHEET_BOM)
    i_qty = _col(header, 'Кол-во на сборку', SHEET_BOM)

    sheet_bom = {}
    for num, row in enumerate(rows[1:], start=2):
        asm_name = str(row[i_asm]).strip() if i_asm < len(row) else ''
        part_name = str(row[i_part]).strip() if i_part < len(row) else ''
        if not asm_name or not part_name:
            report.warnings.append(
                f'«{SHEET_BOM}» строка {num}: не хватает названия сборки '
                'или детали — строка пропущена.')
            continue
        qty = _to_int(row[i_qty] if i_qty < len(row) else None)
        if qty is None or qty < 1:
            report.warnings.append(
                f'Состав «{asm_name}»: количество для «{part_name}» = '
                f'«{row[i_qty] if i_qty < len(row) else ""}» — нужно целое '
                'число не меньше 1, строка пропущена.')
            continue
        parts_qty = sheet_bom.setdefault(asm_name, {})
        if part_name in parts_qty:
            report.warnings.append(
                f'Деталь «{part_name}» в составе «{asm_name}» встречается '
                'несколько раз — количества сложены.')
        parts_qty[part_name] = parts_qty.get(part_name, 0) + qty

    part_by_name = {p.name: p for p in s.query(Part).all()}
    for asm_name in sheet_bom:
        if asm_name not in sheet_asm:
            report.warnings.append(
                f'Строки состава для «{asm_name}» проигнорированы: такой '
                f'сборки нет в листе «{SHEET_ASM}».')

    for name in sheet_asm:
        a = asm_by_name[name]
        wanted = {}
        for part_name, qty in sheet_bom.get(name, {}).items():
            p = part_by_name.get(part_name)
            if not p:
                report.warnings.append(
                    f'В составе «{name}» деталь «{part_name}» отсутствует '
                    f'в листе «{SHEET_PARTS}» — строка пропущена.')
                continue
            wanted[p.id] = qty
        existing = {it.part_id: it
                    for it in s.query(BOMItem).filter_by(
                        assembly_id=a.id).all()}
        for part_id, qty in wanted.items():
            if part_id in existing:
                if existing[part_id].qty_per_assembly != qty:
                    existing[part_id].qty_per_assembly = qty
            else:
                s.add(BOMItem(assembly_id=a.id, part_id=part_id,
                              qty_per_assembly=qty))
        for part_id, it in existing.items():
            if part_id not in wanted:
                s.delete(it)
        report.compositions_synced += 1


def fetch_sheet_data():
    """Читает три листа таблицы. Возвращает {название листа: строки}.

    Нестабильное соединение с Google (обрывы TLS) лечится повторами."""
    if not os.path.exists(CREDENTIALS_FILE):
        raise FileNotFoundError(
            f'Не найден файл ключа «{CREDENTIALS_FILE}». '
            'Создайте сервисный аккаунт в Google Cloud и скачайте JSON.')

    last_err = None
    for attempt in range(3):
        try:
            return _fetch_sheets()
        except SheetImportError:
            raise                        # проблема с данными — повтор бессмыслен
        except Exception as e:           # SSLError, ConnectionError и т.п.
            last_err = e
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
    raise last_err


def _fetch_sheets():
    import gspread
    from google.oauth2.service_account import Credentials

    # поиск таблицы по имени идёт через Drive API — нужен и его scope
    scopes = ['https://www.googleapis.com/auth/spreadsheets.readonly',
              'https://www.googleapis.com/auth/drive.readonly']
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE,
                                                  scopes=scopes)
    client = gspread.authorize(creds)
    try:
        sh = client.open(SPREADSHEET_NAME)
    except gspread.SpreadsheetNotFound:
        raise SheetImportError(
            f'Таблица «{SPREADSHEET_NAME}» не найдена. Создайте её и '
            'расшарьте на e-mail сервисного аккаунта (см. README, раздел '
            '«Экспорт в Google Таблицы»).')

    data = {}
    for title in (SHEET_PARTS, SHEET_ASM, SHEET_BOM):
        try:
            ws = sh.worksheet(title)
        except gspread.WorksheetNotFound:
            raise SheetImportError(
                f'В таблице нет листа «{title}». Сначала выгрузите данные '
                'кнопкой «Выгрузить в Google Таблицы».')
        data[title] = ws.get_all_values()
    return data


async def _run_import():
    n = ui.notification('Импортирую из Google Таблиц…', spinner=True,
                        timeout=None)
    try:
        data = await run.io_bound(fetch_sheet_data)
        report = apply_import(data)
    except Exception as e:
        n.dismiss()
        ui.notify(f'Ошибка импорта: {e}', type='negative', multi_line=True,
                  close_button='OK')
        return
    n.dismiss()
    refresh('parts', 'assemblies', 'bom')
    _show_report(report)


def _show_report(report):
    with ui.dialog() as d, ui.card():
        ui.label('Импорт завершён').classes('font-bold')
        ui.label(f'Детали: добавлено {report.parts_added}, '
                 f'обновлено {report.parts_updated}')
        ui.label(f'Сборки: добавлено {report.assemblies_added}, '
                 f'обновлено {report.assemblies_updated}')
        ui.label(f'Составов сборок синхронизировано: '
                 f'{report.compositions_synced}')
        if report.warnings:
            ui.label('Предупреждения:').classes('font-bold text-warning')
            with ui.scroll_area().classes('max-h-56 w-full'):
                for w in report.warnings:
                    ui.label('• ' + w).classes('text-sm')
        ui.button('Закрыть', on_click=d.close).props('flat')
    d.open()


async def do_import():
    with ui.dialog() as d, ui.card():
        ui.label('Импорт из Google Таблиц').classes('font-bold')
        ui.label('Данные приложения будут обновлены по содержимому таблицы: '
                 'существующие записи обновятся, новые добавятся, составы '
                 'сборок синхронизируются с таблицей. Записи, которых в '
                 'таблице нет, останутся без изменений.').classes('w-96')

        async def start():
            d.close()
            await _run_import()

        with ui.row():
            ui.button('Импортировать', on_click=start).props('color=green')
            ui.button('Отмена', on_click=d.close).props('flat')
    d.open()
