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
import requests

# 添加当前目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

# 全局变量（简化版本）
audio_queue = queue.Queue()
is_speaking = False
speech_start_time = 0
speech_cooldown = 2  # 语音播放后的冷却时间(秒)
IS_ELECTRON = getattr(sys, 'frozen', False)
port = None

# 新增：音频播放状态
audio_playback_active = False
audio_thread = None

# --- 音频上传和工作流配置 ---
# 目标上传 API 的 URL
TARGET_API_URL = 'http://192.168.1.221/v1/files/upload'
# 工作流运行 API 的 URL
WORKFLOW_API_URL = 'http://192.168.1.221/v1/workflows/run'
# 工作流 API 的认证 Token
WORKFLOW_API_KEY = 'app-BlcNrYszyCM0OHIBzmNIfOy3'
# 目标 API 要求的 user ID
USER_ID = 'abc-123'

# 支持的音频格式及其 MIME 类型
SUPPORTED_AUDIO_FORMATS = {
    'mp3': 'audio/mpeg',
    'wav': 'audio/wav',
    'flac': 'audio/flac',
    'm4a': 'audio/mp4',
    'ogg': 'audio/ogg',
    'aac': 'audio/aac',
    'wma': 'audio/x-ms-wma'
}

def upload_audio_to_target(file_obj, file_name: str) -> dict:
    """
    内部函数：将上传的音频文件转发到目标 API
    """
    # 1. 验证文件格式
    file_ext = file_name.split('.')[-1].lower()
    if file_ext not in SUPPORTED_AUDIO_FORMATS:
        supported_formats = ', '.join(SUPPORTED_AUDIO_FORMATS.keys())
        return {'success': False, 'error': f'不支持的音频格式: {file_ext}。仅支持: {supported_formats}'}

    # 2. 构造目标 API 的请求参数
    headers = {
        'Authorization': f'Bearer {WORKFLOW_API_KEY}'
    }
    data = {
        'user': USER_ID
    }

    # 3. 转发文件到目标 API
    try:
        files = {
            'file': (file_name, file_obj, SUPPORTED_AUDIO_FORMATS[file_ext])
        }
        response = requests.post(
            TARGET_API_URL,
            headers=headers,
            data=data,
            files=files
        )

        # 4. 处理目标 API 的响应
        if response.status_code == 201:
            return {'success': True, 'message': '音频上传成功！', 'target_response': response.json()}
        else:
            return {
                'success': False,
                'error': '上传到目标 API 失败',
                'status_code': response.status_code,
                'target_error': response.text
            }

    except requests.exceptions.RequestException as e:
        return {'success': False, 'error': f'请求目标 API 网络异常: {e}'}
    except Exception as e:
        return {'success': False, 'error': f'未知错误: {e}'}

