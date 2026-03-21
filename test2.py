from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory
import pandas as pd
import random
import os
import subprocess
import tempfile
import wave
import base64
import binascii
import struct
import time
from datetime import datetime
import urllib.parse
import re
import requests

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

# 初始化DeepSeek客户端（强烈建议把 key 放到环境变量里）
# 全局变量
group_prompts = {}
all_processed_data_cache = {}

# 指定ffmpeg路径（根据您的实际路径修改）
FFMPEG_PATH = r"C:\ffmpeg\ffmpeg-master-latest-win64-gpl-shared\bin\ffmpeg.exe"

if not os.path.exists(FFMPEG_PATH):
    FFMPEG_PATH = "ffmpeg"

# 只创建一个录音保存目录，用于存储WAV文件
RECORDINGS_DIR = "recordings"
os.makedirs(RECORDINGS_DIR, exist_ok=True)

# 创建图片保存目录结构
IMAGE_BASE_DIR = "image"
IMAGE_SUB_DIRS = {
    'result_data': 'normal',
    'result_data_special': 'special',
    'result_data_free': 'free',
    'result_data_downWord': 'downword',
    'result_data_upWord': 'upword',
    'result_data_normalWord': 'middle'
}

for sub_dir in IMAGE_SUB_DIRS.values():
    os.makedirs(os.path.join(IMAGE_BASE_DIR, sub_dir), exist_ok=True)


