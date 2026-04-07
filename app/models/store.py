from datetime import datetime
from app.extensions import db


class Store(db.Model):
    __tablename__ = "stores"

    id = db.Column(db.Integer, primary_key=True)
    line_user_id = db.Column(db.String(64), nullable=False, index=True)
    name = db.Column(db.String(128), nullable=False)
    email = db.Column(db.String(256), nullable=True)
    drive_folder_id = db.Column(db.String(128), nullable=True)
    google_email = db.Column(db.String(256), nullable=True)   # Google Drive 共有先メール
    style_guide_json = db.Column(db.Text, nullable=True)
    ai_consent_agreed_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Store id={self.id} name={self.name}>"