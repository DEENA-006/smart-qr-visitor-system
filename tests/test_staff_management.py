from app.models.user import User, UserRole
from app.models.audit_log import AuditLog, AuditAction
from app.services.user_service import UserService


def test_admin_can_view_staff_list(client, admin_user):
    """Admin can view the staff management page."""
    client.post('/login', data={'identifier': 'testadmin', 'password': 'Admin@123'})
    res = client.get('/admin/staff')
    assert res.status_code == 200
    assert b"Staff Accounts &amp; Role Permissions" in res.data or b"Staff Accounts" in res.data
    assert b"testadmin" in res.data


def test_non_admin_cannot_view_staff_list(client, faculty_user):
    """Faculty users cannot access staff management (returns 403)."""
    client.post('/login', data={'identifier': 'testfaculty', 'password': 'Faculty@123'})
    res = client.get('/admin/staff')
    assert res.status_code == 403


def test_admin_can_create_staff_user(client, admin_user):
    """Admin can create new staff accounts via POST."""
    client.post('/login', data={'identifier': 'testadmin', 'password': 'Admin@123'})
    res = client.post('/admin/staff', data={
        'username': 'newofficer',
        'email': 'officer@campus.edu',
        'full_name': 'Officer Jenkins',
        'role': UserRole.SECURITY,
        'department': 'South Gate',
        'password': 'Officer@123'
    }, follow_redirects=True)

    assert res.status_code == 200
    assert b"created successfully" in res.data

    user = User.query.filter_by(username='newofficer').first()
    assert user is not None
    assert user.role == UserRole.SECURITY
    assert user.check_password('Officer@123') is True
    assert user.password_hash != 'Officer@123'

    # Verify audit log
    log = AuditLog.query.filter_by(action=AuditAction.USER_CREATE, entity_reference='newofficer').first()
    assert log is not None
    assert log.actor_user_id == admin_user.id


def test_duplicate_username_rejected(client, admin_user):
    """Attempting to create a user with an existing username is rejected."""
    client.post('/login', data={'identifier': 'testadmin', 'password': 'Admin@123'})
    res = client.post('/admin/staff', data={
        'username': 'testadmin',
        'email': 'different@campus.edu',
        'full_name': 'Another Admin',
        'role': UserRole.ADMIN,
        'department': 'Admin',
        'password': 'Password@123'
    }, follow_redirects=True)

    assert b"already in use" in res.data


def test_admin_self_demotion_rejected(db, admin_user):
    """Admin cannot demote their own account away from ADMIN role."""
    updated, err = UserService.update_staff_user(
        user_id=admin_user.id,
        full_name='Renamed Admin',
        email=admin_user.email,
        department=admin_user.department,
        role=UserRole.FACULTY,
        is_active=True,
        actor_user=admin_user
    )
    assert updated is None
    assert "cannot demote their own account" in err


def test_admin_self_deactivation_rejected(db, admin_user):
    """Admin cannot deactivate their own account."""
    updated, err = UserService.update_staff_user(
        user_id=admin_user.id,
        full_name=admin_user.full_name,
        email=admin_user.email,
        department=admin_user.department,
        role=UserRole.ADMIN,
        is_active=False,
        actor_user=admin_user
    )
    assert updated is None
    assert "cannot deactivate their own account" in err


def test_last_active_admin_protection(db, admin_user):
    """Cannot deactivate or demote the last remaining active administrator."""
    # Ensure there is only 1 active admin
    admin_count = User.query.filter_by(role=UserRole.ADMIN, is_active=True).count()
    assert admin_count == 1

    # Create a second admin to act as actor
    second_admin = User(username='admin2', full_name='Second Admin', role=UserRole.ADMIN, is_active=True)
    second_admin.set_password('Admin@456')
    db.session.add(second_admin)
    db.session.commit()

    # Now there are 2 admins. Second admin can deactivate first admin
    updated, err = UserService.update_staff_user(
        user_id=admin_user.id,
        full_name=admin_user.full_name,
        email=admin_user.email,
        department=admin_user.department,
        role=UserRole.ADMIN,
        is_active=False,
        actor_user=second_admin
    )
    assert err is None
    assert updated.is_active is False

    # Now only second_admin remains active (count == 1). Attempting to deactivate second_admin must fail!
    # Even if another user somehow requested it, the last admin check blocks it
    third_actor = User(username='admin3', full_name='Third Admin', role=UserRole.ADMIN, is_active=False)
    third_actor.set_password('Admin@789')
    db.session.add(third_actor)
    db.session.commit()

    blocked, block_err = UserService.update_staff_user(
        user_id=second_admin.id,
        full_name=second_admin.full_name,
        email=second_admin.email,
        department=second_admin.department,
        role=UserRole.ADMIN,
        is_active=False,
        actor_user=third_actor
    )
    assert blocked is None
    assert "last remaining active administrator" in block_err
