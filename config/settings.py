# config/settings.py
import os

class Settings:
    def __init__(self):
        # 数据库配置
        self.database_config = {
            'host': 'localhost',
            'port': 3306,
            'user': 'root',
            'password': '123456',
            'database': 'archive_management'
        }

        # 语音识别配置 (Vosk 相关)
        self.vosk_model_path = "model/vosk-model-cn-0.22"

        # WebSocket服务器配置 - 新增
        self.websocket_config = {
            'host': '0.0.0.0',
            'port': 5000,
            'debug': False
        }

        # 临时文件路径
        self.temp_audio_path = "temp_audio"

        # 日志路径
        self.logs_path = "logs"

        # Qwen 配置
        self.qwen_server_url = "http://localhost:8000"
        self.qwen_model_name = "qwen-30b"
        self.qwen_timeout = 30

        # Coqui TTS 服务配置
        self.coqui_tts_config = {
            'service_url': 'http://localhost:8900',
            'timeout': 30,
            'max_text_length': 1000
        }

# 创建全局设置实例
settings = Settings()