"""
配置模块：读取环境变量、定义路径常量和 API 配置。

职责分工：
- Mimo (mimo-v2.5-asr): 仅负责语音转文字
- DeepSeek (deepseek-v4-pro): 负责所有文本处理（矫正、提取、摘要、记忆）
"""

import os
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

# 加载 .env 文件
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

# ─── 路径常量 ───────────────────────────────────────────────
INPUT_DIR = ROOT_DIR / "input"
OUTPUT_DIR = ROOT_DIR / "output"
TEMPLATES_DIR = ROOT_DIR / "templates"

# ─── Mimo API（仅语音转录）──────────────────────────────────
XIAOMI_API_KEY = os.getenv("XIAOMI_API_KEY")
MIMO_BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"
MODEL_ASR = "mimo-v2.5-asr"

# ─── DeepSeek API（所有文本处理）────────────────────────────
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
MODEL_DEEPSEEK = "deepseek-v4-pro"

# ─── 音频文件扩展名 ──────────────────────────────────────────
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".webm", ".aac"}


def get_mimo_client() -> OpenAI:
    """
    创建 Mimo API 客户端（仅用于语音转录）。

    Raises:
        ValueError: 如果 XIAOMI_API_KEY 未设置。
    """
    if not XIAOMI_API_KEY:
        raise ValueError(
            "未找到 XIAOMI_API_KEY 环境变量。"
            "请在 .env 文件中填写：XIAOMI_API_KEY=your_key"
        )
    return OpenAI(api_key=XIAOMI_API_KEY, base_url=MIMO_BASE_URL)


def get_deepseek_client() -> OpenAI:
    """
    创建 DeepSeek API 客户端（用于所有文本处理任务）。

    Raises:
        ValueError: 如果 DEEPSEEK_API_KEY 未设置。
    """
    if not DEEPSEEK_API_KEY:
        raise ValueError(
            "未找到 DEEPSEEK_API_KEY 环境变量。"
            "请在 .env 文件中填写：DEEPSEEK_API_KEY=your_key"
        )
    return OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
