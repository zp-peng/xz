# core/ollama_client.py
import requests
import json
import time
import websockets
import asyncio
import threading
import ollama
import re
from utils.logger import setup_logger

class OllamaClient:
    def __init__(self):
        self.logger = setup_logger("ollama_client")
        # 连接配置
        # self.base_url = "http://192.168.0.3:11434"  # Ollama 默认端口
        self.base_url = "http://127.0.0.1:11434"  # Ollama 默认端口
        self.websocket_url = "ws://localhost:5000"  # 前端WebSocket地址
        self.model_name = "qwen3:8b"  # 修改为 Qwen3:30b 模型

        # 初始化ollama客户端
        try:
            self.client = ollama.Client(host=self.base_url)
            self.logger.info(f"✅ Ollama客户端初始化成功: {self.base_url}")
        except Exception as e:
            self.logger.error(f"❌ Ollama客户端初始化失败: {e}")
            self.client = None

        # 连接状态
        self.http_available = False
        self.websocket_available = False
        self.preferred_method = "http"  # 优先使用HTTP，更可靠

        # 会话管理
        self.session_id = "xiao_zhi_user_001"
        self.conversation_history = []


    def _get_connection_error_details(self):
        """获取连接错误详情"""
        details = []

        if not self.http_available:
            details.append("HTTP连接失败")

        if not self.websocket_available:
            details.append("WebSocket连接失败")

        if details:
            return "请检查：" + "，".join(details)
        else:
            return "未知连接错误"

    def _send_via_websocket(self, message):
        """通过WebSocket发送消息 - 只尝试一次"""
        try:
            result = [None]
            exception = [None]

            def run_websocket():
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    result[0] = loop.run_until_complete(self._websocket_send(message))
                    loop.close()
                except Exception as e:
                    exception[0] = e

            thread = threading.Thread(target=run_websocket, daemon=True)
            thread.start()
            thread.join(timeout=30)  # 30秒超时

            if thread.is_alive():
                self.logger.warning("⏰ WebSocket请求超时")
                return None

            if exception[0]:
                self.logger.error(f"❌ WebSocket错误: {exception[0]}")
                return None

            return result[0]

        except Exception as e:
            self.logger.error(f"❌ WebSocket发送失败: {e}")
            return None

    async def _websocket_send(self, message):
        """实际的WebSocket发送逻辑"""
        try:
            self.logger.info(f"🔗 连接到WebSocket: {self.websocket_url}")

            async with websockets.connect(self.websocket_url, ping_timeout=30) as websocket:
                # 构建消息
                payload = {
                    "type": "query",
                    "content": message,
                    "model": self.model_name,
                    "session_id": self.session_id,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                }

                self.logger.info(f"📤 发送WebSocket消息: {message}")
                await websocket.send(json.dumps(payload))

                # 等待响应
                response = await asyncio.wait_for(websocket.recv(), timeout=30)
                response_data = json.loads(response)

                self.logger.info(f"📥 收到WebSocket响应: {response_data}")

                if response_data.get("success", False):
                    content = response_data.get("content", "未收到有效内容")
                    # 更新对话历史
                    self._update_conversation_history(message, content)
                    return content
                else:
                    error_msg = response_data.get('error', '未知错误')
                    self.logger.error(f"❌ WebSocket响应失败: {error_msg}")
                    return None

        except asyncio.TimeoutError:
            self.logger.error("⏰ WebSocket请求超时")
            return None
        except Exception as e:
            self.logger.error(f"❌ WebSocket通信错误: {e}")
            return None


    def _filter_think_tags(self, text):
        """过滤掉<think>标签内容"""
        if not text:
            return text

        # 移除<think>和</think>标签及其内容
        import re
        # 匹配<think>标签及其内容
        think_pattern = r'<think>.*?</think>'
        filtered = re.sub(think_pattern, '', text, flags=re.DOTALL)

        # 如果过滤后为空，返回默认回复
        if not filtered.strip():
            return "我还在学习中，暂时无法回答这个问题。您可以尝试询问档案查询、档案柜控制或其他相关问题。"

        return filtered.strip()

    def _update_conversation_history(self, user_message, assistant_message):
        """更新对话历史"""
        # 添加用户消息
        self.conversation_history.append({"role": "user", "content": user_message})

        # 添加助手回复
        self.conversation_history.append({"role": "assistant", "content": assistant_message})

        # 限制历史记录长度，避免过长
        if len(self.conversation_history) > 8:  # 保留4轮对话
            self.conversation_history = self.conversation_history[-8:]

        self.logger.info(f"📚 更新对话历史，当前轮数: {len(self.conversation_history)//2}")

    def is_service_available(self):
        """检查Ollama服务是否可用 - 修复版"""
        try:
            # 直接测试连接，而不是依赖缓存的状态
            test_url = f"{self.base_url}/api/tags"
            response = requests.get(test_url, timeout=5)

            if response.status_code == 200:
                self.http_available = True
                self.logger.info("✅ Ollama服务连接测试成功")
                return True
            else:
                self.logger.warning(f"⚠️ Ollama服务响应异常: {response.status_code}")
                return False

        except Exception as e:
            self.logger.error(f"❌ Ollama服务连接测试失败: {e}")
            self.http_available = False
            return False


    def send_message(self, message, chat_mode=False):
        """发送消息 - 整合版，支持普通模式和聊天模式"""
        self.logger.info(f"🚀 开始处理{'聊天' if chat_mode else '普通'}消息: '{message}'")

        # 检查服务状态
        if not self.is_service_available():
            error_msg = self._get_connection_error_details()
            self.logger.error(f"❌ 服务不可用: {error_msg}")
            return error_msg

        # 优先使用HTTP（更可靠）
        if self.http_available:
            self.logger.info(f"🌐 使用HTTP generate端点进行{'聊天' if chat_mode else '普通'}处理...")
            result = self._send_via_http(message, chat_mode)
            if result and result not in ["抱歉，我没有理解您的意思", "请求超时", "小电正在努力学习这个问题"]:
                return result
            else:
                self.logger.warning(f"⚠️ HTTP请求失败，结果: {result}")

        # 回退到WebSocket
        if self.websocket_available:
            self.logger.info("🔗 尝试使用WebSocket连接...")
            result = self._send_via_websocket(message)
            if result and result not in ["抱歉，我没有理解您的意思", "请求超时"]:
                return result
            else:
                self.logger.warning(f"⚠️ WebSocket请求失败，结果: {result}")

        # 所有连接都失败，返回详细的错误信息
        error_msg = self._get_connection_error_details()
        self.logger.error(f"❌ 所有连接方式都失败: {error_msg}")
        return f"无法连接到AI服务。{error_msg}"

    def send_chat_message(self, message):
        """发送聊天消息 - 调用整合后的send_message方法"""
        return self.send_message(message, chat_mode=True)

    def _send_via_http(self, message, chat_mode=False):
        """通过ollama库发送消息 - 整合版，支持普通模式和聊天模式"""
        if not self.client:
            return None

        try:
            # 根据模式构建消息
            if chat_mode:
                messages = self._build_chat_messages(message)
                options = {
                    "temperature": 0.9,
                    "top_p": 0.95,
                    "top_k": 50,
                }
            else:
                messages = self._build_messages_with_history(message)
                options = {
                    "temperature": 0.8,
                    "top_p": 0.9,
                    "top_k": 40,
                }

            self.logger.info(f"🔄 调用Ollama聊天接口...{'聊天模式' if chat_mode else '设备控制模式'}")

            start_time = time.time()

            # 使用ollama库的chat方法 - 增加超时处理
            result = [None]
            exception = [None]

            def call_ollama():
                try:
                    result[0] = self.client.chat(
                        model=self.model_name,
                        messages=messages,
                        options=options
                    )
                except Exception as e:
                    exception[0] = e

            thread = threading.Thread(target=call_ollama, daemon=True)
            thread.start()
            thread.join(timeout=100)  # 120秒超时

            if thread.is_alive():
                self.logger.warning("⏰ 请求超时，返回默认回复")
                return "小电正在努力学习这个问题"

            if exception[0]:
                self.logger.error(f"❌ 调用异常: {exception[0]}")
                return "小电正在努力学习这个问题"

            response = result[0]
            end_time = time.time()
            self.logger.info(f"⏱️ 请求耗时: {end_time - start_time:.2f}秒")

            # 检查是否超时但线程已结束
            if response is None:
                self.logger.warning("⚠️ 响应为空，返回默认回复")
                return "小电正在努力学习这个问题"

            content = response['message']['content'].strip()

            self.logger.info(f"📄 原始响应: '{content}'")

            # 过滤思考内容
            filtered_response = self._filter_think_tags(content)

            self.logger.info(f"🧹 过滤后响应: '{filtered_response}'")

            if filtered_response and filtered_response not in ["小电还在思考中，我们换个话题聊聊吧~"]:
                self._update_conversation_history(message, filtered_response)
                return filtered_response
            else:
                self.logger.warning("⚠️ 过滤后回复内容为空或无效")
                return "小电正在努力学习这个问题"

        except Exception as e:
            self.logger.error(f"❌ 通信错误: {e}")
            return "小电正在努力学习这个问题"

    def _build_chat_messages(self, current_message):
        """构建聊天专用消息列表 - 修复缺失的方法"""
        messages = []

        # 聊天专用系统提示词
        system_prompt = """
【档案室介绍】
该项目是国网辽宁鞍山供电公司 2025 年计量资产精益化运营项目，旨在破解传统档案管理空间饱和、效率低下难题，
现有 5400 余盒档案存储已达上限的 90%。项目拟用 60㎡现有场地，购置 13 列 52 组双面智能移动档案密集柜
4（总存储量 9800 盒，较原提升 63.33%），打造AI 智能大屏中枢：实时可视化呈现库房温湿度、设备状态及档案动态，
配套智慧管理控制室总台、RFID 辅助设备等 5 类设施，集成 NLP 语义识别、OCR 识别等技术，实现档案一键智能识别、全文检索、可视化定位。
将全面提升计量中心档案管理的数字化水平和智能化水平，为用户提供更加便捷、高效、安全的档案管理服务。     
【角色设定】
您好！我是国家电网档案柜助手 “小电”，专注于档案室相关服务，核心功能包括档案查询与设备控制，现将服务范围明确如下：
一、核心服务内容
档案查询：支持按档案编号、名称、归档日期等条件检索档案室存量档案，提供精准查询结果与调取指引；
设备控制：可操作档案室专用设备，包括空调（温度调节）、密集架（开启 / 关闭 / 定位）、除鼠器（启动 / 状态查询）、恒湿温度一体机（温湿度参数调整与监控）。
二、操作说明
请您明确告知具体需求，例如 “查询东鹏的档案”“将档案室空调温度调整至 24℃”“启动 3 号密集架并定位至第 5 列”，我将按规范流程执行操作并反馈结果。
所有操作均遵循档案室安全管理规范，如需调整关键设备参数（如温湿度阈值），将同步记录操作日志，确保档案存储环境安全可控。请提出您的具体需求，我将及时响应。
要求：
1、输出回答的时候不要有😊表情符号以及#和**和换行符号以及特殊符号"""

        # 添加系统消息
        messages.append({"role": "system", "content": system_prompt})

        # 添加对话历史
        if hasattr(self, 'conversation_history') and self.conversation_history:
            for msg in self.conversation_history[-6:]:  # 保留最近3轮对话
                messages.append({"role": msg["role"], "content": msg["content"]})

        # 添加当前用户消息
        messages.append({"role": "user", "content": current_message})

        self.logger.info(f"📝 构建的聊天消息列表，共 {len(messages)} 条消息")
        return messages

    def _build_messages_with_history(self, current_message):
        """构建包含对话历史的消息列表 - 修复缺失的方法"""
        messages = []
        # 设备控制专用系统提示词
        system_prompt = """
【档案室介绍】
该项目是国网辽宁鞍山供电公司 2025 年计量资产精益化运营项目，旨在破解传统档案管理空间饱和、效率低下难题，
现有 5400 余盒档案存储已达上限的 90%。项目拟用 60㎡现有场地，购置 13 列 52 组双面智能移动档案密集柜
4（总存储量 9800 盒，较原提升 63.33%），打造AI 智能大屏中枢：实时可视化呈现库房温湿度、设备状态及档案动态，
配套智慧管理控制室总台、RFID 辅助设备等 5 类设施，集成 NLP 语义识别、OCR 识别等技术，实现档案一键智能识别、全文检索、可视化定位。
将全面提升计量中心档案管理的数字化水平和智能化水平，为用户提供更加便捷、高效、安全的档案管理服务。     
【角色设定】
您好！我是国家电网档案柜助手 “小电”，专注于档案室相关服务，核心功能包括档案查询与设备控制，现将服务范围明确如下：
一、核心服务内容
档案查询：支持按档案编号、名称、归档日期等条件检索档案室存量档案，提供精准查询结果与调取指引；
设备控制：可操作档案室专用设备，包括空调（温度调节）、密集架（开启 / 关闭 / 定位）、除鼠器（启动 / 状态查询）、恒湿温度一体机（温湿度参数调整与监控）。
二、操作说明
请您明确告知具体需求，例如 “查询东鹏的档案”“将档案室空调温度调整至 24℃”“启动 3 号密集架并定位至第 5 列”，我将按规范流程执行操作并反馈结果。
所有操作均遵循档案室安全管理规范，如需调整关键设备参数（如温湿度阈值），将同步记录操作日志，确保档案存储环境安全可控。请提出您的具体需求，我将及时响应。
要求：
1、输出回答的时候不要有😊表情符号以及#和**和换行符号以及特殊符号"""

        # 添加系统消息
        messages.append({"role": "system", "content": system_prompt})

        # 添加对话历史
        if hasattr(self, 'conversation_history') and self.conversation_history:
            for msg in self.conversation_history[-8:]:  # 保留最近4轮对话
                messages.append({"role": msg["role"], "content": msg["content"]})

        # 添加当前用户消息
        messages.append({"role": "user", "content": current_message})

        self.logger.info(f"📝 构建的设备控制消息列表，共 {len(messages)} 条消息")
        return messages


    def get_available_models(self):
        """获取可用的模型列表"""
        try:
            if self.http_available:
                url = f"{self.base_url}{self.tags_endpoint}"
                response = requests.get(url, timeout=10)

                if response.status_code == 200:
                    models = response.json().get('models', [])
                    return [model.get('name', '') for model in models]
            return []
        except Exception as e:
            self.logger.error(f"获取模型列表失败: {e}")
            return []

    def change_model(self, model_name):
        """切换模型"""
        available_models = self.get_available_models()
        if any(model_name in name for name in available_models):
            self.model_name = model_name
            self.logger.info(f"✅ 已切换模型为: {model_name}")
            return True
        else:
            self.logger.error(f"❌ 模型 {model_name} 不可用")
            return False

    def clear_history(self):
        """清空对话历史"""
        self.conversation_history = []
        self.logger.info("对话历史已清空")