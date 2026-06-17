"""
转录模块：调用小米 Mimo ASR API 将音频转为文本。

官方文档要点：
- 使用 chat.completions.create（非 audio.transcriptions）
- 音频必须 Base64 编码，通过 input_audio 传入
- 仅支持 wav 和 mp3 格式
- Base64 后大小上限 10MB → 自动分段处理
"""

import base64
import logging
import tempfile
from pathlib import Path

import av
from openai import OpenAI

from config import MODEL_ASR

logger = logging.getLogger("AudioChronolog")

# Mimo ASR 支持的音频格式
SUPPORTED_FORMATS = {".wav", ".mp3"}

# 分段参数：wav 16kHz 16bit mono = 32KB/s ≈ 1.92MB/min
# Base64 上限 10MB ≈ 7.5MB raw → 每段约 3.5 分钟，取 3 分钟留余量
CHUNK_DURATION_SEC = 180  # 每段 3 分钟
SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2  # 16-bit PCM
CHANNELS = 1
BYTES_PER_SEC = SAMPLE_RATE * BYTES_PER_SAMPLE * CHANNELS  # 32000


def _convert_to_wav(input_path: Path, output_path: Path) -> None:
    """
    使用 PyAV 将任意音频转换为 wav 格式（16kHz, 单声道 PCM）。

    Args:
        input_path: 输入音频文件路径。
        output_path: 输出 wav 文件路径。
    """
    container = av.open(str(input_path))
    output = av.open(str(output_path), mode="w")
    output_stream = output.add_stream("pcm_s16le", rate=SAMPLE_RATE)
    output_stream.layout = "mono"

    for frame in container.decode(audio=0):
        frame.pts = None
        for packet in output_stream.encode(frame):
            output.mux(packet)

    for packet in output_stream.encode():
        output.mux(packet)

    output.close()
    container.close()


def _split_wav(wav_path: Path) -> list[Path]:
    """
    将 wav 文件按时间分段，每段约 CHUNK_DURATION_SEC 秒。
    直接操作 PCM 字节数据，无需重新编码。

    Args:
        wav_path: 输入 wav 文件路径。

    Returns:
        分段后的 wav 文件路径列表（临时文件）。
    """
    with open(wav_path, "rb") as f:
        raw = f.read()

    # WAV 文件头通常是 44 字节，但为了安全，搜索 "data" 标记
    data_offset = raw.find(b"data")
    if data_offset == -1:
        data_offset = 44  # 默认标准 WAV 头
    else:
        data_offset += 8  # 跳过 "data" + 4字节大小字段

    header = raw[:data_offset]
    pcm_data = raw[data_offset:]
    total_samples = len(pcm_data) // (BYTES_PER_SAMPLE * CHANNELS)
    total_duration = total_samples / SAMPLE_RATE

    chunk_bytes = CHUNK_DURATION_SEC * BYTES_PER_SEC
    # 确保 chunk_bytes 对齐到采样点
    chunk_bytes = chunk_bytes - (chunk_bytes % (BYTES_PER_SAMPLE * CHANNELS))

    num_chunks = max(1, (len(pcm_data) + chunk_bytes - 1) // chunk_bytes)
    logger.info(f"音频时长 {total_duration / 60:.1f} 分钟，拆分为 {num_chunks} 段")

    chunks = []
    for i in range(num_chunks):
        start = i * chunk_bytes
        end = min((i + 1) * chunk_bytes, len(pcm_data))
        chunk_pcm = pcm_data[start:end]

        # 更新 WAV 头中的数据大小
        chunk_size = len(chunk_pcm)
        new_header = bytearray(header)
        # data 标记后的 4 字节是数据大小（小端序）
        data_size_offset = data_offset - 4
        new_header[data_size_offset:data_size_offset + 4] = chunk_size.to_bytes(4, "little")
        # 文件总大小 = header + chunk_size
        file_size = len(new_header) + chunk_size
        # RIFF 头的第 4-8 字节是文件大小 - 8
        new_header[4:8] = (file_size - 8).to_bytes(4, "little")

        tmp = tempfile.NamedTemporaryFile(suffix=f"_chunk{i}.wav", delete=False)
        tmp_path = Path(tmp.name)
        tmp.close()
        with open(tmp_path, "wb") as f:
            f.write(bytes(new_header))
            f.write(chunk_pcm)

        duration = chunk_size / BYTES_PER_SEC
        logger.info(f"  段 {i + 1}: {duration:.1f} 分钟, {chunk_size / 1024 / 1024:.1f}MB")
        chunks.append(tmp_path)

    return chunks


def _wav_to_base64(wav_path: Path) -> str:
    """
    将 wav 文件编码为 data URL 格式的 Base64 字符串。
    """
    with open(wav_path, "rb") as f:
        audio_bytes = f.read()
    b64_str = base64.b64encode(audio_bytes).decode("utf-8")
    return f"data:audio/wav;base64,{b64_str}"


def _call_asr(data_url: str, client: OpenAI) -> str:
    """
    调用 Mimo ASR API 转录单段音频。

    Args:
        data_url: Base64 编码的 data URL。
        client: API 客户端。

    Returns:
        转录文本。
    """
    completion = client.chat.completions.create(
        model=MODEL_ASR,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": data_url,
                        },
                    }
                ],
            }
        ],
        extra_body={
            "asr_options": {
                "language": "zh",
            }
        },
    )
    return completion.choices[0].message.content.strip()


