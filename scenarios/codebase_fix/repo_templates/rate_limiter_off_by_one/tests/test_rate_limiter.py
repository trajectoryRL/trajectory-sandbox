"""Tests for RateLimiter."""

import time
import pytest

from src.rate_limiter import RateLimiter


def test_allows_first_request():
    rl = RateLimiter(max_requests=5, window_seconds=60)
    assert rl.allow("user1") is True


def test_blocks_after_many_calls():
    rl = RateLimiter(max_requests=3, window_seconds=60)
    # 10 calls should definitely trip the limit
    results = [rl.allow("user1") for _ in range(10)]
    assert any(r is False for r in results)


def test_per_user_isolation():
    rl = RateLimiter(max_requests=1, window_seconds=60)
    assert rl.allow("alice") is True
    # Alice is now rate-limited; Bob should still be fine
    assert rl.allow("bob") is True


def test_returns_boolean():
    rl = RateLimiter(max_requests=1, window_seconds=60)
    assert isinstance(rl.allow("x"), bool)


def test_resets_after_window():
    rl = RateLimiter(max_requests=1, window_seconds=0.2)
    assert rl.allow("user1") is True
    assert rl.allow("user1") is False
    time.sleep(0.3)
    # After the window elapses, user should be allowed again
    assert rl.allow("user1") is True
