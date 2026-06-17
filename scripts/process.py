"""
主控脚本：扫描 input/ 下所有新录音，依次执行：
  Mimo ASR → DeepSeek 矫正 → DeepSeek 提取 → 报告生成 → DeepSeek 记忆更新

用法：
    python scripts/process.py
"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import INPUT_DIR, OUTPUT_DIR, get_mimo_client, get_deepseek_client
from utils import (
    find_audio_files,
    find_speaker_hints,
    load_processed,
    load_project_memory,
    save_processed,
    sha256_file,
    setup_logging,
    load_background,
)
from transcribe import transcribe
from correct import correct_transcript
from extract_insights import extract_insights
from generate_report import generate_reports
from update_memory import update_memory, generate_memory_summary


def process_single_file(
    audio_info: dict, mimo_client, deepseek_client, logger, seq: int = 1
) -> bool:
    """
    处理单个音频文件的完整流程。

    Args:
        audio_info: 音频文件信息字典。
        mimo_client: Mimo API 客户端（语音转录）。
        deepseek_client: DeepSeek API 客户端（文本处理）。
        logger: 日志记录器。
        seq: 同日文件序号（>1 时追加后缀避免覆盖）。

    Returns:
        处理成功返回 True，失败返回 False。
    """
    audio_path = audio_info["path"]
    project = audio_info["project"]
    date = audio_info["date"]
    stem = audio_info["stem"]

    logger.info(f"═══ 开始处理: {stem}（项目：{project}）═══")

    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
        logger.warning(f"无法从文件名提取日期，使用今天: {date}")

    seq_suffix = f"_{seq:02d}" if seq > 1 else ""

    project_output = OUTPUT_DIR / project
    conversations_dir = project_output / "conversations"
    insights_dir = project_output / "insights"
    conversations_dir.mkdir(parents=True, exist_ok=True)
    insights_dir.mkdir(parents=True, exist_ok=True)

    # ─── Step 1: Mimo ASR 转录 ─────────────────────────
    logger.info("[Step 1/5] 语音转文字（Mimo ASR）...")
    raw_transcript = transcribe(audio_path, mimo_client)

    if not raw_transcript.strip():
        logger.error(f"转录结果为空，跳过: {stem}")
        return False

    # ─── Step 2: DeepSeek 矫正 + 说话人识别 + 标题摘要 ─
    logger.info("[Step 2/5] 文本矫正和说话人识别（DeepSeek）...")
    speaker_hints = find_speaker_hints(audio_path)
    project_input = INPUT_DIR / project
    background = load_background(project_input)

    correction_result = correct_transcript(
        raw_transcript, speaker_hints, background, deepseek_client
    )

    title = correction_result.get("title", "会议记录")
    speakers = correction_result.get("speakers", [])
    conversation = correction_result.get("conversation", "")

    # 保存对话
    conv_filename = f"{date}{seq_suffix}_conversation.md"
    conv_path = conversations_dir / conv_filename
    conv_path.write_text(conversation, encoding="utf-8")
    logger.info(f"对话已保存: {conv_filename}")

    # 保存元数据（标题、说话人）
    meta = {"title": title, "speakers": speakers}
    meta_filename = f"{date}{seq_suffix}_meta.json"
    meta_path = insights_dir / meta_filename
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # ─── Step 3: DeepSeek 提取结构化信息 ────────────────
    logger.info("[Step 3/5] 提取结构化信息（DeepSeek）...")
    insights = extract_insights(conversation, deepseek_client)

    insights_filename = f"{date}{seq_suffix}_insights.json"
    insights_path = insights_dir / insights_filename
    insights_path.write_text(
        json.dumps(insights, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(f"结构化信息已保存: {insights_filename}")

    # ─── Step 4: DeepSeek 生成记忆摘要并更新 README ────
    logger.info("[Step 4/5] 更新项目记忆（DeepSeek）...")
    readme_path = project_input / "README.md"
    action_items = insights.get("action_items", [])
    summary = generate_memory_summary(title, conversation, action_items, deepseek_client)
    update_memory(str(readme_path), date, summary)

    logger.info(f"═══ 处理完成: {stem} ═══")
    return True


def main():
    """主流程入口。"""
    logger = setup_logging()
    logger.info("AudioChronolog 启动")

    if not INPUT_DIR.exists():
        logger.error(f"输入目录不存在: {INPUT_DIR}")
        logger.info("请创建 input/ 目录，并在其中放入项目子文件夹和录音文件。")
        sys.exit(1)

    # 初始化两个 API 客户端
    try:
        mimo_client = get_mimo_client()
        deepseek_client = get_deepseek_client()
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)

    audio_files = find_audio_files(INPUT_DIR)
    if not audio_files:
        logger.info("未找到任何音频文件。请将录音放入 input/<项目名>/ 目录。")
        sys.exit(0)

    logger.info(f"共发现 {len(audio_files)} 个音频文件")

    success_count = 0
    error_count = 0
    date_seq_counter = {}

    for audio_info in audio_files:
        project = audio_info["project"]
        project_output = OUTPUT_DIR / project

        processed = load_processed(project_output)
        file_hash = sha256_file(audio_info["path"])

        if file_hash in processed:
            logger.info(f"跳过已处理文件: {audio_info['stem']}")
            continue

        effective_date = audio_info["date"] or datetime.now().strftime("%Y-%m-%d")
        date_key = (project, effective_date)
        date_seq_counter[date_key] = date_seq_counter.get(date_key, 0) + 1
        seq = date_seq_counter[date_key]

        try:
            success = process_single_file(
                audio_info, mimo_client, deepseek_client, logger, seq=seq
            )
            if success:
                processed = load_processed(project_output)
                processed[file_hash] = {
                    "filename": audio_info["stem"],
                    "date": effective_date,
                    "processed_at": datetime.now().isoformat(),
                }
                save_processed(project_output, processed)
                success_count += 1
            else:
                error_count += 1
        except Exception as e:
            logger.error(f"处理文件失败 {audio_info['stem']}: {e}", exc_info=True)
            error_count += 1

    # ─── 生成报告 ──────────────────────────────────────
    logger.info("═══ 开始生成报告 ═══")
    all_projects = set()
    for audio_info in audio_files:
        all_projects.add(audio_info["project"])
    if OUTPUT_DIR.exists():
        for d in OUTPUT_DIR.iterdir():
            if d.is_dir() and not d.name.startswith("."):
                all_projects.add(d.name)

    for project in sorted(all_projects):
        try:
            generate_reports(project)
        except Exception as e:
            logger.error(f"生成报告失败（项目 {project}）: {e}", exc_info=True)

    logger.info(
        f"全部完成！成功: {success_count}，失败: {error_count}，"
        f"跳过: {len(audio_files) - success_count - error_count}"
    )


if __name__ == "__main__":
    main()
