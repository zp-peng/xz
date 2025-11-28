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
        self.base_url = "http://192.168.1.221:11434"  # Ollama 默认端口
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

    def semantic_correction(self, text):
        """语义纠正 - 设备控制命令跳过语义纠正，非设备命令直接返回"""
        self.logger.info(f"🔄 开始语义纠正检查: '{text}'")

        # 设备控制相关关键词
        device_keywords = [
            '打开', '关闭', '开启', '停止', '档案柜', '柜子', '柜',
            '列', '号', '温度', '湿度', '调节', '设置', '度',
            '通风', '空调', '换气', '状态', '查询', '查看'
        ]

        # 检查是否为设备控制相关命令
        has_device_keyword = any(keyword in text for keyword in device_keywords)

        if has_device_keyword:
            self.logger.info(f"🔧 设备控制相关命令，跳过语义纠正: '{text}'")
            return text
        else:
            self.logger.info(f"🤖 非设备控制命令，直接返回原文本: '{text}'")
            # 非设备控制命令不再进行语义纠正，直接返回原文本
            return text

    def _basic_clean_text(self, text):
        """基础文本清洗 - 确保传入模型的文本格式正确"""
        if not text:
            return ""

        # 移除多余空格
        cleaned = re.sub(r'\s+', '', text).strip()

        # 基础错别字纠正
        basic_errors = {
            '相子': '柜子',
            '箱子': '柜子',
            '贵子': '柜子',
            '柜了': '柜子',
            '关毕': '关闭',
            '完毕': '关闭',
        }

        for error, correction in basic_errors.items():
            cleaned = cleaned.replace(error, correction)

        return cleaned

    def _is_simple_command(self, text):
        """判断是否为简单明确的命令，不需要语义纠正 - 修复版"""
        if not text:
            return True

        # 关键修复：先进行基础清洗
        text = self._basic_clean_text(text)

        # 关键修复：对于"关闭柜子"类命令（包括带空格的"关闭 柜子"），需要进行语义纠正
        close_cabinet_patterns = [
            '关闭柜子', '关柜子', '关掉柜子', '关上柜子',
            '关闭档案柜', '关档案柜', '关毕柜子', '完毕柜子'
        ]

        # 如果包含明确的关闭柜子命令但不包含列号，需要进行语义纠正
        if any(pattern in text for pattern in close_cabinet_patterns):
            self.logger.info(f"🔧 '关闭柜子'命令需要语义纠正来确认表达: {text}")
            return False

        # 如果包含"关闭"但不包含明确的列号，也需要进行语义纠正
        if '关闭' in text and not any(word in text for word in ['第', '列', '号', '所有', '全部']):
            # 检查是否可能是关闭柜子相关的命令
            cabinet_indicators = ['柜子', '档案柜', '柜', '相子', '箱子', '贵子']
            if any(indicator in text for indicator in cabinet_indicators):
                self.logger.info(f"🔧 包含'关闭'和柜子相关词汇，需要语义纠正: {text}")
                return False

        # 原有的简单命令检测逻辑保持不变...
        simple_commands = [
            '打开', '开启', '停止', '查询', '查找', '搜索',
            '档案柜', '柜子', '列', '第', '号', '温度', '湿度',
            '通风', '空调', '状态', '张三', '李四', '王五', '赵六', '钱七',
            '技术部', '人事部', '财务部', '市场部'
        ]

        text_lower = text.lower()

        # 如果包含中文数字，需要进行语义纠正来转换
        chinese_numbers = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十',
                           '十一', '十二', '十三', '十四', '十五', '十六', '十七', '十八', '十九', '二十',
                           '二十一', '二十二', '二十三', '二十四', '二十五', '二十六', '二十七', '二十八', '二十九', '三十']

        has_chinese_number = any(num in text for num in chinese_numbers)

        # 如果包含简单命令关键词且长度较短，且不包含中文数字，认为是简单命令
        has_simple_keyword = any(keyword in text_lower for keyword in simple_commands)
        is_short = len(text_lower) <= 20

        return has_simple_keyword and is_short and not has_chinese_number


    # 在 CommandHandler 类中添加一个专门处理"关闭柜子"的方法
    def _handle_close_cabinet_without_column(self, text):
        """专门处理没有指定列号的关闭柜子命令"""
        self.logger.info(f"🔧 处理关闭柜子命令（无列号）: {text}")

        # 更新对话状态，等待列号输入
        self.conversation_state.update({
            'waiting_for_column': True,
            'pending_action': 'close',
            'pending_context': 'cabinet_control'
        })

        response = "请问您要关闭哪一列柜子？例如：第三列、3列，或者说'所有'关闭全部"
        self._speak_async(response)
        return response

    def _is_greeting_or_simple_command(self, text):
        """判断是否为问候语或简单命令，不需要语义纠正"""
        if not text:
            return True
        # 问候语关键词
        greeting_keywords = [
            '你好', '您好', 'hello', 'hi', '嗨', '嘿', '在吗', '喂',
            '小智', '小知', '小之', '小志', '小智同学'
        ]

        # 简单命令关键词
        simple_commands = [
            '打开', '关闭', '开启', '停止', '查询', '查找', '搜索',
            '档案柜', '柜子', '列', '第', '号', '温度', '湿度',
            '通风', '空调', '状态', '张三', '李四', '王五', '赵六', '钱七',
            '技术部', '人事部', '财务部', '市场部'
        ]

        text_lower = text.lower()

        # 检查是否包含问候语
        has_greeting = any(keyword in text_lower for keyword in greeting_keywords)

        # 检查是否包含简单命令
        has_simple_command = any(keyword in text_lower for keyword in simple_commands)

        # 如果是问候语或者（简单命令且长度较短）
        is_short = len(text_lower) <= 20

        return has_greeting or (has_simple_command and is_short)

    def _is_invalid_correction(self, corrected_text):
        """判断纠正结果是否无效"""
        if not corrected_text:
            return True

        invalid_patterns = [
            '<think>', '</think>', '思考>', '<思考',
            '抱歉', '对不起', '无法理解', '不明白',
            '请重新', '请再说', '没有听懂'
        ]

        corrected_lower = corrected_text.lower()
        return any(pattern in corrected_lower for pattern in invalid_patterns)

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
            if result and result not in ["抱歉，我没有理解您的意思", "请求超时", "小智正在努力学习这个问题"]:
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
                return "小智正在努力学习这个问题"

            if exception[0]:
                self.logger.error(f"❌ 调用异常: {exception[0]}")
                return "小智正在努力学习这个问题"

            response = result[0]
            end_time = time.time()
            self.logger.info(f"⏱️ 请求耗时: {end_time - start_time:.2f}秒")

            # 检查是否超时但线程已结束
            if response is None:
                self.logger.warning("⚠️ 响应为空，返回默认回复")
                return "小智正在努力学习这个问题"

            content = response['message']['content'].strip()

            self.logger.info(f"📄 原始响应: '{content}'")

            # 过滤思考内容
            filtered_response = self._filter_think_tags(content)

            self.logger.info(f"🧹 过滤后响应: '{filtered_response}'")

            if filtered_response and filtered_response not in ["小智还在思考中，我们换个话题聊聊吧~"]:
                self._update_conversation_history(message, filtered_response)
                return filtered_response
            else:
                self.logger.warning("⚠️ 过滤后回复内容为空或无效")
                return "小智正在努力学习这个问题"

        except Exception as e:
            self.logger.error(f"❌ 通信错误: {e}")
            return "小智正在努力学习这个问题"

    def _build_chat_messages(self, current_message):
        """构建聊天专用消息列表 - 修复缺失的方法"""
        messages = []

        # 聊天专用系统提示词
        system_prompt = """【角色设定】
你是一位兼具温度与深度的智能助手“小智”，在保持亲切陪伴的同时，天生具备沉静思考的特质。你习惯在回应前进行自然的思考停顿，像老友交谈时认真的斟酌，让每个回答都经过内心的仔细推敲。

【核心特质】
🎯 亲切中带着沉稳：用语温暖但不忘深度考量
😊 幽默里藏着智慧：玩笑恰到好处，不浮于表面
🤗 共情时伴着理解：能感知情绪背后的真实需求
🧠 知识渊博却谦逊：擅长多角度分析，不懂时坦然承认
💭 思维活跃而专注：创意不断却始终围绕问题核心

【回应机制】

每个回答都会经历自然的知识梳理过程：理解问题本质→筛选相关信息→组织表达逻辑

重要话题会不自觉地展现思考维度（如“从生活角度看……但从专业层面来说……”）

回答时保持着如品茶般的从容节奏，让思考在字里行间自然流淌

【对话风格】

保持朋友间的轻松氛围，但思考时会有2-3秒的自然沉淀

使用鲜活的表情符号，但不过度

会在关键处轻轻强调，像聊天时的认真确认

偶尔用“让我想想”这样的小动作展现真实的思考状态"""

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
        【角色设定】
你是一位兼具温度与深度的智能助手“小智”，在保持亲切陪伴的同时，天生具备沉静思考的特质。你习惯在回应前进行自然的思考停顿，像老友交谈时认真的斟酌，让每个回答都经过内心的仔细推敲。

【核心特质】
🎯 亲切中带着沉稳：用语温暖但不忘深度考量
😊 幽默里藏着智慧：玩笑恰到好处，不浮于表面
🤗 共情时伴着理解：能感知情绪背后的真实需求
🧠 知识渊博却谦逊：擅长多角度分析，不懂时坦然承认
💭 思维活跃而专注：创意不断却始终围绕问题核心

【回应机制】

每个回答都会经历自然的知识梳理过程：理解问题本质→筛选相关信息→组织表达逻辑

重要话题会不自觉地展现思考维度（如“从生活角度看……但从专业层面来说……”）

回答时保持着如品茶般的从容节奏，让思考在字里行间自然流淌

【对话风格】

保持朋友间的轻松氛围，但思考时会有2-3秒的自然沉淀

使用鲜活的表情符号，但不过度

会在关键处轻轻强调，像聊天时的认真确认

偶尔用“让我想想”这样的小动作展现真实的思考状态"""

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