def run_workflow_and_extract_text(api_key, upload_file_id):
    """
    运行工作流并提取文本内容
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    data = {
        "inputs": {
            "file": [
                {
                    "transfer_method": "local_file",
                    "upload_file_id": upload_file_id,
                    "type": "audio"
                }
            ]
        },
        "response_mode": "streaming",
        "user": USER_ID
    }

    try:
        response = requests.post(
            url=WORKFLOW_API_URL,
            headers=headers,
            json=data,
            timeout=30
        )

        if response.status_code == 200:
            final_text = None

            for line in response.iter_lines(decode_unicode=True):
                if line:
                    # 检查是否是 workflow_finished 事件
                    if '"event": "workflow_finished"' in line:
                        try:
                            # 提取 JSON 数据
                            json_str = line.replace('data: ', '')
                            data_obj = json.loads(json_str)

                            # 获取 outputs.text
                            if 'data' in data_obj and 'outputs' in data_obj['data']:
                                final_text = data_obj['data']['outputs'].get('text', '')

                                if final_text:
                                    return {
                                        'success': True,
                                        'text': final_text,
                                        'message': '文本提取成功'
                                    }

                        except json.JSONDecodeError as e:
                            return {'success': False, 'error': f'JSON解析错误: {e}'}

            if not final_text:
                return {'success': False, 'error': '未找到 workflow_finished 事件中的文本内容'}

        else:
            return {'success': False, 'error': f'工作流请求失败，状态码: {response.status_code}', 'response': response.text}

    except requests.exceptions.RequestException as e:
        return {'success': False, 'error': f'请求工作流异常: {e}'}

# main.py 中的依赖检查部分
def check_dependencies():
    """快速依赖检查"""
    import importlib.util

    required_deps = [
        "requests",
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
        critical_deps = ["flask"]
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
    from core.command_handler import CommandHandler
    from flask_socketio import SocketIO
    # 导入 ArchiveManager
    from core.archive_manager import ArchiveManager
    from flask_cors import CORS
except ImportError as e:
    print(f"❌ 导入核心模块失败: {e}")
    print("💡 请确保所有核心文件都存在且正确")
    sys.exit(1)
    # 在全局变量部分添加
archive_manager = None  # 全局档案管理器实例

class XiaoZhiAssistant:
    def __init__(self):
        print("🔄 正在初始化小智语音助手...")
        # 确保先初始化Flask和SocketIO
        self.app = Flask(__name__)
        CORS(self.app)
        self.socketio = SocketIO(self.app, cors_allowed_origins="*", async_mode='threading')

        # 简化：移除语音模式相关状态
        self.is_running = False
        self.audio_thread_running = False
        self.is_cleaning_up = False

        # 初始化全局档案管理器
        self.init_archive_manager()

        # 立即设置路由
        self.setup_routes()
        self.setup_socketio_events()

        # 立即启动服务器（不等待其他组件）
        self.start_websocket_server_sync()

        # 然后同步初始化其他组件
        self.init_components_sync()

    def init_components_sync(self):
        """同步初始化所有组件"""
        try:
            print("🔄 正在同步初始化所有组件...")

            # 初始化命令处理器
            self.init_command_handler()

            print("✅ 所有组件同步初始化完成")

            return True

        except Exception as e:
            print(f"❌ 同步初始化失败: {e}")
            return False

    def init_archive_manager(self):
        """初始化全局档案管理器"""
        global archive_manager
        try:
            print("🔄 正在初始化档案管理器...")
            archive_manager = ArchiveManager()
            if archive_manager.connect():
                print("✅ 档案管理器初始化成功")
            else:
                print("⚠️ 档案管理器初始化失败，档案查询功能将不可用")
        except Exception as e:
            print(f"❌ 档案管理器初始化异常: {e}")
            archive_manager = None

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

    def init_command_handler(self):
        """初始化命令处理器"""
        try:
            self.command_handler = CommandHandler(
                self.socketio
            )
            print("✅ 命令处理器初始化完成")
        except Exception as e:
            print(f"⚠️ 命令处理器初始化失败: {e}")
            self.command_handler = None

    def setup_routes(self):
        """设置所有路由接口（简化版本）"""
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

        @self.app.route('/api/status', methods=['GET'])
        def get_status():
            return jsonify({
                "audio_queue_size": audio_queue.qsize(),
                "is_speaking": is_speaking,
                "electron_mode": IS_ELECTRON,
                "port": port,
                "speech_cooldown_remaining": max(0, speech_cooldown - (time.time() - speech_start_time)),
                "audio_playback_active": audio_playback_active
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
                    "command_handler": self.command_handler is not None,
                },
                "endpoints": [
                    {"method": "GET", "path": "/", "description": "服务状态"},
                    {"method": "GET", "path": "/api/status", "description": "系统状态"},
                    {"method": "GET", "path": "/api/health/detailed", "description": "详细健康检查"}
                ]
            }
            return jsonify(health_info)

        @self.app.route('/audioConversion', methods=['POST'])
        def audioConversion():
            """运行工作流接口 - 直接接收文件，自动上传并运行工作流（只做语音识别）"""
            try:
                # 从form-data中获取上传的文件
                uploaded_file = request.files.get('file')
                if not uploaded_file:
                    return jsonify({
                        'success': False,
                        'error': '请在form-data中上传名为"file"的音频文件'
                    }), 400

                # 获取上传文件的文件名
                file_name = uploaded_file.filename
                if not file_name:
                    return jsonify({
                        'success': False,
                        'error': '上传的文件无有效名称'
                    }), 400

                # 1. 先上传文件获取文件ID
                upload_result = upload_audio_to_target(uploaded_file, file_name)
                if not upload_result['success']:
                    return jsonify(upload_result), 400

                # 2. 从上传结果中获取文件ID
                upload_file_id = upload_result['target_response']['id']

                # 3. 运行工作流并提取文本（只做语音识别）
                workflow_result = run_workflow_and_extract_text(WORKFLOW_API_KEY, upload_file_id)

                # 4. 只返回语音识别的文本结果，不做后续处理
                if workflow_result['success']:
                    text = workflow_result.get('text', '').strip()
                    print(f"✅ 语音识别结果: {text}")

                    if text:
                        # 构建响应数据 - 只返回语音识别结果
                        response_data = {
                            'success': True,
                            'text': text,
                            'is_processed': False,  # 标记为未处理
                            'message': '语音识别成功',
                            'timestamp': time.time(),
                            'source': 'workflow_audio_processing'
                        }

                        return jsonify(response_data), 200
                    else:
                        return jsonify({
                            'success': True,
                            'text': '',
                            'is_processed': False,
                            'message': '语音识别成功但文本为空',
                            'timestamp': time.time(),
                            'source': 'workflow_audio_processing'
                        }), 200
                else:
                    # 工作流执行失败
                    return jsonify({
                        'success': False,
                        'error': '语音识别失败',
                        'workflow_error': workflow_result.get('error', '未知错误'),
                        'workflow_result': workflow_result
                    }), 400

            except Exception as e:
                print(f"❌ run_workflow_endpoint 异常: {e}")
                return jsonify({
                    'success': False,
                    'error': f'处理请求时出现异常: {str(e)}'
                }), 500

        @self.app.route('/api/health', methods=['GET'])
        def health_check():
            return jsonify({
                "status": "healthy",
                "timestamp": time.time(),
                "service": "voice_wakeup"
            })

        # --- 音频上传和工作流接口 ---
        @self.app.route('/uploadAudio', methods=['POST'])
        def upload_audio_endpoint():
            """
            上传音频文件接口
            """
            # 从form-data中获取上传的文件
            uploaded_file = request.files.get('file')
            if not uploaded_file:
                return jsonify({
                    'success': False,
                    'error': '请在form-data中上传名为"file"的音频文件'
                }), 400

            # 获取上传文件的文件名
            file_name = uploaded_file.filename
            if not file_name:
                return jsonify({
                    'success': False,
                    'error': '上传的文件无有效名称'
                }), 400

            # 转发文件到目标 API
            result = upload_audio_to_target(uploaded_file, file_name)

            # 返回最终响应
            return jsonify(result), 200 if result['success'] else 400

        # 新增档案查询接口
        @self.app.route('/api/archive/query', methods=['POST'])
        def query_archive_formatted_endpoint():
            """
            档案查询API接口（格式化结果）
            请求参数: { "query_text": "查询文本" }
            返回结果: 格式化的文本结果
            """
            try:
                # 检查全局档案管理器
                global archive_manager
                if not archive_manager:
                    return jsonify({
                        'success': False,
                        'error': '档案管理器未初始化',
                        'formatted_result': '档案管理器未初始化，请稍后重试'
                    }), 500

                # 获取请求数据
                data = request.get_json()
                if not data:
                    return jsonify({
                        'success': False,
                        'error': '请求体必须为JSON格式',
                        'formatted_result': '请求格式错误，请使用JSON格式'
                    }), 400

                query_text = data.get('query_text')
                if not query_text:
                    return jsonify({
                        'success': False,
                        'error': '缺少查询文本参数 query_text',
                        'formatted_result': '请输入要查询的档案名称或编号'
                    }), 400

                print(f"📁 格式化档案查询API调用: {query_text}")

                # 执行查询
                query_result = archive_manager.query_archive(query_text)

                # 格式化结果
                formatted_result = archive_manager.format_archive_results(query_result)

                # 返回格式化结果
                return jsonify({
                    'success': query_result.get('success', False),
                    'query_text': query_text,
                    'formatted_result': formatted_result,
                    'raw_result': query_result,  # 可选：包含原始结果供调试
                    'timestamp': time.time()
                }), 200

            except Exception as e:
                print(f"❌ 格式化档案查询API异常: {e}")
                return jsonify({
                    'success': False,
                    'error': f'查询过程中出现错误: {str(e)}',
                    'formatted_result': '查询档案时出现错误，请稍后再试'
                }), 500


        # 在 setup_routes 方法中添加以下代码（可以放在 /api/archive/query 路由之后）

        @self.app.route('/api/archive/attachments', methods=['POST'])
        def query_attachments_by_archive_id():
            """
            根据档案ID查询附件信息API接口
            请求参数: { "archive_id": "档案ID" }
            返回结果: 附件列表信息
            """
            try:
                # 检查全局档案管理器
                global archive_manager
                if not archive_manager:
                    return jsonify({
                        'success': False,
                        'error': '档案管理器未初始化',
                        'message': '档案管理器未初始化，请稍后重试'
                    }), 500

                # 获取请求数据
                data = request.get_json()
                if not data:
                    return jsonify({
                        'success': False,
                        'error': '请求体必须为JSON格式',
                        'message': '请求格式错误，请使用JSON格式'
                    }), 400

                archive_id = data.get('archive_id')
                if not archive_id:
                    return jsonify({
                        'success': False,
                        'error': '缺少档案ID参数 archive_id',
                        'message': '请输入要查询的档案ID'
                    }), 400

                print(f"📁 查询档案附件API调用，档案ID: {archive_id}")

                # 执行查询
                query_result = archive_manager.query_attachment_by_archive_id(archive_id)

                # 格式化附件信息
                attachments = query_result.get('results', [])
                formatted_results = []

                for attachment in attachments:
                    formatted_attachment = {
                        'id': attachment.get('id'),
                        'name': attachment.get('name', '未命名附件'),
                        'file_path': attachment.get('file_path'),
                        'file_size': attachment.get('file_size'),
                        'create_time': attachment.get('create_time'),
                        'archives_id': attachment.get('archives_id')
                    }
                    formatted_results.append(formatted_attachment)

                # 返回结果
                return jsonify({
                    'success': query_result.get('success', False),
                    'archive_id': archive_id,
                    'count': len(formatted_results),
                    'timestamp': time.time(),
                    'raw_result': query_result  # 可选：包含原始结果供调试
                }), 200

            except Exception as e:
                print(f"❌ 查询附件API异常: {e}")
                return jsonify({
                    'success': False,
                    'error': f'查询过程中出现错误: {str(e)}',
                    'message': '查询附件时出现错误，请稍后再试'
                }), 500

        @self.app.route('/runWorkflow', methods=['POST'])
        def run_workflow_endpoint():
            """
            运行工作流接口 - 直接接收文件，自动上传并运行工作流
            """
            try:
                # 从form-data中获取上传的文件
                uploaded_file = request.files.get('file')
                if not uploaded_file:
                    return jsonify({
                        'success': False,
                        'error': '请在form-data中上传名为"file"的音频文件'
                    }), 400

                # 获取上传文件的文件名
                file_name = uploaded_file.filename
                if not file_name:
                    return jsonify({
                        'success': False,
                        'error': '上传的文件无有效名称'
                    }), 400

                # 1. 先上传文件获取文件ID
                upload_result = upload_audio_to_target(uploaded_file, file_name)
                if not upload_result['success']:
                    return jsonify(upload_result), 400

                # 2. 从上传结果中获取文件ID
                upload_file_id = upload_result['target_response']['id']

                # 3. 运行工作流并提取文本
                workflow_result = run_workflow_and_extract_text(WORKFLOW_API_KEY, upload_file_id)

                # 4. 如果工作流成功，则使用command_handler处理提取的文本
                if workflow_result['success']:
                    text = workflow_result.get('text', '').strip()
                    print(f"✅ 获取到的文字------------: {text}")
                    if text:
                        # 使用command_handler处理文本
                        if hasattr(self, 'command_handler') and self.command_handler is not None:
                            # 直接使用command_handler的处理结果作为最终响应
                            command_response = self.command_handler.process_command(text)

                            # 构建响应数据 - 完全基于command_handler的处理结果
                            response_data = {
                                'success': True,
                                'text': text,
                                'processed_response': command_response,
                                'timestamp': time.time(),
                                'source': 'workflow_audio_processing'
                            }

                            # 同时发送WebSocket消息给前端显示
                            if hasattr(self, 'socketio') and self.socketio:
                                self.socketio.emit('workflow_processed', {
                                    'text': text,
                                    'processed_response': command_response,
                                    'timestamp': time.time()
                                })

                            return jsonify(response_data), 200
                        else:
                            return jsonify({
                                'success': False,
                                'error': '命令处理器未初始化',
                                'text': text
                            }), 500
                    else:
                        return jsonify({
                            'success': False,
                            'error': '工作流返回的文本为空',
                            'workflow_result': workflow_result
                        }), 400
                else:
                    # 工作流执行失败
                    return jsonify({
                        'success': False,
                        'error': '工作流执行失败',
                        'workflow_error': workflow_result.get('error', '未知错误'),
                        'workflow_result': workflow_result
                    }), 400

            except Exception as e:
                print(f"❌ run_workflow_endpoint 异常: {e}")
                return jsonify({
                    'success': False,
                    'error': f'处理请求时出现异常: {str(e)}'
                }), 500

    def setup_socketio_events(self):
        """设置SocketIO事件处理器（简化版本）"""
        @self.socketio.on('connect')
        def handle_connect():
            print(f"✅ 客户端连接: {request.sid}")
            self.emit('connected', {'status': 'connected', 'message': 'WebSocket 连接成功'})

        @self.socketio.on('disconnect')
        def handle_disconnect():
            print(f"❌ 客户端断开: {request.sid}")

        @self.socketio.on('record_selected')
        def handle_record_selected(data):
            fileno = data.get('fileno')
            filename = data.get('filename')
            print(f"📌 用户选择了档案: {filename} (编号: {fileno})")

            response_text = f"已成功打开{filename}对应存储位置"
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

    def run_voice_mode(self):
        """运行语音交互模式 - 简化版本"""
        print("🎤 语音模式启动...")
        print("💡 语音模式已通过 /runWorkflow 接口实现")
        print("🌐 请通过前端调用接口使用语音功能")

        # 保持程序运行
        try:
            while self.is_running:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n👋 用户退出")

    def run(self):
        """运行助手 - 修复版本"""
        self.is_running = True

        try:
            print("🚀 系统启动中...")

            # 选择运行模式
            mode = self.choose_mode()

            if mode == 'exit':
                return

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
        """运行文本交互模式 - 简化版本"""
        print("\n" + "="*50)
        print("💬 小智助手 - 文本模式")
        print("="*50)
        print("📚 支持命令:")
        print("  • 查询档案")
        print("  • 设备控制")
        print("="*50)

        while self.is_running:
            try:
                user_input = input("\n👤 您: ").strip()

                if not user_input:
                    continue

                # 处理普通命令
                response = self.command_handler.process_command(user_input)

                if response:
                    print(f"🤖 小智: {response}")
                    # 通过WebSocket发送响应给前端
                    self.emit('response', {'text': response})
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

            # 测试3: 列出所有路由
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
                            "POST /uploadAudio",
                            "POST /runWorkflow"
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
        print("1. 💬 语音 (语音输入)")
        print("2. 💬 文本 (键盘输入)")

        while True:
            try:
                choice = input("\n请选择模式 (1): ").strip()
                if choice == '1':
                    return 'voice'
                elif choice == '2':
                    return 'text'
                else:
                    print("❌ 无效选择，请输入 1 或 2")
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
        print("   2. 在文本模式下运行进行测试")
    finally:
        if assistant:
            assistant.cleanup()

    print("🎯 小智助手服务端已关闭")

if __name__ == "__main__":
    main()