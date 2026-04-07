"""
店舗スタイルガイドの保存・読み込みサービス。
データは Google Drive の店舗フォルダに style_guide.json として保存する。
"""

import logging
from app.services.drive_service import load_json_file, save_json_file

logger = logging.getLogger(__name__)

STYLE_GUIDE_FILENAME = "style_guide.json"

FONT_CHOICES = {
    "1": {"key": "cool",     "label": "クール（Noto Serif JP）- シャープ・高級感"},
    "2": {"key": "modern",   "label": "モダン（Noto Sans JP）- すっきり・都会的"},
    "3": {"key": "natural",  "label": "ナチュラル（Klee One）- 手書き風・温かみ"},
    "4": {"key": "pop",      "label": "ポップ（Dela Gothic One）- 元気・賑やか"},
    "5": {"key": "elegant",  "label": "エレガント（Shippori Mincho）- 上品・女性向け"},
}

FONT_MENU = "\n".join(f"{k}. {v['label']}" for k, v in FONT_CHOICES.items())

COLOR_ALIASES = {
    "白": "#FFFFFF",
    "黒": "#000000",
    "赤": "#FF0000",
    "青": "#0000FF",
    "黄": "#FFFF00",
    "オレンジ": "#FF8C00",
    "ピンク": "#FF69B4",
    "緑": "#228B22",
    "金": "#FFD700",
    "グレー": "#808080",
}

DEFAULT_STYLE_GUIDE = {
    "tone": "",
    "world_view": "",
    "keywords": [],
    "font_style": "modern",
    "text_color": "#FFFFFF",
    "text_position": "bottom",
}


def save_style_guide(store, data: dict) -> None:
    """スタイルガイドをDriveに保存する。"""
    save_json_file(store, STYLE_GUIDE_FILENAME, data)
    logger.info("スタイルガイド保存 | store_id=%s", store.id)


def load_style_guide(store) -> dict:
    """
    スタイルガイドをDriveから読み込む。
    未登録の場合はデフォルト値を返す。
    """
    data = load_json_file(store, STYLE_GUIDE_FILENAME)
    if data is None:
        return DEFAULT_STYLE_GUIDE.copy()
    return {**DEFAULT_STYLE_GUIDE, **data}


def resolve_color(text: str) -> str:
    """
    「白」「黒」などの日本語色名または #RRGGBB 形式を正規化して返す。
    認識できない場合は "#FFFFFF" を返す。
    """
    text = text.strip()
    if text in COLOR_ALIASES:
        return COLOR_ALIASES[text]
    if text.startswith("#") and len(text) in (4, 7):
        return text.upper()
    return "#FFFFFF"


def format_style_guide_summary(data: dict) -> str:
    """確認表示用のサマリーテキストを生成する。"""
    font_label = next(
        (v["label"] for v in FONT_CHOICES.values() if v["key"] == data.get("font_style")),
        data.get("font_style", ""),
    )
    keywords = "、".join(data.get("keywords", [])) or "（なし）"
    return (
        "【スタイルガイド登録内容】\n\n"
        f"🎯 トーン：{data.get('tone', '')}\n"
        f"🌍 世界観：{data.get('world_view', '')}\n"
        f"🔑 キーワード：{keywords}\n"
        f"🖋 フォント：{font_label}\n"
        f"🎨 文字色：{data.get('text_color', '')}\n\n"
        "この内容で登録する？\n\n"
        "1. 登録する\n"
        "2. やり直す"
    )
