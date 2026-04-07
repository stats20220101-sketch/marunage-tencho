"""
月次レポートの自動送信タスク（APScheduler cron）。

毎月1日 0:00 JST に全アクティブ店舗へ前月レポートを送信する。
"""

import logging

logger = logging.getLogger(__name__)


def send_monthly_reports(app):
    """
    全アクティブ店舗に月次レポートを送信する。
    APScheduler から app インスタンスを受け取って app_context 内で実行する。
    """
    from app.models.store import Store
    from app.extensions import db
    from app.services.report_service import generate_monthly_report, _prev_month
    from app.webhooks.line_handler import _push_text

    with app.app_context():
        year, month = _prev_month()
        stores = db.session.query(Store).filter_by(is_active=True).all()

        logger.info("月次レポート自動送信開始 | month=%d-%02d 対象店舗数=%d", year, month, len(stores))

        for store in stores:
            try:
                line_text = generate_monthly_report(store, year, month)
                _push_text(store.line_user_id, line_text)
                logger.info("月次レポート送信完了 | store_id=%s", store.id)
            except Exception as e:
                logger.error("月次レポート送信失敗 | store_id=%s error=%s", store.id, e)
