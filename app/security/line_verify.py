import hashlib
import hmac
import base64
import logging
from functools import wraps

from flask import request, abort, current_app

logger = logging.getLogger(__name__)


def verify_line_signature(channel_secret: str, body: bytes, signature: str) -> bool:
    expected = base64.b64encode(
        hmac.new(
            channel_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).digest()
    ).decode("utf-8")

    return hmac.compare_digest(expected, signature)


def require_line_signature(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        signature = request.headers.get("X-Line-Signature")

        if not signature:
            logger.warning(
                "LINE署名ヘッダーなし | ip=%s path=%s",
                request.remote_addr,
                request.path,
            )
            abort(403)

        body = request.get_data()
        channel_secret = current_app.config["LINE_CHANNEL_SECRET"]

        if not verify_line_signature(channel_secret, body, signature):
            logger.warning(
                "LINE署名検証失敗 | ip=%s",
                request.remote_addr,
            )
            abort(403)

        return f(*args, **kwargs)

    return decorated