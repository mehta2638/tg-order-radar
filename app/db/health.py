from sqlalchemy import text

from app.db.session import async_session_factory


async def check_database() -> None:
    async with async_session_factory() as session:
        await session.execute(text("select 1"))
