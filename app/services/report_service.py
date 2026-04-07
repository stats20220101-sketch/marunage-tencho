"""
月次レポート生成サービス。

処理フロー:
    1. DBから先月の会話・AI改善案件数を集計
    2. DriveからURL診断ファイル数を集計
    3. スタイルガイドの現状を取得
    4. Claude でおすすめアクションを生成
    5. fpdf2 + NotoSansJP で PDF を生成
    6. Drive に保存（PDF）
    7. LINE 送信用テキストを返す
"""

import io
import logging
from datetime import datetime, date

import anthropic
from fpdf import FPDF
from flask import current_app

logger = logging.getLogger(__name__)

_MEDIA_LABELS = {
    "hotpepper": "ホットペッパー",
    "tabelog": "食べログ",
    "gurunavi": "ぐるなび",
    "google": "Googleマイビジネス",
    "instagram": "インスタグラム",
    "unknown": "外部サイト",
}


# ──────────────────────────────────────────────────────────
# データ収集
# ──────────────────────────────────────────────────────────

def _prev_month(today: date | None = None) -> tuple[int, int]:
    """(year, month) の形式で前月を返す。"""
    t = today or date.today()
    if t.month == 1:
        return t.year - 1, 12
    return t.year, t.month - 1


def collect_report_data(store, year: int, month: int) -> dict:
    """
    指定年月のレポートデータを収集する。

    Args:
        store: Store モデルインスタンス
        year: 対象年
        month: 対象月

    Returns:
        レポートデータdict
    """
    from app.models.conversation_history import ConversationHistory
    from app.models.media_account import MediaAccount
    from app.extensions import db
    from app.services.style_guide_service import load_style_guide
    from app.services.drive_service import list_files

    year_month = f"{year:04d}-{month:02d}"
    month_prefix = f"{year:04d}{month:02d}"

    # 月の開始・終了を計算
    start_dt = datetime(year, month, 1)
    if month == 12:
        end_dt = datetime(year + 1, 1, 1)
    else:
        end_dt = datetime(year, month + 1, 1)

    # 会話件数（ユーザー発言のみ）
    total_messages = (
        db.session.query(ConversationHistory)
        .filter(
            ConversationHistory.store_id == store.id,
            ConversationHistory.role == "user",
            ConversationHistory.created_at >= start_dt,
            ConversationHistory.created_at < end_dt,
        )
        .count()
    )

    # AI改善案件数（写真送信の回数）
    photo_analysis_count = (
        db.session.query(ConversationHistory)
        .filter(
            ConversationHistory.store_id == store.id,
            ConversationHistory.content == "[写真を送信]",
            ConversationHistory.created_at >= start_dt,
            ConversationHistory.created_at < end_dt,
        )
        .count()
    )

    # URL診断件数（Driveのファイル名から集計）
    url_diagnosis_files = []
    try:
        files = list_files(store, f"url_diagnosis_{month_prefix}")
        url_diagnosis_files = files
    except Exception as e:
        logger.warning("URL診断ファイルリスト取得失敗: %s", e)

    url_diagnosis_count = len(url_diagnosis_files)
    # 診断した媒体の種類を抽出（ファイル名から）
    diagnosed_media = set()
    for f in url_diagnosis_files:
        parts = f.get("name", "").split("_")
        # url_diagnosis_YYYYMMDD_HHMMSS_media_mode.json → parts[4] が media
        if len(parts) >= 5:
            media_key = parts[4]
            if media_key in _MEDIA_LABELS:
                diagnosed_media.add(_MEDIA_LABELS[media_key])

    # スタイルガイドの現状
    style_guide = load_style_guide(store)
    has_style_guide = bool(style_guide.get("tone") or style_guide.get("world_view"))

    # 登録媒体
    media_accounts = (
        db.session.query(MediaAccount)
        .filter_by(store_id=store.id, is_active=True)
        .all()
    )
    media_list = [
        {
            "label": _MEDIA_LABELS.get(m.media_type, m.media_type),
            "fee": m.monthly_fee or 0,
        }
        for m in media_accounts
    ]
    total_ad_cost = sum(m["fee"] for m in media_list)

    return {
        "year_month": year_month,
        "year": year,
        "month": month,
        "store_name": store.name,
        "total_messages": total_messages,
        "photo_analysis_count": photo_analysis_count,
        "url_diagnosis_count": url_diagnosis_count,
        "diagnosed_media": sorted(diagnosed_media),
        "has_style_guide": has_style_guide,
        "style_guide": style_guide,
        "media_list": media_list,
        "total_ad_cost": total_ad_cost,
    }


