# core/voice_recognizer.py
import audioop
import json
import numpy as np
import os
import pyaudio
import random
import re
import time
import vosk
import wave

from utils.logger import setup_logger


class VoiceRecognizer:
    def __init__(self, database_manager=None, command_handler=None):
        self.database_manager = database_manager
        self.command_handler = command_handler
        self.audio = pyaudio.PyAudio()
        self.logger = setup_logger("VoiceRecognizer")

        # 模型配置
        self.model_path = "model/vosk-model-cn-0.22"
        self.model = None
        self.recognizer = None
        self.system_audio_threshold = 0.8  # 系统声音检测阈值
        self.last_system_audio_time = 0    # 最后检测到系统声音的时间
        self.system_audio_cooldown = 1.0   # 系统声音检测冷却时间

        # 音频参数
        self.chunk = 1024
        self.format = pyaudio.paInt16
        self.channels = 1
        self.rate = 16000

        # 使用保守的默认值，避免立即校准
        self.silence_threshold = 2.0
        self.silence_duration = 1.2
        self.min_voice_duration = 0.3
        self.gain = 1.5

        # 其他状态变量
        self.wake_word = "小智"
        self.wake_word_detected = False
        self._is_cleaning_up = False
        self.ambient_noise_level = 1.5

        # 语音播放状态控制 - 增强版本
        self._is_speaking = False
        self._last_speech_end_time = 0
        self._playback_cooldown = 0.5  # 播放结束后短暂冷却期
        self._playback_state_listeners = []

        # 同步加载模型
        self.model_loaded = False
        self.load_model_sync()  # 改为同步加载
        self.detect_ambient_noise()
        self.cleanup_temp_files()

    def add_playback_state_listener(self, listener):
        """添加播放状态监听器"""
        if listener not in self._playback_state_listeners:
            self._playback_state_listeners.append(listener)

    def remove_playback_state_listener(self, listener):
        """移除播放状态监听器"""
        if listener in self._playback_state_listeners:
            self._playback_state_listeners.remove(listener)

    def _notify_playback_state_change(self, is_speaking):
        """通知所有监听器播放状态变化"""
        for listener in self._playback_state_listeners:
            try:
                if hasattr(listener, 'on_playback_state_change'):
                    listener.on_playback_state_change(is_speaking)
            except Exception as e:
                self.logger.warning(f"播放状态监听器通知失败: {e}")

    def set_speaking_status(self, is_speaking):
        """设置语音播放状态 - 增强版本"""
        old_state = self._is_speaking
        self._is_speaking = is_speaking

        if old_state != is_speaking:
            if is_speaking:
                self.logger.info("🔊 语音播放开始，暂停语音监听")
            else:
                self._last_speech_end_time = time.time()
                self.logger.info("🔇 语音播放结束，准备恢复语音监听")

            # 通知状态变化
            self._notify_playback_state_change(is_speaking)

    def should_ignore_for_playback(self):
        """检查是否因播放状态而忽略语音识别 - 增强版本"""
        if self._is_speaking:
            return True

        # 播放结束后短暂冷却期
        if time.time() - self._last_speech_end_time < self._playback_cooldown:
            return True

        return False

    def is_system_playback_audio(self, audio_data):
        """检测是否为系统自己播放的音频 - 增强版本"""
        try:
            if audio_data is None or len(audio_data) == 0:
                return False

            # 检查是否在冷却期内
            current_time = time.time()
            if current_time - self.last_system_audio_time < self.system_audio_cooldown:
                return True

            # 转换为numpy数组分析
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            if len(audio_array) < 100:
                return False

            # 计算音频特征
            rms = np.sqrt(np.mean(np.square(audio_array.astype(np.float64))))
            peak = np.max(np.abs(audio_array))

            # 计算过零率（Zero Crossing Rate）
            zero_crossings = np.sum(np.diff(np.signbit(audio_array)))
            zcr = zero_crossings / len(audio_array)

            # 计算频谱特征
            fft_data = np.abs(np.fft.fft(audio_array))
            fft_data = fft_data[:len(fft_data)//2]  # 取前半部分
            spectral_centroid = np.sum(fft_data * np.arange(len(fft_data))) / np.sum(fft_data)

            # 系统播放声音的特征（通常更平稳、频谱更集中）
            is_system_sound = (
                # 音量在一定范围内（不是环境噪音，也不是过大的声音）
                    800 < rms < 15000 and
                    # 峰值不会过高
                    peak < 25000 and
                    # 过零率较低（声音较平稳）
                    zcr < 0.2 and
                    # 频谱中心较低（声音频率较低）
                    spectral_centroid < 1000
            )

            if is_system_sound:
                self.last_system_audio_time = current_time

            return is_system_sound

        except Exception as e:
            self.logger.warning(f"系统音频检测失败: {e}")
            return False

    def load_model_sync(self):
        """同步加载Vosk模型 - 修复版本"""
        try:
            print(f"🎯 正在同步加载 Vosk 模型...")

            # 检查模型路径
            if not os.path.exists(self.model_path):
                print(f"❌ Vosk 模型目录不存在: {self.model_path}")
                possible_paths = [
                    "model/vosk-model-cn-0.22",
                    "model/vosk-model-small-cn-0.22",
                    "model",
                    "vosk-model-cn-0.22"
                ]
                for path in possible_paths:
                    if os.path.exists(path):
                        print(f"🔍 找到备选路径: {path}")
                        self.model_path = path
                        break
                else:
                    print("❌ 所有备选路径都不存在")
                    self.model_loaded = False
                    return False

            # 加载模型
            self.model = vosk.Model(self.model_path)
            self.recognizer = vosk.KaldiRecognizer(self.model, self.rate)

            # 简单测试模型是否正常工作
            test_result = self.recognizer.AcceptWaveform(b'test' * 100)  # 添加测试数据
            self.model_loaded = True

            print("✅ Vosk 模型同步加载成功!")
            return True

        except Exception as e:
            print(f"❌ Vosk 模型同步加载失败: {e}")
            self.model_loaded = False
            return False

    def _ensure_temp_audio_dir(self):
        """确保临时音频目录存在"""
        temp_audio_dir = "temp_audio"
        if not os.path.exists(temp_audio_dir):
            os.makedirs(temp_audio_dir, exist_ok=True)
        return temp_audio_dir

    def _get_temp_audio_path(self):
        """获取临时音频文件路径 - 使用项目temp_audio目录"""
        temp_audio_dir = self._ensure_temp_audio_dir()
        timestamp = int(time.time())
        random_suffix = random.randint(1000, 9999)  # 现在random已导入
        temp_file = os.path.join(temp_audio_dir, f"command_{timestamp}_{random_suffix}.wav")
        return temp_file

    def cleanup_temp_files(self, max_age_seconds=3600):
        """清理过期的临时文件"""
        try:
            temp_audio_dir = self._ensure_temp_audio_dir()
            current_time = time.time()
            deleted_count = 0

            for filename in os.listdir(temp_audio_dir):
                file_path = os.path.join(temp_audio_dir, filename)
                if os.path.isfile(file_path) and filename.endswith('.wav'):
                    # 检查文件年龄
                    file_age = current_time - os.path.getctime(file_path)
                    if file_age > max_age_seconds:
                        try:
                            os.remove(file_path)
                            deleted_count += 1
                        except Exception as e:
                            print(f"⚠️ 删除临时文件失败 {filename}: {e}")

            if deleted_count > 0:
                print(f"✅ 已清理 {deleted_count} 个过期临时文件")

        except Exception as e:
            print(f"⚠️ 清理临时文件时出错: {e}")

    def safe_calculate_volume(self, audio_data):
        """安全计算音量，避免无效值"""
        try:
            if audio_data is None or len(audio_data) == 0:
                return 0
            # 确保数据是有效的
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            if len(audio_array) == 0:
                return 0
            # 计算RMS音量
            squared = np.square(audio_array.astype(np.float64))
            mean_squared = np.mean(squared)
            if mean_squared <= 0:
                return 0
            rms = np.sqrt(mean_squared)
            return rms
        except Exception as e:
            return 0

    def _check_audio_quality(self, frames):
        """检查音频数据质量"""
        try:
            if not frames:
                return False, "无音频数据"

            # 合并所有音频数据
            audio_data = b''.join(frames)
            if len(audio_data) < 16000:  # 至少1秒的音频
                return False, f"音频数据过短: {len(audio_data)} bytes"

            # 转换为numpy数组分析
            audio_array = np.frombuffer(audio_data, dtype=np.int16)

            # 检查音量
            rms = np.sqrt(np.mean(np.square(audio_array.astype(np.float64))))
            if rms < 100:
                return False, f"音频音量过低: RMS={rms:.1f}"

            # 检查是否为静音（所有值接近0）
            if np.max(np.abs(audio_array)) < 1000:
                return False, f"可能为静音: 峰值={np.max(np.abs(audio_array))}"

            return True, f"音频质量正常: 长度={len(audio_array)} samples, RMS={rms:.1f}"

        except Exception as e:
            return False, f"音频质量检查失败: {e}"

    def record_until_silence(self, output_file=None):
        """录音方法 - 增强版本：改进播放状态检查"""
        # 增强的播放状态检查
        if self.should_ignore_for_playback():
            self.logger.debug("跳过录音：正在播放语音或冷却期内")
            return None

        if self._is_cleaning_up or not self.recognizer:
            return None

        # 保存唤醒词状态
        is_after_wake_word = self.wake_word_detected

        if is_after_wake_word:
            silence_threshold = 1.2
            silence_duration = 2.0
            min_recording_time = 3.0
        else:
            silence_threshold = self.silence_threshold
            silence_duration = self.silence_duration
            min_recording_time = 0

        try:
            # 创建新的识别器实例
            self.recognizer = vosk.KaldiRecognizer(self.model, self.rate)

            stream = self.audio.open(
                format=self.format,
                channels=self.channels,
                rate=self.rate,
                input=True,
                frames_per_buffer=self.chunk
            )

            if is_after_wake_word:
                print("🎤 唤醒词已识别，现在可以开始说话...")
            else:
                print("🎤 现在可以开始说话...")

            frames = []
            silent_chunks = 0
            voice_chunks = 0
            recognized_text = ""
            last_voice_time = time.time()
            recording_start = time.time()
            min_recording_end = recording_start + min_recording_time

            # 录音循环 - 增强播放状态检查
            while True:
                if self._is_cleaning_up:
                    break

                # 关键：增强的播放状态检查
                if self.should_ignore_for_playback():
                    self.logger.debug("录音中断：检测到语音播放或冷却期")
                    break

                data = stream.read(self.chunk, exception_on_overflow=False)
                if not data:
                    continue

                # 简单的系统声音检测，只过滤明显的系统播放声音
                if self.is_system_playback_audio(data):
                    continue

                frames.append(data)

                volume = self.safe_calculate_volume(data)

                current_time = time.time()
                is_min_recording_period = current_time < min_recording_end

                if volume > silence_threshold or (is_after_wake_word and is_min_recording_period):
                    silent_chunks = 0
                    last_voice_time = current_time
                    voice_chunks += 1

                    if self.recognizer.AcceptWaveform(data):
                        result = json.loads(self.recognizer.Result())
                        text = result.get('text', '').strip()
                        if text:
                            recognized_text = text
                            if is_after_wake_word and len(recognized_text) > 1 and not self._is_wake_word_only(recognized_text):
                                break
                else:
                    silent_chunks += 1

                # 停止条件
                current_time = time.time()
                elapsed_time = current_time - recording_start

                if is_min_recording_period:
                    continue

                if current_time - last_voice_time > silence_duration:
                    break

                if elapsed_time > 6.0:
                    break

            # 停止流
            stream.stop_stream()
            stream.close()

            # 如果因为播放状态而中断录音，直接返回None
            if self.should_ignore_for_playback():
                self.logger.debug("录音因播放状态中断，保持唤醒状态")
                return None

            # 获取最终结果
            try:
                if frames:
                    remaining_data = b''.join(frames)
                    if self.recognizer.AcceptWaveform(remaining_data):
                        result = json.loads(self.recognizer.Result())
                        final_text = result.get('text', '').strip()
                        if final_text:
                            recognized_text = final_text

                    if not recognized_text:
                        partial_result = json.loads(self.recognizer.PartialResult())
                        partial_text = partial_result.get('partial', '').strip()
                        if partial_text:
                            recognized_text = partial_text
            except Exception as e:
                print(f"❌ 最终结果处理失败: {e}")

            # 处理结果
            total_time = time.time() - recording_start

            if recognized_text and recognized_text.strip():
                cleaned_text = self.clean_transcription(recognized_text)

                # 检查无效结果
                invalid_results = ['检测到语音但未能识别', '语音识别失败', '语音识别异常']
                if any(invalid in cleaned_text for invalid in invalid_results):
                    if is_after_wake_word:
                        self.wake_word_detected = False
                    return None

                if is_after_wake_word:
                    self.wake_word_detected = False

                print(f"🎉 录音完成: '{cleaned_text}' (耗时: {total_time:.1f}s)")
                return cleaned_text
            elif voice_chunks > 1:
                if is_after_wake_word:
                    self.wake_word_detected = False
                return "检测到语音但未能识别"
            else:
                if is_after_wake_word:
                    self.wake_word_detected = False
                return None

        except Exception as e:
            print(f"❌ 录音识别失败: {e}")
            if is_after_wake_word:
                self.wake_word_detected = False
            try:
                stream.stop_stream()
                stream.close()
            except:
                pass
            return None

    def _is_likely_system_sound_by_features(self, audio_data):
        """通过音频特征检测是否为系统声音 - 新增方法"""
        try:
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            if len(audio_array) < 100:
                return False

            # 计算音频特征
            rms = np.sqrt(np.mean(np.square(audio_array.astype(np.float64))))
            peak = np.max(np.abs(audio_array))

            # 计算频谱平坦度
            fft_data = np.abs(np.fft.fft(audio_array))
            fft_data = fft_data[:len(fft_data)//2]
            spectral_flatness = np.exp(np.mean(np.log(fft_data + 1e-10))) / (np.mean(fft_data) + 1e-10)

            # 系统声音的特征：中等音量、平稳频谱、特定频率范围
            is_system_sound = (
                # 音量范围（避免环境噪音和过大声音）
                    500 < rms < 12000 and
                    # 峰值限制
                    peak < 20000 and
                    # 频谱平坦度（系统声音通常频谱较平坦）
                    spectral_flatness > 0.1 and spectral_flatness < 0.8
            )

            return is_system_sound

        except Exception as e:
            return False

    def _is_wake_word_only(self, text):
        """判断是否为纯唤醒词（没有实际命令）"""
        wake_word_patterns = [
            r'^小智$',
            r'^你好小智$',
            r'^小智你好$',
            r'^你好$',
            r'^您好$'
        ]

        for pattern in wake_word_patterns:
            if re.match(pattern, text.strip()):
                return True
        return False

    def _save_audio_file(self, frames, output_file):
        """保存音频文件 - 使用项目temp_audio目录"""
        try:
            # 确保目录存在
            output_dir = os.path.dirname(output_file)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)

            wf = wave.open(output_file, 'wb')
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.audio.get_sample_size(self.format))
            wf.setframerate(self.rate)
            wf.writeframes(b''.join(frames))
            wf.close()
            return True
        except Exception as e:
            print(f"⚠️ 保存录音文件失败: {e}")
            return False

    def transcribe_audio(self, audio_file_path, delete_after_transcribe=True):
        """转录音频文件 - 添加自动清理选项"""
        if self._is_cleaning_up:
            return None

        try:
            if not self.recognizer:
                print("❌ Vosk 识别器未初始化")
                return None

            if not os.path.exists(audio_file_path):
                print(f"❌ 音频文件不存在: {audio_file_path}")
                return None

            wf = wave.open(audio_file_path, 'rb')

            # 检查音频格式
            if wf.getnchannels() != 1:
                print("❌ 只支持单声道音频")
                wf.close()
                return None

            # 创建新的识别器
            self.recognizer = vosk.KaldiRecognizer(self.model, wf.getframerate())

            results = []
            while True:
                data = wf.readframes(4000)
                if len(data) == 0:
                    break

                if self.recognizer.AcceptWaveform(data):
                    result = json.loads(self.recognizer.Result())
                    text = result.get('text', '').strip()
                    if text:
                        results.append(text)

            # 获取最终结果
            final_result = json.loads(self.recognizer.FinalResult())
            final_text = final_result.get('text', '').strip()
            if final_text:
                results.append(final_text)

            wf.close()

            # 转录完成后删除文件
            if delete_after_transcribe:
                try:
                    os.remove(audio_file_path)
                except Exception as e:
                    print(f"⚠️ 删除临时文件失败: {e}")

            transcription = ' '.join(results).strip()
            if transcription:
                cleaned_transcription = self.clean_transcription(transcription)
                print(f"✅ 转录完成: '{cleaned_transcription}'")
                return cleaned_transcription
            else:
                return None

        except Exception as e:
            print(f"❌ 转录失败: {e}")
            # 即使失败也尝试删除文件
            if delete_after_transcribe and os.path.exists(audio_file_path):
                try:
                    os.remove(audio_file_path)
                except Exception as e:
                    print(f"⚠️ 删除临时文件失败: {e}")
            return None

    def clean_transcription(self, text):
        """语音识别文本清洗 - 统一清洗逻辑，避免重复清洗"""
        if not text:
            return ""

        original_text = text

        # 第一步：移除所有空格
        text = re.sub(r'\s+', '', text)

        # 第二步：基础语音识别错误纠正（设备控制相关）
        basic_corrections = {
            '小只': '小智', '小知': '小智', '小之': '小智', '小志': '小智',
            '小智小智': '小智',
            '相子': '柜子', '箱子': '柜子', '贵子': '柜子', '柜了': '柜子', '鬼子': '柜子',  # 新增"鬼子"的纠正
            '关毕': '关闭', '完毕': '关闭',
            '类': '列', '号': '列', '个': '列'
        }

        for wrong, correct in basic_corrections.items():
            if wrong in text:
                text = text.replace(wrong, correct)

        # 第三步：特定短语的纠正（新增）
        phrase_corrections = {
            '关闭鬼子': '关闭柜子',
            '打开鬼子': '打开柜子',
            '鬼子关闭': '柜子关闭',
            '鬼子打开': '柜子打开'
        }

        for wrong_phrase, correct_phrase in phrase_corrections.items():
            if wrong_phrase in text:
                text = text.replace(wrong_phrase, correct_phrase)

        return text

    def listen_for_wake_word(self, timeout=8):
        """监听唤醒词 - 修复版本：增强唤醒词检测和播放状态检查"""
        # 在开始时检查播放状态
        if self.should_ignore_for_playback():
            return False

        if self._is_cleaning_up:
            return False

        try:
            # 重置唤醒词状态
            self.wake_word_detected = False

            # 使用更灵敏的录音参数
            original_threshold = self.silence_threshold
            original_duration = self.silence_duration

            # 临时调整参数，提高唤醒词检测灵敏度
            self.silence_threshold = max(1.0, self.ambient_noise_level * 1.5)  # 降低阈值
            self.silence_duration = 1.5  # 缩短静音检测时间

            # 直接录音识别
            transcription = self.record_until_silence()

            # 恢复原始参数
            self.silence_threshold = original_threshold
            self.silence_duration = original_duration

            if transcription:
                # 增强唤醒词检测
                wake_detected = self._enhanced_wake_word_detection(transcription)

                if wake_detected:
                    self.wake_word_detected = True
                    print(f"✅ 唤醒词 '{self.wake_word}' 检测成功!")
                    return True

            return False

        except Exception as e:
            print(f"❌ 唤醒词检测失败: {e}")
            # 确保异常时恢复参数
            if 'original_threshold' in locals():
                self.silence_threshold = original_threshold
                self.silence_duration = original_duration
            return False

    def _enhanced_wake_word_detection(self, text):
        """增强的唤醒词检测 - 修复版本：过滤无效识别结果"""
        if not text:
            return False

        # 移除空格
        cleaned_text = re.sub(r'\s+', '', text)

        # 首先：过滤掉无效的识别结果
        invalid_patterns = [
            '检测到语音但未能识别',
            '语音识别失败',
            '未检测到有效语音',
            '语音识别异常'
        ]

        for invalid in invalid_patterns:
            if invalid in cleaned_text:
                return False

        # 唤醒关键词列表
        wake_keywords = [
            '小智', '小知', '小之', '小志', '小只',
            '你好', '您好', '嗨', '嘿'
        ]

        # 1. 直接检查是否包含任何唤醒关键词
        for keyword in wake_keywords:
            if keyword in cleaned_text:
                return True

        # 2. 检查短文本（长度小于等于6个字符）且必须包含有效关键词
        if len(cleaned_text) <= 6:
            # 短文本必须包含至少一个有效的中文字符或关键词
            has_valid_content = any(
                char in cleaned_text for char in ['小', '你', '您', '嗨', '嘿']
            )
            if has_valid_content:
                return True
            else:
                return False

        # 3. 检查是否以问候开头
        greeting_starts = ['你好', '您好', '嗨', '嘿']
        for greeting in greeting_starts:
            if cleaned_text.startswith(greeting):
                return True

        # 4. 检查是否包含"小"字且长度适中
        if '小' in cleaned_text and len(cleaned_text) <= 8:
            # 确保不是纯无效内容
            if not any(invalid in cleaned_text for invalid in invalid_patterns):
                return True

        return False

    def calibrate_microphone(self):
        """校准麦克风 - 可选执行，避免过度校准"""
        if self._is_cleaning_up:
            return

        # 如果不是强制校准，且已经有合理的阈值，跳过
        if 1.5 <= self.silence_threshold <= 4.0:
            return

        try:
            stream = self.audio.open(
                format=self.format,
                channels=self.channels,
                rate=self.rate,
                input=True,
                frames_per_buffer=self.chunk
            )

            noise_levels = []
            for i in range(30):  # 减少采样次数
                if self._is_cleaning_up:
                    break
                data = stream.read(self.chunk, exception_on_overflow=False)
                if data:
                    volume = self.safe_calculate_volume(data)
                    noise_levels.append(volume)
                time.sleep(0.05)

            stream.stop_stream()
            stream.close()

            if noise_levels:
                # 使用更保守的计算
                median_noise = np.median(noise_levels)
                noise_75th = np.percentile(noise_levels, 75)

                # 设置合理的阈值范围
                base_threshold = max(median_noise * 1.8, 2.0)  # 最低2.0
                self.silence_threshold = min(base_threshold, 4.5)  # 最高4.5
                self.ambient_noise_level = median_noise

            else:
                # 保守的默认值
                self.silence_threshold = 3.0

        except Exception as e:
            print(f"❌ 麦克风校准失败: {e}")
            self.silence_threshold = 3.0  # 保守默认值

    def record_and_transcribe(self, command_handler=None, require_wake_word=False):
        """录音并转文字 - 增强播放状态检查"""
        # 检查播放状态
        if self.should_ignore_for_playback():
            return None

        try:
            # 如果不需要唤醒词，直接录音
            if not require_wake_word:
                text = self.record_until_silence()
                if text and text != "检测到语音但未能识别":
                    # 紧急修复：立即检查是否为唤醒词
                    if command_handler and command_handler._is_pure_wakeup_call(text):
                        return text
                    return text
                elif text == "检测到语音但未能识别":
                    return "语音识别失败，请重试"
                else:
                    return None

            # 如果需要唤醒词，先检测唤醒词
            else:
                wake_detected = self.listen_for_wake_word()
                if wake_detected:
                    text = self.record_until_silence()
                    if text and text != "检测到语音但未能识别":
                        return text
                    elif text == "检测到语音但未能识别":
                        return "语音识别失败，请重试"
                    else:
                        return None
                else:
                    return None

        except Exception as e:
            print(f"❌ 录音过程错误: {e}")
            return "语音识别异常，请重试"

    def detect_ambient_noise(self, duration=3):
        """增强的环境噪音检测"""
        try:
            stream = self.audio.open(
                format=self.format,
                channels=self.channels,
                rate=self.rate,
                input=True,
                frames_per_buffer=self.chunk
            )

            noise_levels = []
            for i in range(int(duration * self.rate / self.chunk)):
                data = stream.read(self.chunk, exception_on_overflow=False)
                volume = self.safe_calculate_volume(data)
                noise_levels.append(volume)

            stream.stop_stream()
            stream.close()

            if noise_levels:
                # 使用更精确的统计方法
                median_noise = np.median(noise_levels)
                noise_75th = np.percentile(noise_levels, 75)

                # 动态设置阈值：使用中位数 + 较小的安全余量
                base_threshold = max(1.0, median_noise * 1.2)  # 最低1.0，较小的乘数
                self.silence_threshold = min(base_threshold, 3.0)  # 最高3.0
                self.ambient_noise_level = median_noise

                return True
            return False

        except Exception as e:
            print(f"❌ 环境噪音检测失败: {e}")
            # 设置保守的默认值
            self.silence_threshold = 2.0
            return False

    def set_playback_status(self, is_playing):
        """设置播放状态 - 兼容性方法，调用set_speaking_status"""
        self.set_speaking_status(is_playing)

    def cleanup(self):
        """安全清理资源 - 包括临时文件和监听器"""
        if self._is_cleaning_up:
            return

        try:
            self._is_cleaning_up = True

            # 清理监听器
            self._playback_state_listeners.clear()

            # 清理临时文件
            self.cleanup_temp_files(max_age_seconds=0)  # 删除所有临时文件

            if hasattr(self, 'audio') and self.audio:
                self.audio.terminate()
            if hasattr(self, 'model') and self.model:
                self.model = None
                self.recognizer = None
        except Exception as e:
            print(f"⚠️ 清理语音识别器时出现警告: {e}")