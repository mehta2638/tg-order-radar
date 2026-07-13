import asyncio

from app.services.seed import seed_keywords


async def main() -> None:
    result = await seed_keywords()
    print(
        "Seed complete: "
        f"{result['positive_inserted']} positive keywords, "
        f"{result['negative_inserted']} negative keywords inserted."
    )


if __name__ == "__main__":
    asyncio.run(main())
