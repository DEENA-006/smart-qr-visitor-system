from datetime import datetime, timezone
from sqlalchemy import TypeDecorator, DateTime


class UTCDateTime(TypeDecorator):
    """
    SQLAlchemy TypeDecorator for timezone-aware UTC datetimes.
    
    Guarantees:
    - Datetimes sent to the database are normalized to UTC and stored without offset
      (standard storage across SQLite and SQL engines).
    - Datetimes retrieved from the database (especially SQLite, which strips tzinfo)
      are always returned with tzinfo=timezone.utc.
    """
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError(f"Expected datetime object, got {type(value).__name__}")
        if value.tzinfo is None:
            # Treat naive datetime as UTC
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        # Store as naive UTC in database
        return value.replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        # When read from database, ensure timezone.utc is attached
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
