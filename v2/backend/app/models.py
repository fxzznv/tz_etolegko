from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Campaign(Base):
    __tablename__ = "campaigns"

    # id совпадает с id кампании в Keitaro
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))


class Stream(Base):
    __tablename__ = "streams"

    # id совпадает с id потока в Keitaro
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"))
    name: Mapped[str] = mapped_column(String(255))
    # published — последнее состояние, известное в Keitaro;
    # draft — локальный черновик, уходит в трекер по кнопке Push.
    # Каждый элемент: {"id": offer_id, "name": str, "share": int,
    #                  "state": "active"|"removed", "pin": bool}
    published: Mapped[list] = mapped_column(JSON)
    draft: Mapped[list] = mapped_column(JSON)
