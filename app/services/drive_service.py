import io
import json
import logging
from datetime import datetime

from flask import current_app
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from app.security.store_authz import assert_store_owns_resource

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/drive"]
_ROOT_FOLDER_NAME = "store-support"


def _build_drive_service():
    """サービスアカウント認証でDrive APIクライアントを構築する。"""
    sa_json = current_app.config.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON が未設定です")

    sa_info = json.loads(sa_json)
    credentials = service_account.Credentials.from_service_account_info(
        sa_info, scopes=_SCOPES
    )
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _get_or_create_folder(service, name: str, parent_id: str | None = None) -> str:
    """指定した名前のフォルダを取得、なければ作成してIDを返す。"""
    # フォルダ名にシングルクォートが含まれる場合はエスケープ
    escaped_name = name.replace("'", "\\'")
    query = (
        f"name = '{escaped_name}'"
        " and mimeType = 'application/vnd.google-apps.folder'"
        " and trashed = false"
    )
    if parent_id:
        query += f" and '{parent_id}' in parents"

    results = (
        service.files()
        .list(
            q=query,
            fields="files(id, name)",
            pageSize=1,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )

    files = results.get("files", [])
    if files:
        return files[0]["id"]

    metadata: dict = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]

    folder = service.files().create(body=metadata, fields="id", supportsAllDrives=True).execute()
    folder_id: str = folder["id"]
    logger.info("Driveフォルダ作成 | name=%s parent=%s id=%s", name, parent_id, folder_id)
    return folder_id


def ensure_store_folder(store) -> str:
    """
    店舗用のDriveフォルダを確保し、フォルダIDを返す。

    store.drive_folder_id が未設定の場合は新規作成してDBに永続化する。
    フォルダ構造: {GOOGLE_DRIVE_ROOT_FOLDER_ID}/{store.id}_{store.name}/

    GOOGLE_DRIVE_ROOT_FOLDER_ID が設定されている場合はそのフォルダを使用する。
    未設定の場合は "store-support" という名前のフォルダを検索・作成する。

    Args:
        store: 認可済みの Store モデルインスタンス

    Returns:
        店舗のDriveフォルダID
    """
    if store.drive_folder_id:
        return store.drive_folder_id

    service = _build_drive_service()

    configured_root = current_app.config.get("GOOGLE_DRIVE_ROOT_FOLDER_ID")
    if configured_root:
        root_id = configured_root
    else:
        root_id = _get_or_create_folder(service, _ROOT_FOLDER_NAME)

    # フォルダ名: "{store.id}_{store.name}" で一意性を保証
    folder_name = f"{store.id}_{store.name}"
    folder_id = _get_or_create_folder(service, folder_name, parent_id=root_id)

    from app.extensions import db

    store.drive_folder_id = folder_id
    db.session.commit()

    logger.info("店舗Driveフォルダ確保 | store_id=%s folder_id=%s", store.id, folder_id)
    return folder_id


def upload_image(
    requesting_store_id: int,
    target_store,
    image_data: bytes,
    filename: str,
    mime_type: str = "image/jpeg",
) -> str:
    """
    店舗のDriveフォルダに画像をアップロードする。

    店舗単位の認可チェックを行い、requesting_store_id と target_store.id が
    一致しない場合は 403 を返す。

    Args:
        requesting_store_id: リクエスト元の店舗ID（認可チェックに使用）
        target_store: アップロード先の Store モデルインスタンス
        image_data: 画像のバイトデータ
        filename: 元のファイル名（タイムスタンプを自動付与して重複を防ぐ）
        mime_type: 画像のMIMEタイプ

    Returns:
        アップロードされたファイルのDrive ファイルID

    Raises:
        werkzeug.exceptions.Forbidden (403): 他店舗リソースへのアクセス時
        RuntimeError: GOOGLE_SERVICE_ACCOUNT_JSON 未設定時
        googleapiclient.errors.HttpError: Drive API エラー時
    """
    assert_store_owns_resource(requesting_store_id, target_store.id)

    folder_id = ensure_store_folder(target_store)
    service = _build_drive_service()

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_filename = f"{timestamp}_{filename}"

    metadata = {
        "name": safe_filename,
        "parents": [folder_id],
    }
    media = MediaIoBaseUpload(
        io.BytesIO(image_data),
        mimetype=mime_type,
        chunksize=1024 * 1024,
        resumable=True,
    )

    try:
        file = (
            service.files()
            .create(body=metadata, media_body=media, fields="id", supportsAllDrives=True)
            .execute()
        )
        file_id: str = file["id"]
        logger.info(
            "Drive画像アップロード完了 | store_id=%s file_id=%s filename=%s",
            target_store.id,
            file_id,
            safe_filename,
        )
        return file_id

    except HttpError as e:
        logger.error(
            "Drive画像アップロード失敗 | store_id=%s filename=%s error=%s",
            target_store.id,
            safe_filename,
            e,
        )
        raise


