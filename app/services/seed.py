from typing import TypedDict

from sqlalchemy.dialects.postgresql import insert

from app.db.session import async_session_factory
from app.models import Keyword, NegativeKeyword


class KeywordSeed(TypedDict):
    phrase: str
    lang: str
    weight: int
    category: str
    is_regex: bool
    enabled: bool


class NegativeKeywordSeed(TypedDict):
    phrase: str
    lang: str
    weight: int
    is_regex: bool
    enabled: bool


POSITIVE_KEYWORDS: tuple[KeywordSeed, ...] = (
    {
        "phrase": "нужен сайт",
        "lang": "ru",
        "weight": 5,
        "category": "explicit_need",
        "is_regex": False,
        "enabled": True,
    },
    {
        "phrase": "ищу разработчика",
        "lang": "ru",
        "weight": 4,
        "category": "explicit_need",
        "is_regex": False,
        "enabled": True,
    },
    {
        "phrase": "сделать лендинг",
        "lang": "ru",
        "weight": 5,
        "category": "landing_page",
        "is_regex": False,
        "enabled": True,
    },
    {
        "phrase": "разработать интернет-магазин",
        "lang": "ru",
        "weight": 5,
        "category": "ecommerce",
        "is_regex": False,
        "enabled": True,
    },
    {
        "phrase": "доработать сайт",
        "lang": "ru",
        "weight": 4,
        "category": "revision",
        "is_regex": False,
        "enabled": True,
    },
    {
        "phrase": "нужен лендинг",
        "lang": "ru",
        "weight": 5,
        "category": "landing_page",
        "is_regex": False,
        "enabled": True,
    },
    {
        "phrase": "требуется интернет-магазин",
        "lang": "ru",
        "weight": 5,
        "category": "ecommerce",
        "is_regex": False,
        "enabled": True,
    },
    {
        "phrase": "ищу веб-разработчика",
        "lang": "ru",
        "weight": 4,
        "category": "explicit_need",
        "is_regex": False,
        "enabled": True,
    },
    {
        "phrase": r"кто\s+может\s+доработать",
        "lang": "ru",
        "weight": 4,
        "category": "revision",
        "is_regex": True,
        "enabled": True,
    },
)

NEGATIVE_KEYWORDS: tuple[NegativeKeywordSeed, ...] = (
    {
        "phrase": "делаю сайты",
        "lang": "ru",
        "weight": 5,
        "is_regex": False,
        "enabled": True,
    },
    {
        "phrase": "моё портфолио",
        "lang": "ru",
        "weight": 4,
        "is_regex": False,
        "enabled": True,
    },
    {
        "phrase": "ищу работу",
        "lang": "ru",
        "weight": 5,
        "is_regex": False,
        "enabled": True,
    },
    {
        "phrase": "опыт работы",
        "lang": "ru",
        "weight": 3,
        "is_regex": False,
        "enabled": True,
    },
    {
        "phrase": "выполню",
        "lang": "ru",
        "weight": 4,
        "is_regex": False,
        "enabled": True,
    },
    {
        "phrase": "делаю сайты недорого",
        "lang": "ru",
        "weight": 5,
        "is_regex": False,
        "enabled": True,
    },
    {
        "phrase": "пишите в лс закажу",
        "lang": "ru",
        "weight": 5,
        "is_regex": False,
        "enabled": True,
    },
    {
        "phrase": "резюме",
        "lang": "ru",
        "weight": 5,
        "is_regex": False,
        "enabled": True,
    },
    {
        "phrase": "создаю интернет-магазины",
        "lang": "ru",
        "weight": 4,
        "is_regex": False,
        "enabled": True,
    },
    {
        "phrase": "разработаю лендинг",
        "lang": "ru",
        "weight": 4,
        "is_regex": False,
        "enabled": True,
    },
)


async def seed_keywords() -> dict[str, int]:
    async with async_session_factory() as session:
        positive_stmt = (
            insert(Keyword)
            .values(list(POSITIVE_KEYWORDS))
            .on_conflict_do_nothing(
                index_elements=["phrase", "lang"],
            )
            .returning(Keyword.id)
        )

        negative_stmt = (
            insert(NegativeKeyword)
            .values(list(NEGATIVE_KEYWORDS))
            .on_conflict_do_nothing(
                index_elements=["phrase", "lang"],
            )
            .returning(NegativeKeyword.id)
        )

        positive_ids = (await session.scalars(positive_stmt)).all()
        negative_ids = (await session.scalars(negative_stmt)).all()
        await session.commit()

    return {
        "positive_inserted": len(positive_ids),
        "negative_inserted": len(negative_ids),
    }
