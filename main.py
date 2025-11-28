# main.py
import os
import sys
import time
import threading
import asyncio
from datetime import datetime
import json
import re
import queue
from flask import Flask, jsonify, request

# 添加当前目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

# 全局变量（与app.py保持一致）
is_listening = False
is_in_conversation = False
audio_queue = queue.Queue()
is_speaking = False
speech_start_time = 0
speech_cooldown = 2  # 语音播放后的冷却时间(秒)
wakeup_history = []
conversation_start_time = 0
IS_ELECTRON = getattr(sys, 'frozen', False)
port = None

# 新增：音频播放状态
audio_playback_active = False
audio_thread = None

# main.py 中的依赖检查部分
def check_dependencies():
    """快速依赖检查"""
    import importlib.util

    required_deps = [
        "vosk", "pyaudio", "pygame", "requests",
        "jieba", "mysql.connector", "flask", "flask_socketio"
    ]

    missing_deps = []
    optional_deps = []

    for dep in required_deps:
        if importlib.util.find_spec(dep) is None:
            missing_deps.append(dep)

    if missing_deps:
        print("⚠️ 缺少以下依赖包:")
        for dep in missing_deps:
            print(f"   - {dep}")
        print("\n💡 某些功能可能受限")

        # 只对关键依赖要求安装
        critical_deps = ["vosk", "pyaudio", "flask"]
        has_critical_missing = any(dep in missing_deps for dep in critical_deps)

        if has_critical_missing:
            choice = input("\n是否继续运行? (y/n): ").strip().lower()
            if choice not in ['y', 'yes', '是']:
                return False

    return True

# 只有在依赖检查通过后才导入其他模块
if not check_dependencies():
    sys.exit(1)

try:
    from core.voice_recognizer import VoiceRecognizer
    from core.command_handler import CommandHandler
    from core.audio_processor import AudioProcessor
    from core.database_manager import DatabaseManager
    from flask_socketio import SocketIO
    from flask_cors import CORS
except ImportError as e:
    print(f"❌ 导入核心模块失败: {e}")
    print("💡 请确保所有核心文件都存在且正确")
    sys.exit(1)

