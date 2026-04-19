"""
飲食店掲載ページのURL診断サービス。

処理フロー:
    1. requests で対象URLのHTMLを取得
    2. BeautifulSoup でテキストを抽出
    3. Claude に診断プロンプトを渡して改善案を生成
    4. 結果を dict で返す（line_handler 側で Drive 保存）
"""

import logging
from datetime import datetime

import anthropic
import requests
from bs4 import BeautifulSoup
from flask import current_app

logger = logging.getLogger(__name__)

# 診断モード定義
DIAGNOSIS_MODES = {
    "1": {"key": "all",         "label": "総合診断（全項目）"},
    "2": {"key": "photo",       "label": "写真・ビジュアル"},
    "3": {"key": "description", "label": "説明文・コンセプト"},
    "4": {"key": "hours",       "label": "営業時間・アクセス情報"},
    "5": {"key": "menu",        "label": "メニュー・価格設定"},
    "6": {"key": "review",      "label": "口コミ・レビュー対応"},
}

DIAGNOSIS_MENU_TEXT = (
    "診断モードを選んでください📋\n\n"
    + "\n".join(f"{k}. {v['label']}" for k, v in DIAGNOSIS_MODES.items())
)

# 診断モード別プロンプト
_MODE_PROMPTS = {
    "photo": (
        "【診断項目：写真・ビジュアル】\n"
        "以下の観点で評価・改善案を提示してください：\n"
        "・トップ画像・メイン写真の魅力度\n"
        "・写真の枚数・種類の充実度（料理/内装/外観/スタッフ）\n"
        "・写真の明るさ・色味・構図\n"
        "・SNS映えするビジュアルになっているか"
    ),
    "description": (
        "【診断項目：説明文・コンセプト】\n"
        "以下の観点で評価・改善案を提示してください：\n"
        "・店舗キャッチコピーの魅力度\n"
        "・お店の特徴・強みが伝わっているか\n"
        "・ターゲット顧客に刺さる言葉が使われているか\n"
        "・SEO（検索）に強いキーワードが含まれているか"
    ),
    "hours": (
        "【診断項目：営業時間・アクセス情報】\n"
        "以下の観点で評価・改善案を提示してください：\n"
        "・営業時間・定休日が明確に記載されているか\n"
        "・ランチ/ディナー/テイクアウトなどの区分が分かりやすいか\n"
        "・アクセス情報（最寄り駅・徒歩分数・駐車場）の充実度\n"
        "・電話番号・予約方法が分かりやすいか"
    ),
    "menu": (
        "【診断項目：メニュー・価格設定】\n"
        "以下の観点で評価・改善案を提示してください：\n"
        "・メニューの見やすさ・分かりやすさ\n"
        "・価格帯の表示が適切か\n"
        "・おすすめ・看板メニューが際立っているか\n"
        "・コース・セットメニューの訴求力\n"
        "・アレルギー・ベジタリアン対応の記載"
    ),
    "review": (
        "【診断項目：口コミ・レビュー対応】\n"
        "以下の観点で評価・改善案を提示してください：\n"
        "・口コミの件数・評価点数\n"
        "・オーナーからの返信が適切にされているか\n"
        "・ネガティブな口コミへの対応\n"
        "・口コミを増やすための施策として何ができるか"
    ),
    "all": (
        "【総合診断】\n"
        "以下の5項目を総合的に評価し、改善の優先順位をつけて提示してください：\n"
        "① 写真・ビジュアル\n"
        "② 説明文・コンセプト\n"
        "③ 営業時間・アクセス情報\n"
        "④ メニュー・価格設定\n"
        "⑤ 口コミ・レビュー対応\n\n"
        "各項目を簡潔に評価し、最も優先すべき改善点を3つ挙げてください。"
    ),
}

# Bot対策回避用ヘッダー
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_FETCH_TIMEOUT = 10  # 秒
_MAX_CONTENT_CHARS = 12000  # Claudeに渡すテキストの上限


