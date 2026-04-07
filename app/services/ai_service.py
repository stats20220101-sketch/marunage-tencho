import base64
import json
import logging

import anthropic
import openai
from flask import current_app

logger = logging.getLogger(__name__)

# TODO: URL診断機能（媒体ページの自動スコアリング）を実装予定
# TODO: 月次レポート自動生成機能を実装予定


def analyze_food_image(
    image_data: bytes,
    media_type: str = "image/jpeg",
    store_name: str = "",
    style_guide: dict | None = None,
) -> str:
    """
    料理・店内写真をClaudeに渡して改善案を生成する。

    AIは提案するだけ。実行はしない（4原則に準拠）。

    Args:
        image_data: 画像のバイトデータ
        media_type: 画像のMIMEタイプ
        store_name: 店舗名（コンテキスト用）
        style_guide: スタイルガイドdict（tone/world_view/keywords）

    Returns:
        改善案のテキスト
    """
    client = anthropic.Anthropic(api_key=current_app.config["ANTHROPIC_API_KEY"])

    store_context = f"店舗名：{store_name}\n" if store_name else ""

    style_context = ""
    if style_guide:
        tone = style_guide.get("tone", "")
        world_view = style_guide.get("world_view", "")
        keywords = style_guide.get("keywords", [])
        if tone or world_view or keywords:
            style_context = (
                "\n【店舗のスタイルガイド】\n"
                + (f"・トーン：{tone}\n" if tone else "")
                + (f"・世界観：{world_view}\n" if world_view else "")
                + (f"・キーワード：{'、'.join(keywords)}\n" if keywords else "")
                + "上記のスタイルに合った改善案を提案してください。\n"
            )

    prompt = (
        f"{store_context}"
        f"{style_context}"
        "この飲食店の写真を見て、SNS・グルメサイト掲載用として改善できる点を教えてください。\n\n"
        "以下の観点で具体的にアドバイスしてください：\n"
        "1. 写真の明るさ・色味\n"
        "2. 構図・アングル\n"
        "3. 料理の見せ方・盛り付け\n"
        "4. 背景・小物の使い方\n"
        "5. SNS映えのポイント\n\n"
        "改善案は箇条書きで、具体的かつ実践しやすい内容でお願いします。"
    )

    image_b64 = base64.standard_b64encode(image_data).decode("utf-8")

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }
            ],
        )

        result = message.content[0].text
        logger.info("AI改善案生成完了 | store=%s", store_name)
        return result

    except Exception as e:
        logger.error("AI改善案生成失敗: %s", e)
        return "申し訳ありません、AI分析に失敗しました。もう一度試してみてください。"