# ──────────────────────────────────────────────────────────
# Claude によるおすすめアクション生成
# ──────────────────────────────────────────────────────────

def generate_recommendations(store, data: dict) -> str:
    """
    データを基に Claude でおすすめアクションを生成する。

    Returns:
        おすすめアクションのテキスト（3〜5項目の箇条書き）
    """
    client = anthropic.Anthropic(api_key=current_app.config["ANTHROPIC_API_KEY"])

    style_summary = ""
    if data["has_style_guide"]:
        sg = data["style_guide"]
        style_summary = (
            f"スタイルガイド登録済み（トーン：{sg.get('tone', '')}、"
            f"世界観：{sg.get('world_view', '')}）"
        )
    else:
        style_summary = "スタイルガイド未登録"

    media_summary = "、".join(m["label"] for m in data["media_list"]) or "なし"

    prompt = (
        f"店舗名：{data['store_name']}\n"
        f"対象月：{data['year']}年{data['month']}月\n"
        f"登録媒体：{media_summary}\n"
        f"総広告費：{data['total_ad_cost']:,}円\n"
        f"会話件数：{data['total_messages']}件\n"
        f"AI写真改善案：{data['photo_analysis_count']}回\n"
        f"URL診断：{data['url_diagnosis_count']}回\n"
        f"スタイルガイド：{style_summary}\n\n"
        "上記のデータを基に、この飲食店が来月取り組むべき\n"
        "おすすめアクションを3〜5項目、箇条書きで提案してください。\n"
        "各項目は「・」始まりで、具体的かつ実行可能な内容にしてください。\n"
        "（例：「・ホットペッパーの写真を5枚追加する」）\n"
        "前置きや後書きは不要です。箇条書きのみ出力してください。"
    )

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.error("おすすめアクション生成失敗: %s", e)
        return "・写真の見直しと追加\n・スタイルガイドの更新\n・URL診断の実施"


# ──────────────────────────────────────────────────────────
# PDF 生成
# ──────────────────────────────────────────────────────────

