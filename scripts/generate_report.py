"""
报告生成模块：读取对话记录和结构化信息，用 Jinja2 渲染按月拆分的 HTML 报告。

数据来源：
- conversations/*.md: 矫正后的对话
- insights/*_insights.json: 结构化信息（问题、待办、决策）
- insights/*_meta.json: 元数据（标题、说话人，由 DeepSeek 生成）
"""

import json
import logging
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import markdown
from jinja2 import Environment, FileSystemLoader

from config import OUTPUT_DIR, TEMPLATES_DIR

logger = logging.getLogger("AudioChronolog")


def _extract_speakers(conversation_text: str) -> list[str]:
    """从对话文本中提取所有说话人名称（作为 fallback）。"""
    pattern = r"\*\*(.+?)\*\*[:：]"
    matches = re.findall(pattern, conversation_text)
    seen = set()
    speakers = []
    for m in matches:
        if m not in seen:
            seen.add(m)
            speakers.append(m)
    return speakers


def _highlight_sentences(conversation_html: str, keywords: list[str]) -> str:
    """在对话 HTML 中高亮包含 Action Items 关键词的句子。"""
    if not keywords:
        return conversation_html
    for kw in keywords:
        if not kw or len(kw) < 4:
            continue
        escaped = re.escape(kw)
        conversation_html = re.sub(
            escaped,
            f'<span class="highlight">{kw}</span>',
            conversation_html,
        )
    return conversation_html


def _conversation_to_html(conversation_md: str) -> str:
    """将对话 Markdown 转换为 HTML 段落。"""
    lines = conversation_md.strip().split("\n")
    html_parts = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        converted = markdown.markdown(line)
        html_parts.append(converted)
    return "\n".join(html_parts)


def _find_json_file(insights_dir: Path, stem: str, date_str: str, suffix: str) -> Path | None:
    """查找 JSON 文件，兼容新旧命名格式。"""
    # 新格式：{date}_{seq}_{suffix}.json
    candidate = insights_dir / f"{stem.replace('_conversation', '')}_{suffix}.json"
    if candidate.exists():
        return candidate
    # 旧格式：{date}_{suffix}.json
    candidate = insights_dir / f"{date_str}_{suffix}.json"
    if candidate.exists():
        return candidate
    return None


def generate_reports(project_name: str) -> None:
    """
    为指定项目生成/更新所有 HTML 报告。
    """
    project_output = OUTPUT_DIR / project_name
    conversations_dir = project_output / "conversations"
    reports_dir = project_output / "reports"
    insights_dir = project_output / "insights"

    if not conversations_dir.exists():
        logger.warning(f"对话目录不存在: {conversations_dir}")
        return

    reports_dir.mkdir(parents=True, exist_ok=True)

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("report_template.html")

    monthly_records = defaultdict(list)
    conversation_files = sorted(conversations_dir.glob("*.md"))

    for conv_file in conversation_files:
        date_match = re.match(r"(\d{4}-\d{2}-\d{2})", conv_file.stem)
        if not date_match:
            logger.warning(f"无法从文件名提取日期，跳过: {conv_file.name}")
            continue

        date_str = date_match.group(1)
        month_key = date_str[:7]

        # 读取对话内容
        conversation_md = conv_file.read_text(encoding="utf-8")
        conversation_html = _conversation_to_html(conversation_md)

        # 读取元数据（标题、说话人）— 由 DeepSeek 生成
        title = "会议记录"
        speakers = _extract_speakers(conversation_md)  # fallback
        meta_file = _find_json_file(insights_dir, conv_file.stem, date_str, "meta")
        if meta_file:
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                title = meta.get("title", title)
                if meta.get("speakers"):
                    speakers = meta["speakers"]
            except json.JSONDecodeError:
                logger.warning(f"meta JSON 解析失败: {meta_file.name}")

        # 读取 insights JSON
        insights = {"questions": [], "action_items": [], "decisions": []}
        insights_file = _find_json_file(insights_dir, conv_file.stem, date_str, "insights")
        if insights_file:
            try:
                insights = json.loads(insights_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                logger.warning(f"insights JSON 解析失败: {insights_file.name}")

        # 高亮
        highlight_keywords = []
        for item in insights.get("action_items", []):
            if isinstance(item, dict):
                highlight_keywords.append(item.get("task", ""))
            elif isinstance(item, str):
                highlight_keywords.append(item)
        for q in insights.get("questions", []):
            if isinstance(q, str) and len(q) > 6:
                highlight_keywords.append(q)
        conversation_html = _highlight_sentences(conversation_html, highlight_keywords)

        record = {
            "date": date_str,
            "title": title,
            "speakers": speakers,
            "conversation_html": conversation_html,
            "insights": insights,
        }
        monthly_records[month_key].append(record)

    if not monthly_records:
        logger.info("没有找到对话记录，跳过报告生成")
        return

    # 按月生成报告
    month_files = []
    for month_key in sorted(monthly_records.keys()):
        records = monthly_records[month_key]
        records.sort(key=lambda r: r["date"])

        year, month = month_key.split("-")
        month_label = f"{year}年{int(month)}月"
        filename = f"report_{month_key}.html"
        page_title = f"{project_name} - {month_label} 会议记录"

        html = template.render(
            title=page_title,
            project_name=project_name,
            is_index=False,
            month_label=month_label,
            records=records,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )

        report_path = reports_dir / filename
        report_path.write_text(html, encoding="utf-8")
        logger.info(f"已生成报告: {filename}（{len(records)} 条记录）")

        month_files.append({
            "filename": filename,
            "label": month_label,
            "count": len(records),
        })

    # 生成索引页
    index_html = template.render(
        title=f"{project_name} - 录音报告索引",
        project_name=project_name,
        is_index=True,
        months=month_files,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )

    index_path = reports_dir / "index.html"
    index_path.write_text(index_html, encoding="utf-8")
    logger.info(f"已更新索引页: index.html（{len(month_files)} 个月份）")
