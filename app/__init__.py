import logging
import sys
import os

from flask import Flask

from app.config import get_config


def create_app() -> Flask:
    app = Flask(__name__)

    config = get_config()
    app.config.from_object(config)

    if os.environ.get("FLASK_ENV") == "production":
        config.validate()

    _configure_logging(app)

    from app.extensions import init_extensions
    init_extensions(app)

    from app.models import Store, ConversationSession, AuditLog, ConversationHistory  # noqa: F401

    from app.webhooks.line_handler import line_bp
    app.register_blueprint(line_bp)

    @app.get("/health")
    def health():
        return {"status": "ok"}, 200

    with app.app_context():
        from app.extensions import db
        db.create_all()

    _start_scheduler(app)

    app.logger.info("アプリケーション起動完了 | env=%s", os.environ.get("FLASK_ENV"))
    return app


def _start_scheduler(app: Flask):
    """APScheduler で月次レポートの自動送信を設定する。"""
    # テスト実行時はスケジューラーを起動しない
    if app.config.get("TESTING"):
        return

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from app.tasks.monthly_report_task import send_monthly_reports

    scheduler = BackgroundScheduler(timezone="Asia/Tokyo")
    scheduler.add_job(
        func=send_monthly_reports,
        trigger=CronTrigger(day=1, hour=0, minute=0, timezone="Asia/Tokyo"),
        args=[app],
        id="monthly_report",
        replace_existing=True,
    )
    scheduler.start()
    app.logger.info("月次レポートスケジューラー起動 | 毎月1日 0:00 JST")


def _configure_logging(app: Flask):
    level = logging.DEBUG if app.config.get("DEBUG") else logging.INFO

    logging.basicConfig(
        stream=sys.stdout,
        level=level,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        force=True,  # 既存ハンドラを上書き（gunicorn配下で重複設定を防止）
    )

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("googleapiclient").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)