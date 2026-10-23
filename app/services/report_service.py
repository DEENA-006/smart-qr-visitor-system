import csv
import io
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple
from sqlalchemy import func, or_
from app.extensions import db
from app.models.visit import (
    VisitRequest,
    VisitRequestStatus,
    VisitSession,
    VisitSessionStatus
)
from app.models.visitor import Visitor
from app.models.user import User
from app.models.visit_type import VisitType

logger = logging.getLogger(__name__)


def sanitize_csv_cell(value: Any) -> str:
    """
    Mitigates spreadsheet formula injection (CSV injection).
    If a cell value starts with '=', '+', '-', '@', '\t', or '\r',
    it is prepended with a single quote (') so spreadsheet engines
    treat it as raw text rather than an executable formula or command.
    """
    if value is None:
        return ""
    str_val = str(value)
    if str_val and str_val[0] in ('=', '+', '-', '@', '\t', '\r'):
        return f"'{str_val}"
    return str_val


class ReportService:
    """Service handling metrics aggregation, visit filtering, and safe CSV exports."""

    @staticmethod
    def parse_date(date_str: Optional[str]) -> Optional[datetime]:
        """Safely parses date string in YYYY-MM-DD or ISO format into timezone-aware UTC datetime."""
        if not date_str:
            return None
        cleaned = date_str.strip()
        try:
            # Handle YYYY-MM-DD
            dt = datetime.strptime(cleaned[:10], '%Y-%m-%d')
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            try:
                dt = datetime.fromisoformat(cleaned)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except Exception:
                logger.warning("Invalid date format received for report filter: %s", date_str)
                return None

    @staticmethod
    def get_summary_metrics(
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        visit_type: Optional[str] = None,
        host_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Calculates authoritative operational metrics from database records without double counting.
        """
        query = VisitRequest.query

        if start_date:
            query = query.filter(VisitRequest.submitted_at >= start_date)
        if end_date:
            # End of specified day
            query = query.filter(VisitRequest.submitted_at <= end_date + timedelta(days=1))
        if visit_type:
            query = query.filter(VisitRequest.visit_type == visit_type)
        if host_id:
            query = query.filter(VisitRequest.host_user_id == host_id)

        total_requests = query.count()
        pending_requests = query.filter(VisitRequest.status == VisitRequestStatus.PENDING_APPROVAL).count()
        approved_visits = query.filter(VisitRequest.status == VisitRequestStatus.APPROVED).count()
        rejected_visits = query.filter(VisitRequest.status == VisitRequestStatus.REJECTED).count()

        # Session metrics
        sess_query = db.session.query(VisitSession).join(VisitRequest, VisitSession.visit_request_id == VisitRequest.id)
        if start_date:
            sess_query = sess_query.filter(VisitSession.checked_in_at >= start_date)
        if end_date:
            sess_query = sess_query.filter(VisitSession.checked_in_at <= end_date + timedelta(days=1))
        if visit_type:
            sess_query = sess_query.filter(VisitRequest.visit_type == visit_type)
        if host_id:
            sess_query = sess_query.filter(VisitRequest.host_user_id == host_id)

        total_checked_in = sess_query.count()
        currently_on_campus = sess_query.filter(VisitSession.status == VisitSessionStatus.ACTIVE).count()
        completed_visits = sess_query.filter(VisitSession.status == VisitSessionStatus.COMPLETED).count()

        # Unchecked-out / Overstay: active sessions older than 12 hours or past planned end
        now_utc = datetime.now(timezone.utc)
        twelve_hours_ago = now_utc - timedelta(hours=12)
        overstay_visitors = sess_query.filter(
            VisitSession.status == VisitSessionStatus.ACTIVE,
            VisitSession.checked_in_at < twelve_hours_ago
        ).count()

        # Category breakdown
        category_rows = db.session.query(
            VisitRequest.visit_type,
            func.count(VisitRequest.id)
        )
        if start_date:
            category_rows = category_rows.filter(VisitRequest.submitted_at >= start_date)
        if end_date:
            category_rows = category_rows.filter(VisitRequest.submitted_at <= end_date + timedelta(days=1))
        if host_id:
            category_rows = category_rows.filter(VisitRequest.host_user_id == host_id)
        category_counts = dict(category_rows.group_by(VisitRequest.visit_type).all())

        return {
            'total_requests': total_requests,
            'pending_requests': pending_requests,
            'approved_visits': approved_visits,
            'rejected_visits': rejected_visits,
            'total_checked_in': total_checked_in,
            'currently_on_campus': currently_on_campus,
            'completed_visits': completed_visits,
            'overstay_visitors': overstay_visitors,
            'category_counts': category_counts
        }

    @staticmethod
    def get_filtered_query(
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        status: Optional[str] = None,
        visit_type: Optional[str] = None,
        host_id: Optional[int] = None,
        session_status: Optional[str] = None
    ):
        """Constructs safe SQLAlchemy query for filtered visit requests."""
        query = VisitRequest.query

        if start_date:
            query = query.filter(VisitRequest.submitted_at >= start_date)
        if end_date:
            query = query.filter(VisitRequest.submitted_at <= end_date + timedelta(days=1))
        if status and status in VisitRequestStatus.ALL:
            query = query.filter(VisitRequest.status == status)
        if visit_type:
            query = query.filter(VisitRequest.visit_type == visit_type)
        if host_id:
            query = query.filter(VisitRequest.host_user_id == host_id)

        if session_status:
            if session_status == 'ACTIVE':
                query = query.join(VisitSession, VisitRequest.id == VisitSession.visit_request_id).filter(
                    VisitSession.status == VisitSessionStatus.ACTIVE
                )
            elif session_status == 'COMPLETED':
                query = query.join(VisitSession, VisitRequest.id == VisitSession.visit_request_id).filter(
                    VisitSession.status == VisitSessionStatus.COMPLETED
                )
            elif session_status == 'NOT_ADMITTED':
                query = query.filter(~VisitRequest.sessions.any())

        return query.order_by(VisitRequest.submitted_at.desc())

    @staticmethod
    def export_visits_to_csv(
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        status: Optional[str] = None,
        visit_type: Optional[str] = None,
        host_id: Optional[int] = None,
        session_status: Optional[str] = None
    ) -> str:
        """
        Exports filtered visits to a sanitised CSV string.
        All cell values are passed through sanitize_csv_cell to prevent formula injection.
        """
        query = ReportService.get_filtered_query(
            start_date=start_date,
            end_date=end_date,
            status=status,
            visit_type=visit_type,
            host_id=host_id,
            session_status=session_status
        )

        records = query.all()

        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

        # Header row
        headers = [
            "Reference Code",
            "Visitor Name",
            "Organization",
            "Category",
            "Host Staff",
            "Host Department",
            "Visit Purpose",
            "Request Status",
            "Submitted (UTC)",
            "Approved (UTC)",
            "Active Session Status",
            "Check-In (UTC)",
            "Check-Out (UTC)"
        ]
        writer.writerow([sanitize_csv_cell(h) for h in headers])

        for req in records:
            # Determine latest session
            latest_sess = req.sessions.first()

            row = [
                sanitize_csv_cell(req.public_reference),
                sanitize_csv_cell(req.visitor.full_name if req.visitor else "Unknown"),
                sanitize_csv_cell(req.visitor.organization if (req.visitor and req.visitor.organization) else ""),
                sanitize_csv_cell(req.visit_type),
                sanitize_csv_cell(req.host_user.full_name if req.host_user else "General Desk"),
                sanitize_csv_cell(req.department or (req.host_user.department if req.host_user else "")),
                sanitize_csv_cell(req.purpose),
                sanitize_csv_cell(req.status),
                sanitize_csv_cell(req.submitted_at.strftime('%Y-%m-%d %H:%M:%S') if req.submitted_at else ""),
                sanitize_csv_cell(req.approved_at.strftime('%Y-%m-%d %H:%M:%S') if req.approved_at else ""),
                sanitize_csv_cell(latest_sess.status if latest_sess else "NOT_ADMITTED"),
                sanitize_csv_cell(latest_sess.checked_in_at.strftime('%Y-%m-%d %H:%M:%S') if (latest_sess and latest_sess.checked_in_at) else ""),
                sanitize_csv_cell(latest_sess.checked_out_at.strftime('%Y-%m-%d %H:%M:%S') if (latest_sess and latest_sess.checked_out_at) else "")
            ]
            writer.writerow(row)

        return output.getvalue()
