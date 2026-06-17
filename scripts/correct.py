"""
矫正模块：调用 DeepSeek API 对 ASR 转录文本进行纠错、说话人识别和摘要。

职责：接收 Mimo ASR 的原始转录，输出：
1. 矫正后的对话 Markdown
2. 一句话摘要标题
3. 识别出的说话人列表
"""

import json
import logging
from openai import OpenAI
from config import MODEL_DEEPSEEK

logger = logging.getLogger("AudioChronolog")

SYSTEM_PROMPT = """\
你是一位专业的会议记录整理专家。你的任务是对 ASR 语音识别的原始转录进行深度处理。

## 任务要求

### 1. 纠正识别错误
- 修正 ASR 转录中的错别字、同音词错误、标点问题
- 专业术语根据上下文推断并纠正
- 去除明显的口语冗余（如反复重复的"嗯嗯""那个那个"），但保留自然的口语风格

### 2. 说话人识别
- 必须严格根据"背景信息"中提供的参会人员来识别和标注说话人
- 利用说话内容、语气、专业领域等线索判断每段话属于哪位参会人
- 如果背景信息中有说话人特征描述（如角色、专业方向），用这些信息辅助判断
- 实在无法确定的说话人，使用"说话人X"（X为字母），但尽量减少这种情况

### 3. 生成摘要标题
- 基于整个对话内容，提炼一句精炼的中文标题（15-30字）
- 标题应概括本次讨论的核心主题，而非取首句话

### 4. 省略闲聊
- 如果背景信息要求省略闲聊，则跳过与会议主题无关的寒暄、闲聊内容

## 输出格式

你必须严格输出以下 JSON 格式，不要添加任何其他文字：

```json
{
    "title": "一句话摘要标题（15-30字）",
    "speakers": ["说话人1", "说话人2"],
    "conversation": "**说话人1**：内容\\n\\n**说话人2**：内容\\n\\n..."
}
```

conversation 字段中每段发言独占一段，段落之间用 \\n\\n 分隔。
"""


def correct_transcript(
    raw_transcript: str,
    speaker_hints: str | None,
    background: str,
    client: OpenAI,
) -> dict:
    """
    调用 DeepSeek 对转录文本进行矫正、说话人识别和摘要。

    Args:
        raw_transcript: Mimo ASR 输出的原始转录文本。
        speaker_hints: 同名 .md 文件的内容（说话人提示），可为 None。
        background: 项目 README 中的 Background 区块内容。
        client: DeepSeek API 客户端。

    Returns:
        字典：
        - title: 一句话摘要标题
        - speakers: 说话人列表
        - conversation: 矫正后的对话 Markdown
    """
    logger.info("开始文本矫正和说话人识别（DeepSeek）...")

    # 构建用户消息
    user_parts = []

    if background:
        user_parts.append(f"## 背景信息（参会人员、讨论主题、说话人识别依据）\n{background}")

    if speaker_hints:
        user_parts.append(f"## 补充上下文（说话人提示）\n{speaker_hints}")

    user_parts.append(f"## ASR 转录原文\n{raw_transcript}")

    user_message = "\n\n".join(user_parts)

    response = client.chat.completions.create(
        model=MODEL_DEEPSEEK,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.3,
    )

    raw = response.choices[0].message.content.strip()

    # 提取 JSON（可能被 ```json ``` 包裹）
    if raw.startswith("```"):
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
        logger.warning("DeepSeek 返回内容无法解析为 JSON，使用原始文本")
        result = {
            "title": "会议记录",
            "speakers": [],
            "conversation": raw,
        }

    # 确保字段完整
    result.setdefault("title", "会议记录")
    result.setdefault("speakers", [])
    result.setdefault("conversation", "")

    logger.info(
        f"文本矫正完成：标题「{result['title']}」，"
        f"说话人 {result['speakers']}，"
        f"对话 {len(result['conversation'])} 字符"
    )
    return result
