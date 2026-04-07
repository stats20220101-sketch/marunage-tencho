"""
Pillow を使って画像にテキストを合成するサービス。
フォント・文字色・位置はスタイルガイドから参照する。
"""

import io
import logging

from PIL import Image, ImageDraw, ImageFont

from app.services.font_service import get_font_path

logger = logging.getLogger(__name__)

# テキスト位置のマージン（画像の短辺に対する比率）
MARGIN_RATIO = 0.05

# フォントサイズの初期値（画像幅に対する比率）
FONT_SIZE_RATIO = 0.07

# 影のオフセット（px）
SHADOW_OFFSET = 3


def overlay_text(
    image_data: bytes,
    text: str,
    font_style: str = "modern",
    text_color: str = "#FFFFFF",
    position: str = "bottom",
) -> bytes:
    """
    画像にテキストを合成して返す。

    Args:
        image_data: 元画像のバイトデータ
        text: 合成するテキスト
        font_style: フォントスタイルキー
        text_color: 文字色（#RRGGBB形式）
        position: "top" / "center" / "bottom"

    Returns:
        合成後の画像バイトデータ（JPEG）
    """
    img = Image.open(io.BytesIO(image_data)).convert("RGBA")
    width, height = img.size

    font_size = max(24, int(width * FONT_SIZE_RATIO))
    font_path = get_font_path(font_style)
    font = ImageFont.truetype(str(font_path), font_size)

    # テキスト描画用レイヤー
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # テキストサイズを計測してレイアウトを決める
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    margin = int(min(width, height) * MARGIN_RATIO)
    x = (width - text_width) // 2

    if position == "top":
        y = margin
    elif position == "center":
        y = (height - text_height) // 2
    else:  # bottom
        y = height - text_height - margin

    # 半透明の黒帯（可読性向上）
    band_padding = int(text_height * 0.4)
    band_top = y - band_padding
    band_bottom = y + text_height + band_padding
    band = Image.new("RGBA", img.size, (0, 0, 0, 0))
    band_draw = ImageDraw.Draw(band)
    band_draw.rectangle([(0, band_top), (width, band_bottom)], fill=(0, 0, 0, 140))
    overlay = Image.alpha_composite(overlay, band)
    draw = ImageDraw.Draw(overlay)

    # 影（読みやすさ向上）
    shadow_color = (0, 0, 0, 180)
    draw.text((x + SHADOW_OFFSET, y + SHADOW_OFFSET), text, font=font, fill=shadow_color)

    # 本文テキスト
    rgb = _hex_to_rgba(text_color)
    draw.text((x, y), text, font=font, fill=rgb)

    # RGBA → RGB に変換してJPEGとして返す
    result = Image.alpha_composite(img, overlay).convert("RGB")
    buf = io.BytesIO()
    result.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _hex_to_rgba(hex_color: str, alpha: int = 255) -> tuple:
    """#RRGGBB または #RGB を (R, G, B, A) タプルに変換する。"""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return (r, g, b, alpha)
