from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from typing import Optional

_client: Optional[AsyncIOMotorClient] = None


async def connect_db(uri: str = "mongodb://localhost:27017") -> None:
    global _client
    _client = AsyncIOMotorClient(uri)


async def close_db() -> None:
    global _client
    if _client:
        _client.close()
        _client = None


def get_db() -> AsyncIOMotorDatabase:
    assert _client is not None, "Database not connected — call connect_db() first"
    return _client["veridion"]
