from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def init_extensions(app):
    db_url = app.config.get("DATABASE_URL", "")

    # Supabase / Heroku は "postgres://" を返すが SQLAlchemy 2.x は "postgresql://" を要求する
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Render無料プランのspin-down対策：
    # 接続腐敗（SSL decryption failed等）を防ぐため利用前に必ずping。
    # pool_recycle で古い接続も定期的に破棄する。
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 280,  # 秒。Renderのアイドル切断より短めに設定
    }

    db.init_app(app)