import base64
import io
import json
import logging

import anthropic
import openai
from PIL import Image
from flask import current_app

logger = logging.getLogger(__name__)

# TODO: URL診断機能（媒体ページの自動スコアリング）を実装予定
# TODO: 月次レポート自動生成機能を実装予定


def _resize_for_openai(image_data: bytes, max_side: int = 1024, jpeg_quality: int = 92) -> tuple[bytes, str]:
    """
    OpenAI API送信前に画像を縮小＋再圧縮してメモリ消費を抑える。
    input_fidelity=high で使うため画質はやや高めにする（quality=92）。

    Returns:
        (縮小後のバイト列, mime_type)  # mime_type は常に "image/jpeg"
    """
    with Image.open(io.BytesIO(image_data)) as img:
        img = img.convert("RGB")
        img.thumbnail((max_side, max_side), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
        return buf.getvalue(), "image/jpeg"


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
        "この飲食店の写真を見て、SNS・グルメサイト掲載用としての"
        "ワンポイントアドバイスを返してください。\n\n"
        "【厳守ルール】\n"
        "・最も効果が大きい改善ポイントを1つだけ選ぶ\n"
        "・全体で120字以内\n"
        "・「何を」「どうやって」「なぜ」を1〜2文で完結\n"
        "・専門用語禁止、絵文字は1〜2個までに抑える\n"
        "・タイトルや見出し、複数の番号付きリスト・箇条書き禁止\n"
        "・観点（明るさ／構図／盛り付け／背景／SNS映え）の中から1つだけ選ぶ\n\n"
        "出力例：\n"
        "「左上から自然光が当たるよう窓際で撮ると料理の照りが出ます✨"
        "今は影が暗めなので、明るさが+1段階だとシズル感UP！」"
    )

    image_b64 = base64.standard_b64encode(image_data).decode("utf-8")

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
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
    料理写真を gpt-image-1 でリタッチする。

    参考写真は登録時に analyze_reference_photos で抽出されたテキストスタイル
    （style_guide["photo_style_en"] 等）をプロンプトに埋め込む形で使用する。
    元画像1枚だけをAPIに送るためメモリ消費を抑えつつ、参考写真の特徴を反映できる。

    Args:
        image_data: 元画像のバイトデータ
        media_type: 元画像のMIMEタイプ
        store_name: 店舗名（コンテキスト用）
        style_guide: スタイルガイドdict（photo_style_en, tone, world_view, keywordsを含む）

    Returns:
        gpt-image-1 が生成したリタッチ画像のバイトデータ（PNG）
    """
    # スタイルガイドを英語コンテキストに整形
    photo_style_en = ""
    style_context = ""
    if style_guide:
        photo_style_en = (style_guide.get("photo_style_en") or "").strip()
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

    # 料理を作り変えないよう強い制約を最初に置く
    preservation_rules = (
        "CRITICAL RULES (must follow strictly):\n"
        "- Do NOT generate, replace, recreate, restyle, or rearrange any food items.\n"
        "- Do NOT change the shape, size, count, quantity, position, or species of any ingredient.\n"
        "- Do NOT change plates, dishware, garnishes, utensils, or background objects.\n"
        "- Treat this as a professional photo retouching task: only adjust lighting, "
        "white balance, color temperature, contrast, saturation, sharpness, and minor "
        "background blur. Pixel-level structure of the food must remain identical.\n"
    )

    if photo_style_en:
        prompt_text = (
            preservation_rules
            + "\nApply the following target style ONLY to lighting and color, "
            f"never to the food itself: {photo_style_en}.\n"
            "Result should look like the same photo professionally retouched, "
            "appetizing for SNS and food delivery sites."
            f"{store_context}{style_context}"
        )
    else:
        prompt_text = (
            preservation_rules
            + "\nProfessionally retouch the lighting and color so the photo looks "
            "appetizing for SNS and food delivery sites. Subject and composition "
            "must remain the same."
            f"{store_context}{style_context}"
        )

    # 送信前に元画像を1024px・JPEG85に圧縮（OOM対策）
    try:
        src_small, _ = _resize_for_openai(image_data)
    except Exception as e:
        logger.warning("元画像リサイズ失敗、原本を使用: %s", e)
        src_small = image_data

    src_buf = io.BytesIO(src_small)
    src_buf.name = "source.jpg"

    import time
    t_start = time.time()
    logger.info(
        "gpt-image-1 リタッチ開始 | store=%s src_bytes=%d style_len=%d",
        store_name, len(src_small), len(photo_style_en),
    )
    try:
        # APIクライアントは120秒でタイムアウト（gunicornの240秒以内に収める）
        openai_client = openai.OpenAI(
            api_key=current_app.config["OPENAI_API_KEY"],
            timeout=120.0,
        )
        response = openai_client.images.edit(
            model="gpt-image-1",
            image=src_buf,
            prompt=prompt_text,
            size="1024x1024",
            quality="high",
            input_fidelity="high",
            n=1,
        )
        image_b64_result = response.data[0].b64_json
        result_bytes = base64.b64decode(image_b64_result)
        elapsed = time.time() - t_start
        logger.info(
            "gpt-image-1 リタッチ完了 | store=%s elapsed=%.1fs result_bytes=%d",
            store_name, elapsed, len(result_bytes),
        )
        return result_bytes
    except Exception as e:
        elapsed = time.time() - t_start
        logger.error(
            "gpt-image-1 リタッチ失敗 | store=%s elapsed=%.1fs error=%s",
            store_name, elapsed, e,
        )
        raise


def consult(
    user_message: str,
    store,
    conversation_history: list[dict],
    style_guide: dict | None = None,
    media_accounts: list | None = None,
    facts_block: str = "",
) -> str:
    """
    飲食店専門コンサルタント「まるちゃん」として経営相談に回答する。

    Args:
        user_message: ユーザーのメッセージ
        store: Store モデルインスタンス
        conversation_history: 過去の会話履歴
        style_guide: スタイルガイドdict
        media_accounts: 登録済み MediaAccount のリスト
        facts_block: facts_service.format_facts_for_prompt() の出力（過去蓄積された店舗事実）

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

    facts_section = (f"\n{facts_block}\n" if facts_block else "")

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
        f"{style_lines if style_lines else '  （未登録）'}\n"
        f"{facts_section}\n"
        "上記の店舗データ・蓄積された事実を踏まえて、具体的なアドバイスを提供してください。"
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


