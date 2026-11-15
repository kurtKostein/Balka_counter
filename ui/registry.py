from collections.abc import Callable

# Реестр refresh-функций вкладок.
# Позволяет модулям ui/* обновлять таблицы других вкладок
# без циклических импортов.
refreshers: dict[str, Callable[[], None]] = {}


def register(name: str, fn: Callable[[], None]) -> None:
    """Привязывает refresh-функцию вкладки к имени."""
    refreshers[name] = fn


def refresh(*names: str) -> None:
    """Обновляет зарегистрированные таблицы по именам."""
    for name in names:
        refreshers[name]()
