import logging
from functools import wraps

from flask import abort, g

logger = logging.getLogger(__name__)


def get_store_by_line_user_id(db_session, line_user_id: str):
    from app.models.store import Store

    return db_session.query(Store).filter_by(
        line_user_id=line_user_id,
        is_active=True,
    ).first()


def require_registered_store(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not getattr(g, "line_user_id", None):
            logger.error("store_authz: line_user_id が g にセットされていない")
            abort(500)

        from app.extensions import db
        store = get_store_by_line_user_id(db.session, g.line_user_id)

        if store is None:
            g.store = None
            g.is_registered = False
        else:
            g.store = store
            g.is_registered = True

        return f(*args, **kwargs)

    return decorated


def assert_store_owns_resource(store_id: int, resource_store_id: int):
    if store_id != resource_store_id:
        logger.warning(
            "他店リソースへのアクセス試行 | 要求店舗=%s リソース所有店舗=%s",
            store_id,
            resource_store_id,
        )
        abort(403)