def extract_store_facts(
    existing_facts: list[dict],
    user_message: str,
    assistant_message: str,
) -> list[dict]:
    """
    最新の会話ターンから店舗の重要事実を抽出/更新する。

    既存の facts に対して、新しい会話で得られた情報を追加・更新・削除する。
    Claudeに既存事実+新会話を渡し、更新後の facts 配列を返してもらう。

    Args:
        existing_facts: 既存の facts のリスト
            [{"category": "...", "text": "...", "updated_at": "..."}, ...]
        user_message: ユーザーの最新メッセージ
        assistant_message: AI の最新返信

    Returns:
        更新後の facts リスト
    """
    client = anthropic.Anthropic(api_key=current_app.config["ANTHROPIC_API_KEY"])

    existing_lines = []
    for f in existing_facts:
        cat = f.get("category", "other")
        text = (f.get("text") or "").strip()
        if text:
            existing_lines.append(f"- [{cat}] {text}")
    existing_block = "\n".join(existing_lines) if existing_lines else "（まだ何もありません）"

    instruction = (
        "あなたは飲食店コンサルの記憶担当アシスタントです。\n"
        "下の『既存の事実リスト』と『最新の会話ターン』を踏まえて、"
        "店舗の重要事実リストを更新してください。\n\n"
        "【カテゴリ】\n"
        "- strength: 店舗の強み・看板メニュー・独自性\n"
        "- challenge: 課題・悩み・伸び悩んでいる点\n"
        "- goal: 目標・KPI・ありたい姿\n"
        "- metric: 客単価・席数・回転率などの数値情報\n"
        "- action: 現在実施中・最近実施した施策\n"
        "- customer: 顧客層の特徴\n"
        "- other: 上記に当てはまらない重要事実\n\n"
        "【ルール】\n"
        "- 雑談やあいさつ等の本質的でない情報は記録しない\n"
        "- 既存事実と矛盾する新情報があれば、新しい方で上書きする\n"
        "- 1事実は1〜2文以内に簡潔に\n"
        "- 推測や決めつけはしない（ユーザーが明示した事実のみ）\n"
        "- 重複を避ける\n"
        "- 全体で最大15件程度に収める\n\n"
        f"【既存の事実リスト】\n{existing_block}\n\n"
        f"【最新の会話ターン】\n"
        f"ユーザー：{user_message}\n"
        f"AI：{assistant_message}\n\n"
        "更新後の事実リストを以下のJSON形式のみで返してください（前後に余分な文字なし）：\n"
        "{\n"
        '  "facts": [\n'
        '    {"category": "strength", "text": "..."},\n'
        '    {"category": "challenge", "text": "..."}\n'
        "  ]\n"
        "}"
    )

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            messages=[{"role": "user", "content": instruction}],
        )
        result_text = response.content[0].text.strip()

        start = result_text.find("{")
        end = result_text.rfind("}") + 1
        if start == -1 or end <= start:
            logger.warning("facts抽出: JSON見つからず | head=%s", result_text[:200])
            return existing_facts

        try:
            parsed = json.loads(result_text[start:end])
        except json.JSONDecodeError as je:
            logger.error("facts抽出JSONパース失敗: %s | head=%s", je, result_text[:200])
            return existing_facts

        from datetime import datetime as _dt
        now_iso = _dt.utcnow().isoformat()
        valid_categories = {
            "strength", "challenge", "goal",
            "metric", "action", "customer", "other",
        }
        new_facts: list[dict] = []
        for f in parsed.get("facts", []):
            cat = f.get("category", "other")
            text = (f.get("text") or "").strip()
            if not text:
                continue
            if cat not in valid_categories:
                cat = "other"
            new_facts.append({
                "category": cat,
                "text": text,
                "updated_at": now_iso,
            })

        logger.info("facts抽出完了 | before=%d after=%d", len(existing_facts), len(new_facts))
        return new_facts

    except Exception as e:
        logger.error("facts抽出失敗: %s", e)
        return existing_facts


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
        + "これらの参考写真から、お店のSNS・媒体展開に適したスタイルを分析してください。\n"
        "店舗スタイルと、リタッチ用の詳細な撮影スタイル記述を両方出してください。\n"
        "photo_style_en は後で英語のAI画像編集プロンプトに組み込むため英語で書いてください。\n\n"
        "以下のJSON形式のみで回答してください（前後に余分なテキストは不要）:\n"
        "{\n"
        '  "tone": "（雰囲気・トーン。例：高級感・洗練された / カジュアル・親しみやすい）",\n'
        '  "world_view": "（世界観・コンセプト。例：モダンなビストロ / アットホームな居酒屋）",\n'
        '  "keywords": ["キーワード1", "キーワード2", "キーワード3"],\n'
        '  "summary": "（写真から読み取れる全体的な印象を2〜3文で）",\n'
        '  "photo_style": {\n'
        '    "lighting": "（照明。例：暖色系の自然光、柔らかい側面光）",\n'
        '    "color_palette": "（色調。例：温かみのあるアンバー系、全体に低彩度）",\n'
        '    "composition": "（構図。例：料理中央・45度俯瞰、余白多め）",\n'
        '    "background": "（背景。例：木目テーブルをぼかし、暗めの色）",\n'
        '    "mood": "（全体の雰囲気。例：落ち着いた上質感、食欲をそそる温かさ）"\n'
        '  },\n'
        '  "photo_style_en": "（上記photo_styleを英語1文でまとめたもの。AIリタッチ用。例：warm natural side-lighting, low-saturation amber palette, 45-degree overhead composition with wooden table blurred in the background, calm upscale mood with appetizing warmth）"\n'
        "}"
    )
    content.append({"type": "text", "text": prompt})

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            messages=[{"role": "user", "content": content}],
        )
        result_text = response.content[0].text.strip()

        # JSON部分のみ抽出
        start = result_text.find("{")
        end = result_text.rfind("}") + 1
        parsed: dict | None = None
        if start != -1 and end > start:
            try:
                parsed = json.loads(result_text[start:end])
            except json.JSONDecodeError as je:
                logger.error(
                    "参考写真解析JSONパース失敗: %s | raw_head=%s",
                    je, result_text[:300],
                )
                parsed = None

        if parsed is None:
            parsed = {
                "tone": "",
                "world_view": "",
                "keywords": [],
                "summary": result_text[:200],
                "photo_style": {},
                "photo_style_en": "",
            }

        logger.info(
            "参考写真解析完了 | store=%s photos=%d photo_style_en_len=%d",
            store_name, len(images), len(parsed.get("photo_style_en", "") or ""),
        )
        return parsed

    except Exception as e:
        logger.error("参考写真解析失敗: %s", e)
        raise


