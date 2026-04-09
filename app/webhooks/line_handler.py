import json
import logging
import re

from flask import Blueprint, request, abort, current_app
from linebot.v3.messaging import (
    ApiClient, Configuration, MessagingApi,
    ReplyMessageRequest, TextMessage, PushMessageRequest,
)

from app.security.line_verify import require_line_signature

logger = logging.getLogger(__name__)
line_bp = Blueprint("line", __name__)

MEDIA_LABELS = {
    "hotpepper": "ホットペッパー",
    "tabelog": "食べログ",
    "gurunavi": "ぐるなび",
    "google": "Googleマイビジネス",
    "instagram": "インスタグラム",
}

URL_PATTERNS = {
    "hotpepper": r"hotpepper\.jp",
    "tabelog": r"tabelog\.com",
    "gurunavi": r"gurunavi\.com",
    "google": r"(maps\.google|goo\.gl|maps\.app\.goo\.gl)",
    "instagram": r"instagram\.com",
}

URL_GUIDE = {
    "hotpepper": "ホットペッパーの店舗ページのURLを送ってね！",
    "tabelog": "食べログの店舗ページのURLを送ってね！",
    "gurunavi": "ぐるなびの店舗ページのURLを送ってね！",
    "google": (
        "GoogleマップでURLを取得する方法だよ📋\n\n"
        "①Googleマップで自分のお店を検索\n"
        "②「共有」ボタンをタップ\n"
        "③「リンクをコピー」をタップ\n\n"
        "コピーしたURLを送ってね！"
    ),
    "instagram": (
        "インスタグラムのプロフィールページのURLを送ってね！\n"
        "（例：https://www.instagram.com/〇〇/）\n\n"
        "※運用代行をしている場合は\n"
        "代行先のプロフィールURLでOKだよ！"
    ),
}

STYLE_GUIDE_QUESTIONS = {
    "sg_tone": (
        "スタイルガイドを登録するよ！📋\n\n"
        "① お店のトーン（雰囲気）を教えて！\n\n"
        "例：カジュアル・親しみやすい、高級感・上品、ナチュラル・温かい、元気・賑やか"
    ),
    "sg_world": (
        "② 店舗の世界観・コンセプトを教えて！\n\n"
        "例：アットホームな居酒屋、おしゃれなカフェ、本格イタリアン"
    ),
    "sg_keywords": (
        "③ お店を表すキーワードをカンマ区切りで教えて！\n\n"
        "例：手作り、こだわり食材、温かい、女子会"
    ),
    "sg_font": (
        "④ フォントスタイルを選んでね！\n\n"
        "1. クール（Noto Serif JP）- シャープ・高級感\n"
        "2. モダン（Noto Sans JP）- すっきり・都会的\n"
        "3. ナチュラル（Klee One）- 手書き風・温かみ\n"
        "4. ポップ（Dela Gothic One）- 元気・賑やか\n"
        "5. エレガント（Shippori Mincho）- 上品・女性向け\n\n"
        "番号で答えてね！"
    ),
    "sg_color": (
        "⑤ 文字色を教えて！\n\n"
        "「白」「黒」「赤」などの色名、または「#FF0000」形式で送ってね！"
    ),
}

