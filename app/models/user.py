from datetime import timedelta
from flask_login import UserMixin
from app import db, bcrypt
from app.utils.app_time import app_now


class User(db.Model, UserMixin):
    """User model for authentication and base user information."""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(128), nullable=False)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # student, lecturer, admin, career_advisor
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=app_now)
    updated_at = db.Column(db.DateTime, default=app_now, onupdate=app_now)
    
    # Notification tracking
    last_notification_read = db.Column(db.DateTime, nullable=True)
    
    # Email/password recovery is disabled in this deployment.
    # (Database columns may still exist from earlier versions; they are intentionally unused.)
    reset_token = db.Column(db.String(100), nullable=True)
    reset_token_expires_at = db.Column(db.DateTime, nullable=True)
    email_verified = db.Column(db.Boolean, default=True)
    email_verification_token = db.Column(db.String(100), nullable=True)
    email_verification_expires_at = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    student = db.relationship('Student', backref='user', uselist=False, lazy=True, cascade="all, delete-orphan")
    lecturer = db.relationship('Lecturer', back_populates='user', uselist=False, lazy=True, cascade="all, delete-orphan")
    
    def unread_notifications_count(self):
        """Get count of unread notifications"""
        from app.models.notification import Notification
        return Notification.query.filter_by(recipient_id=self.id, is_read=False).count()
    
    def get_recent_notifications(self, limit=10):
        """Get recent notifications for dropdown"""
        from app.models.notification import Notification
        return Notification.query.filter_by(recipient_id=self.id).order_by(Notification.created_at.desc()).limit(limit).all()
    
    def add_notification(
        self,
        type,
        title,
        message,
        priority='normal',
        sender=None,
        action_url=None,
        action_text=None,
        entity_type=None,
        entity_id=None,
        metadata=None,
    ):
        """Helper to create notification"""
        from app.models.notification import Notification
        import json
        notif = Notification(
            recipient_id=self.id,
            sender_id=sender.id if sender else None,
            type=type,
            title=title,
            message=message,
            priority=priority,
            action_url=action_url,
            action_text=action_text,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata_json=json.dumps(metadata) if metadata else None
        )
        db.session.add(notif)
        return notif
    
    def set_password(self, password):
        """Hash and set the user password."""
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')
    
    def check_password(self, password):
        """Verify the password."""
        return bcrypt.check_password_hash(self.password_hash, password)
    
    # Legacy methods for email verification / password reset were removed.
    
    @property
    def full_name(self):
        """Return the user's full name."""
        return f"{self.first_name} {self.last_name}"
    
    @full_name.setter
    def full_name(self, name):
        """Set the user's first and last name from a full name."""
        parts = name.split(' ', 1)
        self.first_name = parts[0]
        self.last_name = parts[1] if len(parts) > 1 else ''
        return f'<User {self.email} ({self.role})>'
    
    def to_dict(self):
        """Convert user to dictionary."""
        return {
            'id': self.id,
            'email': self.email,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'full_name': self.full_name,
            'role': self.role,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }