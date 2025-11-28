# core/websocket_server.py
from flask_socketio import SocketIO, emit
import json
import asyncio
import threading
from utils.logger import setup_logger
from flask import request

class WebSocketServer:
    def __init__(self, app=None, command_handler=None):
        self.command_handler = command_handler
        self.logger = setup_logger("websocket_server")
        self.socketio = None
        self.connected_clients = set()
        self.is_running = False

        if app:
            self.init_app(app)

    def init_app(self, app):
        """初始化SocketIO应用 - 修复版本"""
        try:
            self.socketio = SocketIO(
                app,
                cors_allowed_origins="*",
                async_mode='threading',
                logger=True,
                engineio_logger=True
            )
            self._register_handlers()
            self.is_running = True
            self.logger.info("✅ SocketIO服务器初始化成功")
            return True
        except Exception as e:
            self.logger.error(f"❌ SocketIO服务器初始化失败: {e}")
            return False

    def _register_handlers(self):
        """注册SocketIO事件处理器"""
        @self.socketio.on('connect')
        def handle_connect():
            client_id = request.sid  # 使用 request.sid 而不是 id(request.sid)
            self.connected_clients.add(client_id)
            self.logger.info(f"🔗 客户端连接: {client_id}")
            emit('connection_established', {
                "message": "连接服务器成功",
                "timestamp": self._get_current_time()
            })

        @self.socketio.on('disconnect')
        def handle_disconnect():
            client_id = request.sid  # 使用 request.sid 而不是 id(request.sid)
            self.connected_clients.discard(client_id)
            self.logger.info(f"🔌 客户端断开连接: {client_id}")

        @self.socketio.on('message')
        def handle_message(data):
            """处理客户端发送的消息"""
            try:
                if isinstance(data, str):
                    data = json.loads(data)

                message_type = data.get('type')
                params = data.get('params', {})

                self.logger.info(f"📥 收到客户端消息: {message_type} - {params}")
                self._handle_client_message(message_type, params)

            except Exception as e:
                self.logger.error(f"❌ 处理客户端消息失败: {e}")
                emit('error', {
                    "message": f"处理消息失败: {str(e)}",
                    "code": "MESSAGE_PROCESSING_ERROR"
                })

        @self.socketio.on('query_results')
        def handle_query_results(data):
            """处理查询结果"""
            try:
                results = data.get('results', [])
                if self.command_handler:
                    self.command_handler.update_query_results(results)
                    emit('query_received', {
                        "message": "查询结果已接收",
                        "result_count": len(results)
                    })
                else:
                    emit('error', {
                        "message": "命令处理器未就绪",
                        "code": "COMMAND_HANDLER_NOT_READY"
                    })
            except Exception as e:
                self.logger.error(f"❌ 处理查询结果失败: {e}")
                emit('error', {
                    "message": f"处理查询结果失败: {str(e)}",
                    "code": "QUERY_RESULTS_ERROR"
                })

        @self.socketio.on('operation_completed')
        def handle_operation_completed(data):
            """处理操作完成消息"""
            try:
                operation = data.get('operation')
                success = data.get('success', False)
                params = data.get('params', {})
                self._handle_operation_complete(operation, success, params)
            except Exception as e:
                self.logger.error(f"❌ 处理操作完成消息失败: {e}")
                emit('error', {
                    "message": f"处理操作完成消息失败: {str(e)}",
                    "code": "OPERATION_COMPLETED_ERROR"
                })

        @self.socketio.on('error')
        def handle_error(data):
            """处理错误消息"""
            try:
                error_msg = data.get('message', '未知错误')
                error_code = data.get('code', 'UNKNOWN_ERROR')
                self.logger.error(f"❌ 客户端报告错误 [{error_code}]: {error_msg}")
                if self.command_handler:
                    self.command_handler._speak_async(f"操作失败: {error_msg}")
            except Exception as e:
                self.logger.error(f"❌ 处理错误消息失败: {e}")

        @self.socketio.on('ping')
        def handle_ping():
            """处理心跳检测"""
            emit('pong', {
                "timestamp": self._get_current_time()
            })

        @self.socketio.on('start_listening')
        def handle_start_listening():
            """处理开始监听请求 - 增强错误处理"""
            try:
                # 这里可以添加特定的开始监听逻辑
                # 由于具体实现在 main.py 中，这里只做转发或记录
                self.logger.info("📡 收到开始监听请求")
                emit('listening_status', {
                    "status": "processing",
                    "message": "正在处理开始监听请求"
                })
            except Exception as e:
                self.logger.error(f"❌ 处理开始监听请求失败: {e}")
                emit('error', {
                    "message": f"处理开始监听请求失败: {str(e)}",
                    "code": "START_LISTENING_ERROR"
                })

    def _handle_client_message(self, message_type, params):
        """处理客户端消息"""
        try:
            if message_type == 'query_results':
                results = params.get('results', [])
                if self.command_handler:
                    self.command_handler.update_query_results(results)
                    self.emit_to_client('query_received', {
                        "message": "查询结果已接收",
                        "result_count": len(results)
                    })
                else:
                    self.emit_to_client('error', {
                        "message": "命令处理器未就绪",
                        "code": "COMMAND_HANDLER_NOT_READY"
                    })

            elif message_type == 'operation_completed':
                operation = params.get('operation')
                success = params.get('success', False)
                self._handle_operation_complete(operation, success, params)

            elif message_type == 'error':
                error_msg = params.get('message', '未知错误')
                error_code = params.get('code', 'UNKNOWN_ERROR')
                self.logger.error(f"❌ 客户端报告错误 [{error_code}]: {error_msg}")
                if self.command_handler:
                    self.command_handler._speak_async(f"操作失败: {error_msg}")

            elif message_type == 'ping':
                self.emit_to_client('pong', {
                    "timestamp": self._get_current_time()
                })

            elif message_type == 'start_listening':
                self.logger.info("📡 收到开始监听请求")
                self.emit_to_client('listening_status', {
                    "status": "processing",
                    "message": "正在处理开始监听请求"
                })

            else:
                self.logger.warning(f"⚠️ 未知消息类型: {message_type}")
                self.emit_to_client('error', {
                    "message": f"未知消息类型: {message_type}",
                    "code": "UNKNOWN_MESSAGE_TYPE"
                })

        except Exception as e:
            self.logger.error(f"❌ 处理客户端消息失败: {e}")
            self.emit_to_client('error', {
                "message": f"处理客户端消息失败: {str(e)}",
                "code": "CLIENT_MESSAGE_ERROR"
            })

    def _handle_operation_complete(self, operation, success, params):
        """处理操作完成消息"""
        try:
            operation_map = {
                'open_cabinet': "打开",
                'close_cabinet': "关闭",
                'query_record': "查询"
            }

            action_text = operation_map.get(operation, "操作")

            if success:
                message = f"{action_text}操作完成"
                self.logger.info(f"✅ {action_text}操作成功")
            else:
                message = f"{action_text}操作失败"
                self.logger.error(f"❌ {action_text}操作失败")

            # 发送操作结果确认
            self.emit_to_client('operation_acknowledged', {
                "operation": operation,
                "status": "success" if success else "failed",
                "message": message
            })

            # 语音播报
            if self.command_handler:
                self.command_handler._speak_async(message)
            else:
                self.logger.warning("⚠️ 命令处理器未就绪，无法进行语音播报")

        except Exception as e:
            self.logger.error(f"❌ 处理操作完成消息失败: {e}")
            self.emit_to_client('error', {
                "message": f"处理操作完成消息失败: {str(e)}",
                "code": "OPERATION_COMPLETE_ERROR"
            })

    def emit_to_client(self, event, data=None, room=None):
        """发送消息到客户端"""
        try:
            if self.socketio:
                self.socketio.emit(event, data or {}, room=room)
                self.logger.info(f"📤 发送消息到客户端: {event}")
                return True
            return False
        except Exception as e:
            self.logger.error(f"❌ 发送消息到客户端失败: {e}")
            return False

    def broadcast_message(self, event, data=None):
        """广播消息到所有连接的客户端"""
        try:
            if self.socketio:
                self.socketio.emit(event, data or {})
                self.logger.info(f"📢 广播消息: {event}")
                return True
            return False
        except Exception as e:
            self.logger.error(f"❌ 广播消息失败: {e}")
            return False

    def send_to_all_clients(self, event, data=None):
        """发送消息到所有客户端（broadcast的别名）"""
        return self.broadcast_message(event, data)

    def get_client_count(self):
        """获取当前连接的客户端数量"""
        return len(self.connected_clients)

    def _get_current_time(self):
        """获取当前时间字符串"""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def run(self, app, host='0.0.0.0', port=5000, debug=False):
        """运行SocketIO服务器"""
        try:
            self.logger.info(f"🚀 启动SocketIO服务器: {host}:{port}")
            self.socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)
            return True
        except Exception as e:
            self.logger.error(f"❌ 启动SocketIO服务器失败: {e}")
            return False

    def stop_server(self):
        """停止SocketIO服务器"""
        self.is_running = False
        self.logger.info("🛑 SocketIO服务器已停止")