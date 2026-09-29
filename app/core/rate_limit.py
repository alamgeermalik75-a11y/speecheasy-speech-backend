import time
from collections import defaultdict
from app.config import settings
from app.core.exceptions import RateLimitException

class SlidingWindowRateLimiter:
    """
    In-memory rate limiter per user key based on sliding window.
    """
    def __init__(self, max_requests: int = 20, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = defaultdict(list)

    def check_rate_limit(self, user_key: str):
        now = time.time()
        timestamps = self.requests[user_key]

        # Purge older timestamps outside the window
        cutoff = now - self.window_seconds
        valid_timestamps = [t for t in timestamps if t > cutoff]
        self.requests[user_key] = valid_timestamps

        if len(valid_timestamps) >= self.max_requests:
            raise RateLimitException("Too many chatbot requests. Please wait a moment before trying again.")

        self.requests[user_key].append(now)

chat_rate_limiter = SlidingWindowRateLimiter(
    max_requests=settings.CHAT_RATE_LIMIT,
    window_seconds=60
)