MESSAGES = {
    "welcome": (
        "はじめまして！わたし、まるちゃんです🌸\n"
        "飲食店の集客・経営をサポートするAIコンサルタントです！\n\n"
        "まずはお店を登録してください✨\n\n"
        "1. 登録する"
    ),
    "terms": (
        "登録の前にご確認ください📋\n\n"
        "【利用規約】\n"
        "・URLの分析は、ご自身のお店のものに限ります\n"
        "・各サービスの利用規約の遵守はお客様の責任となります\n"
        "・本サービスはお客様の指示に基づき代行するものです\n"
        "・自店舗以外のURLを送信することは禁止します\n\n"
        "1. 同意する\n"
        "2. キャンセル"
    ),
    "terms_required": "1か2の番号で答えてください！\n\n1. 同意する\n2. キャンセル",
    "ask_name": "ありがとうございます！😊\n\nまずお店の名前を教えてください！",
    "ask_media": (
        "使っている媒体を教えてください！\n\n"
        "1. ホットペッパー\n"
        "2. 食べログ\n"
        "3. ぐるなび\n"
        "4. Googleマイビジネス\n"
        "5. インスタグラム\n\n"
        "番号を送ってください😊\n"
        "複数の場合は「135」や「1 3 5」でもOKです！"
    ),
    "ask_fee": (
        "{}の月額費用を教えてください！💰\n\n"
        "・税込金額で入力してください\n"
        "・手数料は含めなくてOKです\n"
        "・運用代行費用がある場合は含めてください\n"
        "・無料の場合は「0」\n\n"
        "数字だけで送ってください！（例：30000）"
    ),
    "url_confirm": (
        "{}のURLですね！\nこれで合っていますか？\n\n"
        "1. はい\n"
        "2. やり直す"
    ),
    "url_retry": "もう一度URLを送ってください！",
    "register_complete": (
        "登録完了です！🎉\n"
        "これからよろしくお願いします！\n\n"
        "【できること】\n"
        "📸 写真を送る → AI改善案\n"
        "🖼 「参考写真登録」→ 写真からスタイル自動抽出\n"
        "💬 何でも相談 → AI経営コンサルタント\n"
        "🎨 「スタイルガイド登録」→ トーン・フォントを設定\n"
        "✍️ 「文字入れ：[テキスト]」→ 画像に文字を合成\n"
        "🔗 「Google連携」→ Driveフォルダを共有\n"
        "🔍 「URL診断：URL」→ 掲載ページを診断\n"
        "📊 「月次レポート」→ 先月の活動レポートを生成\n"
        "🏪 「店舗追加」→ 別のお店を追加\n"
        "🔄 「店舗切替」→ 操作する店舗を変える\n"
        "❓ 「ヘルプ」→ コマンド一覧"
    ),
    "help": (
        "【まるちゃんにできること】\n\n"
        "📝 「登録」→ 新規店舗登録\n"
        "🏪 「店舗追加」→ 別のお店を追加\n"
        "🔄 「店舗切替」→ 操作する店舗を変える\n"
        "📸 写真を送る → AI改善案\n"
        "🖼 「参考写真登録」→ 写真からスタイル自動抽出\n"
        "🎨 「スタイルガイド登録」→ トーン・フォントを設定\n"
        "✍️ 「文字入れ：[テキスト]」→ 画像に文字を合成\n"
        "🔍 「URL診断：URL」→ 掲載ページを診断\n"
        "📊 「月次レポート」→ 先月の活動レポートを生成\n"
        "🔗 「Google連携」→ Driveフォルダを共有\n"
        "💬 何でも聞いてください → AI経営相談\n"
        "↩️ 「やりなおす」→ 入力をやり直す"
    ),
    "select_store": "どの店舗の操作をするか選んでください！\n番号で答えてください😊\n\n",
    "current_store": "今は「{}」の操作中です😊\n\n何かお手伝いできることはありますか？",
    "reset_input": "やりなおしますね！\nもう一度入力してください😊",
    "image_receiving": "写真を受け取りました！📸\nAIが分析中です、少し待ってください～✨",
    "image_error": "ごめんなさい💦画像の処理に失敗しました。もう一度試してみてください！",
    "not_registered": "まず「登録」してからお使いください😊",
    "style_guide_saved": "スタイルガイドを登録しました！🎨\n次からAI分析や文字入れに反映されます✨",
    "style_guide_cancel": "やり直しますね！\nもう一度最初から入力してください😊",
    "text_overlay_ask_image": "文字入れをします！📝\n加工したい画像を送ってください！",
    "text_overlay_processing": "画像に文字を入れています～✨少し待ってください！",
    "text_overlay_error": "ごめんなさい💦文字入れに失敗しました。もう一度試してみてください！",
    "style_guide_not_set": (
        "スタイルガイドがまだ登録されていません！\n"
        "「スタイルガイド登録」と送ると設定できます😊\n\n"
        "今回はデフォルト設定で文字を入れますね！"
    ),
    "ref_photo_start": (
        "参考写真の登録をします！📸\n\n"
        "お店のイメージに合う写真を送ってください。\n"
        "最大3枚まで受け付けます。\n"
        "全部送ったら「0」を送ってください！"
    ),
    "ref_photo_complete_prompt": (
        "全部送ったら「0」を送ってください！\n"
        "（あと{}枚送れます）"
    ),
    "ref_photo_no_photos": "まだ写真が届いていません！参考写真を送ってください📸",
    "google_link_ask": (
        "GoogleドライブフォルダをあなたのGoogleアカウントと共有します🔗\n\n"
        "共有したいGmailアドレスを送ってください！\n"
        "（例：example@gmail.com）\n\n"
        "※ キャンセルする場合は「やりなおす」を送ってください"
    ),
    "google_link_saved": (
        "✅ Google連携完了！\n\n"
        "「{}」とDriveフォルダを共有しました😊\n"
        "これからは改善案・参考写真をGoogleドライブで確認できます！"
    ),
    "google_link_email_saved_but_share_failed": (
        "メールアドレスは保存しましたが、Driveフォルダの共有に失敗しました💦\n"
        "もう一度「Google連携」で試してみてください！"
    ),
    "google_link_invalid_email": (
        "メールアドレスの形式が正しくないようです。\n"
        "「example@gmail.com」のような形式で送ってください！"
    ),
    "ai_thinking": "💭 少し考えますね...",
    "dalle_offer": (
        "📸 DALL-E 3で改善イメージ画像を生成しますか？\n\n"
        "改善案を元に「こんな感じで撮るとGood！」という\n"
        "サンプル画像をAIが作ってくれます✨\n\n"
        "1. 生成する\n"
        "2. スキップ"
    ),
    "dalle_generating": "🎨 DALL-E 3で改善イメージを生成中です！\n少し時間がかかりますが、お待ちください～✨",
    "dalle_complete": "✅ 改善イメージ画像を生成しました！\nこんな雰囲気で撮影してみてください📸",
    "dalle_error": "ごめんなさい💦画像の生成に失敗しました。改善案を参考に撮り直してみてください！",
    "dalle_skip": "わかりました！改善案を参考に撮り直してみてください😊",
    "url_diagnosis_format": (
        "「URL診断：URL」の形式で送ってください！\n\n"
        "例：URL診断：https://hotpepper.jp/..."
    ),
    "url_diagnosis_instagram": (
        "インスタグラムはログインが必要なため\n"
        "自動診断に対応していません🙏\n\n"
        "他の媒体（ホットペッパー・食べログなど）のURLをお試しください！"
    ),
    "url_diagnosis_start": "{}のページを診断します！\n\n",
    "url_diagnosis_fetching": "🔍 ページを取得・診断中です...\n少し待ってください！",
    "url_diagnosis_saved": "\n\n📁 診断結果をGoogleドライブに保存しました！",
    "url_diagnosis_save_failed": "\n\n（Drive保存に失敗しましたが、診断結果は上記の通りです）",
    "report_confirm": (
        "📊 月次レポートを生成します！\n\n"
        "{}年{}月分のレポートを作成しますか？\n\n"
        "1. 生成する\n"
        "2. キャンセル"
    ),
    "report_generating": "📊 レポートを生成中です...\n少し待ってください！",
    "report_error": "ごめんなさい💦レポートの生成に失敗しました。もう一度お試しください！",
    "report_cancel": "キャンセルしました！",
}

MEDIA_MAP = {
    "1": "hotpepper",
    "2": "tabelog",
    "3": "gurunavi",
    "4": "google",
    "5": "instagram",
}


# ──────────────────────────────────────────────────────────
# ユーティリティ
# ──────────────────────────────────────────────────────────

def _detect_media_from_url(url: str):
    for media_type, pattern in URL_PATTERNS.items():
        if re.search(pattern, url):
            return media_type
    return None