def fetch_page_text(url: str) -> str:
    """
    URLからHTMLを取得してプレーンテキストを抽出する。

    Args:
        url: 診断対象のURL

    Returns:
        抽出されたテキスト（最大 _MAX_CONTENT_CHARS 文字）

    Raises:
        ValueError: URLが取得できない場合
        RuntimeError: テキスト抽出に失敗した場合
    """
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_FETCH_TIMEOUT)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
    except requests.exceptions.Timeout:
        raise ValueError("ページの読み込みがタイムアウトしました。時間をおいて再試行してください。")
    except requests.exceptions.HTTPError as e:
        raise ValueError(f"ページの取得に失敗しました（{e.response.status_code}）。URLを確認してください。")
    except requests.exceptions.RequestException as e:
        raise ValueError(f"ページへのアクセスに失敗しました: {e}")

    soup = BeautifulSoup(resp.text, "html.parser")

    # script・style・nav等の不要タグを除去
    for tag in soup(["script", "style", "nav", "footer", "iframe", "noscript"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)

    # 連続する空行を圧縮
    lines = [line for line in text.splitlines() if line.strip()]
    text = "\n".join(lines)

    if not text:
        raise RuntimeError("ページからテキストを抽出できませんでした。")

    return text[:_MAX_CONTENT_CHARS]


def diagnose_url(
    url: str,
    page_text: str,
    media_type: str,
    mode_key: str = "all",
    store_name: str = "",
) -> dict:
    """
    取得済みページテキストをClaudeで診断して改善案を返す。

    Args:
        url: 診断対象のURL
        page_text: fetch_page_text() で取得したテキスト
        media_type: 媒体種別（hotpepper / tabelog / gurunavi / google / instagram）
        mode_key: 診断モードキー（all / photo / description / hours / menu / review）
        store_name: 店舗名（コンテキスト用）

    Returns:
        {
            "url": str,
            "media_type": str,
            "mode": str,
            "mode_label": str,
            "store_name": str,
            "diagnosed_at": str,  # ISO形式
            "result": str,        # 診断結果テキスト
        }
    """
    client = anthropic.Anthropic(api_key=current_app.config["ANTHROPIC_API_KEY"])

    media_labels = {
        "hotpepper": "ホットペッパービューティー/グルメ",
        "tabelog": "食べログ",
        "gurunavi": "ぐるなび",
        "google": "Googleマイビジネス",
        "instagram": "インスタグラム",
    }
    media_label = media_labels.get(media_type, media_type)
    mode_prompt = _MODE_PROMPTS.get(mode_key, _MODE_PROMPTS["all"])
    mode_label = next(
        (v["label"] for v in DIAGNOSIS_MODES.values() if v["key"] == mode_key),
        mode_key,
    )

    store_context = f"店舗名：{store_name}\n" if store_name else ""

    system_prompt = (
        "あなたは飲食店の集客・Web集客の専門コンサルタントです。\n"
        "飲食店の掲載ページを診断し、集客改善に直結する具体的なアドバイスを提供します。\n\n"
        "【厳守ルール（最重要）】\n"
        "・提供された「ページの内容（抜粋）」に明記されていない情報（住所・エリア・営業時間・メニュー名・価格など）は絶対に書かない\n"
        "・一般論や推測で具体的な事実を補完しない（例：掲載媒体の一般的な情報、似た店の傾向などから勝手に住所やエリアを特定しない）\n"
        "・抜粋内で確認できない項目については「抜粋範囲内では確認できませんでした」と明示する\n"
        "・店舗の住所・所在地について言及する場合は、必ず抜粋テキストから該当箇所を引用する形にする\n\n"
        "【回答ルール】\n"
        "・LINEで送るため500文字以内にまとめる\n"
        "・改善点は箇条書きで、優先度が高い順に記載\n"
        "・「すでに良い点」と「改善すべき点」をバランスよく\n"
        "・具体的な行動に落とし込む（「写真を増やす」→「料理写真を最低10枚、内装写真5枚追加する」）\n"
        "・専門用語は使わず、オーナーが自分で実行できる内容にする"
    )

    prompt = (
        f"{store_context}"
        f"【診断媒体】{media_label}\n"
        f"【URL】{url}\n\n"
        f"{mode_prompt}\n\n"
        "【ページの内容（抜粋）】\n"
        f"{page_text}"
    )

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
        )
        result_text = response.content[0].text.strip()
        logger.info(
            "URL診断完了 | store=%s media=%s mode=%s",
            store_name, media_type, mode_key,
        )
    except Exception as e:
        logger.error("URL診断Claude呼び出し失敗: %s", e)
        raise

    return {
        "url": url,
        "media_type": media_type,
        "media_label": media_label,
        "mode": mode_key,
        "mode_label": mode_label,
        "store_name": store_name,
        "diagnosed_at": datetime.utcnow().isoformat(),
        "result": result_text,
    }
