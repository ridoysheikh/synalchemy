"""A FastAPI app with no database setup code: everything is in synalchemy.toml."""

from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends, FastAPI
from models import Note
from sqlalchemy.ext.asyncio import AsyncSession

from synalchemy import db

app = FastAPI(lifespan=db.lifespan)  # check the database on startup, close pools on shutdown
Session = Annotated[AsyncSession, Depends(db.get_session)]


@app.post("/notes")
async def add_note(text: str, session: Session) -> dict:
    note = Note(text=text)
    session.add(note)
    await session.commit()
    return {"id": note.id}


@app.get("/notes")
async def list_notes(session: Session, page: int = 1, limit: int = 20) -> list[dict]:
    rows = await session.scalars(
        sa.select(Note).order_by(Note.id).offset((page - 1) * limit).limit(limit)
    )
    return [{"id": n.id, "text": n.text} for n in rows]


@app.get("/health")
async def health() -> dict:
    return {"pools": db.pool_status()}
