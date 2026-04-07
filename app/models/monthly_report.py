from datetime import datetime
from app.extensions import db


class MonthlyReport(db.Model):
    __tablename__ = "monthly_reports"

    id = db.Column(db.Integer, primary_key=True)
    store_id = db.Column(db.Integer, db.ForeignKey("stores.id"), nullable=False, index=True)
    year_month = db.Column(db.String(7), nullable=False)  # 例: "2026-03"
    report_json = db.Column(db.Text, nullable=True)        # AIのレポート内容
    advice_json = db.Column(db.Text, nullable=True)        # AIのアドバイス
    total_ad_cost = db.Column(db.Integer, nullable=True)   # 合計広告費（円）
    status = db.Column(db.String(32), default="draft")     # draft / completed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    store = db.relationship("Store", backref="monthly_reports")

    def __repr__(self):
        return f"<MonthlyReport store_id={self.store_id} month={self.year_month}>"