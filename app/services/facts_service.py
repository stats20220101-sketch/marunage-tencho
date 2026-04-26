"""
店舗の重要事実（facts）の永続化・読み込みを扱うサービス。

会話の中から抽出された店舗固有のファクト（強み、課題、目標、指標、施策など）を
Google Drive 上の facts.json に保存・読み込みする。

スキーマ:
{
  "facts": [
    {
      "category": "strength" | "challenge" | "goal" | "metric" | "action" | "customer" | "other",
      "text": str,
      "updated_at": ISO8601
    },
    ...
  ],
  "last_extracted_at": ISO8601
}
"""
import logging
from datetime import datetime

from app.services.drive_service import save_json_file, load_json_file

logger = logging.getLogger(__name__)

FACTS_FILENAME = "facts.json"

DEFAULT_FACTS: dict = {
    "facts": [],
    "last_extracted_at": None,
}

VALID_CATEGORIES = {
    "strength",
    "challenge",
    "goal",
    "metric",
    "action",
    "customer",
    "other",
}

CATEGORY_LABELS_JA = {
    "strength": "強み",
    "challenge": "課題",
    "goal": "目標",
    "metric": "指標",
    "action": "実施中の施策",
    "customer": "顧客層",
    "other": "その他",
}


def load_store_facts(store) -> dict:
    """店舗のファクト情報を読み込む（無ければデフォルト）。"""
    data = load_json_file(store, FACTS_FILENAME)
    if data is None:
        return {**DEFAULT_FACTS, "facts": []}
    # 互換性ガード
    if not isinstance(data.get("facts"), list):
        data["facts"] = []
    return data


def save_store_facts(store, data: dict) -> None:
    """店舗のファクト情報を保存する。"""
    data["last_extracted_at"] = datetime.utcnow().isoformat()
    save_json_file(store, FACTS_FILENAME, data)
    logger.info(
        "店舗facts保存 | store_id=%s count=%d",
        store.id, len(data.get("facts", [])),
    )


def format_facts_for_prompt(facts_data: dict) -> str:
    """
    facts データをClaudeのシステムプロンプト用にカテゴリ別整形する。
    空ならから文字列を返す。
    """
    facts = facts_data.get("facts", [])
    if not facts:
        return ""

    by_cat: dict[str, list[str]] = {}
    for f in facts:
        cat = f.get("category", "other")
        text = (f.get("text") or "").strip()
        if not text:
            continue
        by_cat.setdefault(cat, []).append(text)

    if not by_cat:
        return ""

    lines: list[str] = ["【過去のやり取りで把握した店舗固有の事実】"]
    for cat in ("strength", "challenge", "goal", "metric", "action", "customer", "other"):
        if cat not in by_cat:
            continue
        label = CATEGORY_LABELS_JA[cat]
        lines.append(f"・{label}：")
        for t in by_cat[cat]:
            lines.append(f"    - {t}")
    return "\n".join(lines)


def format_facts_for_display(facts_data: dict) -> str:
    """LINEメッセージ用の表示テキストを返す。"""
    facts = facts_data.get("facts", [])
    if not facts:
        return (
            "📋 店舗プロフィール\n\n"
            "まだ蓄積された情報はありません。\n"
            "AI相談（写真改善以外の経営相談など）を重ねるごとに、\n"
            "あなたのお店の特徴・課題・目標を自動で覚えていきます😊"
        )

    by_cat: dict[str, list[str]] = {}
    for f in facts:
        cat = f.get("category", "other")
        text = (f.get("text") or "").strip()
        if text:
            by_cat.setdefault(cat, []).append(text)

    lines = ["📋 店舗プロフィール\n"]
    icon_map = {
        "strength": "💪",
        "challenge": "🤔",
        "goal": "🎯",
        "metric": "📊",
        "action": "🚀",
        "customer": "👥",
        "other": "🗒",
    }
    for cat in ("strength", "challenge", "goal", "metric", "action", "customer", "other"):
        if cat not in by_cat:
            continue
        icon = icon_map[cat]
        label = CATEGORY_LABELS_JA[cat]
        lines.append(f"{icon} {label}")
        for t in by_cat[cat]:
            lines.append(f"  ・{t}")
        lines.append("")

    last = facts_data.get("last_extracted_at", "")
    if last:
        lines.append(f"（最終更新：{last[:10]}）")
    return "\n".join(lines).rstrip()
