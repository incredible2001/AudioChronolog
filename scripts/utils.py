"""
工具模块：哈希计算、文件扫描、日志配置等通用功能。
"""

import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import AUDIO_EXTENSIONS


def setup_logging() -> logging.Logger:
    """
    配置并返回全局日志记录器。
    输出到控制台，格式包含时间戳和级别。
    """
    logger = logging.getLogger("AudioChronolog")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter(
            "[%(asctime)s] %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


def sha256_file(file_path: str | Path) -> str:
    """
    计算文件的 SHA256 哈希值。

    Args:
        file_path: 文件路径。

    Returns:
        十六进制哈希字符串。
    """
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def load_processed(project_output_dir: str | Path) -> dict:
    """
    读取项目的已处理文件清单。

    Args:
        project_output_dir: 项目输出目录（output/<项目名>/）。

    Returns:
        已处理文件字典 {hash: {filename, processed_at, ...}}。
        若文件不存在则返回空字典。
    """
    processed_file = Path(project_output_dir) / ".processed.json"
    if processed_file.exists():
        with open(processed_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_processed(project_output_dir: str | Path, data: dict) -> None:
    """
    保存已处理文件清单到 .processed.json。

    Args:
        project_output_dir: 项目输出目录。
        data: 已处理文件字典。
    """
    processed_file = Path(project_output_dir) / ".processed.json"
    processed_file.parent.mkdir(parents=True, exist_ok=True)
    with open(processed_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def extract_date_from_filename(filename: str) -> Optional[str]:
    """
    从文件名中提取日期字符串。

    支持格式：YYYY-MM-DD 或 YYYYMMDD。

    Args:
        filename: 文件名（不含路径）。

    Returns:
        日期字符串 "YYYY-MM-DD"，未匹配则返回 None。
    """
    # 优先匹配 YYYY-MM-DD 格式
    match = re.search(r"(\d{4}-\d{2}-\d{2})", filename)
    if match:
        try:
            datetime.strptime(match.group(1), "%Y-%m-%d")
            return match.group(1)
        except ValueError:
            pass

    # 备选：YYYYMMDD 格式
    match = re.search(r"(\d{4})(\d{2})(\d{2})", filename)
    if match:
        try:
            date_str = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
            datetime.strptime(date_str, "%Y-%m-%d")
            return date_str
        except ValueError:
            pass

    return None


def find_audio_files(input_dir: str | Path) -> list[dict]:
    """
    扫描 input/ 下所有项目子目录，收集音频文件信息。

    Args:
        input_dir: 输入根目录（input/）。

    Returns:
        音频文件信息列表，每项包含：
        - path: 文件完整路径
        - project: 项目名（子目录名）
        - date: 从文件名提取的日期
        - stem: 文件名（不含扩展名）
        - extension: 文件扩展名
    """
    input_dir = Path(input_dir)
    audio_files = []

    for project_dir in input_dir.iterdir():
        if not project_dir.is_dir():
            continue
        # 跳过隐藏目录
        if project_dir.name.startswith("."):
            continue

        for file in project_dir.iterdir():
            if not file.is_file():
                continue
            if file.suffix.lower() in AUDIO_EXTENSIONS:
                audio_files.append(
                    {
                        "path": str(file),
                        "project": project_dir.name,
                        "date": extract_date_from_filename(file.name),
                        "stem": file.stem,
                        "extension": file.suffix.lower(),
                    }
                )

    return audio_files


def find_speaker_hints(audio_path: str | Path) -> Optional[str]:
    """
    查找与录音文件同名的 .md 文件作为说话人提示。

    例如：对于 2026-06-17-会议.mp3，查找 2026-06-17-会议.md。

    Args:
        audio_path: 音频文件路径。

    Returns:
        .md 文件内容，不存在则返回 None。
    """
    audio_path = Path(audio_path)
    md_path = audio_path.with_suffix(".md")
    if md_path.exists():
        return md_path.read_text(encoding="utf-8")
    return None


def load_project_memory(project_input_dir: str | Path) -> str:
    """
    读取项目 README.md 中的 Memory 区块。

    Args:
        project_input_dir: 项目输入目录（input/<项目名>/）。

    Returns:
        Memory 区块的文本内容，不存在则返回空字符串。
    """
    readme_path = Path(project_input_dir) / "README.md"
    if not readme_path.exists():
        return ""

    content = readme_path.read_text(encoding="utf-8")
    # 提取 MEMORY_START 和 MEMORY_END 之间的内容
    pattern = r"<!--\s*MEMORY_START\s*-->(.*?)<!--\s*MEMORY_END\s*-->"
    match = re.search(pattern, content, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


def load_background(project_input_dir: str | Path) -> str:
    """
    读取项目 README.md 中的 Background 区块。

    提取 ## Background 到下一个 ## 之间的全部内容（含说话人识别依据等）。

    Args:
        project_input_dir: 项目输入目录（input/<项目名>/）。

    Returns:
        Background 区块的文本内容，不存在则返回空字符串。
    """
    readme_path = Path(project_input_dir) / "README.md"
    if not readme_path.exists():
        return ""

    content = readme_path.read_text(encoding="utf-8")
    # 匹配 ## Background 到下一个 ## 或文件末尾
    pattern = r"##\s*Background\s*\n(.*?)(?=\n##\s|\Z)"
    match = re.search(pattern, content, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""
