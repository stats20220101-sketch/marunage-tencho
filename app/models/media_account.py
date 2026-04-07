from datetime import datetime
from app.extensions import db


class MediaAccount(db.Model):
    __tablename__ = "media_accounts"

    id = db.Column(db.Integer, primary_key=True)
    store_id = db.Column(db.Integer, db.ForeignKey("stores.id"), nullable=False, index=True)
    media_type = db.Column(db.String(32), nullable=False)
    # hotpepper / tabelog / gurunavi / google / instagram
    url = db.Column(db.String(512), nullable=True)
    monthly_fee = db.Column(db.Integer, nullable=True)  # 円
    is_active = db.Column(db.Boolean, default=True, nullable=False)