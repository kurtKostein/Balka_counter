from nicegui import ui

from export import do_export
from import_data import do_import
from pages.assemblies import (assemblies_table, edit_assembly_dialog,
                              manage_types_dialog)
from pages.bom import bom_section
from pages.parts import edit_part_dialog, parts_table


@ui.page('/')

def main_page():

    dark = ui.dark_mode()

    with ui.row().classes('items-center w-full justify-between'):
        ui.label('Учёт сборок и деталей').classes('text-2xl font-bold')
        ui.toggle(
            {False: '☀️ Светлая', True: '🌙 Тёмная', None: 'Авто'},
                value=dark.value,
                on_change=lambda e: dark.set_value(e.value)
        )
        with ui.row():
            ui.button('Импорт из Google Таблиц', icon='cloud_download',
                      on_click=do_import)
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
            with ui.row():
                ui.button('+ Сборка', on_click=lambda: edit_assembly_dialog())
                ui.button('Типы', icon='label',
                          on_click=manage_types_dialog)
            assemblies_table()
        with ui.tab_panel(t_bom):
            bom_section()


ui.run(title='Сборки и детали', reload=False)
