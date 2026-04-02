#!/usr/bin/env python3
"""
录音文件转录脚本 - 使用Whisper
将recordings文件夹中的所有录音文件转录为文字
结果保存到translation文件夹的单个txt文件中
"""

import os
import sys
import time
import argparse
import whisper
import wave
import json
from datetime import datetime
from pathlib import Path
import logging

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('transcription.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class WhisperTranscriber:
    def __init__(self, model_size="base", language="zh", output_file=None):
        """
        初始化Whisper转录器

        参数:
            model_size: 模型大小 - tiny, base, small, medium, large (越大越准确，但越慢)
            language: 语言代码，如 'zh' (中文), 'en' (英文)
            output_file: 输出文件路径
        """
        self.model_size = model_size
        self.language = language
        self.output_file = output_file or "translation/all_transcriptions.txt"

        # 创建输出目录
        os.makedirs(os.path.dirname(self.output_file), exist_ok=True)

        # 支持的音频格式
        self.supported_formats = {'.wav', '.mp3', '.m4a', '.flac', '.ogg', '.webm'}

        # 初始化模型（延迟加载）
        self.model = None

        # 统计信息
        self.stats = {
            'total_files': 0,
            'processed': 0,
            'success': 0,
            'failed': 0,
            'total_duration': 0,
            'total_time': 0
        }

    def load_model(self):
        """加载Whisper模型"""
        if self.model is None:
            try:
                logger.info(f"正在加载 Whisper {self.model_size} 模型...")
                start_time = time.time()

                # 加载模型（第一次使用会自动下载模型）
                self.model = whisper.load_model(self.model_size)

                load_time = time.time() - start_time
                logger.info(f"✅ 模型加载完成，耗时: {load_time:.2f}秒")

            except Exception as e:
                logger.error(f"❌ 加载模型时出错: {str(e)}")
                logger.error("请确保已安装whisper库: pip install openai-whisper")
                sys.exit(1)

        return self.model

    def get_audio_info(self, audio_path):
        """获取音频文件信息"""
        try:
            if audio_path.endswith('.wav'):
                with wave.open(audio_path, 'rb') as wav_file:
                    params = wav_file.getparams()
                    duration = params.nframes / params.framerate
                    sample_rate = params.framerate
                    channels = params.nchannels

                return {
                    'duration': duration,
                    'sample_rate': sample_rate,
                    'channels': channels,
                    'file_size': os.path.getsize(audio_path)
                }
            else:
                # 对于非wav文件，使用ffmpeg获取信息
                try:
                    import subprocess
                    cmd = ['ffprobe', '-v', 'error', '-show_entries',
                           'format=duration,sample_rate,channels',
                           '-of', 'json', audio_path]

                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

                    if result.returncode == 0:
                        info = json.loads(result.stdout)
                        format_info = info['format']

                        return {
                            'duration': float(format_info.get('duration', 0)),
                            'sample_rate': int(format_info.get('sample_rate', 0)),
                            'channels': int(format_info.get('channels', 0)),
                            'file_size': os.path.getsize(audio_path)
                        }
                except:
                    pass

                # 如果无法获取详细信息，返回基本信息
                return {
                    'duration': 0,
                    'sample_rate': 0,
                    'channels': 0,
                    'file_size': os.path.getsize(audio_path)
                }

        except Exception as e:
            logger.warning(f"获取音频信息失败: {str(e)}")
            return {
                'duration': 0,
                'sample_rate': 0,
                'channels': 0,
                'file_size': os.path.getsize(audio_path)
            }

    def transcribe_audio(self, audio_path):
        """
        转录单个音频文件

        参数:
            audio_path: 音频文件路径

        返回:
            (成功标志, 转录文本, 处理时间, 音频信息)
        """
        try:
            if not os.path.exists(audio_path):
                return False, f"文件不存在: {audio_path}", 0, None

            filename = os.path.basename(audio_path)
            logger.info(f"开始转录: {filename}")

            # 获取音频信息
            audio_info = self.get_audio_info(audio_path)
            duration = audio_info['duration']

            if duration > 0:
                logger.info(f"  音频时长: {duration:.1f}秒, 大小: {audio_info['file_size'] / 1024:.1f}KB")

            # 加载模型
            model = self.load_model()

            # 开始转录
            start_time = time.time()

            # 转录音频
            result = model.transcribe(
                audio_path,
                language=self.language,
                fp16=False,  # CPU上使用fp16=False
                verbose=False  # 不在控制台显示详细进度
            )

            process_time = time.time() - start_time

            # 提取文本
            text = result["text"].strip()

            if duration > 0:
                real_time_factor = process_time / duration
                logger.info(f"✅ 转录完成! 处理时间: {process_time:.1f}秒, 实时因子: {real_time_factor:.2f}x")
            else:
                logger.info(f"✅ 转录完成! 处理时间: {process_time:.1f}秒")

            return True, text, process_time, audio_info

        except Exception as e:
            logger.error(f"❌ 转录失败: {str(e)}")
            return False, str(e), 0, None

    def save_transcription(self, filename, text, audio_info, process_time, index):
        """
        保存转录结果到文件

        参数:
            filename: 音频文件名
            text: 转录文本
            audio_info: 音频信息
            process_time: 处理时间
            index: 文件序号
        """
        try:
            # 检查文件是否存在，如果不存在则创建并写入头部
            file_exists = os.path.exists(self.output_file)

            with open(self.output_file, 'a', encoding='utf-8') as f:
                # 如果是第一个文件，写入头部信息
                if not file_exists and index == 1:
                    f.write("=" * 80 + "\n")
                    f.write("录音文件转录结果\n")
                    f.write("=" * 80 + "\n")
                    f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"转录模型: Whisper {self.model_size}\n")
                    f.write(f"语言: {self.language}\n")
                    f.write("=" * 80 + "\n\n")

                # 写入文件信息
                f.write(f"[文件 {index}] {filename}\n")
                f.write(f"文件路径: recordings/{filename}\n")

                if audio_info and audio_info['duration'] > 0:
                    f.write(f"音频时长: {audio_info['duration']:.2f}秒\n")
                    f.write(f"采样率: {audio_info['sample_rate']} Hz\n")
                    f.write(f"声道数: {audio_info['channels']}\n")
                    f.write(f"文件大小: {audio_info['file_size'] / 1024:.1f} KB\n")

                f.write(f"处理时间: {process_time:.2f}秒\n")
                f.write(f"转录时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("-" * 50 + "\n")

                # 写入转录文本
                f.write("转录文本:\n")
                f.write(text + "\n")

                f.write("=" * 80 + "\n\n")

            logger.info(f"转录结果已保存到: {self.output_file}")
            return True

        except Exception as e:
            logger.error(f"保存转录结果失败: {str(e)}")
            return False

    def get_audio_files(self, folder_path):
        """获取文件夹中的所有音频文件"""
        folder = Path(folder_path)

        if not folder.exists():
            logger.error(f"❌ 文件夹不存在: {folder.absolute()}")
            return []

        audio_files = []
        for file_path in folder.glob('*'):
            if file_path.suffix.lower() in self.supported_formats:
                audio_files.append(str(file_path))

        # 按文件名排序
        return sorted(audio_files)

    def process_folder(self, folder_path="recordings"):
        """处理整个文件夹的音频文件"""
        logger.info(f"开始处理文件夹: {folder_path}")

        # 获取所有音频文件
        audio_files = self.get_audio_files(folder_path)

        if not audio_files:
            logger.error(f"❌ 在 {folder_path} 中没有找到支持的音频文件")
            logger.info(f"支持的格式: {', '.join(self.supported_formats)}")
            return False

        self.stats['total_files'] = len(audio_files)
        logger.info(f"找到 {len(audio_files)} 个音频文件")

        # 处理每个音频文件
        for index, audio_file in enumerate(audio_files, 1):
            filename = os.path.basename(audio_file)
            logger.info(f"\n[{index}/{len(audio_files)}] 处理文件: {filename}")

            self.stats['processed'] += 1

            # 转录音频
            success, text, process_time, audio_info = self.transcribe_audio(audio_file)

            if success:
                # 保存转录结果
                self.save_transcription(filename, text, audio_info, process_time, index)

                self.stats['success'] += 1
                if audio_info and audio_info['duration'] > 0:
                    self.stats['total_duration'] += audio_info['duration']
                self.stats['total_time'] += process_time
            else:
                self.stats['failed'] += 1

                # 保存错误信息
                try:
                    with open(self.output_file, 'a', encoding='utf-8') as f:
                        f.write(f"[文件 {index}] {filename} - 转录失败\n")
                        f.write(f"错误信息: {text}\n")
                        f.write("=" * 80 + "\n\n")
                except:
                    pass

        return True

    def generate_summary(self):
        """生成处理摘要"""
        try:
            summary_file = os.path.join(os.path.dirname(self.output_file),
                                        f"transcription_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")

            with open(summary_file, 'w', encoding='utf-8') as f:
                f.write("=" * 60 + "\n")
                f.write("转录处理摘要\n")
                f.write("=" * 60 + "\n")
                f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"模型: Whisper {self.model_size}\n")
                f.write(f"语言: {self.language}\n")
                f.write("=" * 60 + "\n\n")

                f.write("处理统计:\n")
                f.write(f"  总计文件数: {self.stats['total_files']}\n")
                f.write(f"  成功转录: {self.stats['success']}\n")
                f.write(f"  转录失败: {self.stats['failed']}\n")

                if self.stats['total_files'] > 0:
                    success_rate = (self.stats['success'] / self.stats['total_files']) * 100
                    f.write(f"  成功率: {success_rate:.1f}%\n")

                if self.stats['total_duration'] > 0:
                    f.write(f"  总音频时长: {self.stats['total_duration']:.1f}秒\n")

                if self.stats['total_time'] > 0:
                    f.write(f"  总处理时间: {self.stats['total_time']:.1f}秒\n")

                    if self.stats['total_duration'] > 0:
                        avg_real_time = self.stats['total_time'] / self.stats['total_duration']
                        f.write(f"  平均实时因子: {avg_real_time:.2f}x\n")

                f.write("\n输出文件:\n")
                f.write(f"  转录结果: {os.path.abspath(self.output_file)}\n")
                f.write(f"  处理摘要: {os.path.abspath(summary_file)}\n")

                f.write("\n" + "=" * 60 + "\n")
                f.write("文件说明:\n")
                f.write(f"- 所有录音文件转录结果保存在: {self.output_file}\n")
                f.write("- 每个文件的信息和转录文本都保存在同一个文件中\n")
                f.write("- 格式: [文件序号] 文件名\n")
                f.write("        文件信息\n")
                f.write("        转录文本\n")
                f.write("=" * 60 + "\n")

            logger.info(f"处理摘要已生成: {summary_file}")
            return summary_file

        except Exception as e:
            logger.error(f"生成摘要失败: {str(e)}")
            return None


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="录音文件转录工具 - 使用Whisper")
    parser.add_argument("-i", "--input", default="recordings", help="输入文件夹路径 (默认: recordings)")
    parser.add_argument("-o", "--output", default="translation/all_transcriptions.txt",
                        help="输出文件路径 (默认: translation/all_transcriptions.txt)")
    parser.add_argument("-m", "--model", default="base",
                        choices=["tiny", "base", "small", "medium", "large"],
                        help="Whisper模型大小 (默认: base)")
    parser.add_argument("-l", "--language", default="zh",
                        help="语言代码 (默认: zh)")
    parser.add_argument("--cpu-only", action="store_true",
                        help="仅使用CPU (默认会自动使用GPU如果可用)")

    args = parser.parse_args()

    print("=" * 60)
    print("录音文件转录工具 - Whisper")
    print("=" * 60)

    # 检查输入文件夹是否存在
    if not os.path.exists(args.input):
        print(f"❌ 输入文件夹不存在: {args.input}")
        print("请确保recordings文件夹存在并包含录音文件")
        sys.exit(1)

    # 检查Whisper是否安装
    try:
        import whisper
        print("✓ Whisper库已安装")
    except ImportError:
        print("❌ Whisper库未安装")
        print("请先安装: pip install openai-whisper")
        print("注意: 第一次运行时会自动下载模型文件")
        sys.exit(1)

    # 创建转录器
    transcriber = WhisperTranscriber(
        model_size=args.model,
        language=args.language,
        output_file=args.output
    )

    print("\n配置信息:")
    print(f"  输入文件夹: {os.path.abspath(args.input)}")
    print(f"  输出文件: {os.path.abspath(args.output)}")
    print(f"  模型大小: {args.model}")
    print(f"  语言: {args.language}")
    print(f"  设备: {'CPU' if args.cpu_only else '自动选择'}")
    print("=" * 60)

    # 开始处理
    start_time = time.time()

    try:
        success = transcriber.process_folder(args.input)

        if success:
            # 生成摘要
            transcriber.generate_summary()

            total_time = time.time() - start_time

            print("\n" + "=" * 60)
            print("✅ 转录完成!")
            print("=" * 60)
            print("处理统计:")
            print(f"  总计文件: {transcriber.stats['total_files']}")
            print(f"  成功: {transcriber.stats['success']}")
            print(f"  失败: {transcriber.stats['failed']}")

            if transcriber.stats['total_files'] > 0:
                success_rate = (transcriber.stats['success'] / transcriber.stats['total_files']) * 100
                print(f"  成功率: {success_rate:.1f}%")

            print(f"  总处理时间: {total_time:.1f}秒")
            print("\n输出文件:")
            print(f"  转录结果: {os.path.abspath(args.output)}")
            print("  日志文件: transcription.log")
            print("=" * 60)

            # 显示文件示例
            if os.path.exists(args.output):
                print("\n转录文件示例 (前5行):")
                print("-" * 40)
                try:
                    with open(args.output, 'r', encoding='utf-8') as f:
                        lines = [next(f).strip() for _ in range(5)]
                        for line in lines:
                            print(line)
                except:
                    pass
                print("-" * 40)
        else:
            print("❌ 转录处理失败")

    except KeyboardInterrupt:
        print("\n❌ 用户中断处理")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 处理过程中出现错误: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()