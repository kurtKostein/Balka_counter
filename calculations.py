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
