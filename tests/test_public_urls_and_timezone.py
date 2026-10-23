import io
import os
from datetime import datetime, timezone
import pytest
from PIL import Image

from app.models.registration_form import RegistrationForm
from app.models.visit_type import VisitType
from app.services.form_service import FormService
from app.services.qr_service import QRService


def test_public_url_local_fallback(app, db, admin_user):
    """Test public URL generation in local development without PUBLIC_BASE_URL."""
    with app.app_context():
        # Clear PUBLIC_BASE_URL
        app.config['PUBLIC_BASE_URL'] = ''
        form, _ = FormService.create_form(
            name='Academic Seminar',
            visit_type=VisitType.ACADEMIC,
            creator_user=admin_user
        )
        assert form.public_token is not None
        assert form.public_token.startswith('FORM-')

        url = form.get_public_url()
        assert url.endswith(f"/register/{form.public_token}")
        assert 'register/' in url

    # Inside explicit request context with local host on port 5000
    with app.test_request_context('/', base_url='http://127.0.0.1:5000'):
        app.config['PUBLIC_BASE_URL'] = ''
        url = form.get_public_url()
        assert url == f"http://127.0.0.1:5000/register/{form.public_token}"


def test_public_url_configured_canonical_base(app, db, admin_user):
    """Test public URL generation when PUBLIC_BASE_URL is explicitly set for production/Vercel."""
    with app.app_context():
        app.config['PUBLIC_BASE_URL'] = 'https://smart-vms-prod.vercel.app'
        form, _ = FormService.create_form(
            name='Campus Event',
            visit_type=VisitType.GENERAL,
            creator_user=admin_user
        )
        url = form.get_public_url()
        assert url == f"https://smart-vms-prod.vercel.app/register/{form.public_token}"


def test_public_url_production_enforces_https_and_no_localhost(app, db, admin_user):
    """Test production mode enforces HTTPS and never emits localhost in public links."""
    with app.app_context():
        form, _ = FormService.create_form(
            name='Production Verification Form',
            visit_type=VisitType.VIP,
            creator_user=admin_user
        )

        # Set production environment flags
        app.config['PUBLIC_BASE_URL'] = 'https://campus-vms.edu'
        app.config['ENV'] = 'production'
        app.config['DEBUG'] = False

        url = form.get_public_url()
        assert url.startswith('https://')
        assert 'localhost' not in url
        assert '127.0.0.1' not in url
        assert url == f"https://campus-vms.edu/register/{form.public_token}"


def test_public_url_vercel_env_detection(app, db, admin_user, monkeypatch):
    """Test auto-detection of Vercel production domain when PUBLIC_BASE_URL is blank."""
    monkeypatch.setenv('VERCEL_PROJECT_PRODUCTION_URL', 'vms-demo.vercel.app')
    with app.app_context():
        app.config['PUBLIC_BASE_URL'] = ''
        form, _ = FormService.create_form(
            name='Vercel Auto Form',
            visit_type=VisitType.CONTRACTOR,
            creator_user=admin_user
        )
        url = form.get_public_url()
        assert url == f"https://vms-demo.vercel.app/register/{form.public_token}"


def test_unauthenticated_public_access_with_token(client, db, admin_user):
    """Test that a public registration URL opens without requiring admin/staff login."""
    form, _ = FormService.create_form(
        name='Official Delegation',
        visit_type=VisitType.OFFICIAL,
        creator_user=admin_user
    )
    v1 = form.versions.first()
    FormService.publish_version(form.id, v1.id, admin_user)

    # Open unauthenticated via test client
    response = client.get(f'/register/{form.public_token}')
    assert response.status_code == 200
    assert b'Official Delegation' in response.data or b'Visitor Registration' in response.data


def test_timezone_format_dt_in_ist(app):
    """Test that format_dt converts UTC timestamps to Indian Standard Time (UTC+05:30)."""
    with app.test_request_context():
        # 06:22:00 UTC = 11:52:00 IST (+05:30)
        utc_time = datetime(2026, 10, 23, 6, 22, 0, tzinfo=timezone.utc)
        
        # Search context processors for format_dt
        format_dt = None
        for cp in app.template_context_processors.get(None, []):
            try:
                res = cp()
                if 'format_dt' in res:
                    format_dt = res['format_dt']
                    break
            except Exception:
                continue

        assert format_dt is not None, "format_dt not found in context processors"
        formatted = format_dt(utc_time, '%d %b %Y, %I:%M %p')
        assert '23 Oct 2026' in formatted
        assert '11:52 AM' in formatted