def save_json_file(store, filename: str, data: dict) -> str:
    """
    店舗フォルダにJSONファイルを保存する（同名ファイルは上書き）。

    Args:
        store: Store モデルインスタンス
        filename: 保存するファイル名（例: "style_guide.json"）
        data: 保存するdict

    Returns:
        DriveファイルID
    """
    folder_id = ensure_store_folder(store)
    service = _build_drive_service()

    json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    media = MediaIoBaseUpload(
        io.BytesIO(json_bytes),
        mimetype="application/json",
        resumable=False,
    )

    # 既存ファイルを検索して上書き or 新規作成
    escaped = filename.replace("'", "\\'")
    query = (
        f"name = '{escaped}'"
        f" and '{folder_id}' in parents"
        " and trashed = false"
    )
    results = service.files().list(
        q=query, fields="files(id)", pageSize=1,
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    files = results.get("files", [])

    if files:
        file_id = files[0]["id"]
        service.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
        logger.info("DriveJSON上書き | store_id=%s file=%s id=%s", store.id, filename, file_id)
    else:
        metadata = {"name": filename, "parents": [folder_id]}
        created = service.files().create(body=metadata, media_body=media, fields="id", supportsAllDrives=True).execute()
        file_id = created["id"]
        logger.info("DriveJSON作成 | store_id=%s file=%s id=%s", store.id, filename, file_id)

    return file_id


def upload_file(
    store,
    file_data: bytes,
    filename: str,
    mime_type: str,
) -> str:
    """
    店舗フォルダに任意ファイル（PDF等）をアップロードする。

    同名ファイルが存在する場合は上書きする。

    Args:
        store: Store モデルインスタンス
        file_data: ファイルのバイトデータ
        filename: 保存するファイル名
        mime_type: MIMEタイプ（例: "application/pdf"）

    Returns:
        DriveファイルID
    """
    folder_id = ensure_store_folder(store)
    service = _build_drive_service()

    media = MediaIoBaseUpload(
        io.BytesIO(file_data),
        mimetype=mime_type,
        resumable=False,
    )

    # 既存ファイルを検索して上書き or 新規作成
    escaped = filename.replace("'", "\\'")
    query = (
        f"name = '{escaped}'"
        f" and '{folder_id}' in parents"
        " and trashed = false"
    )
    results = service.files().list(
        q=query, fields="files(id)", pageSize=1,
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    files = results.get("files", [])

    if files:
        file_id = files[0]["id"]
        service.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
        logger.info("Driveファイル上書き | store_id=%s file=%s id=%s", store.id, filename, file_id)
    else:
        metadata = {"name": filename, "parents": [folder_id]}
        created = (
            service.files()
            .create(body=metadata, media_body=media, fields="id", supportsAllDrives=True)
            .execute()
        )
        file_id = created["id"]
        logger.info("Driveファイル作成 | store_id=%s file=%s id=%s", store.id, filename, file_id)

    return file_id


def list_files(store, name_prefix: str) -> list[dict]:
    """
    店舗フォルダ内のファイルのうち、指定プレフィックスに一致するものを返す。

    Args:
        store: Store モデルインスタンス
        name_prefix: ファイル名のプレフィックス（例: "url_diagnosis_202603"）

    Returns:
        [{"id": str, "name": str, "createdTime": str}, ...]
    """
    folder_id = ensure_store_folder(store)
    service = _build_drive_service()

    escaped = name_prefix.replace("'", "\\'")
    query = (
        f"name contains '{escaped}'"
        f" and '{folder_id}' in parents"
        " and trashed = false"
    )
    results = (
        service.files()
        .list(
            q=query,
            fields="files(id, name, createdTime)",
            pageSize=100,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    return results.get("files", [])


def share_folder_with_email(store, email: str, role: str = "reader") -> None:
    """
    店舗のDriveフォルダを指定メールアドレスと共有する。

    Args:
        store: Store モデルインスタンス
        email: 共有先のGoogleアカウントメールアドレス
        role: "reader" (閲覧のみ・推奨) / "writer" (編集可) / "commenter"

    Raises:
        RuntimeError: GOOGLE_SERVICE_ACCOUNT_JSON 未設定時
        googleapiclient.errors.HttpError: Drive API エラー時
    """
    folder_id = ensure_store_folder(store)
    service = _build_drive_service()

    permission = {
        "type": "user",
        "role": role,
        "emailAddress": email,
    }

    try:
        service.permissions().create(
            fileId=folder_id,
            body=permission,
            sendNotificationEmail=True,
            fields="id",
            supportsAllDrives=True,
        ).execute()
        logger.info(
            "Driveフォルダ共有完了 | store_id=%s email=%s role=%s folder_id=%s",
            store.id, email, role, folder_id,
        )
    except HttpError as e:
        logger.error(
            "Driveフォルダ共有失敗 | store_id=%s email=%s error=%s",
            store.id, email, e,
        )
        raise


def list_folder_permissions(store) -> list[dict]:
    """
    店舗フォルダに付与されている権限の一覧を取得する。
    サービスアカウント自身のowner権限は除外する。

    Returns:
        [{"id": str, "emailAddress": str, "role": str, "type": str}, ...]
    """
    folder_id = ensure_store_folder(store)
    service = _build_drive_service()

    results = service.permissions().list(
        fileId=folder_id,
        fields="permissions(id, emailAddress, role, type, displayName)",
        supportsAllDrives=True,
    ).execute()

    perms = results.get("permissions", [])
    # owner（サービスアカウント自身）は除外
    return [p for p in perms if p.get("role") != "owner"]


def revoke_folder_permission(store, permission_id: str) -> None:
    """
    店舗フォルダの権限を1件削除する。

    Args:
        store: Store モデルインスタンス
        permission_id: 削除対象の permission id
    """
    folder_id = ensure_store_folder(store)
    service = _build_drive_service()

    try:
        service.permissions().delete(
            fileId=folder_id,
            permissionId=permission_id,
            supportsAllDrives=True,
        ).execute()
        logger.info(
            "Drive権限削除完了 | store_id=%s permission_id=%s",
            store.id, permission_id,
        )
    except HttpError as e:
        logger.error(
            "Drive権限削除失敗 | store_id=%s permission_id=%s error=%s",
            store.id, permission_id, e,
        )
        raise


def get_file_view_url(file_id: str) -> str:
    """
    DriveファイルのGoogle標準ビューワーURLを返す（権限を持つユーザーのみ閲覧可）。
    """
    return f"https://drive.google.com/file/d/{file_id}/view"


_REFERENCE_IMAGES_FOLDER_NAME = "reference_images"


def _ensure_reference_images_folder(store) -> str:
    """店舗フォルダ内のreference_imagesサブフォルダを取得/作成する。"""
    parent_id = ensure_store_folder(store)
    service = _build_drive_service()
    return _get_or_create_folder(service, _REFERENCE_IMAGES_FOLDER_NAME, parent_id=parent_id)


def upload_reference_image(store, image_data: bytes, mime_type: str = "image/jpeg") -> str:
    """参考イメージ写真をDriveの reference_images フォルダにアップロードする。"""
    folder_id = _ensure_reference_images_folder(store)
    service = _build_drive_service()

    ext = ".jpg"
    if mime_type == "image/png":
        ext = ".png"
    elif mime_type == "image/webp":
        ext = ".webp"

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"ref_{timestamp}{ext}"

    metadata = {"name": filename, "parents": [folder_id]}
    media = MediaIoBaseUpload(
        io.BytesIO(image_data),
        mimetype=mime_type,
        resumable=False,
    )
    file = service.files().create(
        body=metadata, media_body=media, fields="id", supportsAllDrives=True
    ).execute()
    file_id: str = file["id"]
    logger.info("参考画像アップロード完了 | store_id=%s file_id=%s", store.id, file_id)
    return file_id


def list_reference_images(store) -> list[dict]:
    """店舗の参考画像一覧を返す。"""
    folder_id = _ensure_reference_images_folder(store)
    service = _build_drive_service()
    query = f"'{folder_id}' in parents and trashed = false"
    results = service.files().list(
        q=query,
        fields="files(id, name, mimeType, createdTime)",
        pageSize=10,
        orderBy="createdTime",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    return results.get("files", [])


def download_file_bytes(file_id: str) -> bytes:
    """ファイルIDから生バイトをダウンロードする。"""
    service = _build_drive_service()
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


def clear_reference_images(store) -> int:
    """既存の参考画像を全て削除する（再登録時用）。削除した枚数を返す。"""
    folder_id = _ensure_reference_images_folder(store)
    service = _build_drive_service()
    query = f"'{folder_id}' in parents and trashed = false"
    results = service.files().list(
        q=query, fields="files(id)", pageSize=50,
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    files = results.get("files", [])
    for f in files:
        try:
            service.files().delete(fileId=f["id"], supportsAllDrives=True).execute()
        except HttpError as e:
            logger.warning("参考画像削除失敗 | file_id=%s error=%s", f["id"], e)
    logger.info("参考画像クリア | store_id=%s count=%d", store.id, len(files))
    return len(files)


def load_json_file(store, filename: str) -> dict | None:
    """
    店舗フォルダからJSONファイルを読み込む。

    Args:
        store: Store モデルインスタンス
        filename: 読み込むファイル名

    Returns:
        dictデータ、ファイルが存在しない場合は None
    """
    folder_id = ensure_store_folder(store)
    service = _build_drive_service()

    escaped = filename.replace("'", "\\'")
    query = (
        f"name = '{escaped}'"
        f" and '{folder_id}' in parents"
        " and trashed = false"
    )
    results = service.files().list(
        q=query, fields="files(id)", pageSize=1,
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    files = results.get("files", [])

    if not files:
        return None

    file_id = files[0]["id"]
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()

    return json.loads(buf.getvalue().decode("utf-8"))
