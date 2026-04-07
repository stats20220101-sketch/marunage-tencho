from datetime import datetime
from app.extensions import db


class ConversationSession(db.Model):
    __tablename__ = "conversation_sessions"

    id = db.Column(db.Integer, primary_key=True)
    store_id = db.Column(db.Integer, db.ForeignKey("stores.id"), nullable=False, index=True)
    state = db.Column(db.String(64), nullable=False, default="initial")
    context_json = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    store = db.relationship("Store", backref="sessions")

    def __repr__(self):
        return f"<Session store_id={self.store_id} state={self.state}>"