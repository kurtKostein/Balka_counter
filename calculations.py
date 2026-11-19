from sqlalchemy.orm import joinedload

from database import AssemblyType, BOMItem


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


def parts_stats(session, parts):
    """Все показатели деталей одним запросом: составы со сборками
    загружаются сразу для всего списка. Возвращает {part_id: {...}}."""
    if not parts:
        return {}
    items = (session.query(BOMItem)
             .filter(BOMItem.part_id.in_(p.id for p in parts))
             .options(joinedload(BOMItem.assembly))
             .all())
    by_part = {}
    for it in items:
        by_part.setdefault(it.part_id, []).append(it)
    stats = {}
    for p in parts:
        rows = by_part.get(p.id, [])
        demand = sum(r.qty_per_assembly * r.assembly.planned_qty
                     for r in rows)
        demand_rem = sum(r.qty_per_assembly * r.assembly.remaining
                         for r in rows)
        in_asm = sum(r.qty_per_assembly * r.assembly.assembled_qty
                     for r in rows)
        total_made = p.made_qty + in_asm
        to_make = max(0, demand_rem - p.made_qty)
        stats[p.id] = {
            'demand': demand,
            'demand_rem': demand_rem,
            'in_asm': in_asm,
            'total_made': total_made,
            'to_make': to_make,
            'status': 'Готово' if to_make == 0 else 'В работе',
        }
    return stats



def apply_stock_recalc(session, assembly, old_assembled, new_assembled):
    """Пересчитывает складские остатки деталей сборки после изменения
    количества готовых сборок с old_assembled на new_assembled.

    Прирост «Собрано» списывает детали со склада
    (qty_per_assembly × прирост), уменьшение возвращает их на склад.
    Остаток не уходит в минус: нехватка обрезается до нуля и попадает
    в возвращаемый отчёт {название детали: нехватка, шт.}. Пустой
    отчёт — пересчёт прошёл точно либо изменений не было."""
    delta = new_assembled - old_assembled
    if delta == 0:
        return {}
    items = (session.query(BOMItem)
             .filter_by(assembly_id=assembly.id)
             .options(joinedload(BOMItem.part))
             .all())
    shortages = {}
    for it in items:
        new_qty = it.part.made_qty - delta * it.qty_per_assembly
        if new_qty < 0:
            shortages[it.part.name] = -new_qty
            new_qty = 0
        it.part.made_qty = new_qty
    return shortages


def resolve_type_id(session, raw):
    """Принимает id существующего типа или введённое название.
    Новое название создаёт тип в справочнике. None/пусто — сборка без типа."""
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    name = str(raw).strip()
    if not name:
        return None
    t = session.query(AssemblyType).filter_by(name=name).first()
    if t:
        return t.id
    t = AssemblyType(name=name)
    session.add(t)
    session.flush()
    return t.id