def _get_line_api() -> MessagingApi:
    config = Configuration(
        access_token=current_app.config["LINE_CHANNEL_ACCESS_TOKEN"]
    )
    return MessagingApi(ApiClient(config))


def _reply_text(reply_token: str, text: str):
    if not reply_token:
        return
    try:
        api = _get_line_api()
        api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text)],
            )
        )
    except Exception as e:
        logger.error("LINE返信失敗: %s", e)


def _push_text(line_user_id: str, text: str):
    """Push APIでテキストを送る（reply_tokenが使えない場合）。"""
    try:
        api = _get_line_api()
        api.push_message(
            PushMessageRequest(
                to=line_user_id,
                messages=[TextMessage(text=text)],
            )
        )
    except Exception as e:
        logger.error("Push送信失敗: %s", e)


def _push_image(line_user_id: str, image_data: bytes):
    """加工済み画像をDriveにアップロードしてURLをLINEに送る。"""
    from app.services.drive_service import upload_image
    from linebot.v3.messaging import ImageMessage

    store = _get_current_store(line_user_id)
    if store is None:
        return

    try:
        file_id = upload_image(
            requesting_store_id=store.id,
            target_store=store,
            image_data=image_data,
            filename="text_overlay.jpg",
            mime_type="image/jpeg",
        )
        image_url = f"https://drive.google.com/uc?export=view&id={file_id}"
        api = _get_line_api()
        api.push_message(
            PushMessageRequest(
                to=line_user_id,
                messages=[
                    ImageMessage(
                        original_content_url=image_url,
                        preview_image_url=image_url,
                    )
                ],
            )
        )
        logger.info("文字入れ画像送信完了 | user=%s file_id=%s", line_user_id, file_id)
    except Exception as e:
        logger.error("画像Push失敗: %s", e)
        _push_text(
            line_user_id,
            "文字入れは完了しましたが、画像の送信に失敗しました💦\nDriveを確認してください。",
        )


def _get_stores(line_user_id: str):
    from app.models.store import Store
    from app.extensions import db

    return db.session.query(Store).filter_by(
        line_user_id=line_user_id,
        is_active=True,
    ).all()


def _get_current_store(line_user_id: str):
    temp = _get_temp(line_user_id)
    current_store_id = temp.get("current_store_id")
    if not current_store_id:
        stores = _get_stores(line_user_id)
        if stores:
            temp["current_store_id"] = stores[0].id
            return stores[0]
        return None
    from app.models.store import Store
    from app.extensions import db

    return db.session.get(Store, current_store_id)


def _get_temp(line_user_id: str):
    if not hasattr(current_app, "_temp_sessions"):
        current_app._temp_sessions = {}
    if line_user_id not in current_app._temp_sessions:
        current_app._temp_sessions[line_user_id] = {"state": "initial"}
    return current_app._temp_sessions[line_user_id]


def _make_store_list(stores):
    return "".join(f"{i}. {s.name}\n" for i, s in enumerate(stores, 1))


def _parse_media_numbers(text: str):
    text = text.replace(",", " ").replace("、", " ")
    numbers = text.split() if " " in text else list(text)
    return [MEDIA_MAP[n] for n in numbers if n in MEDIA_MAP]


# ──────────────────────────────────────────────────────────
# 会話履歴 (ConversationHistory)
# ──────────────────────────────────────────────────────────

def _save_history(store_id: int, line_user_id: str, role: str, content: str):
    """会話履歴を1件DBに保存する。"""
    from app.models.conversation_history import ConversationHistory
    from app.extensions import db

    record = ConversationHistory(
        store_id=store_id,
        line_user_id=line_user_id,
        role=role,
        content=content,
    )
    db.session.add(record)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error("会話履歴保存失敗: %s", e)


def _load_history(store_id: int, line_user_id: str) -> list[dict]:
    """
    会話履歴をDBから全件取得してClaude API形式に変換する。

    将来の最適化（直近3ヶ月＋重要サマリー方式）への移行方法:
        from datetime import datetime, timedelta
        cutoff = datetime.utcnow() - timedelta(days=90)
        .filter(ConversationHistory.created_at >= cutoff)
    の行を追加するだけで切り替え可能。
    """
    from app.models.conversation_history import ConversationHistory
    from app.extensions import db

    records = (
        db.session.query(ConversationHistory)
        .filter_by(store_id=store_id, line_user_id=line_user_id)
        .order_by(ConversationHistory.created_at.asc())
        .all()
    )
    return [{"role": r.role, "content": r.content} for r in records]


# ──────────────────────────────────────────────────────────
# URL診断
# ──────────────────────────────────────────────────────────

def _run_url_diagnosis(
    line_user_id: str,
    url: str,
    media_type: str,
    mode: dict,
    store,
):
    """
    URL診断を実行してプッシュ送信 + Driveに保存する。
    reply_token は「診断中...」で消費済みのため Push のみ使用。
    """
    from app.services.url_diagnosis_service import fetch_page_text, diagnose_url
    from app.services.drive_service import save_json_file
    from datetime import datetime

    mode_key = mode["key"]
    mode_label = mode["label"]

    # ページ取得
    try:
        page_text = fetch_page_text(url)
    except ValueError as e:
        _push_text(line_user_id, f"ごめんなさい💦ページの取得に失敗しました。\n{e}")
        return
    except Exception as e:
        logger.error("URL取得失敗: %s", e)
        _push_text(line_user_id, "ごめんなさい💦ページの取得に失敗しました。URLを確認してもう一度お試しください！")
        return

    # Claude診断
    try:
        result = diagnose_url(
            url=url,
            page_text=page_text,
            media_type=media_type,
            mode_key=mode_key,
            store_name=store.name,
        )
    except Exception as e:
        logger.error("URL診断失敗: %s", e)
        _push_text(line_user_id, "ごめんなさい💦診断に失敗しました。もう一度お試しください！")
        return

    # 結果送信
    header = f"📊 診断結果【{result['media_label']} / {mode_label}】\n\n"
    _push_text(line_user_id, header + result["result"])

    # Drive保存
    date_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"url_diagnosis_{date_str}_{media_type}_{mode_key}.json"
    try:
        save_json_file(store, filename, result)
        _push_text(line_user_id, MESSAGES["url_diagnosis_saved"].lstrip())
    except Exception as e:
        logger.error("URL診断Drive保存失敗: %s", e)
        _push_text(line_user_id, MESSAGES["url_diagnosis_save_failed"].lstrip())


