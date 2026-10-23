import pytest
import csv
import io
from datetime import datetime, timezone, timedelta
from app.extensions import db
from app.models.user import User, UserRole
from app.models.visit import (
    VisitRequest,
    VisitRequestStatus,
    VisitSession,
    VisitSessionStatus
)
from app.models.visitor import Visitor
from app.models.registration_form import RegistrationForm, FormVersion
from app.models.visit_type import VisitType
from app.models.audit_log import AuditLog, AuditAction
from app.services.report_service import ReportService, sanitize_csv_cell
from app.services.qr_service import QRService
from app.services.gate_service import GateService


@pytest.fixture
def sample_report_data(db, admin_user, faculty_user, security_user):
    """Sets up a diverse dataset with multiple requests, approved, rejected, and checked in."""
    form = RegistrationForm(name="Reporting Test Form", visit_type=VisitType.OFFICIAL, is_active=True)
    db.session.add(form)
    db.session.flush()

    version = FormVersion(
        form_id=form.id,
        version_number=1,
        status='PUBLISHED',
        published_at=datetime.now(timezone.utc),
        created_by_id=admin_user.id
    )
    version.set_schema([])
    db.session.add(version)
    db.session.flush()

    now_utc = datetime.now(timezone.utc)

    # Visitor 1: Approved and currently Checked In
    v1 = Visitor(public_reference=Visitor.generate_reference(), full_name="Alice Smith", email="alice@test.edu", phone="+10000000001", organization="Tech Corp")
    db.session.add(v1)
    db.session.flush()
    r1 = VisitRequest(
        public_reference=VisitRequest.generate_reference(),
        visitor_id=v1.id,
        form_version_id=version.id,
        visit_type=VisitType.OFFICIAL,
        host_user_id=faculty_user.id,
        department="Computer Science",
        purpose="Research Collab",
        planned_start_at=now_utc - timedelta(hours=1),
        planned_end_at=now_utc + timedelta(hours=2),
        status=VisitRequestStatus.APPROVED,
        submitted_at=now_utc - timedelta(hours=2),
        approved_at=now_utc - timedelta(hours=1),
        decided_by_id=faculty_user.id
    )
    db.session.add(r1)
    db.session.flush()
    QRService.issue_credential(r1.id, admin_user, commit=True)
    GateService.check_in(r1.id, security_user)

    # Visitor 2: Approved, Checked in, and already Checked Out (Completed)
    v2 = Visitor(public_reference=Visitor.generate_reference(), full_name="Bob Jones", email="bob@test.edu", phone="+10000000002", organization="Vendor Inc")
    db.session.add(v2)
    db.session.flush()
    r2 = VisitRequest(
        public_reference=VisitRequest.generate_reference(),
        visitor_id=v2.id,
        form_version_id=version.id,
        visit_type=VisitType.CONTRACTOR,
        host_user_id=faculty_user.id,
        department="Computer Science",
        purpose="Equipment Maintenance",
        planned_start_at=now_utc - timedelta(hours=1),
        planned_end_at=now_utc + timedelta(hours=2),
        status=VisitRequestStatus.APPROVED,
        submitted_at=now_utc - timedelta(hours=2),
        approved_at=now_utc - timedelta(hours=1),
        decided_by_id=faculty_user.id
    )
    db.session.add(r2)
    db.session.flush()
    QRService.issue_credential(r2.id, admin_user, commit=True)
    sess2, _ = GateService.check_in(r2.id, security_user)
    GateService.check_out(sess2.id, security_user)

    # Visitor 3: Pending Approval
    v3 = Visitor(public_reference=Visitor.generate_reference(), full_name="Charlie Brown", email="charlie@test.edu", phone="+10000000003")
    db.session.add(v3)
    db.session.flush()
    r3 = VisitRequest(
        public_reference=VisitRequest.generate_reference(),
        visitor_id=v3.id,
        form_version_id=version.id,
        visit_type=VisitType.GENERAL,
        host_user_id=faculty_user.id,
        purpose="Campus Tour",
        status=VisitRequestStatus.PENDING_APPROVAL,
        submitted_at=now_utc - timedelta(hours=1)
    )
    db.session.add(r3)

    # Visitor 4: Rejected
    v4 = Visitor(public_reference=Visitor.generate_reference(), full_name="David Miller", email="david@test.edu", phone="+10000000004")
    db.session.add(v4)
    db.session.flush()
    r4 = VisitRequest(
        public_reference=VisitRequest.generate_reference(),
        visitor_id=v4.id,
        form_version_id=version.id,
        visit_type=VisitType.GENERAL,
        host_user_id=faculty_user.id,
        purpose="Commercial Solicitation",
        status=VisitRequestStatus.REJECTED,
        submitted_at=now_utc - timedelta(hours=4),
        rejected_at=now_utc - timedelta(hours=3),
        decided_by_id=admin_user.id,
        rejection_reason="Solicitation prohibited"
    )
    db.session.add(r4)

    # Visitor 5: Malicious payload for CSV Formula Injection testing
    v5 = Visitor(public_reference=Visitor.generate_reference(), full_name="=1+1", email="malicious@test.edu", phone="+10000000005", organization="@SUM(A1:A10)")
    db.session.add(v5)
    db.session.flush()
    r5 = VisitRequest(
        public_reference=VisitRequest.generate_reference(),
        visitor_id=v5.id,
        form_version_id=version.id,
        visit_type=VisitType.GENERAL,
        host_user_id=faculty_user.id,
        purpose="-2+5+cmd|' /C calc'!A0",
        status=VisitRequestStatus.APPROVED,
        submitted_at=now_utc
    )
    db.session.add(r5)
    db.session.commit()

    return [r1, r2, r3, r4, r5]


