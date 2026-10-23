import re
from datetime import datetime, timedelta, timezone
from sqlalchemy import or_, func
from app.extensions import db
from app.models.visitor import Visitor
from app.models.visit import VisitRequest, VisitRequestStatus


class DuplicateRiskLevel:
    EXACT_DUPLICATE = 'EXACT_DUPLICATE'
    HIGH_CONFIDENCE_DUPLICATE = 'HIGH_CONFIDENCE_DUPLICATE'
    POSSIBLE_DUPLICATE = 'POSSIBLE_DUPLICATE'
    SUSPICIOUS = 'SUSPICIOUS'
    NONE = 'NONE'


class DuplicateService:
    @staticmethod
    def normalize_phone(phone: str | None) -> str:
        """Strips non-digits and canonicalizes standard 10/11-digit phone numbers."""
        if not phone:
            return ""
        digits = re.sub(r'\D', '', str(phone))
        if len(digits) == 11 and digits.startswith('1'):
            digits = digits[1:]
        return digits

    @staticmethod
    def normalize_email(email: str | None) -> str:
        """Trims whitespace and lowercases email."""
        if not email:
            return ""
        return str(email).strip().lower()

    @staticmethod
    def evaluate_registration(
        phone: str | None,
        email: str | None,
        full_name: str | None = None,
        planned_start_at: datetime | None = None,
        host_user_id: int | None = None,
        window_hours: int = 24
    ) -> dict:
        """
        Evaluates a visitor registration against existing records using a 4-tier risk policy:
        1. SUSPICIOUS: Prior rejection within 7 days or high submission velocity (>=3 in 24h).
        2. HIGH_CONFIDENCE_DUPLICATE / EXACT_DUPLICATE: Both phone & email match an active/pending visit within window.
        3. POSSIBLE_DUPLICATE: Phone OR email matches an active/pending visit within window.
        4. NONE: No risk indicators or scheduled outside time window.

        Guarantees:
        - Non-blocking (does not reject submissions outright).
        - Privacy-safe (reasons for audit log and staff; never exposed directly to external visitors).
        - Returns structured metadata: { 'risk_level', 'is_flagged', 'reason', 'matched_reference' }.
        """
        norm_phone = DuplicateService.normalize_phone(phone)
        norm_email = DuplicateService.normalize_email(email)
        clean_name = (full_name or '').strip().lower()

        if not norm_phone and not norm_email:
            return {
                'risk_level': DuplicateRiskLevel.NONE,
                'is_flagged': False,
                'reason': None,
                'matched_reference': None
            }

        now_utc = datetime.now(timezone.utc)
        ref_time = planned_start_at or now_utc
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)

        # Build contact filter
        contact_clauses = []
        if norm_phone:
            contact_clauses.append(Visitor.normalized_phone == norm_phone)
        if norm_email:
            contact_clauses.append(func.lower(Visitor.email) == norm_email)

        # ============================================================
        # Tier 1: Check Suspicious Indicators
        # ============================================================
        # 1a. Recent rejection within 7 days
        seven_days_ago = now_utc - timedelta(days=7)
        rejected_match = db.session.query(VisitRequest, Visitor).join(
            Visitor, VisitRequest.visitor_id == Visitor.id
        ).filter(
            VisitRequest.status == VisitRequestStatus.REJECTED,
            or_(*contact_clauses),
            VisitRequest.created_at >= seven_days_ago
        ).order_by(VisitRequest.created_at.desc()).first()

        if rejected_match:
            req, vis = rejected_match
            reason = f"Suspicious: Visitor has a previously rejected registration request within the last 7 days ({req.public_reference})"
            return {
                'risk_level': DuplicateRiskLevel.SUSPICIOUS,
                'is_flagged': True,
                'reason': reason,
                'matched_reference': req.public_reference
            }

        # 1b. Submission velocity / flooding check (>= 3 submissions in 24 hours)
        one_day_ago = now_utc - timedelta(hours=24)
        recent_count = db.session.query(VisitRequest).join(
            Visitor, VisitRequest.visitor_id == Visitor.id
        ).filter(
            or_(*contact_clauses),
            VisitRequest.created_at >= one_day_ago
        ).count()

        if recent_count >= 3:
            reason = f"Suspicious: High registration velocity detected ({recent_count} submissions in 24 hours)"
            return {
                'risk_level': DuplicateRiskLevel.SUSPICIOUS,
                'is_flagged': True,
                'reason': reason,
                'matched_reference': None
            }

        # ============================================================
        # Tier 2 & 3: Match Active/Pending Visit Requests
        # ============================================================
        start_window = ref_time - timedelta(hours=window_hours)
        end_window = ref_time + timedelta(hours=window_hours)
        active_statuses = [VisitRequestStatus.PENDING_APPROVAL, VisitRequestStatus.APPROVED]

        query = db.session.query(VisitRequest, Visitor).join(
            Visitor, VisitRequest.visitor_id == Visitor.id
        ).filter(
            VisitRequest.status.in_(active_statuses),
            or_(*contact_clauses),
            or_(
                VisitRequest.planned_start_at.between(start_window, end_window),
                VisitRequest.planned_start_at.is_(None)
            )
        ).order_by(VisitRequest.created_at.desc())

        matches = query.all()
        if matches:
            for req, vis in matches:
                phone_matched = norm_phone and vis.normalized_phone == norm_phone
                email_matched = norm_email and vis.email and vis.email.lower() == norm_email
                name_matched = clean_name and vis.full_name and vis.full_name.strip().lower() == clean_name

                # Tier 2: Exact / High-Confidence Duplicate (both phone and email match, or name + phone match)
                if (phone_matched and email_matched) or (name_matched and phone_matched):
                    matched_parts = []
                    if phone_matched:
                        matched_parts.append("phone")
                    if email_matched:
                        matched_parts.append("email")
                    if name_matched:
                        matched_parts.append("name")

                    reason = f"High-confidence duplicate of {req.public_reference} ({', '.join(matched_parts)} match within {window_hours}h window)"
                    return {
                        'risk_level': DuplicateRiskLevel.HIGH_CONFIDENCE_DUPLICATE,
                        'is_flagged': True,
                        'reason': reason,
                        'matched_reference': req.public_reference
                    }

            # Tier 3: Possible Duplicate (single field matched)
            req, vis = matches[0]
            matched_parts = []
            if norm_phone and vis.normalized_phone == norm_phone:
                matched_parts.append("phone match")
            if norm_email and vis.email and vis.email.lower() == norm_email:
                matched_parts.append("email match")

            reason = f"Potential duplicate of {req.public_reference} ({', '.join(matched_parts)} within {window_hours}h window)"
            return {
                'risk_level': DuplicateRiskLevel.POSSIBLE_DUPLICATE,
                'is_flagged': True,
                'reason': reason,
                'matched_reference': req.public_reference
            }

        # ============================================================
        # Tier 4: No detected duplicate or risk indicator
        # ============================================================
        return {
            'risk_level': DuplicateRiskLevel.NONE,
            'is_flagged': False,
            'reason': None,
            'matched_reference': None
        }

    @staticmethod
    def check_duplicate(
        phone: str | None,
        email: str | None,
        planned_start_at: datetime | None = None,
        host_user_id: int | None = None,
        window_hours: int = 24
    ) -> tuple[bool, str | None]:
        """
        Backward compatible duplicate visitor check.
        Delegates to evaluate_registration and returns (is_flagged, reason).
        """
        eval_result = DuplicateService.evaluate_registration(
            phone=phone,
            email=email,
            planned_start_at=planned_start_at,
            host_user_id=host_user_id,
            window_hours=window_hours
        )
        return eval_result['is_flagged'], eval_result['reason']
