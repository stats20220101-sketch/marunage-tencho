from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def init_extensions(app):
    db_url = app.config.get("DATABASE_URL", "")

    # Supabase / Heroku は "postgres://" を返すが SQLAlchemy 2.x は "postgresql://" を要求する
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)