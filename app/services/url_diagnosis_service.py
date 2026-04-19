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
        "繁盛店の典型パターン：\n"
        "・料理写真20枚以上／内装3〜5枚／外観1〜2枚を揃えている\n"
        "・メイン写真はシズル感のある料理アップか、活気のある店内\n"
        "・明るい自然光で撮影され、全体のトーンが統一されている\n"
        "・看板メニューが必ずトップ近くに配置されている\n"
        "この典型と抜粋情報を比較し、差分から最重要の改善TOP3を出してください。"
    ),
    "description": (
        "【診断項目：説明文・コンセプト】\n"
        "繁盛店の典型パターン：\n"
        "・キャッチコピーに数字・固有名詞・独自性が入っている（例：厳選30種の韓国焼肉）\n"
        "・誰向け・何が売りかが1行で分かる\n"
        "・地名＋ジャンル＋特徴のキーワードが入り検索に強い\n"
        "・料理の背景ストーリー（産地・仕入先・職人歴）で差別化している\n"
        "この典型と抜粋情報を比較し、差分から最重要の改善TOP3を出してください。"
    ),
    "hours": (
        "【診断項目：営業時間・アクセス情報】\n"
        "繁盛店の典型パターン：\n"
        "・営業時間・定休日・ラストオーダー・ランチ/ディナー区分が全て明記\n"
        "・最寄り駅からの徒歩分数と道順の目印（1行程度）がある\n"
        "・予約方法（ネット／電話／席指定）が選びやすく整理されている\n"
        "・駐車場・喫煙可否・個室有無など来店判断に必要な情報が揃っている\n"
        "この典型と抜粋情報を比較し、差分から最重要の改善TOP3を出してください。"
    ),
    "menu": (
        "【診断項目：メニュー・価格設定】\n"
        "繁盛店の典型パターン：\n"
        "・看板メニュー3つを写真＋価格＋一言説明でトップに配置\n"
        "・客単価帯（ランチ/ディナー）が明記されていて選びやすい\n"
        "・コース・食べ飲み放題で「初来店のおすすめ」を1つ明示\n"
        "・季節メニュー／限定メニューで更新感がある\n"
        "この典型と抜粋情報を比較し、差分から最重要の改善TOP3を出してください。"
    ),
    "review": (
        "【診断項目：口コミ・レビュー対応】\n"
        "繁盛店の典型パターン：\n"
        "・口コミ件数が同エリア同ジャンル平均以上（評価3.5以上が目安）\n"
        "・高評価・低評価どちらにもオーナー返信があり、返信は具体的で温度感がある\n"
        "・ネガティブな口コミには改善報告を添えて返信している\n"
        "・来店後に口コミ投稿を促す導線（卓上POP・LINE等）を持っている\n"
        "この典型と抜粋情報を比較し、差分から最重要の改善TOP3を出してください。"
    ),
    "all": (
        "【総合診断】\n"
        "繁盛店の掲載ページに共通する特徴：\n"
        "・写真が20枚以上あり看板メニューが目立つ\n"
        "・キャッチコピーに数字や固有名詞で独自性が出ている\n"
        "・営業時間・アクセス・予約方法が迷わず分かる\n"
        "・看板メニュー3つが写真＋価格で強調されている\n"
        "・口コミにオーナー返信がしっかり付いている\n"
        "抜粋情報とこの典型を比較し、このお店が最優先で直すべきTOP3を"
        "項目横断で選んで出してください。"
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
        "あなたはホットペッパー・食べログ・Googleマイビジネスで上位表示される"
        "繁盛店の掲載ページ構成を熟知した飲食店Web集客コンサルタントです。\n"
        "繁盛店との差分に絞って、今すぐ直すべき改善点だけを伝えます。\n\n"
        "【厳守ルール（最重要）】\n"
        "・提供された「ページの内容（抜粋）」に明記されていない情報（住所・エリア・営業時間・メニュー名・価格など）は絶対に書かない\n"
        "・一般論や推測で具体的な事実を補完しない\n"
        "・抜粋内で確認できない項目は「抜粋範囲内では確認できませんでした」と明示する\n\n"
        "【出力フォーマット（厳守・全体400字以内）】\n"
        "🏁 現状\n"
        "（1〜2行で抜粋から読み取れる状態を要約）\n\n"
        "🎯 改善TOP3（優先度順）\n"
        "1. ［改善項目名］\n"
        "　繁盛店：〜（典型パターンを1行で）\n"
        "　現状：〜（抜粋から読み取れる状態を1行で／不明なら「抜粋範囲内では確認できませんでした」）\n"
        "　対策：〜（今週できる具体行動を1行で。例：『料理写真を10枚追加』『キャッチコピーに「炭火焼20種」と数字を入れる』）\n"
        "2. ［改善項目名］（同じ3行構成）\n"
        "3. ［改善項目名］（同じ3行構成）\n\n"
        "💡 強み\n"
        "（既に出来ている点を1行だけ）\n\n"
        "【表現ルール】\n"
        "・抽象語（魅力的・もっと工夫）禁止。必ず数字や具体アクションで書く\n"
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