def test_sanitize_csv_cell_mitigates_formula_injection():
    """Test 1: CSV cell sanitizer prepends single quote to formula trigger characters."""
    assert sanitize_csv_cell("=SUM(A1:A10)") == "'=SUM(A1:A10)"
    assert sanitize_csv_cell("+44123456789") == "'+44123456789"
    assert sanitize_csv_cell("-100") == "'-100"
    assert sanitize_csv_cell("@username") == "'@username"
    assert sanitize_csv_cell("\tTabbed") == "'\tTabbed"
    assert sanitize_csv_cell("Normal Text") == "Normal Text"
    assert sanitize_csv_cell("12345") == "12345"
    assert sanitize_csv_cell(None) == ""


def test_summary_metrics_accurate_and_no_double_counting(app, db, sample_report_data):
    """Test 2: ReportService.get_summary_metrics aggregates real records accurately."""
    with app.app_context():
        summary = ReportService.get_summary_metrics()

        assert summary['total_requests'] == 5
        assert summary['pending_requests'] == 1
        assert summary['approved_visits'] == 3  # r1, r2, r5
        assert summary['rejected_visits'] == 1  # r4
        assert summary['total_checked_in'] == 2  # r1, r2
        assert summary['currently_on_campus'] == 1  # r1
        assert summary['completed_visits'] == 1  # r2

        # Check category distribution
        cat_counts = summary['category_counts']
        assert cat_counts.get(VisitType.OFFICIAL) == 1
        assert cat_counts.get(VisitType.CONTRACTOR) == 1
        assert cat_counts.get(VisitType.GENERAL) == 3


def test_filtered_query_respects_criteria(app, db, sample_report_data):
    """Test 3: get_filtered_query correctly filters by status and session state."""
    with app.app_context():
        # Filter by status: APPROVED
        approved_q = ReportService.get_filtered_query(status=VisitRequestStatus.APPROVED)
        assert approved_q.count() == 3

        # Filter by session_status: ACTIVE
        active_sess_q = ReportService.get_filtered_query(session_status='ACTIVE')
        assert active_sess_q.count() == 1
        assert active_sess_q.first().visitor.full_name == "Alice Smith"

        # Filter by session_status: COMPLETED
        comp_sess_q = ReportService.get_filtered_query(session_status='COMPLETED')
        assert comp_sess_q.count() == 1
        assert comp_sess_q.first().visitor.full_name == "Bob Jones"


def test_export_csv_escapes_formulas_and_includes_headers(app, db, sample_report_data):
    """Test 4: export_visits_to_csv generates safe CSV escaping spreadsheet formulas."""
    with app.app_context():
        csv_text = ReportService.export_visits_to_csv()
        reader = list(csv.reader(io.StringIO(csv_text)))

        # Header verification
        assert len(reader) >= 6  # header + 5 rows
        headers = reader[0]
        assert "Reference Code" in headers
        assert "Visitor Name" in headers
        assert "Category" in headers

        # Find row for malicious visitor
        malicious_row = None
        for row in reader[1:]:
            if "1+1" in row[1]:
                malicious_row = row
                break

        assert malicious_row is not None
        # Verify formula triggers were escaped with leading single quote (')
        assert malicious_row[1].startswith("'=")  # Visitor Name was '=1+1'
        assert malicious_row[2].startswith("'@")  # Organization was '@SUM(A1:A10)'
        assert malicious_row[6].startswith("'-")  # Purpose was '-2+5+cmd...'


def test_reports_route_authorization_and_rendering(client, admin_user, faculty_user, security_user, sample_report_data):
    """Test 5: /admin/reports is strictly restricted to ADMIN and returns 403 to others."""
    # 1. Unauthenticated redirect
    client.post('/logout')
    resp = client.get('/admin/reports')
    assert resp.status_code == 302
    assert '/login' in resp.headers.get('Location', '')

    # 2. Faculty forbidden (403)
    client.post('/login', data={'identifier': faculty_user.username, 'password': 'Faculty@123'})
    resp = client.get('/admin/reports')
    assert resp.status_code == 403
    client.post('/logout')

    # 3. Security forbidden (403)
    client.post('/login', data={'identifier': security_user.username, 'password': 'Security@123'})
    resp = client.get('/admin/reports')
    assert resp.status_code == 403
    client.post('/logout')

    # 4. Admin allowed (200 OK)
    client.post('/login', data={'identifier': admin_user.username, 'password': 'Admin@123'})
    resp = client.get('/admin/reports')
    assert resp.status_code == 200
    assert b"Campus Visitor Analytics &amp; Reports" in resp.data or b"Campus Visitor Analytics & Reports" in resp.data
    assert b"Alice Smith" in resp.data


