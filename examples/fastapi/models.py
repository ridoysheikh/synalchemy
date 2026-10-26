import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from synalchemy import Model


class Note(Model):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(sa.String(200))
