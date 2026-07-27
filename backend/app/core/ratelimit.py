"""Shared slowapi rate limiter (in-memory; use a Redis storage URI in prod)."""

import os

from slowapi import Limiter
from slowapi.util import get_remote_address

# Disabled under pytest so test setup isn't throttled; the rate-limit test
# re-enables it explicitly.
limiter = Limiter(key_func=get_remote_address, enabled=not bool(os.getenv("TESTING")))
