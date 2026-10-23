import asyncio

import sqlalchemy as sa
from models import Event, User

from synalchemy import SynAlchemy

db = SynAlchemy.from_config()


async def main() -> None:
    async with db.lifespan(), db.session() as session:
        session.add_all([User(name="ada"), Event(kind="signup")])
        await session.commit()
        users = (await session.scalars(sa.select(User))).all()
        events = (await session.scalars(sa.select(Event))).all()
        print(f"default: {len(users)} users, analytics: {len(events)} events")


if __name__ == "__main__":
    asyncio.run(main())
