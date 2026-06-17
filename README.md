# AudioChronolog

自动化处理工作录音，转写并矫正为对话记录，生成累积式 HTML 报告。

## 功能特性

- 🎙️ **语音转文字**：小米 Mimo ASR，自动分段处理长录音
- ✍️ **文本矫正**：DeepSeek AI 纠错 + 智能说话人识别
- 📊 **信息提取**：自动提取问题、待办事项（Action Items）、关键决策
- 📋 **HTML 报告**：按月拆分，左侧目录导航，默认展开对话
- 🧠 **项目记忆**：自动维护每个项目的讨论记忆
- 🔁 **防重复**：SHA256 哈希去重
- 🖥️ **图形界面**：Web GUI，支持项目管理、文件上传、实时进度

## 技术架构

本项目采用**双模型分工**：

| 任务 | 模型 | 说明 |
|------|------|------|
| 语音转录 | [小米 Mimo mimo-v2.5-asr](https://token-plan-cn.xiaomimimo.com) | 专业 ASR 模型，支持中文长音频 |
| 文本处理 | [DeepSeek deepseek-v4-pro](https://platform.deepseek.com) | 矫正、说话人识别、摘要、提取、记忆 |


### 切换模型

如果需要替换为其他模型，编辑 `scripts/config.py`：

```python
# ─── Mimo API（仅语音转录）───
MIMO_BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"
MODEL_ASR = "mimo-v2.5-asr"          # 改为其他 ASR 模型

# ─── DeepSeek API（所有文本处理）───
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
MODEL_DEEPSEEK = "deepseek-v4-pro"   # 可改为 deepseek-v4-flash（更快更便宜）
```

由于两个 API 都兼容 OpenAI 协议，理论上任何兼容 OpenAI 的模型服务都可以替换（如 OpenAI 自身、智谱、月之暗面等），只需修改 `BASE_URL` 和模型名。

## 快速开始

### 1. 环境要求

- Python 3.10+
- 两个 API Key：
  - 小米 Mimo：[获取地址](https://token-plan-cn.xiaomimimo.com)，格式 `tp-xxxxx`
  - DeepSeek：[获取地址](https://platform.deepseek.com)，格式 `sk-xxxxx`

### 2. 安装依赖

```bash
git clone https://github.com/incredible2001/AudioChronolog.git
cd AudioChronolog
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
```

### 3. 配置 API Key

```bash
cp .env.example .env
```

编辑 `.env`，填入两个 Key：

```
XIAOMI_API_KEY=tp-你的mimo密钥
DEEPSEEK_API_KEY=sk-你的deepseek密钥
```

### 4. 启动 GUI（推荐）

```bash
python scripts/app.py
```

浏览器会自动打开 `http://localhost:5000`，然后：

1. **创建项目** → 填写项目名和 Background（包含参会人员信息，用于说话人识别）
2. **上传录音** → 拖拽音频文件，支持 mp3/wav/m4a/flac/ogg/webm/aac
3. **开始处理** → 实时查看进度
4. **查看报告** → 处理完成后直接浏览

### 5. 或使用命令行

```bash
# 将录音放入 input/<项目名>/ 后运行
python scripts/process.py
# 报告生成在 output/<项目名>/reports/index.html
```

## 说话人识别

Background 中的参会人员信息是说话人识别的关键。写得越详细，识别越准确：

```markdown
## Background
本项目记录课题组讨论。
参会人员：
- XF：PI，负责临床分组建议，说话风格直接
- LT：博士生，负责生信数据分析，会展示代码和图表
- SQ：合作者，参与讨论设计，提问较多
```

也可以在录音同目录放一个同名 `.md` 文件作为补充提示：

```
input/课题组/
├── 2026-06-17-讨论.mp3
└── 2026-06-17-讨论.md    ← 写上"今日参会：张三、李四、王五"
```

## 目录结构

```
AudioChronolog/
├── input/                         # 录音输入
│   └── <项目名>/
│       ├── README.md              # 项目描述 + 自动维护的记忆
│       └── YYYY-MM-DD-*.mp3       # 录音文件
│
├── output/                        # 自动生成（不提交 Git）
│   └── <项目名>/
│       ├── conversations/         # 矫正后的对话 Markdown
│       ├── insights/              # 结构化信息 JSON
│       └── reports/               # HTML 报告
│
├── scripts/
│   ├── app.py                     # GUI 入口
│   ├── process.py                 # 命令行入口
│   ├── transcribe.py              # 语音转文字（Mimo）
│   ├── correct.py                 # 矫正 + 说话人识别（DeepSeek）
│   ├── extract_insights.py        # 提取结构化信息（DeepSeek）
│   ├── generate_report.py         # 生成 HTML 报告
│   ├── update_memory.py           # 更新记忆（DeepSeek）
│   ├── config.py                  # 配置管理
│   └── utils.py                   # 工具函数
│
├── templates/
│   ├── gui/                       # GUI 页面模板
│   └── report_template.html       # 报告模板
├── .env.example                   # API Key 模板
└── requirements.txt
```

## 环境变量

| 变量名 | 说明 | 用途 | 必填 |
|--------|------|------|------|
| `XIAOMI_API_KEY` | 小米 Mimo API Key | 语音转录 | ✅ |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | 文本处理 | ✅ |

## 常见问题

**Q: 处理很慢？** 长录音需要分段转录，一般 1 分钟录音约需 1 分钟处理。DeepSeek 文本处理部分通常 30-60 秒。

**Q: 说话人识别不准？** 在 Background 中补充更多说话人线索（角色、说话风格、专业领域）。

**Q: 想用更便宜的模型？** 把 `config.py` 中的 `MODEL_DEEPSEEK` 改为 `deepseek-v4-flash`。

**Q: 报告在哪里？** `output/<项目名>/reports/index.html`，标准 HTML 文件，可离线查看和打印。
