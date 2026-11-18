from sqlalchemy import (create_engine, String, Integer, ForeignKey,
                        UniqueConstraint, CheckConstraint, event)
from sqlalchemy.orm import (declarative_base, relationship, sessionmaker,
                            Mapped, mapped_column)

Base = declarative_base()
engine = create_engine("sqlite:///assemblies.db")
Session = sessionmaker(bind=engine)


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_conn, _):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class Part(Base):
    __tablename__ = "parts"
    __table_args__ = (CheckConstraint("made_qty >= 0"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    made_qty: Mapped[int] = mapped_column(Integer, default=0)   # на складе


class AssemblyType(Base):
    __tablename__ = "assembly_types"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)


class Assembly(Base):
    __tablename__ = "assemblies"
    __table_args__ = (
        CheckConstraint("planned_qty >= 0"),
        CheckConstraint("assembled_qty >= 0"),
        CheckConstraint("assembled_qty <= planned_qty"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    planned_qty: Mapped[int] = mapped_column(Integer, default=1)
    assembled_qty: Mapped[int] = mapped_column(Integer, default=0)  # собрано
    type_id: Mapped[int | None] = mapped_column(
        ForeignKey("assembly_types.id"), nullable=True)
    asm_type = relationship("AssemblyType")
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
    __table_args__ = (
        UniqueConstraint("assembly_id", "part_id"),
        CheckConstraint("qty_per_assembly >= 1"),
    )


Base.metadata.create_all(engine)