# ──────────────────────────────────────────────────────────
# AIフリートーク・経営相談
# ──────────────────────────────────────────────────────────

def _handle_ai_consult(
    line_user_id: str,
    user_message: str,
    store,
    reply_token: str,
):
    """
    コマンドに一致しない入力をClaudeに渡して経営相談として回答する。
    店舗データ・スタイルガイド・会話履歴を全てコンテキストとして渡す。
    """
    from app.services.ai_service import consult
    from app.services.style_guide_service import load_style_guide
    from app.models.media_account import MediaAccount
    from app.extensions import db

    # 即座に「考え中」を返信（reply_token は1回限り）
    _reply_text(reply_token, MESSAGES["ai_thinking"])

    # ユーザーメッセージを履歴に保存
    _save_history(store.id, line_user_id, "user", user_message)

    # コンテキスト収集
    style_guide = load_style_guide(store)
    media_accounts = (
        db.session.query(MediaAccount)
        .filter_by(store_id=store.id, is_active=True)
        .all()
    )
    conversation_history = _load_history(store.id, line_user_id)
    # 最後に追加した今回のメッセージは除外（consult内で末尾に追加される）
    if conversation_history and conversation_history[-1]["content"] == user_message:
        conversation_history = conversation_history[:-1]

    # AI回答生成
    try:
        response = consult(
            user_message=user_message,
            store=store,
            conversation_history=conversation_history,
            style_guide=style_guide,
            media_accounts=media_accounts,
        )
    except Exception as e:
        logger.error("AI経営相談失敗: %s", e)
        response = "申し訳ありません、うまく回答できませんでした。もう一度お試しください。"

    # アシスタントの返答を履歴に保存
    _save_history(store.id, line_user_id, "assistant", response)

    _push_text(line_user_id, response)


# ──────────────────────────────────────────────────────────
# 参考写真解析
# ──────────────────────────────────────────────────────────

def _analyze_ref_photos(line_user_id: str, store):
    """
    tempに蓄積された参考写真をClaude Visionで解析し、
    スタイルを抽出して確認メッセージをプッシュする。
    """
    from app.services.ai_service import analyze_reference_photos

    temp = _get_temp(line_user_id)
    ref_photos = temp.get("ref_photos", [])

    try:
        extracted = analyze_reference_photos(ref_photos, store.name)
        temp["ref_extracted"] = extracted
        temp["state"] = "ref_photo_confirm"

        keywords = "、".join(extracted.get("keywords", []))
        summary = extracted.get("summary", "")

        confirm_text = (
            "📊 解析完了です！\n\n"
            "【抽出されたスタイル】\n"
            f"🎯 トーン：{extracted.get('tone', '')}\n"
            f"🌍 世界観：{extracted.get('world_view', '')}\n"
            f"🔑 キーワード：{keywords}\n"
            + (f"\n💬 {summary}\n" if summary else "")
            + "\nこのスタイルをスタイルガイドに登録しますか？\n\n"
            "1. 登録する\n"
            "2. やり直す（写真を撮り直す）"
        )
        _push_text(line_user_id, confirm_text)

    except Exception as e:
        logger.error("参考写真解析失敗: %s", e)
        temp["state"] = "initial"
        temp.pop("ref_photos", None)
        _push_text(
            line_user_id,
            "ごめんなさい💦解析に失敗しました。\nもう一度「参考写真登録」から試してください！",
        )


# ──────────────────────────────────────────────────────────
# 店舗保存
# ──────────────────────────────────────────────────────────

def _save_store(line_user_id: str, temp: dict):
    from app.models.store import Store
    from app.models.session import ConversationSession
    from app.models.media_account import MediaAccount
    from app.extensions import db
    from datetime import datetime

    store = Store(
        line_user_id=line_user_id,
        name=temp.get("name", ""),
        email="",
        is_active=True,
        ai_consent_agreed_at=datetime.utcnow(),
    )
    db.session.add(store)
    db.session.flush()

    for media_type in temp.get("media_list", []):
        media = MediaAccount(
            store_id=store.id,
            media_type=media_type,
            url=temp.get(f"url_{media_type}", ""),
            monthly_fee=int(temp.get(f"fee_{media_type}", 0)),
        )
        db.session.add(media)

    session = ConversationSession(store_id=store.id, state="completed")
    db.session.add(session)
    db.session.commit()

    # 店舗登録時にDriveフォルダを自動作成
    try:
        from app.services.drive_service import ensure_store_folder
        ensure_store_folder(store)
    except Exception as e:
        logger.warning("Driveフォルダ自動作成失敗（後で再試行可能）: %s", e)

    logger.info("店舗登録完了 | store_id=%s name=%s", store.id, temp.get("name"))
    return store


# ──────────────────────────────────────────────────────────
# 画像ハンドラ
# ──────────────────────────────────────────────────────────