def check_ffmpeg_available():
    """检查ffmpeg是否已安装并可调用"""
    try:
        cmd = FFMPEG_PATH if os.path.exists(FFMPEG_PATH) else 'ffmpeg'
        result = subprocess.run(
            [cmd, '-version'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


# ========== 新增：生成安全的文件名（直接使用中文姓名） ==========
def decode_process_output(output_bytes):
    """将子进程输出字节尽量安全地解码为字符串。"""
    if not output_bytes:
        return ""
    if isinstance(output_bytes, str):
        return output_bytes

    for encoding in ("utf-8", "gbk", "cp936"):
        try:
            return output_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return output_bytes.decode("utf-8", errors="replace")


def normalize_duration_seconds(duration_seconds):
    """将耗时规范为非负浮点秒数。"""
    try:
        value = float(duration_seconds)
        return value if value >= 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


def format_duration_for_filename(duration_seconds):
    """生成用于文件名的耗时片段，例如 12.34s。"""
    return f"{normalize_duration_seconds(duration_seconds):.2f}s"


def sanitize_student_name_for_path(student_id, student_name):
    """清理姓名为可用于路径的安全片段。"""
    safe_name = re.sub(r'[<>:"/\\|?*]', '_', student_name.strip())
    safe_name = safe_name.replace(',', '，')
    safe_name = safe_name.replace('\n', '').replace('\r', '').replace('\t', '')
    if not safe_name:
        safe_name = f"Student{student_id[-4:]}"
    if len(safe_name) > 30:
        safe_name = safe_name[:30]
    return safe_name


def build_student_folder_name(student_id, safe_name):
    """未完成阶段的实验者子文件夹名。"""
    return f"{student_id}_{safe_name}"


def build_completed_student_folder_name(student_id, safe_name, total_duration):
    """完成阶段的实验者子文件夹名（包含总耗时）。"""
    total_part = format_duration_for_filename(total_duration)
    folder_name = f"{student_id}_{safe_name}_total_{total_part}"
    return re.sub(r'[<>:\"/\\\\|?*]', '_', folder_name)


def generate_safe_filename(student_id, student_name, group, unique_key, timestamp, question_duration=None):
    """
    生成安全的文件名：直接使用中文姓名作为文件名的一部分（不转拼音）
    仅清理 Windows 不允许的字符，并处理逗号等会影响记录解析的字符。
    """
    # 清理文件名非法字符（Windows）
    safe_name = sanitize_student_name_for_path(student_id, student_name)

    safe_unique_key = unique_key.replace('_', '-')
    duration_segment = format_duration_for_filename(question_duration)
    filename = f"{student_id}_{safe_name}_{duration_segment}_{group}_{safe_unique_key}_{timestamp}.wav"
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)

    # 为了兼容原有字段名，仍返回 pinyin_name（这里其实就是“安全中文名”）
    return filename, safe_name


def create_empty_wav_file(filepath, duration_seconds=1):
    """创建空的WAV文件（静音）"""
    try:
        sample_rate = 16000
        num_samples = int(sample_rate * duration_seconds)
        silent_data = b'\x00' * (num_samples * 2)
        
        with wave.open(filepath, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(silent_data)
        return True
    except Exception as e:
        print(f"创建空WAV文件失败: {e}")
        return False


def convert_base64_to_wav(audio_data_base64, output_path):
    """直接将Base64编码的音频数据转换为WAV文件"""
    try:
        if not isinstance(audio_data_base64, str):
            return False, "音频数据类型错误"

        audio_data_base64 = audio_data_base64.strip()
        if not audio_data_base64:
            return False, "音频数据为空"

        # 支持标准 data URL：data:audio/<mime>;base64,<payload>
        if audio_data_base64.startswith("data:audio/"):
            if ";base64," not in audio_data_base64:
                return False, "音频数据不是 base64 data URL"
            header, payload = audio_data_base64.split(",", 1)
            mime_type = header.split(":", 1)[1].split(";", 1)[0].lower()
        else:
            # 兼容历史前端：直接传纯 base64
            mime_type = "audio/webm"
            payload = audio_data_base64

        payload = re.sub(r"\s+", "", payload)
        if not payload:
            return False, "音频 base64 负载为空"

        # 处理缺失 padding 的情况
        missing_padding = len(payload) % 4
        if missing_padding:
            payload += "=" * (4 - missing_padding)

        try:
            audio_bytes = base64.b64decode(payload, validate=True)
        except binascii.Error as decode_error:
            return False, f"音频 base64 解码失败: {decode_error}"

        if not audio_bytes:
            return False, "音频字节为空"

        # wav 直接落盘，无需 ffmpeg 转换
        if mime_type in {"audio/wav", "audio/x-wav", "audio/wave"}:
            with open(output_path, "wb") as f:
                f.write(audio_bytes)
            if os.path.getsize(output_path) == 0:
                return False, "WAV 文件为空"
            return True, output_path

        suffix_map = {
            "audio/webm": ".webm",
            "audio/mp4": ".m4a",
            "audio/x-m4a": ".m4a",
            "audio/mpeg": ".mp3",
            "audio/mp3": ".mp3",
            "audio/ogg": ".ogg",
            "audio/opus": ".opus",
            "audio/aac": ".aac",
        }
        temp_suffix = suffix_map.get(mime_type, ".bin")

        with tempfile.NamedTemporaryFile(suffix=temp_suffix, delete=False) as temp_file:
            temp_path = temp_file.name
            temp_file.write(audio_bytes)

        try:
            cmd = [FFMPEG_PATH, "-y", "-i", temp_path, "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", output_path]
            process = subprocess.run(cmd, capture_output=True, timeout=30)
        finally:
            try:
                os.remove(temp_path)
            except Exception:
                pass

        if process.returncode != 0:
            stderr_text = decode_process_output(process.stderr)
            stderr_tail = (stderr_text or "").strip()[-300:]
            return False, f"音频转换失败(ffmpeg): {stderr_tail or '无错误输出'}"

        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            return False, "音频转换后文件为空"

        return True, output_path

    except FileNotFoundError:
        return False, f"未找到 ffmpeg，可执行路径: {FFMPEG_PATH}"
    except subprocess.TimeoutExpired:
        return False, "音频转换超时"
    except Exception as e:
        return False, f"音频转换异常: {str(e)}"


def is_wav_effectively_silent(filepath, max_seconds=3, amplitude_threshold=120):
    """粗略判断 wav 是否几乎静音（16-bit PCM）"""
    try:
        with wave.open(filepath, "rb") as wav_file:
            sample_width = wav_file.getsampwidth()
            channels = wav_file.getnchannels()
            framerate = wav_file.getframerate()
            total_frames = wav_file.getnframes()

            if sample_width != 2 or channels <= 0 or framerate <= 0 or total_frames <= 0:
                return False

            frames_to_read = min(total_frames, framerate * max_seconds)
            raw = wav_file.readframes(frames_to_read)
            if not raw:
                return True

            sample_count = len(raw) // 2
            if sample_count <= 0:
                return True

            samples = struct.unpack("<" + ("h" * sample_count), raw[:sample_count * 2])
            max_amp = max(abs(v) for v in samples) if samples else 0
            return max_amp < amplitude_threshold
    except Exception as e:
        print(f"静音检测失败: {e}")
        return False


# ========== 保存音频文件函数 - 确保即使为空也保存 ==========
def build_audio_info(filepath, filename, student_name, safe_name, success, empty, message, student_folder, error=None):
    result = {
        'filepath': filepath,
        'filename': filename,
        'original_name': student_name,
        'pinyin_name': safe_name,
        'format': 'wav',
        'success': success,
        'empty': empty,
        'message': message,
        'student_folder': student_folder
    }
    if error is not None:
        result['error'] = error
    return result


def save_audio_file(audio_data, student_id, student_name, group, unique_key, question_duration=None):
    """保存录音为WAV格式文件，文件名直接使用中文姓名。"""
    wav_filepath = None
    wav_filename = None
    wav_relative_path = None
    safe_name = None

    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        wav_filename, safe_name = generate_safe_filename(
            student_id, student_name, group, unique_key, timestamp, question_duration
        )

        student_folder = build_student_folder_name(student_id, safe_name)
        student_dir = os.path.join(RECORDINGS_DIR, student_folder)
        os.makedirs(student_dir, exist_ok=True)

        wav_filepath = os.path.join(student_dir, wav_filename)
        wav_relative_path = os.path.join(student_folder, wav_filename)

        print(f"开始处理WAV文件: {wav_filename}")
        print(f"  原始姓名: {student_name}")
        print(f"  文件名姓名段: {safe_name}")
        print(f"  子文件夹: {student_folder}")

        if not audio_data or audio_data.strip() == '':
            print("⚠️ 录音数据为空，创建空WAV文件")
            create_empty_wav_file(wav_filepath)
            return build_audio_info(
                wav_filepath, wav_relative_path, student_name, safe_name,
                success=False, empty=True, message='录音为空，请检查麦克风权限后重试', student_folder=student_folder
            )

        if not audio_data.startswith('data:audio/'):
            print("⚠️ 音频数据格式不正确，尝试修复")
            if audio_data.strip():
                audio_data = f"data:audio/webm;base64,{audio_data}"
            else:
                print("⚠️ 音频数据修复后仍为空，创建空WAV文件")
                create_empty_wav_file(wav_filepath)
                return build_audio_info(
                    wav_filepath, wav_relative_path, student_name, safe_name,
                    success=False, empty=True, message='音频数据格式错误，请重试录音', student_folder=student_folder
                )

        try:
            success, result = convert_base64_to_wav(audio_data, wav_filepath)
            if success:
                if is_wav_effectively_silent(wav_filepath):
                    print("⚠️ 检测到录音文件几乎静音")
                    return build_audio_info(
                        wav_filepath, wav_relative_path, student_name, safe_name,
                        success=False, empty=True, message='检测到静音，请检查麦克风输入设备后重试',
                        student_folder=student_folder, error='wav_silent'
                    )
                print(f"✅ WAV文件保存成功: {wav_filename}")
                return build_audio_info(
                    wav_filepath, wav_relative_path, student_name, safe_name,
                    success=True, empty=False, message='录音文件保存成功', student_folder=student_folder
                )
            else:
                print(f"❌ WAV文件转换失败: {result}")
                create_empty_wav_file(wav_filepath)
                return build_audio_info(
                    wav_filepath, wav_relative_path, student_name, safe_name,
                    success=False, empty=True, message='音频转换失败',
                    student_folder=student_folder, error=result
                )

        except Exception as e:
            print(f"音频转换异常: {e}")
            create_empty_wav_file(wav_filepath)
            return build_audio_info(
                wav_filepath, wav_relative_path, student_name, safe_name,
                success=False, empty=True, message='音频处理异常',
                student_folder=student_folder, error=str(e)
            )

    except Exception as e:
        print(f"保存音频文件时出错: {e}")
        try:
            if wav_filepath and wav_filename:
                create_empty_wav_file(wav_filepath)
                print(f"⚠️ 创建了空的WAV文件作为备份: {wav_filename}")
                backup_name = safe_name or sanitize_student_name_for_path(student_id, student_name)
                return build_audio_info(
                    wav_filepath, wav_relative_path or wav_filename, student_name, safe_name or student_name,
                    success=False, empty=True, message='系统错误，已创建空文件',
                    student_folder=build_student_folder_name(student_id, backup_name), error=str(e)
                )
        except Exception as e2:
            print(f"连空文件都无法创建: {e2}")
            import traceback
            traceback.print_exc()
            backup_name = safe_name or sanitize_student_name_for_path(student_id, student_name)
            return build_audio_info(
                None, wav_relative_path or wav_filename, student_name, safe_name or student_name,
                success=False, empty=True, message='系统严重错误，无法创建文件',
                student_folder=build_student_folder_name(student_id, backup_name),
                error=f"{str(e)}; {str(e2)}"
            )


def get_record_info(parts):
    """根据逗号分隔的parts列表解析记录信息"""
    if len(parts) >= 15:
        question_duration = normalize_duration_seconds(parts[13]) if parts[13] != '' else None
        total_duration = normalize_duration_seconds(parts[14]) if parts[14] != '' else None
        return {
            'student_id': parts[0], 'original_name': parts[1], 'pinyin_name': parts[2],
            'group': parts[3], 'vg_object_id': parts[4], 'filename': parts[5],
            'timestamp': parts[6], 'unique_key': parts[7], 'source_file': parts[8],
            'format': parts[9], 'success': parts[10] == 'True', 'empty': parts[11] == 'True',
            'message': parts[12] if len(parts) > 12 else '',
            'question_duration': question_duration,
            'total_duration': total_duration
        }
    elif len(parts) >= 13:
        return {
            'student_id': parts[0], 'original_name': parts[1], 'pinyin_name': parts[2],
            'group': parts[3], 'vg_object_id': parts[4], 'filename': parts[5],
            'timestamp': parts[6], 'unique_key': parts[7], 'source_file': parts[8],
            'format': parts[9], 'success': parts[10] == 'True', 'empty': parts[11] == 'True',
            'message': parts[12] if len(parts) > 12 else '',
            'question_duration': None,
            'total_duration': None
        }
    elif len(parts) >= 10:
        return {
            'student_id': parts[0], 'original_name': parts[1], 'pinyin_name': parts[1],
            'group': parts[2], 'vg_object_id': parts[3], 'filename': parts[4],
            'timestamp': parts[5], 'unique_key': parts[6], 'source_file': parts[7],
            'format': parts[8], 'success': parts[9] == 'True', 'empty': False, 'message': '',
            'question_duration': None,
            'total_duration': None
        }
    return None


def check_completion(group, student_id):
    """检查参与者是否完成了该组的所有题目"""
    if not os.path.exists("recordings_info.txt"):
        return False
    if group not in group_prompts:
        return False

    group_images = group_prompts[group]
    group_unique_keys = {data['unique_key'] for data in group_images.values()}
    answered_unique_keys = set()
    
    with open("recordings_info.txt", "r", encoding='utf-8') as f:
        for line in f:
            parts = line.strip().split(',')
            record_info = get_record_info(parts)
            if record_info and record_info['student_id'] == student_id and record_info['group'] == group:
                if record_info.get('unique_key'):
                    answered_unique_keys.add(record_info['unique_key'])

    return group_unique_keys.issubset(answered_unique_keys)


def has_completed_experiment(student_id):
    """检查学号是否已完成任意一组实验"""
    if not os.path.exists("recordings_info.txt"):
        return False

    completed_groups = set()
    with open("recordings_info.txt", "r", encoding='utf-8') as f:
        for line in f:
            parts = line.strip().split(',')
            record_info = get_record_info(parts)
            if record_info and record_info['student_id'] == student_id:
                if record_info['group'] in group_prompts:
                    if check_completion(record_info['group'], student_id):
                        completed_groups.add(record_info['group'])

    return len(completed_groups) > 0


def save_recording_info(student_id, student_name, group, vg_object_id, unique_key, source_file, audio_info,
                        question_duration=None, total_duration=None):
    """保存录音信息到记录文件"""
    try:
        os.makedirs(RECORDINGS_DIR, exist_ok=True)

        filename = audio_info['filename']
        # 兼容字段名：这里可能是“安全中文名”
        pinyin_name = audio_info.get('pinyin_name', student_name)
        success = audio_info.get('success', False)
        empty = audio_info.get('empty', False)
        message = audio_info.get('message', '')

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        question_duration_value = normalize_duration_seconds(question_duration)
        total_duration_value = normalize_duration_seconds(total_duration) if total_duration is not None else None
        question_duration_str = f"{question_duration_value:.3f}"
        total_duration_str = f"{total_duration_value:.3f}" if total_duration_value is not None else ""

        # 新格式：学号,原始姓名,拼音姓名(这里存安全中文名),组别,图片ID,文件名,时间戳,唯一键,来源文件,格式,是否成功,是否为空,备注,单题耗时秒,总耗时秒
        record_line = (
            f"{student_id},{student_name},{pinyin_name},{group},{vg_object_id},{filename},"
            f"{timestamp},{unique_key},{source_file},wav,{success},{empty},{message},"
            f"{question_duration_str},{total_duration_str}\n"
        )

        with open("recordings_info.txt", "a", encoding='utf-8') as f:
            f.write(record_line)

        status_text = "成功" if success else "失败"
        empty_text = "（空文件）" if empty else ""
        print(f"录音信息已记录: 学号={student_id}, 姓名={student_name}, 组别={group}, 文件={filename}, 状态={status_text}{empty_text}, 备注={message}")

        return success

    except Exception as e:
        print(f"保存录音信息时出错: {e}")
        import traceback
        traceback.print_exc()
        return False


def calculate_total_duration(student_id, group):
    """统计某位参与者在某组内所有题目的累计耗时（秒）。"""
    total_duration = 0.0
    if not os.path.exists("recordings_info.txt"):
        return total_duration

    with open("recordings_info.txt", "r", encoding='utf-8') as f:
        for line in f:
            parts = line.strip().split(',')
            record_info = get_record_info(parts)
            if not record_info:
                continue
            if record_info.get('student_id') != student_id or record_info.get('group') != group:
                continue
            question_duration = record_info.get('question_duration')
            if question_duration is None:
                continue
            total_duration += normalize_duration_seconds(question_duration)
    return total_duration


def has_total_duration_record(student_id, group):
    """避免重复写入 TOTAL_DURATION 记录。"""
    if not os.path.exists("recordings_info.txt"):
        return False

    with open("recordings_info.txt", "r", encoding='utf-8') as f:
        for line in f:
            parts = line.strip().split(',')
            record_info = get_record_info(parts)
            if not record_info:
                continue
            if (record_info.get('student_id') == student_id and
                    record_info.get('group') == group and
                    record_info.get('unique_key') == 'TOTAL_DURATION'):
                return True
    return False


def get_next_image_index(group, current_index):
    """按组内题目顺序获取下一题索引。"""
    group_images = group_prompts[group]
    sorted_indices = sorted([int(idx) for idx in group_images.keys()])
    try:
        current_pos = sorted_indices.index(int(current_index))
        next_pos = (current_pos + 1) % len(sorted_indices)
        return str(sorted_indices[next_pos])
    except ValueError:
        return str(sorted_indices[0])


def update_recordings_info_folder_name(student_id, group, old_folder_name, new_folder_name):
    """重命名子文件夹后，同步修正 recordings_info.txt 里的相对路径。"""
    info_path = "recordings_info.txt"
    if not os.path.exists(info_path):
        return

    updated_lines = []
    changed = False
    old_prefix = old_folder_name + os.sep
    new_prefix = new_folder_name + os.sep

    with open(info_path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")
            parts = line.split(',')
            if len(parts) >= 13 and parts[0] == student_id and parts[3] == group:
                filename = parts[5]
                if filename.startswith(old_prefix):
                    parts[5] = new_prefix + filename[len(old_prefix):]
                    line = ",".join(parts)
                    changed = True
            updated_lines.append(line + "\n")

    if changed:
        with open(info_path, "w", encoding="utf-8") as f:
            f.writelines(updated_lines)


def finalize_student_folder_with_total_duration(student_id, student_name, group, total_duration):
    """把实验者子文件夹重命名为包含总耗时的名称。"""
    safe_name = sanitize_student_name_for_path(student_id, student_name)
    old_folder_name = build_student_folder_name(student_id, safe_name)
    new_folder_name = build_completed_student_folder_name(student_id, safe_name, total_duration)

    old_dir = os.path.join(RECORDINGS_DIR, old_folder_name)
    if not os.path.exists(old_dir):
        return old_folder_name

    final_folder_name = new_folder_name
    final_dir = os.path.join(RECORDINGS_DIR, final_folder_name)
    suffix = 1
    while os.path.exists(final_dir):
        final_folder_name = f"{new_folder_name}_{suffix}"
        final_dir = os.path.join(RECORDINGS_DIR, final_folder_name)
        suffix += 1

    os.rename(old_dir, final_dir)
    update_recordings_info_folder_name(student_id, group, old_folder_name, final_folder_name)
    return final_folder_name


def download_single_image(image_url, save_path, max_retries=3):
    """下载单张图片到本地"""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    for attempt in range(max_retries):
        try:
            if os.path.exists(save_path) and os.path.getsize(save_path) > 1024:
                return save_path

            response = requests.get(image_url, headers=headers, timeout=10)
            response.raise_for_status()

            with open(save_path, 'wb') as f:
                f.write(response.content)

            if os.path.exists(save_path) and os.path.getsize(save_path) > 1024:
                return save_path
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            continue
    return None


def get_local_image_path(image_url, source_file, vg_object_id):
    """根据图片URL、来源文件和vg_object_id获取本地图片路径"""
    parsed_url = urllib.parse.urlparse(image_url)
    filename = os.path.basename(parsed_url.path)

    if not os.path.splitext(filename)[1]:
        filename += '.jpg'

    file_base = os.path.splitext(filename)[0]
    file_ext = os.path.splitext(filename)[1]

    safe_source = source_file.replace('result_data_', '').replace('result_data', '')
    filename = f"{safe_source}_{vg_object_id}_{file_base}{file_ext}"

    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)

    if source_file in IMAGE_SUB_DIRS:
        sub_dir = IMAGE_SUB_DIRS[source_file]
    else:
        sub_dir = 'other'

    local_path = os.path.join(IMAGE_BASE_DIR, sub_dir, filename)
    web_path = f"/image/{sub_dir}/{urllib.parse.quote(filename)}"

    return local_path, web_path


def load_and_download_all_data():
    """加载所有Excel文件并下载图片"""
    data_files = {
        'result_data': 'result_data.xlsx',
        'result_data_special': 'result_data_special.xlsx',
        'result_data_free': 'result_data_free.xlsx',
        'result_data_downWord': 'result_data_downWord.xlsx',
        'result_data_upWord': 'result_data_upWord.xlsx',
        'result_data_normalWord': 'result_data_normalWord.xlsx'
    }

    all_processed_data = {}

    for file_key, file_path in data_files.items():
        try:
            data = pd.read_excel(file_path)
            required_columns = ['vg_object_id', 'prompt', 'link_mn']
            if not all(col in data.columns for col in required_columns):
                continue

            processed_images = {}
            for idx, row in data.iterrows():
                vg_object_id = str(row['vg_object_id'])
                unique_key = f"{file_key}_{vg_object_id}"
                local_path, web_path = get_local_image_path(row['link_mn'], file_key, vg_object_id)

                if not (os.path.exists(local_path) and os.path.getsize(local_path) > 1024):
                    download_single_image(row['link_mn'], local_path)

                use_path = web_path if os.path.exists(local_path) else row['link_mn']
                processed_images[unique_key] = {
                    'unique_key': unique_key, 'vg_object_id': vg_object_id,
                    'prompt': row['prompt'], 'image_url': row['link_mn'],
                    'image_local_path': use_path, 'source_file': file_key, 'original_index': idx
                }

            all_processed_data[file_key] = processed_images
        except Exception as e:
            print(f"处理文件 {file_path} 时出错: {e}")

    return all_processed_data


def create_groups_from_processed_data(all_processed_data):
    """从处理后的数据创建实验组"""
    target_group_size = 72
    per_file_minimum = 12

    if not all_processed_data:
        return {}

    total_unique_questions = sum(len(images) for images in all_processed_data.values())
    if total_unique_questions < target_group_size:
        return {}

    for file_key, images in all_processed_data.items():
        if len(images) < per_file_minimum:
            return {}

    groups = {f'group_{i}': [] for i in range(1, 6)}

    for group_name in groups.keys():
        selected_images = []
        for file_key, images in all_processed_data.items():
            all_unique_keys = list(images.keys())
            selected_keys = random.sample(all_unique_keys, per_file_minimum)
            selected_images.extend([images[key] for key in selected_keys])

        if len(selected_images) < target_group_size:
            remaining = target_group_size - len(selected_images)
            for file_key, images in all_processed_data.items():
                if remaining <= 0:
                    break
                selected_keys = {img['unique_key'] for img in selected_images}
                available_keys = [k for k in images.keys() if k not in selected_keys]
                if available_keys:
                    supplement = random.sample(available_keys, min(remaining, len(available_keys)))
                    selected_images.extend([images[key] for key in supplement])
                    remaining -= len(supplement)

        if len(selected_images) < target_group_size:
            return {}

        random.shuffle(selected_images)
        groups[group_name] = selected_images

    return groups


def assign_prompts_to_groups(groups):
    """为每个组的图片分配提示词和序号"""
    group_prompts_dict = {}
    for group_name, images in groups.items():
        group_data = {}
        for idx, image_data in enumerate(images, 1):
            group_data[str(idx)] = {
                'index': idx, 'unique_key': image_data['unique_key'],
                'vg_object_id': image_data['vg_object_id'], 'prompt': image_data['prompt'],
                'image_url': image_data['image_url'], 'image_local_path': image_data['image_local_path'],
                'source_file': image_data['source_file'], 'original_index': image_data.get('original_index', idx)
            }
        group_prompts_dict[group_name] = group_data
    return group_prompts_dict


def refresh_group_prompts(force_reload=False):
    """刷新5个实验组的图片分配。"""
    global group_prompts, all_processed_data_cache

    if force_reload or not all_processed_data_cache:
        all_processed_data_cache = load_and_download_all_data()
        if not all_processed_data_cache:
            print("刷新实验组失败：未能加载数据文件")
            return False

    groups = create_groups_from_processed_data(all_processed_data_cache)
    if not groups:
        print("刷新实验组失败：未能创建实验组")
        return False

    group_prompts = assign_prompts_to_groups(groups)
    print(f"实验组图片已刷新，共创建了 {len(group_prompts)} 个实验组")
    return True


def is_valid_student_id(student_id):
    """验证学号是否为10位数字"""
    return bool(re.match(r'^\d{10}$', student_id))


def student_id_exists_in_recording_folders(student_id):
    """检查 recordings 一级子文件夹名中是否已存在该学号"""
    if not os.path.isdir(RECORDINGS_DIR):
        return False

    pattern = re.compile(rf'^{re.escape(student_id)}(?:_|$)')
    try:
        for folder_name in os.listdir(RECORDINGS_DIR):
            folder_path = os.path.join(RECORDINGS_DIR, folder_name)
            if os.path.isdir(folder_path) and pattern.match(folder_name):
                return True
    except Exception as e:
        print(f"检查 recordings 子文件夹失败: {e}")
    return False


def is_valid_student_name(student_name):
    """验证姓名格式"""
    if not student_name:
        return False
    if re.search(r'[<>:"/\\|?*,\n\r\t]', student_name):
        return False
    return True


def clear_student_session():
    """清除学生的session信息"""
    session.pop('student_id', None)
    session.pop('student_name', None)
    session.pop('completed_group', None)
    session.pop('current_group', None)
    session.pop('total_duration', None)


# ========== Flask路由（保持不变）==========
@app.route('/')
def home():
    clear_student_session()
    return redirect(url_for('rules'))


@app.route('/rules', methods=['GET', 'POST'])
def rules():
    student_id = ''
    student_name = ''
    show_rules = False
    error = ''
    completed_warning = ''

    if request.method == 'POST':
        student_id = request.form.get('student_id', '').strip()
        student_name = request.form.get('student_name', '').strip()

        if not student_id:
            error = '请输入学号'
        elif not is_valid_student_id(student_id):
            error = '学号必须是10位数字'
        elif student_id_exists_in_recording_folders(student_id):
            error = '学号有误'
        elif not student_name:
            error = '请输入姓名'
        elif not is_valid_student_name(student_name):
            error = '姓名包含不允许的特殊字符或逗号（<>:"/\\|?* ,）'
        else:
            try:
                if has_completed_experiment(student_id):
                    completed_warning = f'学号 {student_id} 已完成实验。如需重新实验，请使用新的学号。'
                    show_rules = False
                else:
                    session['student_id'] = student_id
                    session['student_name'] = student_name
                    show_rules = True
            except Exception as e:
                print(f"检查实验完成状态时出错: {e}")
                error = "系统错误"
                show_rules = False

    elif 'student_id' in session and 'student_name' in session:
        student_id = session['student_id']
        student_name = session['student_name']
        if is_valid_student_id(student_id) and is_valid_student_name(student_name):
            try:
                if has_completed_experiment(student_id):
                    completed_warning = f'学号 {student_id} 已完成实验。如需重新实验，请使用新的学号。'
                    show_rules = False
                    clear_student_session()
                else:
                    show_rules = True
            except Exception as e:
                print(f"检查实验完成状态时出错: {e}")
                error = "系统错误"
                show_rules = False
                clear_student_session()

    return render_template('rules.html',
                           student_id=student_id,
                           student_name=student_name,
                           show_rules=show_rules,
                           error=error,
                           completed_warning=completed_warning)


@app.route('/index')
def index():
    if 'student_id' not in session or 'student_name' not in session:
        return redirect(url_for('rules'))

    student_id = session['student_id']
    student_name = session['student_name']

    if not is_valid_student_id(student_id) or not is_valid_student_name(student_name):
        clear_student_session()
        return redirect(url_for('rules'))

    try:
        if has_completed_experiment(student_id):
            clear_student_session()
            return redirect(url_for('rules'))
    except Exception as e:
        print(f"检查实验完成状态时出错: {e}")
        clear_student_session()
        return redirect(url_for('rules'))

    global group_prompts
    return render_template('index.html',
                           groups=list(group_prompts.keys()),
                           student_id=student_id,
                           student_name=student_name)


@app.route('/answer/<group>/<image_index>', methods=['GET', 'POST'])
def answer(group, image_index):
    if 'student_id' not in session or 'student_name' not in session:
        return redirect(url_for('rules'))

    student_id = session['student_id']
    student_name = session['student_name']

    if not is_valid_student_id(student_id) or not is_valid_student_name(student_name):
        clear_student_session()
        return redirect(url_for('rules'))

    try:
        if has_completed_experiment(student_id):
            clear_student_session()
            return redirect(url_for('rules'))
    except Exception as e:
        print(f"检查实验完成状态时出错: {e}")
        clear_student_session()
        return redirect(url_for('rules'))

    if group not in group_prompts:
        return f"无效的实验组: {group}", 404

    image_data = group_prompts[group].get(image_index)
    if not image_data:
        return "Image not found", 404

    image_url = image_data.get('image_local_path', image_data.get('image_url', ''))
    prompt = image_data['prompt']
    total_images = len(group_prompts[group])
    vg_object_id = image_data['vg_object_id']
    unique_key = image_data['unique_key']
    source_file = image_data['source_file']

    if request.method == 'POST':
        audio_data = request.form.get('audio_data', '')
        question_duration = normalize_duration_seconds(request.form.get('question_duration', '0'))

        next_image_index = get_next_image_index(group, image_index)

        audio_info = save_audio_file(audio_data or '', student_id, student_name, group, unique_key, question_duration)

        if audio_info:
            save_recording_info(
                student_id, student_name, group, vg_object_id, unique_key, source_file, audio_info,
                question_duration=question_duration
            )

            if not audio_info.get('success', False):
                error_message = audio_info.get('error') or audio_info.get('message') or '录音保存失败，请重试'
                return jsonify({
                    'status': 'warning',
                    'message': error_message,
                    'next_index': image_index,
                    'file_saved': False,
                    'empty_file': audio_info.get('empty', True)
                })

            if check_completion(group, student_id):
                session['completed_group'] = group
                total_duration = calculate_total_duration(student_id, group)
                session['total_duration'] = total_duration
                if not has_total_duration_record(student_id, group):
                    save_recording_info(
                        student_id, student_name, group, "TOTAL", "TOTAL_DURATION", "system",
                        {'filename': 'TOTAL_DURATION', 'pinyin_name': student_name, 'success': True, 'empty': False,
                         'message': 'all_questions_completed'},
                        question_duration=0,
                        total_duration=total_duration
                    )
                completed_folder = finalize_student_folder_with_total_duration(
                    student_id, student_name, group, total_duration
                )
                return jsonify({
                    'status': 'completed',
                    'message': '所有题目已完成',
                    'next_index': next_image_index,
                    'question_duration': question_duration,
                    'total_duration': total_duration,
                    'completed_folder': completed_folder
                })
            else:
                empty_file = audio_info.get('empty', False)
                file_message = audio_info.get('message', '')

                if empty_file:
                    status_msg = f'录音已保存{file_message}'
                else:
                    status_msg = '录音WAV文件已保存'

                return jsonify({
                    'status': 'success',
                    'message': status_msg,
                    'next_index': next_image_index,
                    'file_saved': True,
                    'empty_file': empty_file,
                    'pinyin_name': audio_info.get('pinyin_name', ''),
                    'question_duration': question_duration
                })
        else:
            return jsonify({
                'status': 'warning',
                'message': '录音保存失败，但继续下一张图片',
                'next_index': next_image_index,
                'file_saved': False
            })

    return render_template('answer_audio_new.html',
                           image_url=image_url,
                           prompt=prompt,
                           image_index=image_index,
                           total_images=total_images,
                           group=group,
                           student_id=student_id,
                           student_name=student_name,
                           vg_object_id=vg_object_id,
                           unique_key=unique_key,
                           source_file=source_file)


@app.route('/next_image/<group>/<image_index>', methods=['GET'])
def next_image(group, image_index):
    if 'student_id' not in session or 'student_name' not in session:
        return redirect(url_for('rules'))

    student_id = session['student_id']
    student_name = session['student_name']

    if not is_valid_student_id(student_id) or not is_valid_student_name(student_name):
        clear_student_session()
        return redirect(url_for('rules'))

    try:
        if has_completed_experiment(student_id):
            clear_student_session()
            return redirect(url_for('rules'))
    except Exception as e:
        print(f"检查实验完成状态时出错: {e}")
        clear_student_session()
        return redirect(url_for('rules'))

    if group not in group_prompts:
        return f"无效的实验组: {group}", 404

    next_image_index = get_next_image_index(group, image_index)

    return redirect(url_for('answer', group=group, image_index=next_image_index))


@app.route('/completion')
def completion():
    if 'student_id' not in session or 'student_name' not in session:
        return redirect(url_for('rules'))

    student_id = session['student_id']
    student_name = session['student_name']

    if not is_valid_student_id(student_id) or not is_valid_student_name(student_name):
        clear_student_session()
        return redirect(url_for('rules'))

    group = session.get('completed_group', '未知组')

    recording_count = 0
    success_count = 0
    total_duration = session.get('total_duration', 0.0)
    if os.path.exists("recordings_info.txt"):
        with open("recordings_info.txt", "r", encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split(',')
                record_info = get_record_info(parts)
                if record_info and record_info['student_id'] == student_id:
                    if record_info.get('unique_key') == 'TOTAL_DURATION':
                        continue
                    recording_count += 1
                    if record_info.get('success', False):
                        success_count += 1
    if not total_duration:
        total_duration = calculate_total_duration(student_id, group)

    return render_template('completion.html',
                           group=group,
                           student_id=student_id,
                           student_name=student_name,
                           recording_count=recording_count,
                           success_count=success_count,
                           total_duration=round(total_duration, 2))


@app.route('/restart')
def restart():
    refreshed = refresh_group_prompts()
    if not refreshed:
        refreshed = refresh_group_prompts(force_reload=True)
    if not refreshed:
        print("警告：重新实验时未能刷新实验组，保留当前实验组配置")

    clear_student_session()
    return redirect(url_for('rules'))


@app.route('/start/<group>')
def start_group(group):
    if 'student_id' not in session or 'student_name' not in session:
        return redirect(url_for('rules'))

    student_id = session['student_id']
    student_name = session['student_name']

    if not is_valid_student_id(student_id) or not is_valid_student_name(student_name):
        clear_student_session()
        return redirect(url_for('rules'))

    try:
        if has_completed_experiment(student_id):
            clear_student_session()
            return redirect(url_for('rules'))
    except Exception as e:
        print(f"检查实验完成状态时出错: {e}")
        clear_student_session()
        return redirect(url_for('rules'))

    if group not in group_prompts:
        return "Group not found", 404

    session['current_group'] = group
    session['total_duration'] = 0.0

    first_image = "1"
    return redirect(url_for('answer', group=group, image_index=first_image))


@app.route('/recordings/<path:filename>')
def serve_recordings(filename):
    try:
        return send_from_directory(RECORDINGS_DIR, filename)
    except Exception:
        return "File not found", 404


@app.route('/image/<path:path>')
def serve_image_generic(path):
    try:
        path = urllib.parse.unquote(path)
        dir_name, filename = os.path.split(path)
        image_dir = os.path.join(IMAGE_BASE_DIR, dir_name)
        return send_from_directory(image_dir, filename)
    except Exception:
        return "Image not found", 404


@app.errorhandler(KeyError)
def handle_key_error(e):
    return render_template('error.html', error="系统内部错误"), 500


@app.errorhandler(404)
def handle_404(e):
    return render_template('error.html', error="页面未找到"), 404


@app.errorhandler(500)
def handle_500(e):
    return render_template('error.html', error="服务器内部错误"), 500


# ========== 主程序 ==========
if __name__ == '__main__':
    ffmpeg_ready = check_ffmpeg_available()
    if ffmpeg_ready:
        print(f"ffmpeg 可用: {FFMPEG_PATH}")
    else:
        print(f"警告: ffmpeg 不可用，录音转码将失败。当前路径: {FFMPEG_PATH}")

    if not refresh_group_prompts(force_reload=True):
        print("错误: 未能初始化实验组")
        exit(1)

    print(f"系统初始化完成，共创建了 {len(group_prompts)} 个实验组")
    
    app.run(debug=True, host='0.0.0.0', port=5000)
