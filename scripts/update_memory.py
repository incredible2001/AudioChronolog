"""
记忆更新模块：调用 DeepSeek 生成精炼摘要，追加到项目 README.md 的 Memory 区块。
"""

import logging
import re
from pathlib import Path

from openai import OpenAI
from config import MODEL_DEEPSEEK

logger = logging.getLogger("AudioChronolog")

MEMORY_START_MARKER = "<!-- MEMORY_START -->"
MEMORY_END_MARKER = "<!-- MEMORY_END -->"

SUMMARY_PROMPT = """\
请用一句简洁的中文（30-60字）总结以下会议内容，格式为：
主题概括；关键待办1、待办2

只输出这一句话，不要添加任何其他文字。
"""


def generate_memory_summary(
    title: str,
    conversation: str,
    action_items: list[dict],
    client: OpenAI,
) -> str:
    """
    调用 DeepSeek 生成精炼的会议记忆摘要。

    Args:
        title: 会议标题。
        conversation: 对话全文。
        action_items: 提取的待办事项列表。
        client: DeepSeek API 客户端。

    Returns:
        精炼摘要字符串。
    """
    # 构建摘要输入
    items_str = ""
    if action_items:
        items_str = "\n待办事项：\n" + "\n".join(
            f"- {item.get('task', '')}" for item in action_items[:5]
        )

    user_msg = f"会议标题：{title}\n{items_str}\n\n对话片段（前2000字）：\n{conversation[:2000]}"

    try:
        response = client.chat.completions.create(
            model=MODEL_DEEPSEEK,
            messages=[
                {"role": "system", "content": SUMMARY_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.3,
            max_tokens=200,
        )
        summary = response.choices[0].message.content.strip()
        # 清理可能的引号
        summary = summary.strip('"\'')
        if summary and len(summary) > 5:
            return summary
        logger.warning("DeepSeek 返回的摘要过短，使用标题回退")
        return title
    except Exception as e:
        logger.warning(f"生成记忆摘要失败，使用标题回退: {e}")
        return title


def update_memory(
    readme_path: str,
    date: str,
    summary: str,
) -> None:
    """
    在 README.md 的 Memory 区块末尾追加摘要。

    Args:
        readme_path: README.md 文件的完整路径。
        date: 日期字符串（YYYY-MM-DD）。
        summary: 精炼摘要（由 DeepSeek 生成）。
    """
    readme_path = Path(readme_path)

    if not readme_path.exists():
        logger.warning(f"README 不存在，跳过记忆更新: {readme_path}")
        return

    content = readme_path.read_text(encoding="utf-8")
    summary_line = f"- {date}：{summary}"

    if MEMORY_START_MARKER in content and MEMORY_END_MARKER in content:
        pattern = re.compile(
            rf"({re.escape(MEMORY_START_MARKER)}.*?)"
            rf"({re.escape(MEMORY_END_MARKER)})",
            re.DOTALL,
        )
        match = pattern.search(content)
        if match:
            existing_block = match.group(1)
            if not existing_block.endswith("\n"):
                existing_block += "\n"
            new_block = f"{existing_block}{summary_line}\n\n{MEMORY_END_MARKER}"
            content = content[: match.start()] + new_block + content[match.end() :]
        else:
            logger.warning("Memory 标记格式异常，跳过更新")
            return
    else:
        logger.info("README 中未找到 Memory 标记，将自动创建")
        if not content.endswith("\n"):
            content += "\n"
        content += f"\n## Memory\n{MEMORY_START_MARKER}\n{summary_line}\n{MEMORY_END_MARKER}\n"

    readme_path.write_text(content, encoding="utf-8")
    logger.info(f"记忆已更新: {readme_path.name}")
