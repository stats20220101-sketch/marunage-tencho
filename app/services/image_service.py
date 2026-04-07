import logging
import requests
from flask import current_app

logger = logging.getLogger(__name__)

# 許可する画像タイプ
ALLOWED_MIME_TYPES = {
    "image/jpeg": "image/jpeg",
    "image/png": "image/png",
    "image/gif": "image/gif",
    "image/webp": "image/webp",
}

# 最大ファイルサイズ（5MB）
MAX_FILE_SIZE = 5 * 1024 * 1024


def download_line_image(message_id: str) -> tuple[bytes, str]:
    """
    LINEから画像をダウンロードする。

    Args:
        message_id: LINEメッセージID

    Returns:
        (画像データ, MIMEタイプ)
    """
    access_token = current_app.config["LINE_CHANNEL_ACCESS_TOKEN"]
    url = f"https://api-data.line.me/v2/bot/message/{message_id}/content"

    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        # ファイルサイズチェック
        content = response.content
        if len(content) > MAX_FILE_SIZE:
            raise ValueError(f"ファイルサイズが大きすぎます（最大5MB）")

        # MIMEタイプチェック
        content_type = response.headers.get("Content-Type", "image/jpeg")
        mime_type = content_type.split(";")[0].strip()

        if mime_type not in ALLOWED_MIME_TYPES:
            raise ValueError(f"許可されていないファイル形式です: {mime_type}")

        logger.info("画像ダウンロード完了 | message_id=%s size=%d", message_id, len(content))
        return content, ALLOWED_MIME_TYPES[mime_type]

    except requests.RequestException as e:
        logger.error("画像ダウンロード失敗: %s", e)
        raise