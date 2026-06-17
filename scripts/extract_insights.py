"""
提取模块：从矫正后的对话中提取结构化信息（问题、待办、决策）。
"""

import json
import logging
from openai import OpenAI
from config import MODEL_DEEPSEEK

logger = logging.getLogger("AudioChronolog")

EXTRACT_PROMPT = """\
你是一位会议分析专家。请从以下对话记录中提取结构化信息。

请严格以 JSON 格式输出，包含以下三个字段：
{
    "questions": ["对话中提出的问题或难点（字符串数组）"],
    "action_items": [
        {
            "task": "待办事项描述",
            "owner": "负责人（如对话中未明确则为空字符串）",
            "deadline": "截止时间（如对话中未明确则为空字符串）"
        }
    ],
    "decisions": ["已做出的关键决策（字符串数组）"]
}

注意：
- 只输出 JSON，不要添加任何说明文字。
- 如果某类信息不存在，返回空数组 []。
- 保持简洁准确，不要添加对话中没有的信息。
"""


def extract_insights(conversation_md: str, client: OpenAI) -> dict:
    """
    从矫正后的对话文本中提取结构化信息。

    Args:
        conversation_md: 矫正后的对话 Markdown 文本。
        client: OpenAI 兼容的 API 客户端。

    Returns:
        字典，包含 keys: questions, action_items, decisions。
    """
    logger.info("开始提取结构化信息（DeepSeek）...")

    response = client.chat.completions.create(
        model=MODEL_DEEPSEEK,
        messages=[
            {"role": "system", "content": EXTRACT_PROMPT},
            {"role": "user", "content": conversation_md},
        ],
        temperature=0.2,
    )

    raw = response.choices[0].message.content.strip()

    # 尝试提取 JSON（模型可能在 JSON 外包裹 ```json ``` 标记）
    if raw.startswith("```"):
        # 去掉代码块标记
        lines = raw.split("\n")
        json_lines = []
        in_block = False
        for line in lines:
            if line.strip().startswith("```") and not in_block:
                in_block = True
                continue
            elif line.strip() == "```" and in_block:
                break
            elif in_block:
                json_lines.append(line)
        raw = "\n".join(json_lines)

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("AI 返回的内容无法解析为 JSON，返回空结构")
        result = {
            "questions": [],
            "action_items": [],
            "decisions": [],
        }

    # 确保返回结构完整
    result.setdefault("questions", [])
    result.setdefault("action_items", [])
    result.setdefault("decisions", [])

    logger.info(
        f"提取完成: {len(result['questions'])} 个问题, "
        f"{len(result['action_items'])} 个待办, "
        f"{len(result['decisions'])} 个决策"
    )
    return result
