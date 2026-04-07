"""
Google Fonts のフォントファイルを自動ダウンロードしてローカルキャッシュするサービス。
フォントは fonts/ ディレクトリに保存される。
"""

import logging
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

FONTS_DIR = Path(__file__).parent.parent.parent / "fonts"

# Google Fonts GitHub リポジトリからの直接ダウンロードURL
FONT_URLS = {
    "cool": (
        "https://github.com/google/fonts/raw/main/ofl/notoserifjp/NotoSerifJP%5Bwght%5D.ttf",
        "NotoSerifJP.ttf",
    ),
    "modern": (
        "https://github.com/google/fonts/raw/main/ofl/notosansjp/NotoSansJP%5Bwght%5D.ttf",
        "NotoSansJP.ttf",
    ),
    "natural": (
        "https://github.com/google/fonts/raw/main/ofl/kleeone/KleeOne-Regular.ttf",
        "KleeOne-Regular.ttf",
    ),
    "pop": (
        "https://github.com/google/fonts/raw/main/ofl/delagothicone/DelaGothicOne-Regular.ttf",
        "DelaGothicOne-Regular.ttf",
    ),
    "elegant": (
        "https://github.com/google/fonts/raw/main/ofl/shipporimincho/ShipporiMincho-Regular.ttf",
        "ShipporiMincho-Regular.ttf",
    ),
}


def get_font_path(font_style: str) -> Path:
    """
    指定スタイルのフォントファイルパスを返す。
    未ダウンロードの場合は自動でダウンロードする。

    Args:
        font_style: "cool" / "modern" / "natural" / "pop" / "elegant"

    Returns:
        フォントファイルの Path

    Raises:
        ValueError: 未知のフォントスタイル
        RuntimeError: ダウンロード失敗
    """
    if font_style not in FONT_URLS:
        raise ValueError(f"未知のフォントスタイル: {font_style}")

    url, filename = FONT_URLS[font_style]
    font_path = FONTS_DIR / filename

    if not font_path.exists():
        _download_font(url, font_path)

    return font_path


def _download_font(url: str, dest: Path) -> None:
    """フォントファイルをダウンロードして保存する。"""
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("フォントダウンロード開始 | url=%s", url)

    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        dest.write_bytes(response.content)
        logger.info("フォントダウンロード完了 | file=%s size=%d", dest.name, len(response.content))
    except requests.RequestException as e:
        logger.error("フォントダウンロード失敗 | url=%s error=%s", url, e)
        raise RuntimeError(f"フォントのダウンロードに失敗しました: {e}") from e


def ensure_all_fonts() -> None:
    """全フォントをまとめてダウンロードする（起動時・管理コマンド用）。"""
    for style in FONT_URLS:
        get_font_path(style)
