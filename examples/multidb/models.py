import enum

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from synalchemy import Model


class Role(enum.Enum):
    admin = "admin"
    member = "member"


class User(Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(50))
    role: Mapped[Role] = mapped_column(sa.Enum(Role, name="user_role"), default=Role.member)


class Event(Model):
    __tablename__ = "events"
    __db_name__ = "analytics"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(sa.String(30))
