# core/audio_processor.py
import pygame
import os
import tempfile
import threading
import time
import re
import requests
from datetime import datetime
from config.settings import settings
from utils.logger import setup_logger

class AudioProcessor:
    def __init__(self, database_manager=None):
        self.database_manager = database_manager
        self.logger = setup_logger("audio_processor")

        # 音频播放控制
        self.pygame_initialized = False
        self.currently_playing = False
        self.play_lock = threading.Lock()

        # Coqui TTS 服务配置 - 使用settings中的配置
        self.tts_service_url = settings.coqui_tts_config['service_url']
        self.service_available = False
        self.timeout = settings.coqui_tts_config['timeout']
        self.max_text_length = settings.coqui_tts_config['max_text_length']
        self._check_tts_service()

        # 确保临时目录存在
        self._ensure_temp_directory()

        # 处理锁
        self._is_processing_tts = False
        self._tts_lock = threading.Lock()

    def _check_tts_service(self):
        """检查 Coqui TTS 服务是否可用"""
        try:
            response = requests.get(f"{self.tts_service_url}/health", timeout=5)
            if response.status_code == 200:
                data = response.json()
                self.service_available = data.get('status') == 'healthy'
                if self.service_available:
                    self.logger.info("✅ Coqui TTS 服务连接成功")
                else:
                    self.logger.warning("⚠️ TTS 服务未就绪")
            else:
                self.logger.error(f"❌ TTS 服务健康检查失败: {response.status_code}")
                self.service_available = False
        except Exception as e:
            self.logger.error(f"❌ 无法连接到 TTS 服务: {e}")
            self.service_available = False

    def _ensure_temp_directory(self):
        """确保临时目录存在"""
        try:
            os.makedirs(settings.temp_audio_path, exist_ok=True)
            self.logger.info(f"✅ 临时音频目录: {settings.temp_audio_path}")
        except Exception as e:
            self.logger.error(f"❌ 创建临时目录失败: {e}")
            settings.temp_audio_path = "temp_audio"
            os.makedirs(settings.temp_audio_path, exist_ok=True)

    def _ensure_pygame_init(self):
        """确保pygame已初始化"""
        if not self.pygame_initialized:
            pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
            self.pygame_initialized = True

    def _clean_tts_text(self, text):
        """清理TTS文本"""
        if not text:
            return "语音播报"
        if not isinstance(text, str):
            text = str(text)

        cleaned = text.replace('\n', '。').replace('\r', '')
        cleaned = re.sub(r'[^\w\u4e00-\u9fff\s\.\,\!\?\;\\:\(\)\"\'\-\+]', '', cleaned)

        # 限制文本长度
        if len(cleaned) > self.max_text_length:
            cleaned = cleaned[:self.max_text_length] + "。"

        cleaned = cleaned.strip()
        if cleaned and cleaned[-1] not in ['。', '！', '？', '.', '!', '?']:
            cleaned += '。'

        return cleaned

    def _get_output_file_path(self):
        """获取输出文件路径"""
        try:
            thread_id = threading.get_ident()
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            filename = f"speech_{thread_id}_{timestamp}.wav"
            output_file = os.path.join(settings.temp_audio_path, filename)
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            return output_file
        except Exception as e:
            self.logger.error(f"❌ 生成输出文件路径失败: {e}")
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav', dir=settings.temp_audio_path)
            temp_file.close()
            return temp_file.name

    def text_to_speech(self, text, output_file=None):
        """通过 HTTP 接口调用 Coqui TTS 服务"""
        if self._is_processing_tts:
            self.logger.warning("⚠️ TTS正在处理中，跳过重复请求")
            return None

        with self._tts_lock:
            self._is_processing_tts = True
            try:
                # 检查服务状态
                if not self.service_available:
                    self.logger.error("❌ TTS 服务不可用")
                    return None

                # 检查文本
                if text is None or not text.strip():
                    text = "抱歉，没有获取到要播报的内容"

                self.logger.info(f"🎯 调用 Coqui TTS 服务处理文本: {text}")

                # 获取输出文件路径
                if output_file is None:
                    output_file = self._get_output_file_path()

                # 清理文本
                cleaned_text = self._clean_tts_text(text)

                # 调用 Coqui TTS 服务的下载接口
                try:
                    response = requests.get(
                        f"{self.tts_service_url}/tts/download",
                        params={"text": cleaned_text},
                        timeout=self.timeout,
                        stream=True
                    )

                    if response.status_code == 200:
                        # 保存音频文件
                        with open(output_file, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                f.write(chunk)

                        # 检查文件
                        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                            file_size = os.path.getsize(output_file)
                            self.logger.info(f"✅ Coqui TTS 服务调用成功: {output_file} (大小: {file_size} 字节)")

                            # 记录到数据库
                            if self.database_manager:
                                try:
                                    self.database_manager.log_interaction(
                                        "assistant",
                                        text,
                                        f"coqui_tts_output: {output_file}"
                                    )
                                except Exception as e:
                                    self.logger.error(f"⚠️ 数据库记录失败: {e}")
                            return output_file
                        else:
                            self.logger.error(f"❌ 输出文件异常: {output_file}")
                            return None
                    else:
                        error_msg = f"Coqui TTS 服务返回错误: {response.status_code} - {response.text}"
                        self.logger.error(f"❌ {error_msg}")
                        return None

                except requests.exceptions.Timeout:
                    self.logger.error("❌ Coqui TTS 服务请求超时")
                    return None
                except requests.exceptions.ConnectionError:
                    self.logger.error("❌ 无法连接到 Coqui TTS 服务")
                    self.service_available = False
                    return None
                except Exception as e:
                    self.logger.error(f"❌ Coqui TTS 服务调用失败: {e}")
                    return None

            finally:
                self._is_processing_tts = False

    def play_audio(self, audio_file):
        """播放音频文件"""
        with self.play_lock:
            try:
                if not audio_file or not os.path.exists(audio_file):
                    self.logger.error(f"❌ 音频文件不存在: {audio_file}")
                    return False

                file_size = os.path.getsize(audio_file)
                if file_size < 1024:
                    self.logger.error(f"❌ 音频文件太小: {file_size} bytes")
                    return False

                self._ensure_pygame_init()

                # 停止当前播放
                if self.currently_playing:
                    pygame.mixer.music.stop()
                    pygame.mixer.music.unload()
                    time.sleep(0.5)

                # 开始播放
                self.currently_playing = True
                pygame.mixer.music.load(audio_file)
                pygame.mixer.music.play()

                # 等待播放完成
                start_time = time.time()
                max_wait_time = 60
                while pygame.mixer.music.get_busy():
                    pygame.time.Clock().tick(10)
                    if time.time() - start_time > max_wait_time:
                        self.logger.warning("⏰ 播放超时，强制停止")
                        pygame.mixer.music.stop()
                        break
                    time.sleep(0.05)

                # 清理资源
                pygame.mixer.music.unload()
                time.sleep(0.3)
                self.currently_playing = False

                self.logger.info(f"✅ 音频播放完成: {audio_file}")
                return True

            except Exception as e:
                self.logger.error(f"❌ 音频播放失败: {e}")
                try:
                    pygame.mixer.music.stop()
                    pygame.mixer.music.unload()
                except:
                    pass
                self.currently_playing = False
                return False

    def speak(self, text, output_file=None):
        """说出文本 - 主要接口"""
        try:
            if not text or not text.strip():
                return False

            self.logger.info(f"🎯 准备播报: {text}")
            audio_file = self.text_to_speech(text, output_file)

            if audio_file and os.path.exists(audio_file):
                success = self.play_audio(audio_file)
                if success:
                    # 异步清理文件
                    self._schedule_cleanup(audio_file)
                    return True
            return False

        except Exception as e:
            self.logger.error(f"❌ 语音播报失败: {e}")
            return False

    def _schedule_cleanup(self, audio_file):
        """延迟清理临时文件"""
        def cleanup_async():
            time.sleep(3)
            try:
                if os.path.exists(audio_file):
                    os.remove(audio_file)
                    self.logger.info(f"🗑️ 清理临时文件: {audio_file}")
            except Exception as e:
                self.logger.error(f"⚠️ 清理文件失败: {e}")

        threading.Thread(target=cleanup_async, daemon=True).start()

    def cleanup(self):
        """清理资源"""
        try:
            if self.pygame_initialized:
                pygame.mixer.music.stop()
                pygame.mixer.music.unload()
                pygame.mixer.quit()

            # 清理临时文件
            self._cleanup_temp_files()

        except Exception as e:
            self.logger.error(f"⚠️ 清理资源时出错: {e}")

    def _cleanup_temp_files(self):
        """清理所有临时文件"""
        try:
            import glob
            temp_dir = settings.temp_audio_path
            if os.path.exists(temp_dir):
                wav_files = glob.glob(os.path.join(temp_dir, "speech_*.wav"))
                for wav_file in wav_files:
                    try:
                        os.remove(wav_file)
                    except:
                        pass
        except Exception as e:
            self.logger.error(f"⚠️ 清理临时文件失败: {e}")

    def get_service_status(self):
        """获取 TTS 服务状态"""
        return {
            'service_available': self.service_available,
            'service_url': self.tts_service_url,
            'timeout': self.timeout,
            'max_text_length': self.max_text_length
        }

    def set_voice(self, voice_key):
        """设置语音类型 - 兼容性方法"""
        self.logger.info(f"语音类型设置请求: {voice_key} (Coqui TTS 暂不支持动态切换)")
        return True

    def get_available_voices(self):
        """获取可用的语音列表 - 兼容性方法"""
        return ["Coqui TTS 中文语音"]

    def retry_connection(self):
        """重新尝试连接 TTS 服务"""
        self.logger.info("🔄 重新尝试连接 TTS 服务...")
        self._check_tts_service()
        return self.service_available