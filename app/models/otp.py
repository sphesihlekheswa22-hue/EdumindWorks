"""OTP model for storing one-time passwords."""
from datetime import timedelta
from app import db
from app.utils.app_time import app_now, APP_TZ


class OTP(db.Model):
    """OTP model for storing one-time passwords with expiry."""
    __tablename__ = 'otps'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False, index=True)
    otp_code = db.Column(db.String(6), nullable=False)
    purpose = db.Column(db.String(20), nullable=False)  # 'registration' or 'password_reset'
    created_at = db.Column(db.DateTime, default=app_now)
    expires_at = db.Column(db.DateTime, nullable=False)
    is_used = db.Column(db.Boolean, default=False)
    
    def __init__(self, email, otp_code, purpose, expires_in_minutes=5):
        """Initialize OTP with email, code, and purpose."""
        self.email = email
        self.otp_code = otp_code
        self.purpose = purpose
        self.expires_at = app_now() + timedelta(minutes=expires_in_minutes)
    
    def is_expired(self):
        """Check if OTP has expired."""
        now = app_now()
        exp = self.expires_at
        # Postgres TIMESTAMPTZ columns return timezone-aware datetimes, while
        # the app uses naive "wall-clock" datetimes. Normalize for comparison.
        if getattr(exp, "tzinfo", None) is not None:
            exp = exp.astimezone(APP_TZ).replace(tzinfo=None)
        return now > exp
    
    def is_valid(self):
        """Check if OTP is valid (not used and not expired)."""
        return not self.is_used and not self.is_expired()
    
    def mark_as_used(self):
        """Mark OTP as used."""
        self.is_used = True
    
    @staticmethod
    def generate_otp_code():
        """Generate a 6-digit OTP code."""
        import random
        return str(random.randint(100000, 999999))
    
    @staticmethod
    def create_otp(email, purpose, expires_in_minutes=5):
        """Create a new OTP for the given email and purpose."""
        # Delete any existing unused OTPs for this email and purpose
        OTP.query.filter_by(
            email=email,
            purpose=purpose,
            is_used=False
        ).delete()
        
        # Generate new OTP
        otp_code = OTP.generate_otp_code()
        otp = OTP(
            email=email,
            otp_code=otp_code,
            purpose=purpose,
            expires_in_minutes=expires_in_minutes
        )
        db.session.add(otp)
        return otp
    
    @staticmethod
    def verify_otp(email, otp_code, purpose):
        """Verify an OTP code for the given email and purpose."""
        otp = OTP.query.filter_by(
            email=email,
            otp_code=otp_code,
            purpose=purpose,
            is_used=False
        ).first()
        
        if not otp:
            return None
        
        if otp.is_expired():
            return None
        
        return otp
    
    def __repr__(self):
        return f'<OTP {self.email} ({self.purpose})>'
