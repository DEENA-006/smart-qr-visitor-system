import pytest
from app import create_app
from app.extensions import db as _db
from app.models.user import User, UserRole


@pytest.fixture(scope='session')
def app():
    """Session-wide test Flask application."""
    app = create_app('testing')
    return app


@pytest.fixture(scope='function')
def db(app):
    """Function-scoped fresh in-memory database."""
    with app.app_context():
        _db.create_all()
        yield _db
        _db.session.remove()
        _db.drop_all()


@pytest.fixture(scope='function')
def client(app, db):
    """Test client."""
    return app.test_client()


@pytest.fixture(scope='function')
def runner(app):
    """CLI runner."""
    return app.test_cli_runner()


@pytest.fixture
def admin_user(db):
    """Creates test Admin user."""
    user = User(
        username='testadmin',
        email='admin@test.edu',
        full_name='Test Admin',
        role=UserRole.ADMIN,
        is_active=True
    )
    user.set_password('Admin@123')
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def faculty_user(db):
    """Creates test Faculty user."""
    user = User(
        username='testfaculty',
        email='faculty@test.edu',
        full_name='Test Faculty',
        role=UserRole.FACULTY,
        department='Computer Science',
        is_active=True
    )
    user.set_password('Faculty@123')
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def security_user(db):
    """Creates test Security user."""
    user = User(
        username='testsecurity',
        email='security@test.edu',
        full_name='Test Security',
        role=UserRole.SECURITY,
        department='Main Gate',
        is_active=True
    )
    user.set_password('Security@123')
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def inactive_user(db):
    """Creates deactivated user."""
    user = User(
        username='inactive',
        email='inactive@test.edu',
        full_name='Inactive User',
        role=UserRole.FACULTY,
        is_active=False
    )
    user.set_password('Inactive@123')
    db.session.add(user)
    db.session.commit()
    return user


class AuthClientHelper:
    """Helper for testing authentication and role requests."""
    def __init__(self, client):
        self.client = client

    def login(self, identifier, password):
        return self.client.post('/login', data={
            'identifier': identifier,
            'password': password
        }, follow_redirects=True)

    def logout(self):
        return self.client.post('/logout', follow_redirects=True)


@pytest.fixture
def auth_client(client):
    return AuthClientHelper(client)