def generate_improved_photo(
    image_data: bytes,
    media_type: str = "image/jpeg",
    store_name: str = "",
    style_guide: dict | None = None,
) -> bytes:
    """
    料理写真をClaudeで分析してDALL-E 3用プロンプトを生成し、
    改善イメージ画像をDALL-E 3で生成して返す。

    処理フロー:
        1. Claude Vision で元写真を分析 → 英語プロンプト生成
        2. DALL-E 3 で改善イメージ画像を生成（1024×1024）
        3. 生成画像のバイトデータを返す

    Args:
        image_data: 元画像のバイトデータ
        media_type: 元画像のMIMEタイプ
        store_name: 店舗名（コンテキスト用）
        style_guide: スタイルガイドdict

    Returns:
        DALL-E 3が生成した画像のバイトデータ（JPEG）
    """
    claude_client = anthropic.Anthropic(api_key=current_app.config["ANTHROPIC_API_KEY"])

    # スタイルガイドを整形
    style_context = ""
    if style_guide:
        tone = style_guide.get("tone", "")
        world_view = style_guide.get("world_view", "")
        keywords = style_guide.get("keywords", [])
        parts = []
        if tone:
            parts.append(f"tone: {tone}")
        if world_view:
            parts.append(f"concept: {world_view}")
        if keywords:
            parts.append(f"keywords: {', '.join(keywords)}")
        if parts:
            style_context = f" The restaurant's style is: {'; '.join(parts)}."

    store_context = f" The restaurant is called '{store_name}'." if store_name else ""

    prompt_gen_instruction = (
        "Look at this food/restaurant photo and create a DALL-E 3 prompt "
        "for generating an improved version of this image optimized for SNS and food delivery sites."
        f"{store_context}{style_context}\n\n"
        "The prompt should describe:\n"
        "- The dish or scene in detail\n"
        "- Improved lighting (bright, natural light or warm studio lighting)\n"
        "- Better composition and plating/styling\n"
        "- A clean, appetizing presentation\n"
        "- Professional food photography style\n\n"
        "Return ONLY the English prompt text for DALL-E 3. "
        "Do not include any explanation or extra text. "
        "Keep it under 800 characters."
    )

    image_b64 = base64.standard_b64encode(image_data).decode("utf-8")

    # Step 1: Claude でDALL-E 3用プロンプト生成
    try:
        claude_resp = claude_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": prompt_gen_instruction},
                    ],
                }
            ],
        )
        dalle_prompt = claude_resp.content[0].text.strip()
        logger.info("DALL-E 3プロンプト生成完了 | store=%s prompt_len=%d", store_name, len(dalle_prompt))
    except Exception as e:
        logger.error("DALL-E 3プロンプト生成失敗: %s", e)
        raise

    # Step 2: DALL-E 3 で画像生成
    try:
        openai_client = openai.OpenAI(api_key=current_app.config["OPENAI_API_KEY"])
        response = openai_client.images.generate(
            model="dall-e-3",
            prompt=dalle_prompt,
            size="1024x1024",
            quality="standard",
            response_format="b64_json",
            n=1,
        )
        image_b64_result = response.data[0].b64_json
        result_bytes = base64.b64decode(image_b64_result)
        logger.info("DALL-E 3画像生成完了 | store=%s", store_name)
        return result_bytes
    except Exception as e:
        logger.error("DALL-E 3画像生成失敗: %s", e)
        raise


def consult(
    user_message: str,
    store,
    conversation_history: list[dict],
    style_guide: dict | None = None,
    media_accounts: list | None = None,
) -> str:
    """
    飲食店専門コンサルタント「まるちゃん」として経営相談に回答する。

    毎回のリクエストに店舗データ（名前・媒体・スタイルガイド）と
    会話の全履歴をコンテキストとして渡す。

    Args:
        user_message: ユーザーのメッセージ
        store: Store モデルインスタンス
        conversation_history: 過去の会話履歴
            [{"role": "user"|"assistant", "content": str}, ...]
            ※ 現在はフル履歴。将来は直近3ヶ月＋重要サマリー方式に移行予定。
        style_guide: スタイルガイドdict
        media_accounts: 登録済み MediaAccount のリスト

    Returns:
        AIの回答テキスト
    """
    client = anthropic.Anthropic(api_key=current_app.config["ANTHROPIC_API_KEY"])

    # 媒体情報を整形
    media_lines = ""
    if media_accounts:
        for m in media_accounts:
            label = _MEDIA_LABELS.get(m.media_type, m.media_type)
            url_part = f"（{m.url}）" if m.url else ""
            fee_part = f"月額{m.monthly_fee:,}円" if m.monthly_fee else "費用不明"
            media_lines += f"  ・{label}{url_part}：{fee_part}\n"

    # スタイルガイドを整形
    style_lines = ""
    if style_guide:
        tone = style_guide.get("tone", "")
        world_view = style_guide.get("world_view", "")
        keywords = style_guide.get("keywords", [])
        if tone:
            style_lines += f"  ・トーン：{tone}\n"
        if world_view:
            style_lines += f"  ・世界観：{world_view}\n"
        if keywords:
            style_lines += f"  ・キーワード：{'、'.join(keywords)}\n"

    system_prompt = (
        "あなたは飲食店専門の経営コンサルタント「まるちゃん」です。\n\n"
        "【キャラクター設定】\n"
        "・プロフェッショナルで頼れる口調（友達っぽくなく、でも親しみやすい）\n"
        "・語尾は「〜ですね」「〜しましょう」「〜がポイントです」など丁寧だが堅苦しくない\n"
        "・絵文字は適度に使う（多用しない）\n"
        "・回答はLINEで送るため500文字以内にまとめ、読みやすい改行を入れる\n\n"
        "【得意分野】\n"
        "・集客・SNS改善\n"
        "・媒体（グルメサイト）の改善\n"
        "・メニュー・写真改善\n"
        "・経営相談全般\n\n"
        "【担当店舗情報】\n"
        f"店舗名：{store.name}\n"
        "登録媒体：\n"
        f"{media_lines if media_lines else '  （未登録）'}\n"
        "スタイルガイド：\n"
        f"{style_lines if style_lines else '  （未登録）'}\n\n"
        "上記の店舗データを踏まえた上で、具体的なアドバイスを提供してください。"
    )

    # 会話履歴 ＋ 今回のメッセージ
    messages = list(conversation_history) + [
        {"role": "user", "content": user_message}
    ]

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
        )
        result = response.content[0].text
        logger.info("コンサル回答生成完了 | store=%s", store.name)
        return result

    except Exception as e:
        logger.error("コンサル回答生成失敗: %s", e)
        return "申し訳ありません、うまく回答できませんでした。もう一度試してみてください。"


