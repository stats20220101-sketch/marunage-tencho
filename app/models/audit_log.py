from datetime import datetime
from app.extensions import db


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    store_id = db.Column(db.Integer, db.ForeignKey("stores.id"), nullable=True, index=True)
    action = db.Column(db.String(128), nullable=False)
    actor = db.Column(db.String(128), nullable=False)
    result = db.Column(db.String(32), nullable=False)
    detail_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<AuditLog action={self.action} result={self.result}>"