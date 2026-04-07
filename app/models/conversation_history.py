from datetime import datetime
from app.extensions import db


class ConversationHistory(db.Model):
    """
    AIフリートーク・経営相談の会話履歴。

    将来の最適化に向けた設計:
    - created_at にインデックスを張り、直近Nヶ月フィルタに対応済み
    - 現在はフル履歴を使用。移行時は _load_history() 内の
      コメントアウトされたフィルタを有効化するだけで切り替え可能。
    """

    __tablename__ = "conversation_history"

    id = db.Column(db.Integer, primary_key=True)
    store_id = db.Column(
        db.Integer, db.ForeignKey("stores.id"), nullable=False, index=True
    )
    line_user_id = db.Column(db.String(64), nullable=False, index=True)
    role = db.Column(db.String(16), nullable=False)   # "user" | "assistant"
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False,
        index=True,   # 直近3ヶ月フィルタへの移行時に使用
    )

    store = db.relationship("Store", backref="conversation_history")

    def __repr__(self):
        return (
            f"<ConversationHistory id={self.id} "
            f"store_id={self.store_id} role={self.role}>"
        )