def analyze_reference_photos(
    images: list[dict],
    store_name: str = "",
) -> dict:
    """
    参考写真（最大3枚）からお店のスタイルを自動抽出する。

    Args:
        images: [{"data": bytes, "media_type": str}, ...] 形式のリスト
        store_name: 店舗名（コンテキスト用）

    Returns:
        {
            "tone": str,           # トーン・雰囲気
            "world_view": str,     # 世界観・コンセプト
            "keywords": list[str], # キーワード
            "summary": str,        # 全体的な印象（2〜3文）
        }
    """
    client = anthropic.Anthropic(api_key=current_app.config["ANTHROPIC_API_KEY"])

    content: list[dict] = []

    for img in images:
        image_b64 = base64.standard_b64encode(img["data"]).decode("utf-8")
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": img.get("media_type", "image/jpeg"),
                    "data": image_b64,
                },
            }
        )

    prompt = (
        (f"店舗名：{store_name}\n" if store_name else "")
        + "これらの参考写真から、お店のSNS・媒体展開に適したスタイルを分析してください。\n\n"
        "以下のJSON形式のみで回答してください（前後に余分なテキストは不要）:\n"
        "{\n"
        '  "tone": "（雰囲気・トーン。例：高級感・洗練された / カジュアル・親しみやすい）",\n'
        '  "world_view": "（世界観・コンセプト。例：モダンなビストロ / アットホームな居酒屋）",\n'
        '  "keywords": ["キーワード1", "キーワード2", "キーワード3"],\n'
        '  "summary": "（写真から読み取れる全体的な印象を2〜3文で）"\n'
        "}"
    )
    content.append({"type": "text", "text": prompt})

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": content}],
        )
        result_text = response.content[0].text.strip()

        # JSON部分のみ抽出
        start = result_text.find("{")
        end = result_text.rfind("}") + 1
        if start != -1 and end > start:
            parsed = json.loads(result_text[start:end])
        else:
            parsed = {
                "tone": "",
                "world_view": "",
                "keywords": [],
                "summary": result_text,
            }

        logger.info("参考写真解析完了 | store=%s photos=%d", store_name, len(images))
        return parsed

    except Exception as e:
        logger.error("参考写真解析失敗: %s", e)
        raise


# ──────────────────────────────────────────────────────────
# 内部定数
# ──────────────────────────────────────────────────────────

_MEDIA_LABELS = {
    "hotpepper": "ホットペッパー",
    "tabelog": "食べログ",
    "gurunavi": "ぐるなび",
    "google": "Googleマイビジネス",
    "instagram": "インスタグラム",
}
