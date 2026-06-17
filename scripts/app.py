"""
AudioChronolog GUI — Flask Web 应用入口。

功能：
- 项目列表、创建新项目
- 上传音频文件
- 实时处理进度（SSE）
- 报告浏览（iframe 嵌入）

启动：
    python scripts/app.py
"""

import json
import os
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from flask import Flask, Response, jsonify, redirect, render_template, request, send_from_directory

from config import INPUT_DIR, OUTPUT_DIR, TEMPLATES_DIR, get_deepseek_client, get_mimo_client
from utils import find_audio_files, load_processed, sha256_file, setup_logging

app = Flask(
    __name__,
    template_folder=str(TEMPLATES_DIR),
    static_folder=None,
)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500MB 上传上限

logger = setup_logging()

# ─── 进度事件队列（项目名 → 事件列表）────────────────────
_progress_queues: dict[str, list] = {}


def _emit(project: str, event: dict):
    """向指定项目的进度队列推入一个事件。"""
    _progress_queues.setdefault(project, []).append(event)


# ═══════════════════════════════════════════════════════
#  页面路由
# ═══════════════════════════════════════════════════════

@app.route("/help")
def help_page():
    """使用说明页。"""
    return render_template("gui/help.html")


@app.route("/")
def index():
    """首页：项目列表。"""
    projects = []
    if INPUT_DIR.exists():
        for d in sorted(INPUT_DIR.iterdir()):
            if not d.is_dir() or d.name.startswith((".", "_")):
                continue
            audio_files = find_audio_files(d)
            has_reports = (OUTPUT_DIR / d.name / "reports" / "index.html").exists()
            # 取最新录音日期
            dates = [f["date"] for f in audio_files if f["date"]]
            last_date = max(dates) if dates else None
            projects.append({
                "name": d.name,
                "audio_count": len(audio_files),
                "last_date": last_date,
                "has_reports": has_reports,
            })
    return render_template("gui/index.html", projects=projects)


@app.route("/project/<name>")
def project_page(name):
    """项目页。"""
    project_input = INPUT_DIR / name
    if not project_input.exists():
        return redirect("/")

    # 读取 README
    readme_path = project_input / "README.md"
    readme_content = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""

    # 检查报告
    reports_dir = OUTPUT_DIR / name / "reports"
    has_reports = (reports_dir / "index.html").exists()

    # 收集月份报告列表
    months = []
    if has_reports:
        for f in sorted(reports_dir.glob("report_*.html")):
            # report_2026-06.html → 2026年6月
            stem = f.stem.replace("report_", "")
            try:
                y, m = stem.split("-")
                label = f"{y}年{int(m)}月"
            except ValueError:
                label = stem
            months.append({"filename": f.name, "label": label})

    return render_template(
        "gui/project.html",
        project_name=name,
        readme_content=readme_content,
        has_reports=has_reports,
        months=months,
    )


# ═══════════════════════════════════════════════════════
#  报告代理（提供报告文件访问）
# ═══════════════════════════════════════════════════════

@app.route("/project/<name>/report/<path:filename>")
def serve_report(name, filename):
    """代理报告文件（HTML / CSS / JS）。"""
    reports_dir = OUTPUT_DIR / name / "reports"
    return send_from_directory(str(reports_dir), filename)


# ═══════════════════════════════════════════════════════
#  API 路由
# ═══════════════════════════════════════════════════════

@app.route("/api/project/create", methods=["POST"])
def api_create_project():
    """创建新项目。"""
    data = request.get_json()
    name = (data.get("name") or "").strip()
    background = (data.get("background") or "").strip()

    if not name:
        return jsonify({"ok": False, "error": "项目名不能为空"})
    if "/" in name or "\\" in name:
        return jsonify({"ok": False, "error": "项目名不能包含路径分隔符"})

    project_dir = INPUT_DIR / name
    if project_dir.exists():
        return jsonify({"ok": False, "error": "项目已存在"})

    project_dir.mkdir(parents=True, exist_ok=True)

    # 生成 README.md
    bg_section = background if background else "（请补充项目背景描述）"
    readme = f"# 项目：{name}\n\n## Background\n{bg_section}\n\n## Memory\n<!-- MEMORY_START -->\n<!-- MEMORY_END -->\n"
    (project_dir / "README.md").write_text(readme, encoding="utf-8")

    return jsonify({"ok": True})


@app.route("/api/project/<name>/upload", methods=["POST"])
def api_upload(name):
    """上传音频文件到项目目录。"""
    project_dir = INPUT_DIR / name
    if not project_dir.exists():
        return jsonify({"ok": False, "error": "项目不存在"})

    files = request.files.getlist("files")
    if not files:
        return jsonify({"ok": False, "error": "未选择文件"})

    saved = []
    for f in files:
        if not f.filename:
            continue
        save_path = project_dir / f.filename
        f.save(str(save_path))
        saved.append(f.filename)
        logger.info(f"文件已上传: {f.filename}")

    return jsonify({"ok": True, "saved": saved})


