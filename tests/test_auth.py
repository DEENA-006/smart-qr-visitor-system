from app.models.audit_log import AuditLog, AuditAction, AuditOutcome


def test_login_page_renders(client):
    """Test that the login page displays properly for unauthenticated users."""
    response = client.get('/login')
    assert response.status_code == 200
    assert b"Staff Sign In" in response.data
    assert b"identifier" in response.data
    assert b"password" in response.data


def test_login_success_with_username(client, admin_user):
    """Test successful login using username."""
    response = client.post('/login', data={
        'identifier': 'testadmin',
        'password': 'Admin@123'
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"Campus Administration Command Center" in response.data
    assert b"Sign out" in response.data

    # Verify audit trail
    log = AuditLog.query.filter_by(action=AuditAction.LOGIN_SUCCESS).first()
    assert log is not None
    assert log.actor_user_id == admin_user.id
    assert log.outcome == AuditOutcome.SUCCESS


def test_login_success_with_email(client, faculty_user):
    """Test successful login using email address (case-insensitive)."""
    response = client.post('/login', data={
        'identifier': 'FACULTY@TEST.EDU',
        'password': 'Faculty@123'
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"Host & Faculty Workspace" in response.data

    log = AuditLog.query.filter_by(action=AuditAction.LOGIN_SUCCESS).first()
    assert log is not None
    assert log.actor_user_id == faculty_user.id


def test_login_failure_wrong_password(client, admin_user):
    """Test that incorrect password returns 401 and logs failure."""
    response = client.post('/login', data={
        'identifier': 'testadmin',
        'password': 'WrongPassword@999'
    })

    assert response.status_code == 401
    assert b"Invalid username/email or password" in response.data

    log = AuditLog.query.filter_by(action=AuditAction.LOGIN_FAILURE).first()
    assert log is not None
    assert log.outcome == AuditOutcome.FAILURE


def test_login_failure_nonexistent_user(client, db):
    """Test that unknown username returns 401 and logs failure."""
    response = client.post('/login', data={
        'identifier': 'ghost_user',
        'password': 'Password@123'
    })

    assert response.status_code == 401
    assert b"Invalid username/email or password" in response.data

    log = AuditLog.query.filter_by(action=AuditAction.LOGIN_FAILURE).first()
    assert log is not None
    assert log.outcome == AuditOutcome.FAILURE


def test_login_failure_inactive_user(client, inactive_user):
    """Test that deactivated accounts cannot log in."""
    response = client.post('/login', data={
        'identifier': 'inactive',
        'password': 'Inactive@123'
    })

    assert response.status_code == 401
    assert b"account is inactive" in response.data

    log = AuditLog.query.filter_by(action=AuditAction.LOGIN_FAILURE).first()
    assert log is not None
    assert log.outcome == AuditOutcome.FAILURE


def test_logout_behavior(client, security_user):
    """Test that logout invalidates the user session."""
    # Login first
    client.post('/login', data={
        'identifier': 'testsecurity',
        'password': 'Security@123'
    }, follow_redirects=True)

    # Logout
    response = client.post('/logout', follow_redirects=True)
    assert response.status_code == 200
    assert b"signed out safely" in response.data
    assert b"Staff Sign In" in response.data

    # Protected route should now redirect to login
    protected = client.get('/security/dashboard')
    assert protected.status_code == 302
    assert '/login' in protected.headers['Location']

    # Verify audit entry
    log = AuditLog.query.filter_by(action=AuditAction.LOGOUT).first()
    assert log is not None
    assert log.actor_user_id == security_user.id


def test_logout_get_method_rejected(client):
    """GET requests to /logout must be rejected with 405 Method Not Allowed."""
    response = client.get('/logout')
    assert response.status_code == 405


def test_csrf_protection_enforces_token_on_post():
    """Verify that POST requests without a valid CSRF token are rejected with 400 when CSRF is enabled."""
    from app import create_app
    csrf_app = create_app('testing')
    csrf_app.config['WTF_CSRF_ENABLED'] = True
    client = csrf_app.test_client()

    # 1. Login without CSRF token must return 400 Bad Request
    login_res = client.post('/login', data={
        'identifier': 'admin',
        'password': 'Admin@123'
    })
    assert login_res.status_code == 400
    assert b"CSRF" in login_res.data or b"Bad Request" in login_res.data

    # 2. Logout without CSRF token must return 400 Bad Request
    logout_res = client.post('/logout')
    assert logout_res.status_code == 400
    assert b"CSRF" in logout_res.data or b"Bad Request" in logout_res.data


def test_logout_with_valid_csrf_token():
    """Verify that POST logout succeeds when a valid CSRF token is provided."""
    import re
    from app import create_app
    csrf_app = create_app('testing')
    csrf_app.config['WTF_CSRF_ENABLED'] = True

    client = csrf_app.test_client()
    # 1. Access login page to establish session and receive CSRF token
    login_page = client.get('/login')
    assert login_page.status_code == 200

    match = re.search(r'name=["\']csrf_token["\']\s+value=["\']([^"\']+)["\']', login_page.get_data(as_text=True))
    assert match is not None, "CSRF token not found in rendered HTML"
    valid_token = match.group(1)

    # 2. Submit POST logout with the extracted valid token
    response = client.post('/logout', data={'csrf_token': valid_token}, follow_redirects=False)
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