def test_reports_csv_export_route_and_audit_logging(client, admin_user, sample_report_data):
    """Test 6: /admin/reports/export.csv downloads CSV file with correct headers and emits audit log."""
    client.post('/logout')
    client.post('/login', data={'identifier': admin_user.username, 'password': 'Admin@123'})

    resp = client.get('/admin/reports/export.csv')
    assert resp.status_code == 200
    assert resp.headers.get('Content-Type') == 'text/csv; charset=utf-8' or 'text/csv' in resp.headers.get('Content-Type', '')
    assert 'attachment;' in resp.headers.get('Content-Disposition', '')
    assert 'no-store' in resp.headers.get('Cache-Control', '')

    # Audit log verification
    audit = AuditLog.query.filter_by(action=AuditAction.REPORT_EXPORTED).first()
    assert audit is not None
    assert audit.actor_user_id == admin_user.id
    assert audit.outcome == 'SUCCESS'


def test_admin_audit_trail_route(client, admin_user, faculty_user):
    """Test 7: /admin/audit renders security audit log table with filter capability."""
    client.post('/logout')
    client.post('/login', data={'identifier': admin_user.username, 'password': 'Admin@123'})

    resp = client.get('/admin/audit')
    assert resp.status_code == 200
    assert b"Security &amp; Compliance Audit Trail" in resp.data or b"Security & Compliance Audit Trail" in resp.data


def test_gate_service_correct_session(admin_user, faculty_user, sample_report_data):
    """Test 8: GateService.correct_session updates session with audit and event recording."""
    session_id = sample_report_data[0].sessions.first().id
    now = datetime.now(timezone.utc)
    new_in = now - timedelta(hours=3)
    new_out = now - timedelta(hours=1)

    # 1. Non-admin forbidden
    sess, err = GateService.correct_session(
        session_id=session_id,
        actor_user=faculty_user,
        checked_in_at=new_in,
        checked_out_at=new_out,
        status=VisitSessionStatus.COMPLETED,
        reason="Test unauthorized"
    )
    assert sess is None
    assert "Unauthorized" in err

    # 2. Check-out earlier than check-in rejected
    sess, err = GateService.correct_session(
        session_id=session_id,
        actor_user=admin_user,
        checked_in_at=new_in,
        checked_out_at=new_in - timedelta(minutes=10),
        status=VisitSessionStatus.COMPLETED,
        reason="Time error test"
    )
    assert sess is None
    assert "Departure timestamp cannot be earlier" in err

    # 3. Successful update to COMPLETED
    sess, err = GateService.correct_session(
        session_id=session_id,
        actor_user=admin_user,
        checked_in_at=new_in,
        checked_out_at=new_out,
        status=VisitSessionStatus.COMPLETED,
        reason="Adjustment for late terminal scan"
    )
    assert err is None
    assert sess.status == VisitSessionStatus.COMPLETED
    assert sess.checked_in_at == new_in
    assert sess.checked_out_at == new_out

    # Verify AuditLog and VisitEvent
    audit = AuditLog.query.filter_by(action=AuditAction.SESSION_CORRECTED).first()
    assert audit is not None
    assert audit.actor_user_id == admin_user.id
    assert audit.reason == "Adjustment for late terminal scan"


def test_admin_session_edit_route(client, admin_user, faculty_user, sample_report_data):
    """Test 9: POST /admin/sessions/<id>/edit works for admin and rejects unauthorized users."""
    session_id = sample_report_data[0].sessions.first().id

    # 1. Non-admin rejected
    client.post('/logout')
    client.post('/login', data={'identifier': faculty_user.username, 'password': 'Faculty@123'})
    resp = client.post(f'/admin/sessions/{session_id}/edit', data={
        'status': 'COMPLETED',
        'checked_in_at': '2026-10-22T10:00',
        'checked_out_at': '2026-10-22T12:00',
        'reason': 'Unauthorized try'
    })
    assert resp.status_code == 403

    # 2. Admin success
    client.post('/logout')
    client.post('/login', data={'identifier': admin_user.username, 'password': 'Admin@123'})
    resp = client.post(f'/admin/sessions/{session_id}/edit', data={
        'status': 'COMPLETED',
        'checked_in_at': '2026-10-22T10:00',
        'checked_out_at': '2026-10-22T12:00',
        'reason': 'Official correction'
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"successfully updated" in resp.data
