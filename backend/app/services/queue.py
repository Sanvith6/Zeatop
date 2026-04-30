import asyncio
from app.config import get_settings
from app.models.schemas import SignalIn

settings = get_settings()
signal_queue: asyncio.Queue[SignalIn] = asyncio.Queue(maxsize=settings.queue_max_size)
