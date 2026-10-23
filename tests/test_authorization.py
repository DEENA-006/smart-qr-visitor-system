from app.models.audit_log import AuditLog, AuditAction, AuditOutcome


def test_unauthenticated_redirect(client):
    """Unauthenticated users must be redirected to login from all protected routes."""
    for path in ['/admin/dashboard', '/faculty/dashboard', '/security/dashboard']:
        res = client.get(path)
        assert res.status_code == 302
        assert '/login' in res.headers['Location']


def test_admin_role_authorization(client, admin_user):
    """Admin can access admin dashboard, but receives 403 on other role-restricted endpoints."""
    # Login as admin
    client.post('/login', data={'identifier': 'testadmin', 'password': 'Admin@123'})

    # Allowed
    res_admin = client.get('/admin/dashboard')
    assert res_admin.status_code == 200
    assert b"Campus Administration Command Center" in res_admin.data

    # Restricted
    res_faculty = client.get('/faculty/dashboard')
    assert res_faculty.status_code == 403
    assert b"Restricted Resource" in res_faculty.data

    res_security = client.get('/security/dashboard')
    assert res_security.status_code == 403
    assert b"Restricted Resource" in res_security.data

    # Verify audit event for unauthorized attempt
    log = AuditLog.query.filter_by(action=AuditAction.UNAUTHORIZED_ACCESS).first()
    assert log is not None
    assert log.actor_user_id == admin_user.id
    assert log.outcome == AuditOutcome.FAILURE


def test_faculty_role_authorization(client, faculty_user):
    """Faculty can access faculty dashboard, but receives 403 on admin or security routes."""
    # Login as faculty
    client.post('/login', data={'identifier': 'testfaculty', 'password': 'Faculty@123'})

    # Allowed
    res_fac = client.get('/faculty/dashboard')
    assert res_fac.status_code == 200
    assert b"Host & Faculty Workspace" in res_fac.data

    # Restricted
    res_admin = client.get('/admin/dashboard')
    assert res_admin.status_code == 403

    res_sec = client.get('/security/dashboard')
    assert res_sec.status_code == 403


def test_security_role_authorization(client, security_user):
    """Security staff can access security dashboard, but receives 403 on admin or faculty routes."""
    # Login as security
    client.post('/login', data={'identifier': 'testsecurity', 'password': 'Security@123'})

    # Allowed
    res_sec = client.get('/security/dashboard')
    assert res_sec.status_code == 200
    assert b"Campus Gate Security Operations" in res_sec.data

    # Restricted
    res_admin = client.get('/admin/dashboard')
    assert res_admin.status_code == 403

    res_fac = client.get('/faculty/dashboard')
    assert res_fac.status_code == 403


def test_root_index_redirection(client, admin_user, faculty_user, security_user):
    """Root URL (/) redirects authenticated users to their assigned role dashboard."""
    # Unauthenticated
    res = client.get('/')
    assert res.status_code == 302
    assert '/login' in res.headers['Location']

    # Admin
    client.post('/login', data={'identifier': 'testadmin', 'password': 'Admin@123'})
    res = client.get('/')
    assert res.status_code == 302
    assert '/admin/dashboard' in res.headers['Location']
    client.post('/logout')

    # Faculty
    client.post('/login', data={'identifier': 'testfaculty', 'password': 'Faculty@123'})
    res = client.get('/')
    assert res.status_code == 302
    assert '/faculty/dashboard' in res.headers['Location']
    client.post('/logout')

    # Security
    client.post('/login', data={'identifier': 'testsecurity', 'password': 'Security@123'})
    res = client.get('/')
    assert res.status_code == 302
    assert '/security/dashboard' in res.headers['Location']
