from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.shared.config import settings

url = settings().database_url
engine = create_async_engine(
    url,
    pool_pre_ping=True,
    **({"pool_size": 10, "max_overflow": 10} if url.startswith("postgresql") else {}),
)
Session = async_sessionmaker(engine, expire_on_commit=False)


async def get_session():
    async with Session() as session:
        yield session
