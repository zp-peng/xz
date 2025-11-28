"""
音频工具函数
"""
import numpy as np
import wave
import os

def calculate_volume_level(audio_data):
    """计算音频音量级别"""
    audio_array = np.frombuffer(audio_data, dtype=np.int16)
    rms = np.sqrt(np.mean(audio_array**2))
    return rms

def save_wav_file(frames, filename, channels=1, sample_width=2, rate=16000):
    """保存音频为WAV文件"""
    with wave.open(filename, 'wb') as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(b''.join(frames))

def cleanup_temp_files(filename):
    """清理临时文件"""
    if os.path.exists(filename):
        try:
            os.remove(filename)
        except Exception as e:
            print(f"清理临时文件失败: {e}")

def get_volume_indicator(volume, max_level=20):
    """获取音量指示器"""
    level = min(int(volume / 50), max_level)
    return "█" * level + " " * (max_level - level)