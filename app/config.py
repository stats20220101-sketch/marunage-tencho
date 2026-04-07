import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY")
    DEBUG = False
    TESTING = False

    LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
    LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")

    DATABASE_URL = os.environ.get("DATABASE_URL")

    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
    GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI")
    GOOGLE_DRIVE_ROOT_FOLDER_ID = os.environ.get("GOOGLE_DRIVE_ROOT_FOLDER_ID")
    GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")

    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

    SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY")
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL")

    ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY")

    IMAGE_TEMP_RETENTION_DAYS = 30

    REQUIRED_VARS = [
        "SECRET_KEY",
        "LINE_CHANNEL_SECRET",
        "LINE_CHANNEL_ACCESS_TOKEN",
        "DATABASE_URL",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "ANTHROPIC_API_KEY",
        "SENDGRID_API_KEY",
        "ADMIN_EMAIL",
        "ENCRYPTION_KEY",
    ]

    @classmethod
    def validate(cls):
        missing = [var for var in cls.REQUIRED_VARS if not os.environ.get(var)]
        if missing:
            raise EnvironmentError(
                f"必須環境変数が未設定です: {', '.join(missing)}"
            )


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
}


def get_config():
    env = os.environ.get("FLASK_ENV", "development")
    return config_map.get(env, DevelopmentConfig)