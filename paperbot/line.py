from __future__ import annotations

import uuid

import httpx

from paperbot.models import PaperCandidate, PaperSummary

LINE_PUSH_API = "https://api.line.me/v2/bot/message/push"
LINE_TEXT_LIMIT = 5000


def format_digest(
    paper: PaperCandidate, summary: PaperSummary, model_used: str
) -> list[str]:
    authors = "、".join(summary.authors) if summary.authors else "未提供"
    sections = [
        f"📄 每日論文\n\n標題：{summary.title}\n會議：{summary.venue or paper.venue or '未確認'}"
        f"\n作者：{authors}\n連結：{summary.paper_url or paper.entry_url}\n摘要模型：{model_used}",
        _section("大綱", summary.overview),
        _section("要解決的問題", summary.problem),
        _section("作者提出的方案及架構", summary.solution_architecture),
        _section("成果", summary.results),
        _section("與其他論文比較", summary.comparisons),
        _section("作者明確提出的 Future Work", summary.future_work_explicit),
        _section("可延伸方向（AI 推論）", summary.future_work_inferred),
    ]
    return split_messages("\n\n".join(section for section in sections if section))


def split_messages(text: str, limit: int = 4900) -> list[str]:
    if len(text) <= limit:
        return [text]
    messages: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            messages.append(current)
        while len(paragraph) > limit:
            cut = paragraph.rfind("\n", 0, limit)
            if cut < limit // 2:
                cut = limit
            messages.append(paragraph[:cut])
            paragraph = paragraph[cut:].lstrip()
        current = paragraph
    if current:
        messages.append(current)
    return messages


class LineMessenger:
    def __init__(self, client: httpx.Client, access_token: str, user_id: str):
        self.client = client
        self.access_token = access_token
        self.user_id = user_id

    def send(self, messages: list[str]) -> None:
        for start in range(0, len(messages), 5):
            batch = messages[start : start + 5]
            response = self.client.post(
                LINE_PUSH_API,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json",
                    "X-Line-Retry-Key": str(uuid.uuid4()),
                },
                json={
                    "to": self.user_id,
                    "messages": [{"type": "text", "text": message} for message in batch],
                },
            )
            response.raise_for_status()

    def notify_error(self, detail: str) -> None:
        message = f"⚠️ 每日論文機器人執行失敗\n{detail[:4500]}"
        self.send([message])


def _section(title: str, items: list[str]) -> str:
    if not items:
        return f"【{title}】\n• 未提供"
    return f"【{title}】\n" + "\n".join(f"• {item}" for item in items)