def _handle_image(line_user_id: str, reply_token: str, message: dict):
    """
    画像を受け取る。
    - ref_photo_collecting : 参考写真として蓄積
    - waiting_text_overlay_image : テキストを合成して返す
    - 通常時 : AIで改善案を生成し履歴保存
    """
    from app.services.image_service import download_line_image
    from app.services.ai_service import analyze_food_image
    from app.services.style_guide_service import load_style_guide

    store = _get_current_store(line_user_id)
    if store is None:
        _reply_text(reply_token, MESSAGES["not_registered"])
        return

    temp = _get_temp(line_user_id)
    message_id = message.get("id")
    state = temp.get("state", "initial")

    # ── 参考写真収集中 ──────────────────────────────────────
    if state == "ref_photo_collecting":
        ref_photos = temp.setdefault("ref_photos", [])
        if len(ref_photos) >= 3:
            _reply_text(
                reply_token,
                "写真は最大3枚までです！\n「0」を送って解析を始めてください。",
            )
            return

        try:
            image_data, mime_type = download_line_image(message_id)
        except Exception as e:
            logger.error("参考写真ダウンロード失敗: %s", e)
            _reply_text(reply_token, "画像の受け取りに失敗しました💦もう一度送ってください！")
            return

        ref_photos.append({"data": image_data, "media_type": mime_type})
        count = len(ref_photos)

        if count >= 3:
            _reply_text(
                reply_token,
                f"✅ {count}枚目を受け取りました！\n3枚揃ったので解析を始めます🔍",
            )
            _analyze_ref_photos(line_user_id, store)
        else:
            remaining = 3 - count
            _reply_text(
                reply_token,
                f"✅ {count}枚目を受け取りました！\n"
                f"あと{remaining}枚送れます。\n"
                "全部送ったら「0」を送ってください！",
            )
        return

    # ── 文字入れ待機中 ─────────────────────────────────────
    if state == "waiting_text_overlay_image":
        overlay_text = temp.pop("overlay_text", "")
        temp["state"] = "initial"
        _reply_text(reply_token, MESSAGES["text_overlay_processing"])
        try:
            from app.services.text_overlay_service import overlay_text as do_overlay

            image_data, _ = download_line_image(message_id)
            style = load_style_guide(store)
            result_data = do_overlay(
                image_data=image_data,
                text=overlay_text,
                font_style=style.get("font_style", "modern"),
                text_color=style.get("text_color", "#FFFFFF"),
                position=style.get("text_position", "bottom"),
            )
            _push_image(line_user_id, result_data)
        except Exception as e:
            logger.error("文字入れ失敗: %s", e)
            _push_text(line_user_id, MESSAGES["text_overlay_error"])
        return

    # ── 通常: AI改善案 → DALL-E 3再生成オファー ───────────
    _reply_text(reply_token, MESSAGES["image_receiving"])
    try:
        image_data, mime_type = download_line_image(message_id)
        style = load_style_guide(store)
        advice = analyze_food_image(
            image_data=image_data,
            media_type=mime_type,
            store_name=store.name,
            style_guide=style,
        )
        reply_message = f"📊 AI改善案です！\n\n{advice}\n\n参考にしてみてください😊"
        _push_text(line_user_id, reply_message)

        # 改善案を会話履歴に保存
        _save_history(store.id, line_user_id, "user", "[写真を送信]")
        _save_history(store.id, line_user_id, "assistant", reply_message)

        # DALL-E 3再生成を提案（元画像データをtempに保持）
        temp["dalle_image_data"] = image_data
        temp["dalle_mime_type"] = mime_type
        temp["state"] = "waiting_dalle_confirm"
        _push_text(line_user_id, MESSAGES["dalle_offer"])

    except Exception as e:
        logger.error("画像処理失敗: %s", e)
        _push_text(line_user_id, MESSAGES["image_error"])


# ──────────────────────────────────────────────────────────
# Webhook エントリーポイント
# ──────────────────────────────────────────────────────────

@line_bp.post("/webhook/line")
@require_line_signature
def webhook():
    body = request.get_data(as_text=True)
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        abort(400)

    for event in data.get("events", []):
        _handle_event(event)

    return {}, 200


