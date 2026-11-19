import sys
from pathlib import Path

# Позволяет тестам импортировать модули проекта (import_data, database и т.д.)
# независимо от того, откуда запущен pytest.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