@app.route("/api/project/<name>/process")
def api_process(name):
    """
    SSE 端点：启动处理流程并实时推送进度。
    """
    project_dir = INPUT_DIR / name
    if not project_dir.exists():
        return jsonify({"error": "项目不存在"})

    def generate():
        _progress_queues[name] = []
        # 在后台线程运行处理
        thread = threading.Thread(target=_run_processing, args=(name,), daemon=True)
        thread.start()

        sent_idx = 0
        while thread.is_alive() or sent_idx < len(_progress_queues.get(name, [])):
            events = _progress_queues.get(name, [])
            while sent_idx < len(events):
                yield f"data: {json.dumps(events[sent_idx], ensure_ascii=False)}\n\n"
                sent_idx += 1
            if thread.is_alive():
                time.sleep(0.3)

        # 发送剩余事件
        events = _progress_queues.get(name, [])
        while sent_idx < len(events):
            yield f"data: {json.dumps(events[sent_idx], ensure_ascii=False)}\n\n"
            sent_idx += 1

        # 清理
        _progress_queues.pop(name, None)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _run_processing(project: str):
    """后台处理线程（带进度回调）。"""
    try:
        mimo_client = get_mimo_client()
        deepseek_client = get_deepseek_client()
    except ValueError as e:
        _emit(project, {"type": "error", "msg": str(e)})
        return

    project_input = INPUT_DIR / project
    project_output = OUTPUT_DIR / project

    audio_files = find_audio_files(project_input)
    if not audio_files:
        _emit(project, {"type": "error", "msg": "未找到音频文件"})
        return

    # 过滤已处理
    processed = load_processed(project_output)
    pending = []
    for info in audio_files:
        h = sha256_file(info["path"])
        if h in processed:
            _emit(project, {"type": "log", "level": "info", "msg": f"跳过已处理: {info['stem']}"})
        else:
            info["_hash"] = h
            pending.append(info)

    if not pending:
        _emit(project, {"type": "done", "success": 0, "error": 0, "msg": "没有新文件需要处理"})
        return

    total = len(pending)
    _emit(project, {"type": "progress", "percent": 0, "msg": f"共 {total} 个文件待处理"})

    success = 0
    error = 0
    date_seq = {}

    for idx, info in enumerate(pending, 1):
        stem = info["stem"]
        _emit(project, {"type": "log", "level": "step", "msg": f"[{idx}/{total}] 处理: {stem}"})

        effective_date = info["date"] or datetime.now().strftime("%Y-%m-%d")
        date_key = (project, effective_date)
        date_seq[date_key] = date_seq.get(date_key, 0) + 1
        seq = date_seq[date_key]
        seq_suffix = f"_{seq:02d}" if seq > 1 else ""

        try:
            # Step 1: 转录
            _emit(project, {"type": "log", "level": "info", "msg": f"  [Step 1] 语音转文字..."})
            from transcribe import transcribe
            raw = transcribe(info["path"], mimo_client)
            _emit(project, {"type": "log", "level": "info", "msg": f"  转录完成: {len(raw)} 字符"})

            # Step 2: 矫正
            _emit(project, {"type": "log", "level": "info", "msg": f"  [Step 2] 文本矫正+说话人识别..."})
            from correct import correct_transcript
            from utils import find_speaker_hints, load_background
            hints = find_speaker_hints(info["path"])
            bg = load_background(project_input)
            result = correct_transcript(raw, hints, bg, deepseek_client)
            _emit(project, {"type": "log", "level": "info", "msg": f"  标题: {result['title']}"})

            # 保存对话
            conversations_dir = project_output / "conversations"
            insights_dir = project_output / "insights"
            conversations_dir.mkdir(parents=True, exist_ok=True)
            insights_dir.mkdir(parents=True, exist_ok=True)

            conv_path = conversations_dir / f"{effective_date}{seq_suffix}_conversation.md"
            conv_path.write_text(result["conversation"], encoding="utf-8")

            meta_path = insights_dir / f"{effective_date}{seq_suffix}_meta.json"
            meta_path.write_text(json.dumps({"title": result["title"], "speakers": result["speakers"]}, ensure_ascii=False, indent=2), encoding="utf-8")

            # Step 3: 提取
            _emit(project, {"type": "log", "level": "info", "msg": f"  [Step 3] 提取结构化信息..."})
            from extract_insights import extract_insights
            insights = extract_insights(result["conversation"], deepseek_client)
            ins_path = insights_dir / f"{effective_date}{seq_suffix}_insights.json"
            ins_path.write_text(json.dumps(insights, ensure_ascii=False, indent=2), encoding="utf-8")

            # Step 4: 记忆
            _emit(project, {"type": "log", "level": "info", "msg": f"  [Step 4] 更新记忆..."})
            from update_memory import update_memory, generate_memory_summary
            summary = generate_memory_summary(result["title"], result["conversation"], insights.get("action_items", []), deepseek_client)
            update_memory(str(project_input / "README.md"), effective_date, summary)

            # 标记完成
            processed[info["_hash"]] = {
                "filename": stem, "date": effective_date,
                "processed_at": datetime.now().isoformat(),
            }
            from utils import save_processed
            save_processed(project_output, processed)

            success += 1
            _emit(project, {"type": "log", "level": "info", "msg": f"  ✅ {stem} 完成"})

        except Exception as e:
            error += 1
            _emit(project, {"type": "log", "level": "error", "msg": f"  ❌ {stem} 失败: {e}"})

        pct = int(idx / total * 100)
        _emit(project, {"type": "progress", "percent": pct, "msg": f"进度: {idx}/{total}"})

    # 生成报告
    _emit(project, {"type": "log", "level": "step", "msg": "生成 HTML 报告..."})
    try:
        from generate_report import generate_reports
        generate_reports(project)
        _emit(project, {"type": "log", "level": "info", "msg": "报告生成完成"})
    except Exception as e:
        _emit(project, {"type": "log", "level": "error", "msg": f"报告生成失败: {e}"})

    _emit(project, {"type": "done", "success": success, "error": error})


# ═══════════════════════════════════════════════════════
#  启动
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AudioChronolog GUI")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{args.port}")).start()

    logger.info(f"AudioChronolog GUI 启动: http://localhost:{args.port}")

    app.run(host="127.0.0.1", port=args.port, debug=False, threaded=True)