def transcribe(audio_path: str, client: OpenAI) -> str:
    """
    调用 mimo-v2.5-asr 模型转录音频文件。

    自动处理格式转换（m4a/flac/ogg → wav）和大文件分段。

    Args:
        audio_path: 音频文件的完整路径。
        client: OpenAI 兼容的 API 客户端。

    Returns:
        转录后的纯文本（所有分段拼接）。
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"音频文件不存在: {audio_path}")

    logger.info(f"开始转录: {audio_path.name}")

    tmp_files = []  # 需要清理的临时文件
    try:
        # Step 1: 转换为 wav（如需要）
        suffix = audio_path.suffix.lower()
        if suffix in SUPPORTED_FORMATS:
            wav_path = audio_path
        else:
            tmp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp_wav_path = Path(tmp_wav.name)
            tmp_wav.close()
            logger.info(f"转换音频格式: {audio_path.name} → wav")
            _convert_to_wav(audio_path, tmp_wav_path)
            wav_path = tmp_wav_path
            tmp_files.append(tmp_wav_path)
            logger.info(f"转换完成: {tmp_wav_path.stat().st_size / 1024 / 1024:.1f}MB")

        # Step 2: 检查是否需要分段
        # WAV 大小 ≈ raw + 44 字节头，base64 后约 1.33 倍
        file_size = wav_path.stat().st_size
        estimated_base64 = file_size * 4 / 3 + 100  # 粗略估算

        if estimated_base64 <= 10 * 1024 * 1024:
            # 不需要分段
            logger.info(f"音频大小合适（{estimated_base64 / 1024 / 1024:.1f}MB），直接转录")
            data_url = _wav_to_base64(wav_path)
            text = _call_asr(data_url, client)
            logger.info(f"转录完成: {audio_path.name}，共 {len(text)} 字符")
            return text

        # Step 3: 分段转录
        chunks = _split_wav(wav_path)
        tmp_files.extend(chunks)

        texts = []
        for i, chunk_path in enumerate(chunks):
            logger.info(f"转录第 {i + 1}/{len(chunks)} 段...")
            data_url = _wav_to_base64(chunk_path)
            chunk_text = _call_asr(data_url, client)
            texts.append(chunk_text)
            logger.info(f"第 {i + 1} 段完成，{len(chunk_text)} 字符")

        full_text = "\n".join(texts)
        logger.info(f"全部转录完成: {audio_path.name}，共 {len(full_text)} 字符")
        return full_text

    finally:
        # 清理所有临时文件
        for f in tmp_files:
            f.unlink(missing_ok=True)