def generate_caption(
    image_data: bytes,
    media_type: str,
    store_name: str = "",
    style_guide: dict | None = None,
    situation: str = "",
    dish_name: str = "",
    reference_content: str = "",
) -> dict:
    """
    投稿用テキストを生成する（媒体別）。

    投稿型媒体（instagram, google）→ SNS投稿用キャプション
    グルメ媒体（hotpepper, tabelog, gurunavi）→ メニュー紹介文

    Args:
        image_data: リタッチ済み画像のバイトデータ
        media_type: 媒体種別
        store_name: 店舗名
        style_guide: スタイルガイドdict
        situation: 投稿の状況（SNS媒体のみ使用）
        dish_name: ユーザーが入力した料理名（必須・推測禁止のキー情報）
        reference_content: 店舗公式ページから取得した本文（情報源として使用）

    Returns:
        {
            "caption": str,       # 本文（SNS投稿）またはメニュー紹介文
            "hashtags": str,      # Instagram のみ
            "story_text": str,    # Instagram のみ
            "best_time": str,     # SNS媒体のみ
        }
    """
    client = anthropic.Anthropic(api_key=current_app.config["ANTHROPIC_API_KEY"])

    is_menu_mode = media_type in ("hotpepper", "tabelog", "gurunavi")

    style_lines = ""
    if style_guide:
        tone = style_guide.get("tone", "")
        world_view = style_guide.get("world_view", "")
        keywords = style_guide.get("keywords", [])
        if tone:
            style_lines += f"・トーン：{tone}\n"
        if world_view:
            style_lines += f"・世界観：{world_view}\n"
        if keywords:
            style_lines += f"・キーワード：{'、'.join(keywords)}\n"

    media_label = {
        "instagram": "Instagram（写真投稿）",
        "google": "Googleビジネスプロフィール（ローカル投稿）",
        "hotpepper": "ホットペッパー（メニュー紹介文）",
        "tabelog": "食べログ（メニュー紹介文）",
        "gurunavi": "ぐるなび（メニュー紹介文）",
    }.get(media_type, media_type)

    # 引用本文（あれば優先情報源として使う）
    reference_block = ""
    if reference_content:
        truncated = reference_content[:3000]
        reference_block = (
            "【店舗公式ページから取得した本文】\n"
            f"{truncated}\n\n"
        )

    # 厳守ルール（共通の幻覚抑制）
    strict_rules = (
        "【厳守ルール（最重要）】\n"
        f"・料理名は『{dish_name}』のみ使用。別の料理名を発明・推測しない\n"
        "・店舗の業態（料理ジャンル）は引用本文から読み取る。引用に書かれていない業態（例：韓国焼肉店なのにピザ店扱い）にしない\n"
        "・引用に無い具体情報（材料、産地、調理時間、店主歴など）を勝手に作らない\n"
        "・引用本文と画像から確認できる情報のみで書く\n"
        "・不明な点は無理に補わず、確実な情報だけで構成する\n"
    )

    if is_menu_mode:
        # グルメサイト共通メニュー紹介文モード（短文）
        media_specific_rules = (
            "【出力仕様（グルメサイト用 メニュー紹介文）】\n"
            f"・caption は『{dish_name}』の超短文メニュー紹介。**20〜30字以内**\n"
            "・グルメサイト（ホットペッパー・食べログ・ぐるなび等）の\n"
            "  メニューリストの説明欄に貼る一言として書く\n"
            "・絵文字・記号はなし、敬体ではなく簡潔な体言止めや「。」止め\n"
            "・hashtags / story_text / best_time / best_time_reason は空文字"
        )
    elif media_type == "instagram":
        media_specific_rules = (
            "【出力仕様（Instagram投稿）】\n"
            "・caption は200〜300字、改行を多用、絵文字も適度に使う\n"
            "・hashtags は20〜25個、店舗のジャンル・地域・料理名をミックス（# で始める）\n"
            "・story_text は10〜18字のストーリーズ用短文\n"
            "・best_time は曜日と時刻を具体的に1つ（例：金曜19時）\n"
            "・best_time_reason は20〜35字でその時間帯がベストな理由を簡潔に"
        )
    else:  # google
        media_specific_rules = (
            "【出力仕様（Googleビジネスプロフィール投稿）】\n"
            "・caption は150〜250字、業務的で敬体、過度な絵文字なし\n"
            "・hashtags / story_text は空文字\n"
            "・best_time は時刻を具体的に1つ（例：11:30）\n"
            "・best_time_reason は20〜35字でその時間帯がベストな理由を簡潔に"
        )

    situation_line = f"投稿の状況：{situation}\n" if situation else ""

    image_b64 = base64.standard_b64encode(image_data).decode("utf-8")

    prompt = (
        (f"店舗名：{store_name}\n" if store_name else "")
        + f"料理名：{dish_name}\n"
        + (situation_line if not is_menu_mode else "")
        + (f"店舗のスタイル：\n{style_lines}\n" if style_lines else "")
        + f"投稿先：{media_label}\n\n"
        + reference_block
        + strict_rules
        + "\n"
        + media_specific_rules
        + "\n\n以下のJSON形式のみで返してください（前後に余分な文字なし）：\n"
        "{\n"
        '  "caption": "本文",\n'
        '  "hashtags": "#xxx ...（該当なしは空文字）",\n'
        '  "story_text": "（該当なしは空文字）",\n'
        '  "best_time": "おすすめ投稿時刻（該当なしは空文字）",\n'
        '  "best_time_reason": "その時間帯がベストな理由（該当なしは空文字）"\n'
        "}"
    )

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1200,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        result_text = response.content[0].text.strip()

        start = result_text.find("{")
        end = result_text.rfind("}") + 1
        parsed: dict | None = None
        if start != -1 and end > start:
            try:
                parsed = json.loads(result_text[start:end])
            except json.JSONDecodeError as je:
                logger.error(
                    "キャプションJSONパース失敗 | media=%s error=%s | raw_head=%s",
                    media_type, je, result_text[:300],
                )
                parsed = None

        if parsed is None:
            parsed = {
                "caption": result_text[:300],
                "hashtags": "",
                "story_text": "",
                "best_time": "",
                "best_time_reason": "",
            }

        logger.info(
            "キャプション生成完了 | media=%s mode=%s caption_len=%d",
            media_type,
            "menu" if is_menu_mode else "sns",
            len(parsed.get("caption", "")),
        )
        return parsed

    except Exception as e:
        logger.error("キャプション生成失敗 | media=%s error=%s", media_type, e)
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
