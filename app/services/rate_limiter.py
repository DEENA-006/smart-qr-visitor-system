import math
import re
import threading
import time
from collections import defaultdict, deque
from functools import wraps
from typing import Tuple, Optional
from flask import current_app, request, jsonify, render_template, make_response


def parse_rate_limit(rate_str: str) -> Tuple[int, int]:
    """
    Parses a rate limit string like '10/minute', '5/second', '100/hour'.
    Returns (max_requests, period_seconds).
    """
    match = re.match(r'^\s*(\d+)\s*/\s*([a-zA-Z]+)\s*$', rate_str)
    if not match:
        raise ValueError(f"Invalid rate limit format: '{rate_str}'. Expected '<count>/<unit>' (e.g., '10/minute').")

    count = int(match.group(1))
    unit = match.group(2).lower()

    if unit in ('s', 'sec', 'second', 'seconds'):
        period = 1
    elif unit in ('m', 'min', 'minute', 'minutes'):
        period = 60
    elif unit in ('h', 'hr', 'hour', 'hours'):
        period = 3600
    elif unit in ('d', 'day', 'days'):
        period = 86400
    else:
        raise ValueError(f"Unknown time unit '{unit}' in rate limit string '{rate_str}'.")

    return count, period


class InMemoryRateLimiter:
    """Thread-safe in-memory sliding-window rate limiter."""

    def __init__(self):
        self._storage = defaultdict(deque)
        self._lock = threading.Lock()

    def is_allowed(self, key: str, limit: int, period_seconds: int) -> Tuple[bool, int]:
        """
        Records an attempt and checks if the key has exceeded the limit.
        Returns (is_allowed, retry_after_seconds).
        """
        now = time.time()
        window_start = now - period_seconds

        with self._lock:
            timestamps = self._storage[key]

            # Prune expired timestamps
            while timestamps and timestamps[0] < window_start:
                timestamps.popleft()

            if len(timestamps) >= limit:
                # Exceeded: calculate time remaining until oldest entry drops out
                oldest = timestamps[0]
                retry_after = max(1, int(math.ceil(oldest + period_seconds - now)))
                return False, retry_after

            # Allowed: record timestamp
            timestamps.append(now)
            return True, 0

    def reset(self, key: Optional[str] = None):
        """Clears records for a specific key or all keys (useful for testing)."""
        with self._lock:
            if key:
                self._storage.pop(key, None)
            else:
                self._storage.clear()


# Global limiter instance
limiter = InMemoryRateLimiter()


def get_remote_address() -> str:
    """Extracts client IP, supporting standard reverse proxy X-Forwarded-For header."""
    forwarded = request.headers.get('X-Forwarded-For')
    if forwarded:
        # First IP in comma-separated list is client IP
        return forwarded.split(',')[0].strip()
    return request.remote_addr or '127.0.0.1'


def rate_limit(limit_expr_or_config_key: str, methods: Optional[list] = None):
    """
    Decorator to apply sliding-window rate limiting to Flask routes by IP.
    
    :param limit_expr_or_config_key: Config key name (e.g. 'RATE_LIMIT_LOGIN') or limit string (e.g. '10/minute').
    :param methods: List of HTTP methods to apply limiting to (defaults to ['POST']).
    """
    if methods is None:
        methods = ['POST']

    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not current_app.config.get('RATE_LIMIT_ENABLED', True):
                return f(*args, **kwargs)

            if request.method not in methods:
                return f(*args, **kwargs)

            # Resolve limit expression
            expr = current_app.config.get(limit_expr_or_config_key, limit_expr_or_config_key)
            try:
                max_requests, period = parse_rate_limit(expr)
            except Exception as e:
                current_app.logger.error(f"Rate limit configuration error for {limit_expr_or_config_key}: {e}")
                return f(*args, **kwargs)

            ip = get_remote_address()
            endpoint = request.endpoint or f.__name__
            rate_key = f"{ip}:{endpoint}"

            allowed, retry_after = limiter.is_allowed(rate_key, max_requests, period)
            if not allowed:
                current_app.logger.warning(
                    f"Rate limit exceeded: IP={ip} endpoint={endpoint} limit={expr} retry_after={retry_after}s"
                )
                if request.is_json or (request.headers.get('Accept') and 'application/json' in request.headers.get('Accept')):
                    return jsonify({
                        "error": "Too many requests. Please try again later.",
                        "retry_after": retry_after
                    }), 429, {'Retry-After': str(retry_after)}

                resp = make_response(render_template('errors/429.html', retry_after=retry_after), 429)
                resp.headers['Retry-After'] = str(retry_after)
                return resp

            return f(*args, **kwargs)

        return wrapped

    return decorator