def _handle_event(event: dict):
    event_type = event.get("type")
    source = event.get("source", {})
    line_user_id = source.get("userId")
    reply_token = event.get("replyToken")

    if not line_user_id:
        return

    if event_type == "follow":
        _reply_text(reply_token, MESSAGES["welcome"])
        return

    if event_type != "message":
        return

    message = event.get("message", {})
    message_type = message.get("type")

    # 画像が送られてきた場合
    if message_type == "image":
        _handle_image(line_user_id, reply_token, message)
        return

    if message_type != "text":
        _reply_text(reply_token, "テキストか画像を送ってください！")
        return

    text = message.get("text", "").strip()
    temp = _get_temp(line_user_id)
    state = temp.get("state", "initial")

    # ── グローバルコマンド ──────────────────────────────────
    if text == "ヘルプ":
        _reply_text(reply_token, MESSAGES["help"])
        return

    if text == "やりなおす":
        prev_map = {
            "waiting_name": "waiting_terms",
            "waiting_media": "waiting_name",
            "waiting_url": "waiting_media",
            "waiting_fee": "waiting_url",
            "waiting_google_email": "initial",
            "ref_photo_collecting": "initial",
            "ref_photo_confirm": "initial",
            "waiting_dalle_confirm": "initial",
            "waiting_url_diagnosis_menu": "initial",
            "waiting_report_confirm": "initial",
        }
        if state in prev_map:
            temp["state"] = prev_map[state]
            # 参考写真フローをリセット
            if state in ("ref_photo_collecting", "ref_photo_confirm"):
                temp.pop("ref_photos", None)
                temp.pop("ref_extracted", None)
            # DALL-E確認フローをリセット
            if state == "waiting_dalle_confirm":
                temp.pop("dalle_image_data", None)
                temp.pop("dalle_mime_type", None)
            # URL診断フローをリセット
            if state == "waiting_url_diagnosis_menu":
                temp.pop("diagnosis_url", None)
                temp.pop("diagnosis_media", None)
            # 月次レポートフローをリセット
            if state == "waiting_report_confirm":
                temp.pop("report_year", None)
                temp.pop("report_month", None)
            _reply_text(reply_token, MESSAGES["reset_input"])
        else:
            _reply_text(reply_token, MESSAGES["reset_input"])
        return

    stores = _get_stores(line_user_id)

    # ── 登録済みユーザー向けコマンド ────────────────────────
    if stores:
        if text == "店舗追加":
            temp["state"] = "waiting_terms"
            temp["is_adding"] = True
            _reply_text(reply_token, MESSAGES["terms"])
            return

        if text == "店舗切替":
            if len(stores) == 1:
                _reply_text(
                    reply_token,
                    f"登録されているお店は「{stores[0].name}」だけです！",
                )
                return
            store_list = _make_store_list(stores)
            temp["state"] = "waiting_store_select"
            _reply_text(reply_token, MESSAGES["select_store"] + store_list)
            return

        if text == "スタイルガイド登録":
            current_store = _get_current_store(line_user_id)
            if current_store is None:
                _reply_text(reply_token, MESSAGES["not_registered"])
                return
            temp["state"] = "sg_tone"
            temp["sg_data"] = {}
            _reply_text(reply_token, STYLE_GUIDE_QUESTIONS["sg_tone"])
            return

        if text == "参考写真登録":
            current_store = _get_current_store(line_user_id)
            if current_store is None:
                _reply_text(reply_token, MESSAGES["not_registered"])
                return
            temp["state"] = "ref_photo_collecting"
            temp["ref_photos"] = []
            _reply_text(reply_token, MESSAGES["ref_photo_start"])
            return

        if text == "Google連携":
            current_store = _get_current_store(line_user_id)
            if current_store is None:
                _reply_text(reply_token, MESSAGES["not_registered"])
                return
            temp["state"] = "waiting_google_email"
            _reply_text(reply_token, MESSAGES["google_link_ask"])
            return

        if text == "月次レポート":
            current_store = _get_current_store(line_user_id)
            if current_store is None:
                _reply_text(reply_token, MESSAGES["not_registered"])
                return
            from app.services.report_service import _prev_month
            from datetime import date
            year, month = _prev_month(date.today())
            temp["state"] = "waiting_report_confirm"
            temp["report_year"] = year
            temp["report_month"] = month
            _reply_text(reply_token, MESSAGES["report_confirm"].format(year, month))
            return

        if text.startswith("URL診断：") or text.startswith("URL診断:"):
            current_store = _get_current_store(line_user_id)
            if current_store is None:
                _reply_text(reply_token, MESSAGES["not_registered"])
                return
            url = text.split("：", 1)[-1].split(":", 1)[-1].strip()
            if not url.startswith("http"):
                _reply_text(reply_token, MESSAGES["url_diagnosis_format"])
                return
            # Instagram は自動取得不可
            detected = _detect_media_from_url(url)
            if detected == "instagram":
                _reply_text(reply_token, MESSAGES["url_diagnosis_instagram"])
                return
            from app.services.url_diagnosis_service import DIAGNOSIS_MENU_TEXT
            temp["state"] = "waiting_url_diagnosis_menu"
            temp["diagnosis_url"] = url
            temp["diagnosis_media"] = detected or "unknown"
            media_label = MEDIA_LABELS.get(detected, "外部サイト") if detected else "外部サイト"
            _reply_text(
                reply_token,
                MESSAGES["url_diagnosis_start"].format(media_label) + DIAGNOSIS_MENU_TEXT,
            )
            return

        if text.startswith("文字入れ：") or text.startswith("文字入れ:"):
            current_store = _get_current_store(line_user_id)
            if current_store is None:
                _reply_text(reply_token, MESSAGES["not_registered"])
                return
            overlay_text = text.split("：", 1)[-1].split(":", 1)[-1].strip()
            if not overlay_text:
                _reply_text(
                    reply_token,
                    "文字入れするテキストを「文字入れ：〇〇」の形式で送ってください！",
                )
                return
            from app.services.style_guide_service import load_style_guide

            style = load_style_guide(current_store)
            if not style.get("tone"):
                _push_text(line_user_id, MESSAGES["style_guide_not_set"])
            temp["state"] = "waiting_text_overlay_image"
            temp["overlay_text"] = overlay_text
            _reply_text(reply_token, MESSAGES["text_overlay_ask_image"])
            return

    # ── 登録フロー ──────────────────────────────────────────
    if state == "initial":
        if text in ("登録", "1"):
            temp["state"] = "waiting_terms"
            _reply_text(reply_token, MESSAGES["terms"])
        else:
            # 登録前はウェルカムメッセージ
            _reply_text(reply_token, MESSAGES["welcome"])

    elif state == "waiting_terms":
        if text == "1":
            temp["state"] = "waiting_name"
            _reply_text(reply_token, MESSAGES["ask_name"])
        elif text == "2":
            temp["state"] = "initial"
            _reply_text(reply_token, "キャンセルしました。また「登録」で始められます！")
        else:
            _reply_text(reply_token, MESSAGES["terms_required"])

    elif state == "waiting_name":
        temp["name"] = text
        temp["state"] = "waiting_media"
        _reply_text(reply_token, MESSAGES["ask_media"])

    elif state == "waiting_media":
        media_list = _parse_media_numbers(text)
        if not media_list:
            _reply_text(reply_token, "番号で入力してください！\n例：「135」や「1 3 5」")
            return
        temp["media_list"] = media_list
        temp["media_queue"] = media_list.copy()
        temp["state"] = "waiting_url"
        _reply_text(reply_token, URL_GUIDE[temp["media_queue"][0]])

    elif state == "waiting_url":
        current_media = temp["media_queue"][0]
        detected = _detect_media_from_url(text)
        if detected and detected != current_media:
            _reply_text(
                reply_token,
                f"{MEDIA_LABELS[detected]}のURLのようですが、"
                f"今は{MEDIA_LABELS[current_media]}のURLを聞いています！\n"
                "もう一度送ってください！",
            )
            return
        temp[f"url_{current_media}"] = text
        temp["state"] = "waiting_url_confirm"
        _reply_text(
            reply_token,
            MESSAGES["url_confirm"].format(MEDIA_LABELS[current_media]),
        )

    elif state == "waiting_url_confirm":
        current_media = temp["media_queue"][0]
        if text == "1":
            temp["state"] = "waiting_fee"
            _reply_text(
                reply_token,
                MESSAGES["ask_fee"].format(MEDIA_LABELS[current_media]),
            )
        elif text == "2":
            temp["state"] = "waiting_url"
            _reply_text(reply_token, URL_GUIDE[current_media])
        else:
            _reply_text(
                reply_token,
                "1か2の番号で答えてください！\n\n1. はい\n2. やり直す",
            )

    elif state == "waiting_fee":
        if not temp.get("media_queue"):
            _reply_text(reply_token, "エラーが発生しました。最初からやり直してください。")
            temp["state"] = "initial"
            return
        current_media = temp["media_queue"][0]
        fee_text = text.replace(",", "").replace("円", "").strip()
        if not fee_text.isdigit():
            _reply_text(reply_token, "数字だけで送ってください！\n例：「30000」")
            return
        temp[f"fee_{current_media}"] = fee_text
        temp["media_queue"].pop(0)

        if temp["media_queue"]:
            next_media = temp["media_queue"][0]
            temp["state"] = "waiting_url"
            _reply_text(reply_token, URL_GUIDE[next_media])
        else:
            store = _save_store(line_user_id, temp)
            temp["current_store_id"] = store.id
            temp["state"] = "initial"
            temp.pop("is_adding", None)
            _reply_text(reply_token, MESSAGES["register_complete"])

    elif state == "waiting_store_select":
        try:
            idx = int(text) - 1
            selected = stores[idx]
            temp["current_store_id"] = selected.id
            temp["state"] = "initial"
            _reply_text(
                reply_token,
                MESSAGES["current_store"].format(selected.name),
            )
        except (ValueError, IndexError):
            store_list = _make_store_list(stores)
            _reply_text(reply_token, "番号で選んでください！\n\n" + store_list)

    # ── スタイルガイド登録フロー ────────────────────────────

    elif state == "sg_tone":
        temp["sg_data"]["tone"] = text
        temp["state"] = "sg_world"
        _reply_text(reply_token, STYLE_GUIDE_QUESTIONS["sg_world"])

    elif state == "sg_world":
        temp["sg_data"]["world_view"] = text
        temp["state"] = "sg_keywords"
        _reply_text(reply_token, STYLE_GUIDE_QUESTIONS["sg_keywords"])

    elif state == "sg_keywords":
        keywords = [k.strip() for k in text.replace("、", ",").split(",") if k.strip()]
        temp["sg_data"]["keywords"] = keywords
        temp["state"] = "sg_font"
        _reply_text(reply_token, STYLE_GUIDE_QUESTIONS["sg_font"])

    elif state == "sg_font":
        from app.services.style_guide_service import FONT_CHOICES

        if text not in FONT_CHOICES:
            _reply_text(reply_token, "1〜5の番号で選んでください！")
            return
        temp["sg_data"]["font_style"] = FONT_CHOICES[text]["key"]
        temp["state"] = "sg_color"
        _reply_text(reply_token, STYLE_GUIDE_QUESTIONS["sg_color"])

    elif state == "sg_color":
        from app.services.style_guide_service import (
            resolve_color,
            format_style_guide_summary,
        )

        temp["sg_data"]["text_color"] = resolve_color(text)
        temp["sg_data"]["text_position"] = "bottom"
        temp["state"] = "sg_confirm"
        _reply_text(reply_token, format_style_guide_summary(temp["sg_data"]))

    elif state == "sg_confirm":
        if text == "1":
            from app.services.style_guide_service import save_style_guide

            current_store = _get_current_store(line_user_id)
            if current_store is None:
                temp["state"] = "initial"
                _reply_text(reply_token, MESSAGES["not_registered"])
                return
            sg_data = temp.get("sg_data")
            if not sg_data:
                temp["state"] = "initial"
                _reply_text(
                    reply_token,
                    "登録データが見つかりませんでした💦もう一度「スタイルガイド登録」から始めてください！",
                )
                return
            try:
                save_style_guide(current_store, sg_data)
                temp.pop("sg_data", None)
                temp["state"] = "initial"
                _reply_text(reply_token, MESSAGES["style_guide_saved"])
            except Exception as e:
                logger.error(
                    "スタイルガイド保存失敗 | store_id=%s error=%s",
                    current_store.id,
                    e,
                )
                temp["state"] = "initial"
                _reply_text(reply_token, "ごめんなさい💦保存に失敗しました。もう一度試してみてください！")
        elif text == "2":
            temp["sg_data"] = {}
            temp["state"] = "sg_tone"
            _reply_text(
                reply_token,
                MESSAGES["style_guide_cancel"] + "\n\n" + STYLE_GUIDE_QUESTIONS["sg_tone"],
            )
        else:
            _reply_text(
                reply_token,
                "1か2の番号で答えてください！\n\n1. 登録する\n2. やり直す",
            )

    # ── 参考写真フロー ──────────────────────────────────────

    elif state == "ref_photo_collecting":
        if text == "0":
            ref_photos = temp.get("ref_photos", [])
            if not ref_photos:
                _reply_text(reply_token, MESSAGES["ref_photo_no_photos"])
                return
            _reply_text(
                reply_token,
                f"🔍 {len(ref_photos)}枚の写真を解析します！少し待ってください...",
            )
            current_store = _get_current_store(line_user_id)
            _analyze_ref_photos(line_user_id, current_store)
        else:
            _reply_text(
                reply_token,
                "参考写真を送ってください📸\n"
                "（最大3枚。全部送ったら「0」を送ってください）",
            )

    elif state == "ref_photo_confirm":
        current_store = _get_current_store(line_user_id)
        if text == "1":
            extracted = temp.get("ref_extracted", {})
            from app.services.style_guide_service import load_style_guide, save_style_guide

            existing = load_style_guide(current_store)
            if extracted.get("tone"):
                existing["tone"] = extracted["tone"]
            if extracted.get("world_view"):
                existing["world_view"] = extracted["world_view"]
            if extracted.get("keywords"):
                existing["keywords"] = extracted["keywords"]

            # 参考写真をDriveに保存
            from app.services.drive_service import upload_image

            for i, photo in enumerate(temp.get("ref_photos", []), 1):
                try:
                    upload_image(
                        requesting_store_id=current_store.id,
                        target_store=current_store,
                        image_data=photo["data"],
                        filename=f"ref_photo_{i}.jpg",
                        mime_type=photo.get("media_type", "image/jpeg"),
                    )
                except Exception as e:
                    logger.error("参考写真Drive保存失敗: %s", e)

            save_style_guide(current_store, existing)
            temp.pop("ref_photos", None)
            temp.pop("ref_extracted", None)
            temp["state"] = "initial"
            _reply_text(
                reply_token,
                "✅ 参考写真のスタイルをガイドに反映しました！\n写真もDriveに保存しました😊",
            )
        elif text == "2":
            temp.pop("ref_photos", None)
            temp.pop("ref_extracted", None)
            temp["state"] = "ref_photo_collecting"
            temp["ref_photos"] = []
            _reply_text(
                reply_token,
                "やり直しますね！\n参考写真をもう一度送ってください📸\n"
                "（最大3枚、送り終わったら「0」）",
            )
        else:
            _reply_text(
                reply_token,
                "1か2の番号で答えてください！\n\n1. 登録する\n2. やり直す",
            )

    # ── Google連携フロー ────────────────────────────────────

    elif state == "waiting_google_email":
        email = text.strip()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            _reply_text(reply_token, MESSAGES["google_link_invalid_email"])
            return

        current_store = _get_current_store(line_user_id)
        if current_store is None:
            temp["state"] = "initial"
            _reply_text(reply_token, MESSAGES["not_registered"])
            return

        from app.extensions import db

        current_store.google_email = email
        db.session.commit()

        try:
            from app.services.drive_service import share_folder_with_email

            share_folder_with_email(current_store, email)
            temp["state"] = "initial"
            _reply_text(reply_token, MESSAGES["google_link_saved"].format(email))
        except Exception as e:
            logger.error("Drive共有失敗: %s", e)
            temp["state"] = "initial"
            _reply_text(
                reply_token,
                MESSAGES["google_link_email_saved_but_share_failed"],
            )

    # ── DALL-E 3再生成確認 ──────────────────────────────────

    elif state == "waiting_dalle_confirm":
        current_store = _get_current_store(line_user_id)
        if text == "1":
            temp["state"] = "initial"
            image_data = temp.pop("dalle_image_data", None)
            mime_type = temp.pop("dalle_mime_type", "image/jpeg")
            if image_data is None or current_store is None:
                _reply_text(reply_token, MESSAGES["dalle_error"])
                return
            _reply_text(reply_token, MESSAGES["dalle_generating"])
            try:
                from app.services.ai_service import generate_improved_photo
                from app.services.style_guide_service import load_style_guide as _load_sg

                style = _load_sg(current_store)
                result_data = generate_improved_photo(
                    image_data=image_data,
                    media_type=mime_type,
                    store_name=current_store.name,
                    style_guide=style,
                )
                _push_text(line_user_id, MESSAGES["dalle_complete"])
                _push_image(line_user_id, result_data)
            except Exception as e:
                logger.error("DALL-E 3再生成失敗: %s", e)
                _push_text(line_user_id, MESSAGES["dalle_error"])
        elif text == "2":
            temp.pop("dalle_image_data", None)
            temp.pop("dalle_mime_type", None)
            temp["state"] = "initial"
            _reply_text(reply_token, MESSAGES["dalle_skip"])
        else:
            _reply_text(
                reply_token,
                "1か2の番号で答えてください！\n\n1. 生成する\n2. スキップ",
            )

    # ── URL診断モード選択 ───────────────────────────────────

    elif state == "waiting_url_diagnosis_menu":
        from app.services.url_diagnosis_service import DIAGNOSIS_MODES

        if text not in DIAGNOSIS_MODES:
            from app.services.url_diagnosis_service import DIAGNOSIS_MENU_TEXT
            _reply_text(
                reply_token,
                "1〜6の番号で選んでください！\n\n" + DIAGNOSIS_MENU_TEXT,
            )
            return

        mode = DIAGNOSIS_MODES[text]
        url = temp.pop("diagnosis_url", "")
        media_type = temp.pop("diagnosis_media", "unknown")
        temp["state"] = "initial"

        current_store = _get_current_store(line_user_id)
        if not url or current_store is None:
            _reply_text(reply_token, "診断情報が見つかりませんでした。もう一度「URL診断：URL」から始めてください！")
            return

        _reply_text(reply_token, MESSAGES["url_diagnosis_fetching"])
        _run_url_diagnosis(line_user_id, url, media_type, mode, current_store)

    # ── 月次レポート生成確認 ────────────────────────────────

    elif state == "waiting_report_confirm":
        current_store = _get_current_store(line_user_id)
        if text == "1":
            year = temp.pop("report_year", None)
            month = temp.pop("report_month", None)
            temp["state"] = "initial"
            if year is None or current_store is None:
                _reply_text(reply_token, MESSAGES["report_error"])
                return
            _reply_text(reply_token, MESSAGES["report_generating"])
            try:
                from app.services.report_service import generate_monthly_report
                line_text = generate_monthly_report(current_store, year, month)
                _push_text(line_user_id, line_text)
            except Exception as e:
                logger.error("月次レポート生成失敗: %s", e)
                _push_text(line_user_id, MESSAGES["report_error"])
        elif text == "2":
            temp.pop("report_year", None)
            temp.pop("report_month", None)
            temp["state"] = "initial"
            _reply_text(reply_token, MESSAGES["report_cancel"])
        else:
            from app.services.report_service import _prev_month
            from datetime import date
            year = temp.get("report_year")
            month = temp.get("report_month")
            if year and month:
                _reply_text(reply_token, MESSAGES["report_confirm"].format(year, month))
            else:
                _reply_text(reply_token, "1か2の番号で答えてください！\n\n1. 生成する\n2. キャンセル")

    # ── フォールバック：AIフリートーク・経営相談 ────────────

    else:
        current_store = _get_current_store(line_user_id)
        if current_store:
            _handle_ai_consult(line_user_id, text, current_store, reply_token)
        else:
            _reply_text(reply_token, MESSAGES["welcome"])
