from app import db


class StaffProfile(db.Model):
    """Staff identifier for non-lecturer staff (admin, career advisor, etc.)."""
    __tablename__ = "staff_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True, index=True)
    staff_number = db.Column(db.String(20), nullable=False, unique=True, index=True)

    user = db.relationship("User", backref=db.backref("staff_profile", uselist=False, lazy=True, cascade="all, delete-orphan"))

    def __repr__(self):
        return f"<StaffProfile {self.staff_number}>"