def test_qr_code_rgb_format(app, db, admin_user):
    """Test that QRService produces a valid 24-bit RGB PNG openable by standard viewers."""
    qr_bytes = QRService.generate_qr_image_bytes('https://smart-vms.vercel.app/pass/REQ-TEST-1234')
    assert qr_bytes is not None
    assert len(qr_bytes) > 0

    # Verify PIL opens it and it is in RGB mode (not 1-bit monochrome '1')
    img = Image.open(io.BytesIO(qr_bytes))
    assert img.format == 'PNG'
    assert img.mode == 'RGB'
    assert img.size[0] >= 100 and img.size[1] >= 100


def test_public_url_production_strict_never_localhost(app, db, admin_user, monkeypatch):
    """Test production mode strictly never produces localhost even if request host is 127.0.0.1 or base is localhost."""
    monkeypatch.setenv('VERCEL', '1')
    with app.test_request_context('/', base_url='http://127.0.0.1:5000'):
        app.config['PUBLIC_BASE_URL'] = 'http://localhost:5000'
        form, _ = FormService.create_form(
            name='Strict Prod Form',
            visit_type=VisitType.GENERAL,
            creator_user=admin_user
        )
        url = form.get_public_url()
        assert not url.startswith('http://localhost')
        assert not url.startswith('http://127.0.0.1')
        assert url.startswith('https://')
        assert url.endswith(f"/register/{form.public_token}")


def test_public_form_unauthenticated_submission(client, db, admin_user, faculty_user):
    """Test full unauthenticated public visitor submission saves visitor and visit request record."""
    from app.models.visit import VisitRequest
    from app.models.visitor import Visitor

    form, err = FormService.create_form(
        name='Public Guest Intake',
        visit_type=VisitType.GENERAL,
        creator_user=admin_user
    )
    assert err is None
    version = form.versions.first()
    FormService.publish_version(form.id, version.id, admin_user)

    # Submit without any login session
    post_data = {
        'full_name': 'Dr. Arthur Conan',
        'email': 'arthur@bakerstreet.org',
        'phone': '+91 9876543210',
        'organization': 'Baker Street Foundation',
        'purpose': 'Consultation with campus researchers',
        'dyn__purpose_detail': 'Consultation with campus researchers on AI forensics',
        'host_user_id': str(faculty_user.id)
    }
    response = client.post(
        f'/register/{form.public_token}',
        data=post_data,
        follow_redirects=True
    )
    assert response.status_code == 200

    # Verify database persistence
    visitor = Visitor.query.filter_by(phone='+91 9876543210').first()
    assert visitor is not None
    assert visitor.full_name == 'Dr. Arthur Conan'

    req = VisitRequest.query.filter_by(visitor_id=visitor.id).first()
    assert req is not None
    assert req.public_reference.startswith('REQ-')
    assert req.host_user_id == faculty_user.id
    assert req.status == 'PENDING_APPROVAL'


def test_unpublished_and_archived_form_access_denied(client, db, admin_user):
    """Test unpublished draft tokens and invalid form links return 404."""
    form, err = FormService.create_form(
        name='Draft Form Only',
        visit_type=VisitType.VIP,
        creator_user=admin_user
    )
    assert err is None
    # Never published
    res = client.get(f'/register/{form.public_token}')
    assert res.status_code == 404

    # Invalid token returns 404
    res_invalid = client.get('/register/FORM-NONEXISTENT-TOKEN')
    assert res_invalid.status_code == 404


def test_public_url_rejects_rogue_and_invalid_domains(app, db, admin_user):
    """Test that rogue domains (like Smart_QR_tracking or domains with underscores) are rejected."""
    with app.app_context():
        form, _ = FormService.create_form(
            name='Sanitization Test',
            visit_type=VisitType.GENERAL,
            creator_user=admin_user
        )
        # Attempt to inject rogue domain with underscore
        app.config['PUBLIC_BASE_URL'] = 'https://Smart_QR_tracking.vercel.app'
        url = form.get_public_url()
        assert 'Smart_QR_tracking' not in url
        assert 'smart_qr_tracking' not in url

    # Inside live request context on smart-qr-visitor-system.vercel.app
    with app.test_request_context('/', base_url='https://smart-qr-visitor-system.vercel.app'):
        app.config['PUBLIC_BASE_URL'] = 'https://Smart_QR_tracking.vercel.app'
        url = form.get_public_url()
        assert url == f"https://smart-qr-visitor-system.vercel.app/register/{form.public_token}"


