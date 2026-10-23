"""Unit and route integration tests for sliding-window rate limiting service (Finding F-02)."""
import time
import pytest
from app.services.rate_limiter import parse_rate_limit, InMemoryRateLimiter, limiter


def test_parse_rate_limit():
    assert parse_rate_limit("10/minute") == (10, 60)
    assert parse_rate_limit("5/second") == (5, 1)
    assert parse_rate_limit("100/hour") == (100, 3600)
    assert parse_rate_limit("500/day") == (500, 86400)
    assert parse_rate_limit(" 20 / m ") == (20, 60)

    with pytest.raises(ValueError):
        parse_rate_limit("invalid")

    with pytest.raises(ValueError):
        parse_rate_limit("10/fortnight")


def test_in_memory_rate_limiter_sliding_window():
    test_limiter = InMemoryRateLimiter()
    key = "192.168.1.10:test_endpoint"

    # Allow 3 requests in 2 seconds
    limit = 3
    period = 2

    # First 3 attempts succeed
    allowed1, retry1 = test_limiter.is_allowed(key, limit, period)
    assert allowed1 is True
    assert retry1 == 0

    allowed2, retry2 = test_limiter.is_allowed(key, limit, period)
    assert allowed2 is True
    assert retry2 == 0

    allowed3, retry3 = test_limiter.is_allowed(key, limit, period)
    assert allowed3 is True
    assert retry3 == 0

    # 4th attempt is blocked
    allowed4, retry4 = test_limiter.is_allowed(key, limit, period)
    assert allowed4 is False
    assert retry4 >= 1

    # Reset clears key
    test_limiter.reset(key)
    allowed5, _ = test_limiter.is_allowed(key, limit, period)
    assert allowed5 is True


def test_login_rate_limiting_route(client, app):
    """Verify POST /login throttles repeated attempts when rate limiting is active."""
    app.config['RATE_LIMIT_ENABLED'] = True
    app.config['RATE_LIMIT_LOGIN'] = '3/minute'
    limiter.reset()

    try:
        # First 3 failed login attempts return 401
        for _ in range(3):
            resp = client.post('/login', data={'identifier': 'wrong', 'password': 'wrong'})
            assert resp.status_code == 401

        # 4th attempt exceeds limit -> 429 Too Many Requests
        resp_blocked = client.post('/login', data={'identifier': 'wrong', 'password': 'wrong'})
        assert resp_blocked.status_code == 429
        assert 'Retry-After' in resp_blocked.headers
        assert b"429 Too Many Requests" in resp_blocked.data or b"Rate Limit Exceeded" in resp_blocked.data

        # GET /login remains accessible and is not blocked
        resp_get = client.get('/login')
        assert resp_get.status_code == 200

        # Different client IP is not blocked
        resp_other_ip = client.post(
            '/login',
            data={'identifier': 'wrong', 'password': 'wrong'},
            headers={'X-Forwarded-For': '198.51.100.42'}
        )
        assert resp_other_ip.status_code == 401

    finally:
        # Restore test config
        app.config['RATE_LIMIT_ENABLED'] = False
        limiter.reset()


def test_registration_rate_limiting_route(client, app, db, admin_user):
    """Verify POST /register/<visit_type> throttles repeated submissions."""
    from app.services.form_service import FormService
    from app.models.visit_type import VisitType

    form, _ = FormService.create_form(name="General Form", visit_type=VisitType.GENERAL, creator_user=admin_user)
    v1 = form.versions.first()
    FormService.publish_version(form.id, v1.id, actor_user=admin_user)

    app.config['RATE_LIMIT_ENABLED'] = True
    app.config['RATE_LIMIT_REGISTER'] = '2/minute'
    limiter.reset()

    try:
        # 1st attempt
        client.post('/register/GENERAL', data={'full_name': ''})
        # 2nd attempt
        client.post('/register/GENERAL', data={'full_name': ''})
        # 3rd attempt exceeds limit -> 429
        resp = client.post('/register/GENERAL', data={'full_name': ''})
        assert resp.status_code == 429
        assert 'Retry-After' in resp.headers
    finally:
        app.config['RATE_LIMIT_ENABLED'] = False
        limiter.reset()
