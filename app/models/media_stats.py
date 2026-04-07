from datetime import datetime
from app.extensions import db


class MediaStats(db.Model):
    __tablename__ = "media_stats"

    id = db.Column(db.Integer, primary_key=True)
    store_id = db.Column(db.Integer, db.ForeignKey("stores.id"), nullable=False, index=True)
    media_type = db.Column(db.String(32), nullable=False)
    year_month = db.Column(db.String(7), nullable=False)   # 例: "2026-03"
    access_count = db.Column(db.Integer, nullable=True)    # アクセス数
    reservation_count = db.Column(db.Integer, nullable=True)  # 予約数
    sales_amount = db.Column(db.Integer, nullable=True)    # 売上（円）
    ad_cost = db.Column(db.Integer, nullable=True)         # 広告費（円）
    raw_data_json = db.Column(db.Text, nullable=True)      # AIが読み取った生データ
    source_type = db.Column(db.String(32), nullable=True)  # screenshot/pdf/excel
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    store = db.relationship("Store", backref="media_stats")

    def __repr__(self):
        return f"<MediaStats store_id={self.store_id} media={self.media_type} month={self.year_month}>"