class XiaoZhiAssistant:
    def __init__(self):
        print("🔄 正在初始化小智语音助手...")
        # 确保先初始化Flask和SocketIO
        self.app = Flask(__name__)
        CORS(self.app)
        self.socketio = SocketIO(self.app, cors_allowed_origins="*", async_mode='threading')

        # 新增：初始化语音模式所需的属性
        self.is_running = False
        self.is_awake = False
        self.is_exited = True
        self.wake_timeout = 60  # 唤醒超时时间（秒）
        self.last_wake_time = 0
        self.audio_thread_running = False
        self.is_cleaning_up = False

        # 立即设置路由
        self.setup_routes()
        self.setup_socketio_events()

        # 立即启动服务器（不等待其他组件）
        self.start_websocket_server_sync()

        # 然后同步初始化其他组件
        self.init_components_sync()

    def on_playback_state_change(self, is_speaking):
        """播放状态变化回调"""
        if is_speaking:
            print("🎵 检测到语音播放开始，暂停语音监听")
        else:
            print("🔇 检测到语音播放结束，准备恢复语音监听")
            # 通知前端播放状态变化
            self.emit('playback_state', {'is_playing': False})

    def init_components_sync(self):
        """同步初始化所有组件"""
        try:
            print("🔄 正在同步初始化所有组件...")

            # 初始化基础组件
            self.init_basic_components()

            # 初始化音频处理器
            self.init_audio_processor()

            # 初始化命令处理器
            self.init_command_handler()

            # 初始化语音识别器
            voice_success = self.init_voice_recognizer()

            if voice_success:
                print("✅ 所有组件同步初始化完成")
            else:
                print("⚠️ 组件初始化完成，但语音识别器有问题")

            return voice_success

        except Exception as e:
            print(f"❌ 同步初始化失败: {e}")
            return False

    def start_websocket_server_sync(self):
        """同步启动WebSocket服务器 - 修复版本"""
        def run_server():
            try:
                print("🌐 正在启动Flask-SocketIO服务器...")
                # 使用正确的SocketIO运行方式
                self.socketio.run(
                    self.app,
                    host='0.0.0.0',
                    port=5000,
                    debug=False,
                    use_reloader=False,
                    allow_unsafe_werkzeug=True
                )
            except Exception as e:
                print(f"❌ WebSocket服务器运行失败: {e}")
                import traceback
                traceback.print_exc()

        # 在新线程中启动服务器
        self.server_thread = threading.Thread(target=run_server, daemon=True)
        self.server_thread.start()

        # 等待更长时间确保服务器完全启动
        print("⏳ 等待服务器启动...")
        time.sleep(3)

        # 测试连接
        return self.test_server_connection()

    def test_server_connection(self):
        """测试服务器连接 - 增强版本"""
        import requests
        max_retries = 15  # 增加重试次数
        for i in range(max_retries):
            try:
                response = requests.get('http://localhost:5000/', timeout=5)
                if response.status_code == 200:
                    print("✅ WebSocket服务器启动成功!")
                    print("💡 前端可以连接到: http://localhost:5000")
                    print("🔌 WebSocket地址: ws://localhost:5000/socket.io/")
                    return True
            except Exception as e:
                if i < max_retries - 1:
                    wait_time = 2
                    print(f"⏳ 等待服务器启动... ({i+1}/{max_retries}) - 等待{wait_time}秒")
                    time.sleep(wait_time)
                else:
                    print(f"❌ 服务器启动失败: {e}")
                    print("💡 请检查端口5000是否被占用")
        return False

    def init_basic_components(self):
        """初始化基础组件"""
        try:
            self.database_manager = DatabaseManager()
            print("✅ 数据库管理器初始化完成")
        except Exception as e:
            print(f"⚠️ 数据库管理器初始化失败: {e}")
            self.database_manager = None

    def init_heavy_components_parallel(self):
        """并行初始化耗时组件"""
        threads = []

        # 音频处理器
        audio_thread = threading.Thread(target=self.init_audio_processor)
        threads.append(audio_thread)

        # 命令处理器
        command_thread = threading.Thread(target=self.init_command_handler)
        threads.append(command_thread)

        # 语音识别器
        voice_thread = threading.Thread(target=self.init_voice_recognizer)
        threads.append(voice_thread)

        # 启动所有线程
        for thread in threads:
            thread.start()

        # 等待所有线程完成
        for thread in threads:
            thread.join(timeout=10)  # 10秒超时

    def init_audio_processor(self):
        """初始化音频处理器"""
        try:
            self.audio_processor = AudioProcessor(self.database_manager)
            print("✅ 音频处理器初始化完成")
        except Exception as e:
            print(f"⚠️ 音频处理器初始化失败: {e}")
            self.audio_processor = None

    def init_command_handler(self):
        """初始化命令处理器"""
        try:
            self.command_handler = CommandHandler(
                self.audio_processor,
                self.database_manager,
                self.socketio
            )
            print("✅ 命令处理器初始化完成")
        except Exception as e:
            print(f"⚠️ 命令处理器初始化失败: {e}")
            self.command_handler = None

    def init_voice_recognizer(self):
        """初始化语音识别器 - 增强版本"""
        try:
            print("🎯 正在初始化语音识别器...")
            self.voice_recognizer = VoiceRecognizer(
                self.database_manager,
                self.command_handler
            )

            # 添加播放状态监听器
            self.voice_recognizer.add_playback_state_listener(self)

            # 直接检查模型是否加载成功 - 增强检查逻辑
            if (hasattr(self.voice_recognizer, 'model_loaded') and
                    self.voice_recognizer.model_loaded and
                    hasattr(self.voice_recognizer, 'model') and
                    self.voice_recognizer.model is not None):
                print("✅ 语音识别器初始化完成 (模型已加载)")
                return True
            else:
                print("⚠️ 语音识别器初始化完成，但模型加载失败或状态异常")
                # 添加详细的状态信息
                print(f"   - model_loaded: {getattr(self.voice_recognizer, 'model_loaded', '无此属性')}")
                print(f"   - model exists: {hasattr(self.voice_recognizer, 'model')}")
                print(f"   - model is None: {getattr(self.voice_recognizer, 'model', None) is None}")
                return False

        except Exception as e:
            print(f"⚠️ 语音识别器初始化失败: {e}")
            self.voice_recognizer = None
            return False

    def init_voice_async(self):
        """异步初始化语音功能"""
        def voice_init_task():
            try:
                print("🎯 正在初始化语音功能...")
                voice_ready = self.initialize_voice()
                if voice_ready:
                    print("✅ 语音功能初始化完成")
                else:
                    print("⚠️ 语音功能初始化部分失败")
            except Exception as e:
                print(f"❌ 语音功能初始化失败: {e}")

        voice_thread = threading.Thread(target=voice_init_task, daemon=True)
        voice_thread.start()

    def setup_routes(self):
        """设置所有路由接口（与app.py保持一致）"""
        # 添加调试路由，显示所有可用路由
        @self.app.route('/api/debug/routes', methods=['GET'])
        def debug_routes():
            routes = []
            for rule in self.app.url_map.iter_rules():
                routes.append({
                    'endpoint': rule.endpoint,
                    'methods': list(rule.methods),
                    'rule': str(rule)
                })
            return jsonify({"routes": routes})

        @self.app.route('/')
        def index():
            return jsonify({
                "status": "running",
                "service": "智能柜语音唤醒系统",
                "electron_mode": IS_ELECTRON,
                "port": port
            })

        @self.app.route('/api/start', methods=['POST'])
        def api_start_listening():
            global is_listening
            if not self.voice_recognizer or not self.voice_recognizer.model:
                return jsonify({"error": "Vosk 未初始化"}), 500
            if is_listening:
                return jsonify({"error": "已经在监听中"}), 400

            is_listening = True
            # 这里可以启动语音检测线程
            return jsonify({"status": "started", "message": "开始语音检测"})

        @self.app.route('/api/stop', methods=['POST'])
        def api_stop_listening():
            global is_listening
            is_listening = False
            # 删除结束对话处理，交给command_handler
            return jsonify({"status": "stopped", "message": "停止语音检测"})

        @self.app.route('/api/status', methods=['GET'])
        def get_status():
            return jsonify({
                "is_listening": is_listening,
                "is_in_conversation": is_in_conversation,
                "vosk_ready": self.voice_recognizer and self.voice_recognizer.model is not None,
                "wakeup_count": len(wakeup_history),
                "audio_queue_size": audio_queue.qsize(),
                "is_speaking": is_speaking,
                "electron_mode": IS_ELECTRON,
                "port": port,
                "speech_cooldown_remaining": max(0, speech_cooldown - (time.time() - speech_start_time)),
                "audio_playback_active": audio_playback_active
            })

        @self.app.route('/api/history', methods=['GET'])
        def get_history():
            history_list = list(wakeup_history)
            return jsonify({
                "history": history_list,
                "count": len(history_list)
            })

        @self.app.route('/api/speak', methods=['POST'])
        def api_speak():
            data = request.get_json()
            text = data.get('text', '')
            if text:
                self.speak_text(text)
                return jsonify({"status": "speaking", "text": text})
            else:
                return jsonify({"error": "没有提供文本"}), 400

        @self.app.route('/api/test_speech', methods=['POST'])
        def api_test_speech():
            data = request.get_json()
            text = data.get('text', '测试语音')

            self.speak_text(text)
            return jsonify({
                "status": "success",
                "message": "语音已加入播放队列",
                "text": text,
                "queue_size": audio_queue.qsize()
            })

        @self.app.route('/api/health/detailed', methods=['GET'])
        def detailed_health_check():
            """详细的健康检查接口"""
            health_info = {
                "status": "healthy",
                "timestamp": time.time(),
                "service": "voice_wakeup",
                "server_running": True,
                "components": {
                    "flask_app": hasattr(self, 'app'),
                    "socketio": hasattr(self, 'socketio'),
                    "voice_recognizer": self.voice_recognizer is not None,
                    "audio_processor": self.audio_processor is not None,
                    "command_handler": self.command_handler is not None,
                    "database_manager": self.database_manager is not None
                },
                "endpoints": [
                    {"method": "GET", "path": "/", "description": "服务状态"},
                    {"method": "POST", "path": "/api/speak", "description": "语音播报"},
                    {"method": "POST", "path": "/api/test_speech", "description": "测试语音"},
                    {"method": "GET", "path": "/api/status", "description": "系统状态"},
                    {"method": "GET", "path": "/api/health/detailed", "description": "详细健康检查"}
                ]
            }
            return jsonify(health_info)

        @self.app.route('/api/health', methods=['GET'])
        def health_check():
            return jsonify({
                "status": "healthy",
                "timestamp": time.time(),
                "service": "voice_wakeup"
            })

    def setup_socketio_events(self):
        """设置SocketIO事件处理器（与app.py保持一致）"""
        @self.socketio.on('connect')
        def handle_connect():
            print(f"✅ 客户端连接: {request.sid}")
            self.emit('connected', {'status': 'connected', 'message': 'WebSocket 连接成功'})

        @self.socketio.on('disconnect')
        def handle_disconnect():
            print(f"❌ 客户端断开: {request.sid}")

        @self.socketio.on('test_speech')
        def handle_test_speech(data):
            text = data.get('text', '测试语音')
            self.speak_text(text)
            self.emit('test_speech_result', {'status': 'playing', 'text': text})

        @self.socketio.on('start_listening')
        def handle_start_listening():
            global is_listening
            if not is_listening and self.voice_recognizer and self.voice_recognizer.model:
                is_listening = True
                # 这里可以启动语音检测线程
                self.emit('listening_started', {'status': 'started'})

        @self.socketio.on('stop_listening')
        def handle_stop_listening():
            global is_listening
            is_listening = False
            # 删除结束对话处理，交给command_handler
            self.emit('listening_stopped', {'status': 'stopped'})

        # 删除 end_conversation 事件处理器，交给command_handler处理

        @self.socketio.on('record_selected')
        def handle_record_selected(data):
            fileno = data.get('fileno')
            filename = data.get('filename')
            print(f"📌 用户选择了档案: {filename} (编号: {fileno})")

            response_text = f"已成功打开{filename}对应存储位置"
            self.speak_text(response_text)

            self.emit('record_processed', {
                'status': 'success',
                'message': response_text,
                'fileno': fileno
            })

    def emit(self, event, data):
        """发送SocketIO消息"""
        try:
            self.socketio.emit(event, data)
        except Exception as e:
            print(f"❌ 发送SocketIO消息失败: {e}")

    def speak_text(self, text):
        """将文本添加到音频队列（与app.py保持一致）"""
        if text:
            try:
                audio_queue.put(text)
                print(f"📝 已添加到音频队列: {text}")
                # 通知前端
                self.emit('speech_added', {
                    'text': text,
                    'queue_size': audio_queue.qsize(),
                    'timestamp': time.time()
                })
            except Exception as e:
                print(f"❌ 无法添加到音频队列: {e}")

    def start_audio_playback_thread(self):
        """启动音频播放线程 - 增强版本：改进状态管理和互斥控制"""
        if self.audio_thread_running:
            return

        # 确保 audio_processor 已初始化
        if not hasattr(self, 'audio_processor') or self.audio_processor is None:
            print("❌ 音频处理器未初始化，无法启动音频播放线程")
            return

        print("🔊 启动音频播放线程...")
        self.audio_thread_running = True

        def audio_playback_worker():
            global audio_playback_active, is_speaking

            while self.audio_thread_running:
                try:
                    # 非阻塞获取队列中的音频
                    try:
                        text = audio_queue.get(timeout=1.0)
                    except queue.Empty:
                        continue

                    if text and hasattr(self, 'audio_processor') and self.audio_processor:
                        print(f"🔊 开始播放语音: {text}")

                        # 设置播放状态
                        audio_playback_active = True
                        is_speaking = True

                        # 通知语音识别器开始播放
                        if hasattr(self, 'voice_recognizer') and self.voice_recognizer:
                            self.voice_recognizer.set_speaking_status(True)

                        # 通知前端开始播放
                        self.emit('playback_state', {'is_playing': True})
                        self.emit('speech_started', {
                            'text': text,
                            'timestamp': time.time()
                        })

                        try:
                            # 实际播放音频
                            success = self.audio_processor.speak(text)
                            if not success:
                                print(f"❌ 语音播放失败: {text}")
                        except Exception as e:
                            print(f"❌ 播放语音时出错: {e}")

                        # 重置播放状态
                        audio_playback_active = False
                        is_speaking = False

                        # 通知语音识别器播放结束
                        if hasattr(self, 'voice_recognizer') and self.voice_recognizer:
                            self.voice_recognizer.set_speaking_status(False)

                        # 关键修改：语音播放完成后重置唤醒超时时间
                        if self.is_awake:
                            self.last_wake_time = time.time()
                            print(f"⏰ 语音播放完成，重置唤醒超时时间: {self.last_wake_time}")

                        # 通知前端播放结束
                        self.emit('speech_finished', {
                            'text': text,
                            'timestamp': time.time()
                        })

                        print(f"✅ 语音播放完成: {text}")

                    # 标记任务完成
                    audio_queue.task_done()

                except Exception as e:
                    print(f"❌ 音频播放线程错误: {e}")
                    # 确保在异常情况下也重置播放状态
                    if hasattr(self, 'voice_recognizer') and self.voice_recognizer:
                        self.voice_recognizer.set_speaking_status(False)
                    audio_playback_active = False
                    is_speaking = False
                    time.sleep(1)

        # 启动音频播放线程
        self.audio_thread = threading.Thread(target=audio_playback_worker, daemon=True)
        self.audio_thread.start()
        print("✅ 音频播放线程已启动")

    def start_websocket_server(self):
        """启动WebSocket服务器"""
        print("🌐 正在启动Flask-SocketIO服务器...")

        def run_server():
            try:
                # 使用SocketIO运行Flask应用
                print(f"🔧 服务器配置: host=0.0.0.0, port=5000, debug=False")
                self.socketio.run(
                    self.app,
                    host='0.0.0.0',  # 允许所有IP访问
                    port=5000,
                    debug=False,
                    use_reloader=False,
                    allow_unsafe_werkzeug=True
                )
            except Exception as e:
                print(f"❌ WebSocket服务器运行失败: {e}")
                import traceback
                traceback.print_exc()

        # 在新线程中启动服务器
        self.server_thread = threading.Thread(target=run_server, daemon=True)
        self.server_thread.start()

        # 等待服务器启动并检查
        max_retries = 10
        for i in range(max_retries):
            time.sleep(1)
            try:
                import requests
                response = requests.get('http://localhost:5000/', timeout=2)
                if response.status_code == 200:
                    print("✅ Flask-SocketIO服务器启动成功")
                    print("💡 前端可以连接到: http://localhost:5000")
                    print("💡 WebSocket连接地址: ws://localhost:5000/socket.io/")

                    # 显示可用路由
                    try:
                        routes_response = requests.get('http://localhost:5000/api/debug/routes', timeout=2)
                        if routes_response.status_code == 200:
                            routes_data = routes_response.json()
                            print("📋 可用路由:")
                            for route in routes_data.get('routes', []):
                                if '/api/' in route['rule']:
                                    print(f"   {list(route['methods'])} {route['rule']}")
                    except:
                        print("⚠️ 无法获取路由列表")

                    return True
            except:
                if i < max_retries - 1:
                    print(f"⏳ 等待服务器启动... ({i+1}/{max_retries})")
                else:
                    print("❌ Flask-SocketIO服务器启动失败 - 超时")
                    return False

        return False

    def initialize_voice(self):
        """初始化语音功能 - 更健壮的版本"""
        try:
            print("🎯 正在初始化语音功能...")

            # 检查关键组件
            if not hasattr(self, 'audio_processor') or not self.audio_processor:
                print("❌ 音频处理器不可用")
                return False

            if not hasattr(self, 'voice_recognizer') or not self.voice_recognizer:
                print("❌ 语音识别器不可用")
                return False

            try:
                from core.ollama_client import OllamaClient
                print("🔍 检查AI服务状态...")

                # 测试连接
                if self.command_handler and hasattr(self.command_handler, 'ollama_client'):
                    ollama_client = self.command_handler.ollama_client
                    if ollama_client.is_service_available():
                        if ollama_client.websocket_available:
                            print("✅ WebSocket服务可用")
                        elif ollama_client.http_available:
                            print("✅ HTTP服务可用")
                    else:
                        print("❌ AI服务不可用")
                        print("💡 请确保已启动AI服务")
            except Exception as e:
                print(f"⚠️ AI服务检查失败: {e}")

            print("🔧 正在校准麦克风...")
            try:
                self.voice_recognizer.calibrate_microphone()
            except Exception as e:
                print(f"⚠️ 麦克风校准失败: {e}")
                print("💡 将继续使用默认设置")

            # 启动音频播放线程（现在会检查组件）
            self.start_audio_playback_thread()

            print("🔊 测试语音播报...")
            try:
                # 直接测试语音播放
                test_text = "小智语音助手启动成功，请说'小智'唤醒我"
                print(f"🔊 测试播放: {test_text}")

                # 使用音频队列而不是直接调用
                self.speak_text(test_text)
                print("✅ 语音播报测试已加入队列")

            except Exception as e:
                print(f"⚠️ 语音播报测试失败: {e}")

            return True
        except Exception as e:
            print(f"❌ 语音初始化失败: {e}")
            print("⚠️ 将使用文本模式")
            self.voice_enabled = False
            return False

    def voice_control_loop(self):
        """语音控制主循环 - 支持唤醒词模式"""
        print("🎤 语音控制已启动，等待唤醒词...")

        while not self.is_cleaning_up:
            try:
                # 使用唤醒词模式进行录音
                text = self.voice_recognizer.record_and_transcribe(
                    command_handler=self.command_handler,
                    require_wake_word=True  # 启用唤醒词检测
                )

                if text and text not in ["语音识别失败，请重试", "语音识别异常，请重试"]:
                    print(f"🎯 接收到语音命令: {text}")

                    # 处理命令
                    response = self.command_handler.process_command_with_wake_word(text)

                    if response:
                        print(f"🤖 系统回复: {response}")
                    else:
                        print("🔇 未检测到有效命令或唤醒词")

                elif text:
                    print(f"⚠️ 语音识别问题: {text}")

                # 短暂延迟，避免过度占用CPU
                time.sleep(0.5)

            except Exception as e:
                print(f"❌ 语音控制循环异常: {e}")
                time.sleep(1)

    def run_voice_mode(self):
        """运行语音交互模式 - 增强版本：改进播放状态检查"""
        print("\n" + "="*50)
        print("🎉 小智语音助手 - 智能语音模式")
        print("="*50)
        print("💡 语音唤醒功能已启用")
        print("💡 播放状态互斥：语音播放时暂停监听，播放结束后恢复")
        print("💡 请清晰地说出 '你好小智' 或 '小智' 来唤醒系统")
        print("="*50)

        # 初始状态为休眠
        self.is_awake = False
        self.is_exited = True
        self.last_wake_time = time.time()

        # 确保语音识别器就绪
        if not hasattr(self, 'voice_recognizer') or not self.voice_recognizer:
            print("❌ 语音识别器不可用，无法启动语音模式")
            return

        # 确保命令处理器就绪
        if not hasattr(self, 'command_handler') or not self.command_handler:
            print("❌ 命令处理器不可用，无法启动语音模式")
            return

        print("✅ 语音模式启动完成，开始监听唤醒词...")

        # 主循环
        while self.is_running:
            try:
                current_time = datetime.now().strftime("%H:%M:%S")

                # 增强的播放状态检查
                if hasattr(self, 'voice_recognizer') and self.voice_recognizer:
                    if self.voice_recognizer.should_ignore_for_playback():
                        # 显示播放状态信息
                        if self.voice_recognizer._is_speaking:
                            print(f"\r[{current_time}] 🔊 系统正在播放语音，暂停监听...", end="", flush=True)
                        else:
                            cooldown_remaining = self.voice_recognizer._playback_cooldown - (time.time() - self.voice_recognizer._last_speech_end_time)
                            if cooldown_remaining > 0:
                                print(f"\r[{current_time}] ⏳ 播放冷却期中... ({cooldown_remaining:.1f}s)  ", end="", flush=True)
                        time.sleep(0.5)
                        continue

                # 检查是否在唤醒状态
                if not self.is_awake:
                    # 休眠状态：只监听唤醒词
                    wake_prompts = [
                        f"\r[{current_time}] 💤 休眠中... 说'你好小智'唤醒我",
                        f"\r[{current_time}] 😴 休息中... 喊'小智'叫醒我",
                        f"\r[{current_time}] ⏸️  待命中... 说'小智'激活",
                        f"\r[{current_time}] 🔊 聆听中... 呼唤'你好小智'开始对话"
                    ]
                    prompt_index = int(time.time()) % len(wake_prompts)
                    print(wake_prompts[prompt_index], end="", flush=True)

                    # 关键修复：使用语音识别器的唤醒词检测
                    try:
                        # 直接使用语音识别器的唤醒词检测功能
                        wake_detected = self.voice_recognizer.listen_for_wake_word()

                        if wake_detected:
                            print(f"\n✅ 检测到唤醒词，激活系统")
                            self._handle_wakeup()

                        # 短暂延迟避免过度占用CPU
                        time.sleep(0.5)

                    except Exception as e:
                        print(f"\n❌ 唤醒词检测失败: {e}")
                        time.sleep(1)

                    continue

                # 唤醒状态的处理逻辑
                else:
                    # 检查唤醒超时
                    if time.time() - self.last_wake_time > self.wake_timeout:
                        print(f"\n⏰ 唤醒超时，自动休眠")
                        self._handle_sleep()
                        continue

                    # 在唤醒状态下录音
                    try:
                        text = self.voice_recognizer.record_and_transcribe(
                            self.command_handler,
                            require_wake_word=False  # 唤醒状态下不需要唤醒词
                        )

                        if text and text not in ["语音识别失败，请重试", "语音识别异常", "语音识别异常，请重试"]:
                            print(f"\n🎯 接收到命令: {text}")

                            # 处理命令
                            response = self.command_handler.process_command(text)

                            if response:
                                print(f"🤖 系统回复: {response}")
                                # 语音播报回复
                                self.speak_text(response)

                                # 检查是否为退出命令
                                if self.command_handler._is_exit_command(text):
                                    print("👋 用户要求退出，进入休眠")
                                    self._handle_sleep()

                            else:
                                print("🔇 未识别到有效命令")

                        elif text:
                            print(f"⚠️ 语音识别问题: {text}")

                    except Exception as e:
                        print(f"❌ 命令处理异常: {e}")

                    # 短暂延迟
                    time.sleep(0.5)

            except KeyboardInterrupt:
                print(f"\n\n🛑 用户中断")
                break
            except Exception as e:
                print(f"\n❌ 语音循环错误: {e}")
                time.sleep(1)

    def _handle_wakeup(self):
        """处理唤醒"""
        self.is_awake = True
        self.is_exited = False
        self.last_wake_time = time.time()

        # 小爱风格的唤醒回复
        wake_responses = [
            "哎~ 小智来啦~ 有什么可以帮您的吗？",
            "在呢~ 小智随时为您服务~",
            "来啦~ 需要小智做什么呢？",
            "嗯~ 小智已就位，请吩咐~"
        ]
        import random
        response = random.choice(wake_responses)

        print(f"\n✅ 检测到唤醒词，系统已激活")
        self.speak_text(response)

        # 通过WebSocket通知前端
        self.emit('wakeup', {'message': '系统已唤醒'})

    def _handle_sleep(self):
        """处理休眠"""
        self.is_awake = False
        self.is_exited = True

        # 重置对话状态
        if self.command_handler:
            self.command_handler.reset_conversation_state()

        sleep_responses = [
            "好的，小智先退下啦，需要的时候随时叫我~",
            "再见啦，有事随时喊小智哦~",
            "小智去休息啦，想我了就说'小智'~",
            "好的，下次见~ 记得叫'小智'唤醒我哦~"
        ]
        import random
        response = random.choice(sleep_responses)

        print(f"✅ 系统进入休眠状态，等待唤醒词")
        self.speak_text(response)

        # 通过WebSocket通知前端
        self.emit('sleep', {'message': '系统已休眠'})

    def _is_exit_command(self, text):
        """判断是否为退出命令"""
        exit_keywords = ['退出', '结束', '结束对话', '退出系统', '再见', '拜拜']
        text_lower = text.lower().strip()
        return any(exit_word in text_lower for exit_word in exit_keywords)

    def run(self):
        """运行助手 - 修复版本"""
        self.is_running = True

        try:
            print("🚀 系统启动中...")

            # 检查语音识别器是否就绪 - 简化检查逻辑
            voice_ready = (
                    hasattr(self, 'voice_recognizer') and
                    self.voice_recognizer is not None and
                    hasattr(self.voice_recognizer, 'model_loaded') and
                    self.voice_recognizer.model_loaded
            )

            # 启动音频播放线程
            self.start_audio_playback_thread()

            # 服务启动成功的语音播报
            if voice_ready:
                self.speak_text("小智语音助手服务启动成功，请说'小智'唤醒我")
            else:
                self.speak_text("小智语音助手服务已启动，文本模式可用")

            # 选择运行模式
            mode = self.choose_mode()

            if mode == 'exit':
                return

            if mode == 'voice' and not voice_ready:
                print("❌ 语音模式不可用，切换到文本模式")
                mode = 'text'
            elif mode == 'auto':
                mode = 'voice' if voice_ready else 'text'
                print(f"🔍 自动选择模式: {'语音模式' if mode == 'voice' else '文本模式'}")

            # 运行选定的模式
            if mode == 'voice':
                print("🎤 启动语音模式...")
                self.run_voice_mode()
            else:
                print("💬 启动文本模式...")
                self.run_text_mode()

        except Exception as e:
            print(f"❌ 运行错误: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.cleanup()

    def run_text_mode(self):
        """运行文本交互模式 - 修复版本"""
        print("\n" + "="*50)
        print("💬 小智助手 - 文本模式")
        print("="*50)
        print("📚 支持命令:")
        print("  • 查询张三的档案")
        print("  • 技术部有哪些人员")
        print("  • 显示李四的信息")
        print("  • 现在几点")
        print("  • 技术部信息")
        print("  • 项目信息")
        print("  • 退出")
        print("="*50)

        while self.is_running:
            try:
                user_input = input("\n👤 您: ").strip()

                if not user_input:
                    continue

                # 检查退出命令
                if self._is_exit_command(user_input):
                    response = self.command_handler.process_command(user_input)
                    if response:
                        print(f"🤖 小智: {response}")
                        # 通过WebSocket发送响应给前端
                        self.emit('response', {'text': response})
                        # 语音播报响应
                        self.speak_text(response)
                    # 更新本地状态
                    self._handle_sleep()
                    print("💤 系统已休眠，输入任意内容唤醒...")
                    # 等待唤醒
                    wake_input = input("👤 唤醒: ").strip()
                    if wake_input:
                        self._handle_wakeup()
                    continue

                # 处理普通命令
                response = self.command_handler.process_command(user_input)

                if response:
                    print(f"🤖 小智: {response}")
                    # 通过WebSocket发送响应给前端
                    self.emit('response', {'text': response})
                    # 语音播报响应
                    self.speak_text(response)

                    # 可选语音播报
                    if hasattr(self, 'voice_enabled') and self.voice_enabled:
                        speak_choice = input("🔊 播放语音？(y/n): ").strip().lower()
                        if speak_choice in ['y', 'yes', '是']:
                            try:
                                self.speak_text(response)
                            except Exception as e:
                                print(f"⚠️  语音播报失败: {e}")
                else:
                    print("❌ 未识别到有效命令，请重试")

            except KeyboardInterrupt:
                print(f"\n👋 再见！")
                break
            except Exception as e:
                print(f"❌ 错误: {e}")

    def test_api_connections(self):
        """测试API连接"""
        try:
            import requests
            import time

            # 给服务器一点时间完全启动
            time.sleep(2)

            base_url = "http://localhost:5000"

            # 测试1: 基础状态接口
            print("📡 测试基础状态接口...")
            try:
                response = requests.get(f"{base_url}/", timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    print(f"✅ 基础接口正常 - 状态: {data.get('status', 'unknown')}")
                else:
                    print(f"❌ 基础接口返回状态码: {response.status_code}")
            except Exception as e:
                print(f"❌ 基础接口测试失败: {e}")

            # 测试2: 健康检查接口
            print("📡 测试健康检查接口...")
            try:
                response = requests.get(f"{base_url}/api/health", timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    print(f"✅ 健康检查正常 - {data.get('status', 'unknown')}")
                else:
                    print(f"❌ 健康检查返回状态码: {response.status_code}")
            except Exception as e:
                print(f"❌ 健康检查测试失败: {e}")

            # 测试3: Speak接口
            print("📡 测试Speak接口...")
            try:
                test_data = {"text": "API连接测试"}
                response = requests.post(
                    f"{base_url}/api/speak",
                    json=test_data,
                    timeout=10,
                    headers={'Content-Type': 'application/json'}
                )
                if response.status_code == 200:
                    data = response.json()
                    print(f"✅ Speak接口正常 - 状态: {data.get('status', 'unknown')}")
                    print(f"   📝 测试文本: '{test_data['text']}' 已加入队列")
                else:
                    print(f"❌ Speak接口返回状态码: {response.status_code}")
                    print(f"   📋 响应内容: {response.text}")
            except Exception as e:
                print(f"❌ Speak接口测试失败: {e}")

            # 测试4: 列出所有路由
            print("📡 检查可用路由...")
            try:
                response = requests.get(f"{base_url}/", timeout=5)
                if response.status_code == 200:
                    print("✅ 服务器响应正常")

                    # 尝试获取路由信息（如果存在调试接口）
                    try:
                        debug_response = requests.get(f"{base_url}/api/debug/routes", timeout=5)
                        if debug_response.status_code == 200:
                            routes_data = debug_response.json()
                            api_routes = [r for r in routes_data.get('routes', []) if '/api/' in str(r.get('rule', ''))]
                            print(f"📋 发现 {len(api_routes)} 个API路由:")
                            for route in api_routes:
                                methods = list(route.get('methods', set()))
                                rule = route.get('rule', '')
                                print(f"   {methods} {rule}")
                    except:
                        print("ℹ️  无调试路由信息，显示已知路由:")
                        known_routes = [
                            "GET  /",
                            "GET  /api/status",
                            "GET  /api/health",
                            "GET  /api/history",
                            "POST /api/speak",
                            "POST /api/test_speech",
                            "POST /api/start",
                            "POST /api/stop"
                        ]
                        for route in known_routes:
                            print(f"   {route}")
                else:
                    print(f"❌ 服务器响应异常: {response.status_code}")
            except Exception as e:
                print(f"❌ 路由检查失败: {e}")

            print("\n💡 API测试完成，如果看到错误请检查:")
            print("   1. 端口5000是否被占用")
            print("   2. 防火墙设置")
            print("   3. 请求头 Content-Type: application/json")

        except ImportError:
            print("❌ 无法导入requests模块，请安装: pip install requests")
        except Exception as e:
            print(f"❌ API测试过程出错: {e}")

    def choose_mode(self):
        """选择运行模式"""
        print("\n请选择运行模式:")
        print("1. 🎤 语音模式 (Vosk语音识别 + 唤醒词)")
        print("2. 💬 文本模式 (键盘输入)")
        print("3. ⚡ 自动模式 (自动检测)")

        while True:
            try:
                choice = input("\n请选择模式 (1/2/3): ").strip()

                if choice == '1':
                    return 'voice'
                elif choice == '2':
                    return 'text'
                elif choice == '3':
                    return 'auto'
                else:
                    print("❌ 无效选择，请输入 1, 2 或 3")
            except KeyboardInterrupt:
                return 'exit'
            except Exception as e:
                print(f"❌ 输入错误: {e}")

    def cleanup(self):
        """清理资源 - 增强版本"""
        print("\n🗑️ 正在清理资源...")
        self.is_running = False
        self.audio_thread_running = False
        self.is_cleaning_up = True

        try:
            # 移除播放状态监听器
            if hasattr(self, 'voice_recognizer') and self.voice_recognizer:
                self.voice_recognizer.remove_playback_state_listener(self)

            # 等待音频队列处理完成
            if hasattr(self, 'audio_thread') and self.audio_thread:
                print("🔄 等待音频播放线程结束...")
                self.audio_thread.join(timeout=5.0)

            if hasattr(self, 'voice_recognizer') and self.voice_recognizer:
                self.voice_recognizer.cleanup()

            if hasattr(self, 'audio_processor') and self.audio_processor:
                self.audio_processor.cleanup()

            if hasattr(self, 'command_handler') and self.command_handler:
                self.command_handler.cleanup()

            print("✅ 资源清理完成")
        except Exception as e:
            print(f"⚠️ 清理过程中出现警告: {e}")


def main():
    """主函数"""
    print("🚀 启动小智语音助手服务端...")

    # 创建必要的目录
    os.makedirs("temp_audio", exist_ok=True)
    os.makedirs("logs", exist_ok=True)

    # 检查 Vosk 模型
    model_paths_to_check = [
        "model/vosk-model-cn-0.22",
        "model/vosk-model-small-cn-0.22",
        "model",
        "vosk-model-cn-0.22"
    ]

    found_model = False
    for path in model_paths_to_check:
        if os.path.exists(path):
            print(f"✅ 找到 Vosk 模型: {path}")
            found_model = True
            break

    if not found_model:
        print("❌ Vosk 模型目录不存在!")
        print("💡 请检查模型目录结构:")
        print("   您的模型应该在: model/vosk-model-cn-0.22/")
        print("   目录内容应该包含: am/final.mdl, graph/HCLG.fst, ivector/, conf/ 等")
        print("\n📥 您可以从这里下载模型:")
        print("   https://alphacephei.com/vosk/models")
        print("   推荐下载: vosk-model-cn-0.22 或 vosk-model-small-cn-0.22")
        return

    assistant = None
    try:
        assistant = XiaoZhiAssistant()
        assistant.run()
    except KeyboardInterrupt:
        print("\n\n👋 用户退出")
    except Exception as e:
        print(f"\n❌ 程序错误: {e}")
        import traceback
        traceback.print_exc()
        print("💡 如果问题持续存在，请尝试:")
        print("   1. 检查所有依赖是否安装正确")
        print("   2. 检查模型路径是否正确")
        print("   3. 在文本模式下运行进行测试")
    finally:
        if assistant:
            assistant.cleanup()

    print("🎯 小智助手服务端已关闭")

if __name__ == "__main__":
    main()