def build_pdf(data: dict, recommendations: str) -> bytes:
    """
    fpdf2 + NotoSansJP で月次レポートPDFを生成する。

    Returns:
        PDFのバイトデータ
    """
    from app.services.font_service import get_font_path

    font_path = str(get_font_path("modern"))  # NotoSansJP

    pdf = FPDF()
    pdf.add_page()
    pdf.add_font("NotoSansJP", fname=font_path)
    pdf.add_font("NotoSansJP", style="B", fname=font_path)

    W = pdf.epw  # 有効幅

    # ── タイトル ──
    pdf.set_font("NotoSansJP", style="B", size=18)
    pdf.cell(W, 12, f"月次レポート  {data['year']}年{data['month']}月", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(2)

    pdf.set_font("NotoSansJP", size=11)
    pdf.cell(W, 8, f"店舗名：{data['store_name']}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(W, 8, f"作成日：{datetime.utcnow().strftime('%Y年%m月%d日')}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # ── 区切り線 ──
    def _divider():
        pdf.set_draw_color(180, 180, 180)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + W, pdf.get_y())
        pdf.ln(4)

    # ── セクション見出し ──
    def _section(title: str):
        pdf.set_font("NotoSansJP", style="B", size=13)
        pdf.set_fill_color(245, 245, 245)
        pdf.cell(W, 10, f"  {title}", new_x="LMARGIN", new_y="NEXT", fill=True)
        pdf.ln(2)
        pdf.set_font("NotoSansJP", size=11)

    # ── 行追加 ──
    def _row(label: str, value: str):
        pdf.set_font("NotoSansJP", style="B", size=11)
        pdf.cell(60, 8, label, new_x="RIGHT", new_y="TOP")
        pdf.set_font("NotoSansJP", size=11)
        pdf.multi_cell(W - 60, 8, value, new_x="LMARGIN", new_y="NEXT")

    # ── 先月の活動サマリー ──
    _section("先月の活動サマリー")
    _row("まるちゃんとの会話：", f"{data['total_messages']}件")
    _row("AI写真改善案：", f"{data['photo_analysis_count']}回")

    diag_text = f"{data['url_diagnosis_count']}回"
    if data["diagnosed_media"]:
        diag_text += f"（{' / '.join(data['diagnosed_media'])}）"
    _row("URL診断：", diag_text)

    sg_text = "登録済み" if data["has_style_guide"] else "未登録"
    if data["has_style_guide"]:
        sg = data["style_guide"]
        if sg.get("tone"):
            sg_text += f"  トーン：{sg['tone']}"
    _row("スタイルガイド：", sg_text)
    pdf.ln(4)

    # ── 登録媒体と広告費 ──
    _divider()
    _section("登録媒体・広告費")
    if data["media_list"]:
        for m in data["media_list"]:
            fee_text = f"{m['fee']:,}円/月" if m["fee"] else "無料"
            _row(f"  {m['label']}：", fee_text)
        pdf.set_font("NotoSansJP", style="B", size=11)
        pdf.cell(W, 8, f"合計広告費：{data['total_ad_cost']:,}円/月", new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.cell(W, 8, "登録なし", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # ── 今月のおすすめアクション ──
    _divider()
    _section("今月のおすすめアクション")
    pdf.set_font("NotoSansJP", size=11)
    for line in recommendations.splitlines():
        if line.strip():
            pdf.multi_cell(W, 8, line.strip(), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # ── フッター ──
    _divider()
    pdf.set_font("NotoSansJP", size=9)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(W, 6, "Powered by まるちゃん（AI飲食店経営コンサルタント）", new_x="LMARGIN", new_y="NEXT", align="C")

    return bytes(pdf.output())


# ──────────────────────────────────────────────────────────
# LINE 送信用テキスト生成
# ──────────────────────────────────────────────────────────

def build_line_text(data: dict, recommendations: str) -> str:
    """LINE 送信用の月次レポートテキストを生成する。"""
    diag_text = f"{data['url_diagnosis_count']}回"
    if data["diagnosed_media"]:
        diag_text += f"（{' / '.join(data['diagnosed_media'])}）"

    sg_text = "登録済み ✅" if data["has_style_guide"] else "未登録 ⚠️"

    lines = [
        f"📊 {data['year']}年{data['month']}月 月次レポート",
        f"【{data['store_name']}】",
        "",
        "━━ 先月の活動 ━━",
        f"💬 会話件数：{data['total_messages']}件",
        f"📸 AI写真改善案：{data['photo_analysis_count']}回",
        f"🔍 URL診断：{diag_text}",
        f"🎨 スタイルガイド：{sg_text}",
    ]

    if data["total_ad_cost"]:
        lines += [
            "",
            "━━ 広告費 ━━",
            f"💰 合計：{data['total_ad_cost']:,}円/月",
        ]

    lines += [
        "",
        "━━ 今月のおすすめ ━━",
        recommendations,
        "",
        "📁 詳細レポートをDriveに保存しました！",
    ]

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────
# メイン関数
# ──────────────────────────────────────────────────────────

def generate_monthly_report(store, year: int, month: int) -> str:
    """
    月次レポートを生成して Drive に保存し、LINE 送信用テキストを返す。

    Args:
        store: Store モデルインスタンス
        year: 対象年
        month: 対象月

    Returns:
        LINE 送信用テキスト
    """
    from app.services.drive_service import upload_file

    # データ収集
    data = collect_report_data(store, year, month)

    # Claude でおすすめアクション生成
    recommendations = generate_recommendations(store, data)

    # PDF生成
    try:
        pdf_bytes = build_pdf(data, recommendations)
        filename = f"monthly_report_{data['year_month']}.pdf"
        upload_file(store, pdf_bytes, filename, "application/pdf")
        logger.info("月次レポートPDF保存完了 | store_id=%s month=%s", store.id, data["year_month"])
        drive_saved = True
    except Exception as e:
        logger.error("月次レポートPDF生成/保存失敗: %s", e)
        drive_saved = False

    # LINE用テキスト生成
    line_text = build_line_text(data, recommendations)
    if not drive_saved:
        line_text = line_text.replace("📁 詳細レポートをDriveに保存しました！", "（Drive保存に失敗しました💦）")

    logger.info("月次レポート生成完了 | store_id=%s month=%s", store.id, data["year_month"])
    return line_text
