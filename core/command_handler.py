import re
from datetime import datetime
from config.wake_words import WAKE_WORDS
from utils.logger import setup_logger
from core.archive_manager import ArchiveManager
from core.ollama_client import OllamaClient
import jieba
import threading
import time
import random
import os
import glob
from typing import Optional

class CommandHandler:
    def __init__(self,  socketio=None):
        self.socketio = socketio

        # 立即初始化基础组件
        self.archive_manager = ArchiveManager()
        self.logger = setup_logger("command_handler")

        # 对话状态
        self.conversation_context = {
            'last_command': None,
            'last_user': None,
            'last_time': None
        }

        # 线程管理
        self.active_threads = []
        self.conversation_history = []
        self.is_cleaning_up = False
        self._is_speaking = False

        # 初始化对话状态
        self.conversation_state = {}
        self.reset_conversation_state()

        self.is_exited = False
        self.is_exited = False
        self.is_speaking = False
        self.last_speak_time = 0
        self.speak_cooldown = 3.0  # 增加到3秒冷却时间
        self.exit_keywords = ['退出', '结束', '结束对话', '退出系统', '关闭', '再见']

        # 聊天模式标志
        self.chat_mode = False
        self.chat_start_time = None

        # 空调控制相关
        self.air_conditioner_asset_id = "OE99O7T9TT13571J1J1AA59TAOE5A1T3"
        self.air_conditioner_port = 8001

        # 空调命令映射
        self.air_conditioner_commands = {
            '开机': 0,
            '关机': 1,
            '制冷18': 2,
            '制冷20': 3,
            '制冷22': 4,
            '除湿25': 5,
            '制热20': 6,
            '制热22': 7,
            '制热24': 8
        }

        # 加湿器控制相关 - 新增
        self.dehumidifier_asset_id = "J33AA3T1979EO73AA3JJTJ7O91E33JTJ"  # 根据图片修正的assetId
        self.dehumidifier_port = 8004

        # 加湿器命令映射
        self.dehumidifier_commands = {
            '开机': {'command': 1, 'switchOnOrOff': True},
            '关机': {'command': 2, 'switchOnOrOff': True},
            '除湿': {'command': 3, 'switchOnOrOff': False},
            '净化': {'command': 7, 'switchOnOrOff': False},
            '加湿': {'command': 4, 'switchOnOrOff': False}
        }

        # 除鼠器控制相关 - 更新
        self.rodent_repeller_asset_id = "99757JOO39T573OOA915JJ31OTTA1O3E"
        self.rodent_repeller_port = 8005

        # 除鼠器命令映射 - 更新为三个命令
        self.rodent_repeller_commands = {
            '关闭': {'command': 0, 'switchOnOrOff': True},  # 总开关关闭
            '低频': {'command': 1, 'switchOnOrOff': False},       # 低频模式
            '高频': {'command': 2, 'switchOnOrOff': False}        # 高频模式
        }

        # 异步初始化耗时组件
        self.init_heavy_components_async()

    def init_heavy_components_async(self):
        """异步初始化耗时组件"""
        def init_task():
            try:
                # 初始化jieba（相对较快）
                self._init_jieba()
                self.logger.info("✅ jieba分词器初始化成功")

                # 异步初始化Ollama（不阻塞）
                self.init_ollama_async()

            except Exception as e:
                self.logger.error(f"❌ 异步初始化失败: {e}")

        init_thread = threading.Thread(target=init_task, daemon=True)
        init_thread.start()

    def init_ollama_async(self):
        """异步初始化Ollama客户端"""
        def ollama_task():
            try:
                self.ollama_client = OllamaClient()
                # 异步测试连接，不阻塞
                self.test_ollama_async()
            except Exception as e:
                self.logger.error(f"❌ Ollama客户端初始化失败: {e}")
                self.ollama_client = None

        ollama_thread = threading.Thread(target=ollama_task, daemon=True)
        ollama_thread.start()

    def test_ollama_async(self):
        """异步测试Ollama连接"""
        def test_task():
            try:
                if self.ollama_client and self.ollama_client.is_service_available():
                    self.logger.info("✅ Ollama服务器连接成功")
                else:
                    self.logger.warning("⚠️ 无法连接到Ollama服务器，将使用本地命令处理")
            except Exception as e:
                self.logger.error(f"❌ Ollama连接测试异常: {e}")

        test_thread = threading.Thread(target=test_task, daemon=True)
        test_thread.start()

    def send_websocket_message(self, message_type, params=None, user_text=None):
        """发送WebSocket消息到前端"""
        if not self.socketio:
            print(f"❌ SocketIO未初始化，无法发送消息: {message_type}")
            return False

        try:
            data = {
                'type': message_type,
                'params': params or {},
                'user_text': user_text or ''
            }
            self.socketio.emit('command', data)
            print(f"📤 发送SocketIO消息: {message_type} - {params}")
            return True
        except Exception as e:
            print(f"❌ 发送SocketIO消息失败: {e}")
            return False


    def _is_exit_command(self, text):
        """判断是否为退出命令 - 增强版：支持退出聊天模式"""
        if not text:
            return False

        # 清洗文本
        cleaned_text = self._clean_text(text)
        text_lower = cleaned_text.lower().strip()

        self.logger.info(f"🔍 退出命令检测 - 原始文本: '{text}', 清洗后: '{cleaned_text}'")

        # 如果是聊天模式，检查是否要退出聊天
        if self.chat_mode:
            chat_exit_keywords = ['退出聊天', '结束聊天', '停止聊天', '不聊了', '聊完了', '结束对话']
            if any(keyword in cleaned_text for keyword in chat_exit_keywords):
                self.logger.info("🎯 检测到退出聊天命令")
                return True

        # 紧急修复：如果是"关闭柜子"相关命令，直接返回False
        close_cabinet_keywords = [
            '关闭柜子', '关柜子', '关掉柜子', '关上柜子', '关毕柜子', '完毕柜子',
            '关闭档案柜', '关档案柜', '关掉档案柜', '关上档案柜',
            '关闭柜了', '关柜了', '关掉柜了', '关上柜了',
            '关相子', '关箱子', '关贵子','把柜子关上'
                                         '关闭相子', '关闭箱子', '关闭贵子'
        ]

        for keyword in close_cabinet_keywords:
            if keyword in cleaned_text:
                self.logger.info(f"🚫 检测到关闭柜子命令 '{keyword}'，不是退出: {cleaned_text}")
                return False

        # 简化设备相关词汇检查
        device_indicators = [
            '柜子', '档案柜', '柜', '列', '号', '温度', '湿度', '度',
            '通风', '空调', '换气', '状态', '查询', '查看'
        ]

        for indicator in device_indicators:
            if indicator in cleaned_text:
                self.logger.info(f"🔧 检测到设备词汇 '{indicator}'，不是退出: {cleaned_text}")
                return False

        if '关闭' in cleaned_text:
            close_index = cleaned_text.find('关闭')
            if close_index >= 0:
                remaining_text = cleaned_text[close_index + 2:]
                device_after_close = any(indicator in remaining_text for indicator in device_indicators)
                if device_after_close:
                    self.logger.info(f"🔧 '关闭'后面跟着设备词汇，识别为设备控制: {cleaned_text}")
                    return False

        # 退出命令模式
        exit_patterns = [
            r'^退出$', r'^结束$', r'^再见$', r'^拜拜$',
            r'^退出系统$', r'^结束对话$', r'^关闭系统$',
            r'^小智退出$', r'^小智再见$', r'^小智拜拜$',
            r'^系统退出$', r'^程序退出$', r'^应用退出$',
            r'^关闭助手$', r'^关闭语音$', r'^关闭对话$',
            r'^停止语音$', r'^停止对话$'
        ]

        for pattern in exit_patterns:
            if re.match(pattern, text_lower):
                self.logger.info(f"🎯 模式匹配到退出命令: {cleaned_text}")
                return True

        exit_keywords = ['退出', '结束', '结束对话', '退出系统', '再见', '拜拜', '停止语音', '停止对话']
        has_exit_keyword = any(exit_word in text_lower for exit_word in exit_keywords)

        if '关闭' in cleaned_text:
            exit_indicators = ['系统', '程序', '应用', '助手', '小智', '语音', '对话']
            has_exit_indicator = any(indicator in text_lower for indicator in exit_indicators)

            if has_exit_indicator:
                self.logger.info(f"🎯 系统相关'关闭'命令识别为退出: {cleaned_text}")
                return True
            else:
                self.logger.info(f"🔧 '关闭'命令识别为设备控制: {cleaned_text}")
                return False

        if has_exit_keyword:
            self.logger.info(f"🎯 确认为退出命令: {cleaned_text}")
            return True

        self.logger.info(f"❌ 不是退出命令: {cleaned_text}")
        return False

    def _is_device_control(self, text):
        """判断是否为设备控制命令"""
        if not text:
            return False

        cleaned_text = self._clean_text(text)
        text_lower = cleaned_text.lower()

        device_patterns = [
            '温度', '湿度', '调节温度', '设置温度', '升温', '降温', '调温',
            '度', '摄氏度', '调到', '调制', '调至', '设置为',
            '通风', '空调', '换气', '空气',
            '关闭柜子', '关柜子', '关掉柜子', '关上柜子', '关毕柜子', '完毕柜子',
            '打开柜子', '开柜子', '开启柜子', '拉开柜子',
            '关闭档案柜', '关档案柜', '打开档案柜', '开档案柜',
            '关闭相子', '关相子', '关闭箱子', '关箱子',
            '状态', '查询状态', '查看状态',
            # 空调相关关键词
            '空调', '制冷', '制热', '除湿','开机', '关机',
            # 加湿器相关关键词 - 扩展
            '加湿器', '除湿', '净化', '加湿', '一体机', '温湿度一体机', '湿度一体机', '温度一体机',
            # 除鼠器相关关键词 - 大幅扩展
            '除鼠器', '驱鼠器', '老鼠', "打开除鼠器", '驱鼠', '低频', '高频', '总开关关闭',
            # 同音字和变体
            '出除数', '出鼠器', '储鼠器', '出鼠', '鼠器', '鼠设备', '老鼠器','楚楚','楚鼠'
            '打鼠器', '灭鼠器', '防鼠器', '抗鼠器',
            '树器', '数器', '开树器', '开数器',
            '开老鼠', '开大老鼠', '开小老鼠', '开耗子',
            '开鼠', '打鼠', '开树', '打树', '开数', '打数',
            '鼠', '树', '数',  # 单独的字也要识别
        ]

        for pattern in device_patterns:
            if pattern in cleaned_text:
                self.logger.info(f"🔧 直接匹配设备控制模式: {pattern}")
                return True

        if (any(word in cleaned_text for word in ['第', '列']) and
                any(word in cleaned_text for word in ['打开', '关闭', '开', '关'])):
            self.logger.info(f"🔧 检测到列号控制模式: {cleaned_text}")
            return True

        if cleaned_text in ['打开', '开启', '启动', '关闭', '关', '关掉', '停止']:
            self.logger.info(f"🔧 识别为单独的打开/关闭命令: {cleaned_text}")
            return True

        self.logger.info(f"❌ 不是设备控制命令: {cleaned_text}")
        return False

    def process_command(self, text):
        """处理命令 - 优化流程：先检查唤醒词再判断"""
        if not text:
            self.logger.info("❌ 文本为空，跳过处理")
            return None

        if self.is_cleaning_up:
            return "系统正在关闭，无法处理命令"

        try:
            # 第一步：文本清洗（移除空格+基本纠正）
            cleaned_text = self._clean_text(text)
            self.logger.info(f"🎯 处理命令 - 原始文本: '{text}', 清洗后: '{cleaned_text}'")

            # 第二步：紧急修复 - 优先检查是否为纯唤醒词
            is_pure_wakeup = self._is_pure_wakeup_call(cleaned_text)
            self.logger.info(f"🔍 纯唤醒词检测结果: {is_pure_wakeup}")

            if is_pure_wakeup:
                # 如果是纯唤醒词，直接返回问候语，不进行后续处理
                response = self._get_greeting_response()
                return response

            # 第五步：检查退出命令
            is_exit = self._is_exit_command(cleaned_text)
            self.logger.info(f"🔍 退出命令检测结果: {is_exit}")

            if is_exit:
                self.logger.info("🎯 识别为退出命令")
                return self._handle_exit_command(cleaned_text, text)

            # 🔥 新增：即使不在选择状态，如果文本看起来像选择命令，也尝试处理
            # 例如：第一条、第二个、选择第一个等
            if self._looks_like_selection_command(cleaned_text):
                self.logger.info(f"🔄 检测到类似选择命令: '{cleaned_text}'")
                return self._handle_selection(cleaned_text, text)

            # 第六步：状态检查和命令处理（优先处理等待用户输入的状态）
            if self.conversation_state.get('waiting_for_column', False):
                self.logger.info("🔄 处理列号输入")
                return self._handle_column_input(cleaned_text, text)

            # 第七步：优先检查档案查询命令
            if self._is_archive_query_by_name(cleaned_text):
                self.logger.info("📁 识别为按姓名查询档案命令")
                return self._handle_archive_query_by_name_websocket(cleaned_text, text)

            # 第八步：设备控制命令检测和处理
            if self._is_explicit_device_control(cleaned_text):
                self.logger.info("🎯 识别为明确设备控制命令，直接处理")
                return self._handle_device_control_websocket(cleaned_text, text)

            # 第十步：所有其他非设备控制命令都交给AI处理
            self.logger.info("🤖 非设备控制命令，交给AI处理")
            return self._handle_with_ollama_enhanced(cleaned_text)

        except Exception as e:
            self.logger.error(f"❌ 命令处理异常: {e}")
            error_msg = "处理命令时出现错误，请重试"
            return error_msg

    def _looks_like_selection_command(self, text):
        """判断文本是否看起来像选择命令"""
        if not text:
            return False

        # 选择命令的模式
        selection_patterns = [
            r'^第[一二三四五六七八九十\d]+[条个项记录]$',
            r'^选择?第[一二三四五六七八九十\d]+[条个项记录]$',
            r'^[一二三四五六七八九十\d]+[条个项记录]$',
            r'^选择?[一二三四五六七八九十\d]+[条个项记录]$',
            r'^第一条$', r'^第二条$', r'^第三条$', r'^第四条$', r'^第五条$',
            r'^第一个$', r'^第二个$', r'^第三个$', r'^第四个$', r'^第五个$',
            r'^首选$', r'^首条$', r'^首个$', r'^第一个$', r'^第一条$',
            r'^选择一$', r'^选择二$', r'^选择三$', r'^选择四$', r'^选择五$',
        ]

        for pattern in selection_patterns:
            if re.match(pattern, text):
                self.logger.info(f"✅ 匹配到选择命令模式: {pattern} -> {text}")
                return True

        # 检查是否包含中文数字 + 量词的简单模式
        simple_patterns = [
            r'第[一二三四五六七八九十]+',
            r'[一二三四五六七八九十]+[条个]'
        ]

        for pattern in simple_patterns:
            match = re.search(pattern, text)
            if match and len(text) <= 6:  # 短文本更可能是选择命令
                self.logger.info(f"✅ 简单模式匹配到选择命令: {pattern} -> {text}")
                return True

        return False


    def _extract_selection_index(self, text):
        """提取选择序号 - 增强版"""
        try:
            # 中文数字映射
            chinese_numbers = {
                '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
                '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
                '第一': 1, '第二': 2, '第三': 3, '第四': 4, '第五': 5,
                '第六': 6, '第七': 7, '第八': 8, '第九': 9, '第十': 10,
                '十一': 11, '十二': 12, '十三': 13, '十四': 14, '十五': 15,
                '十六': 16, '十七': 17, '十八': 18, '十九': 19, '二十': 20,
                '首个': 1, '第一个': 1, '第一个': 1, '首条': 1, '第一条': 1,
                '首选': 1, '第一个': 1, '头一个': 1, '第一个': 1
            }

            # 🔥 新增：支持更多表达方式
            # 匹配模式
            patterns = [
                r'选择?第([一二三四五六七八九十]+)(?:条|个|项|记录)',  # 选择第一条、选择第一个
                r'第([一二三四五六七八九十]+)(?:条|个|项|记录)',     # 第一条、第一个
                r'选择?([一二三四五六七八九十]+)(?:号|号记录)',       # 选择1号、1号记录
                r'第([一二三四五六七八九十]+)号',                   # 第1号
                r'选择?第(\d+)(?:条|个|项|记录)',                   # 选择第1条、选择第1个
                r'第(\d+)(?:条|个|项|记录)',                        # 第1条、第1个
                r'选择?(\d+)(?:号|号记录)',                         # 选择1号、1号记录
                r'第(\d+)号',                                      # 第1号
                r'首选',                                            # 首选
                r'第一个',                                          # 第一个
                r'第一条',                                          # 第一条
                r'首条',                                            # 首条
                r'首个',                                            # 首个
            ]

            for pattern in patterns:
                match = re.search(pattern, text)
                if match:
                    number_str = None
                    if len(match.groups()) > 0:
                        number_str = match.group(1)

                    # 中文数字转换
                    if number_str and number_str in chinese_numbers:
                        return chinese_numbers[number_str]
                    elif number_str and number_str.isdigit():
                        return int(number_str)
                    else:
                        # 对于"首选"、"第一个"等没有捕获组的模式
                        if pattern in ['首选', '第一个', '第一条', '首条', '首个']:
                            return chinese_numbers.get(pattern, 1)

            # 🔥 新增：支持简单的数字直接匹配
            # 如果文本是纯数字，直接返回
            if text.isdigit():
                return int(text)

            # 🔥 新增：支持"选择1"、"选择一"等简单表达
            simple_match = re.search(r'选择([一二三四五六七八九十\d]+)', text)
            if simple_match:
                number_str = simple_match.group(1)
                if number_str in chinese_numbers:
                    return chinese_numbers[number_str]
                elif number_str.isdigit():
                    return int(number_str)

            return None
        except Exception as e:
            self.logger.error(f"❌ 提取选择序号失败: {e}")
            return None

    def _is_explicit_device_control(self, text):
        """判断是否为明确的设备控制命令，不需要语义纠正 - 增强版本"""
        if not text:
            return False

        # 明确的设备控制命令模式
        explicit_patterns = [
            # 打开柜子相关
            r'打开第?[一二两三四五六七八九十\d]+列?柜子',
            r'打开柜子',
            r'开启柜子',
            r'启动柜子',
            # 🔥 新增：支持不完整的打开命令
            r'打开第?[一二两三四五六七八九十\d]+列?',
            r'打开第?[一二两三四五六七八九十\d]+',
            # 关闭柜子相关
            r'关闭第?[一二两三四五六七八九十\d]+列?柜子',
            r'关闭柜子',
            r'关柜子',
            r'关掉柜子',
            # 通风相关
            r'打开通风',
            r'开启通风',
            r'关闭通风',
            r'关通风',
            # 空调相关
            r'打开?空调',
            r'关闭?空调',
            r'空调开机',
            r'空调关机',
            r'空调制冷',
            r'空调制热',
            r'空调除湿',
            r'制冷\d+度',
            r'制热\d+度',
            r'除湿\d+度',
            r'空调调到\d+度',
            r'空调设置为\d+度',
            # 加湿器控制相关 - 扩展
            r'打开?加湿器',
            r'关闭?加湿器',
            r'加湿器开机',
            r'加湿器关机',
            r'开启除湿',
            r'关闭除湿',
            r'开启净化',
            r'关闭净化',
            r'开启加湿',
            r'关闭加湿',
            r'打开一体机',
            r'关闭一体机',
            r'打开温湿度一体机',
            r'关闭温湿度一体机',
            r'打开温度一体机',
            r'关闭温度一体机',
            r'打开湿度一体机',
            r'关闭湿度一体机',
            # 除鼠器控制相关 - 更新
            r'关闭?除鼠器',
            r'除鼠器关闭',
            r'除鼠器低频',
            r'除鼠器高频',
            r'打开除鼠器',
            r'打开除鼠设备',
            r'打开驱鼠设备',
            r'低频模式',
            r'高频模式',
            r'总开关关闭',
            # 温度调节相关
            r'温度调到[一二两三四五六七八九十\d]+度',
            r'温度设置为[一二两三四五六七八九十\d]+度',
            r'调节温度到[一二两三四五六七八九十\d]+度',
            # 状态查询
            r'查询状态',
            r'查看状态',
            r'状态查询',
            r'状态查看',
        ]

        for pattern in explicit_patterns:
            if re.search(pattern, text):
                return True

        return False

    def _exit_chat_mode(self):
        """退出聊天模式"""
        self.chat_mode = False
        chat_duration = time.time() - self.chat_start_time if self.chat_start_time else 0
        self.logger.info(f"💬 退出聊天模式，持续时间: {chat_duration:.1f}秒")

        responses = [
            "好的，聊天结束啦~ 需要的时候再叫小智哦！",
            "聊得很开心呢~ 小智先退下啦，有事随时叫我~",
            "好的，小智去忙别的啦，想聊天了随时喊我~",
            "聊天时间结束~ 小智继续待命，等你召唤哦~"
        ]

        return random.choice(responses)

    def _handle_dehumidifier_control_websocket(self, text, original_text):
        """处理加湿器控制 - 增强版：明确区分打开设备和模式切换"""
        try:
            cleaned_text = self._clean_text(text)
            text_lower = cleaned_text.lower()

            self.logger.info(f"💧 处理加湿器控制命令: '{text}' -> '{cleaned_text}'")

            # 映射用户命令到加湿器命令
            command_info = None
            response_text = ""

            # 🔥 关键修改：优先匹配设备开关命令，再匹配模式命令

            # 1. 开机命令 - 明确区分设备打开和模式打开
            if any(word in cleaned_text for word in ['打开除湿器', '打开温湿度一体机', '打开加湿器', '开启除湿器', '启动除湿器']):
                # "打开除湿器"应该理解为打开设备电源，而不是开启除湿模式
                command_info = self.dehumidifier_commands['开机']
                response_text = "正在为您打开加湿器"

            # 2. 关机命令
            elif any(word in cleaned_text for word in ['关闭除湿器', '关闭加湿器', '关加湿器', '关闭温湿度一体机']):
                command_info = self.dehumidifier_commands['关机']
                response_text = "正在为您关闭加湿器"

            # 3. 除湿模式命令 - 当设备已开机时，切换到此模式
            elif '除湿模式' in cleaned_text or '开启除湿' in cleaned_text:
                command_info = self.dehumidifier_commands['除湿']
                response_text = "正在开启除湿模式"

            # 4. 净化模式命令
            elif '净化模式' in cleaned_text or '开启净化' in cleaned_text:
                command_info = self.dehumidifier_commands['净化']
                response_text = "正在开启净化模式"

            # 5. 加湿模式命令
            elif '加湿模式' in cleaned_text or '开启加湿' in cleaned_text:
                command_info = self.dehumidifier_commands['加湿']
                response_text = "正在开启加湿模式"

            # 6. 如果没有精确匹配，尝试智能匹配
            if command_info is None:
                # 首先检查是否包含设备名称
                has_device_name = any(word in cleaned_text for word in ['加湿器', '除湿器', '一体机', '温湿度一体机'])

                # 然后检查动作
                has_open_action = any(word in cleaned_text for word in ['打开', '开启', '启动'])
                has_close_action = any(word in cleaned_text for word in ['关闭', '关', '关掉'])
                has_mode_action = any(word in cleaned_text for word in ['除湿', '净化', '加湿'])

                # 逻辑判断
                if has_device_name and has_open_action and not has_mode_action:
                    # "打开设备" -> 开机命令
                    command_info = self.dehumidifier_commands['开机']
                    response_text = "正在为您打开加湿器"
                elif has_device_name and has_close_action:
                    # "关闭设备" -> 关机命令
                    command_info = self.dehumidifier_commands['关机']
                    response_text = "正在为您关闭加湿器"
                elif has_mode_action:
                    # 只有模式没有设备开关 -> 模式切换
                    if '除湿' in cleaned_text:
                        command_info = self.dehumidifier_commands['除湿']
                        response_text = "正在开启除湿模式"
                    elif '净化' in cleaned_text:
                        command_info = self.dehumidifier_commands['净化']
                        response_text = "正在开启净化模式"
                    elif '加湿' in cleaned_text:
                        command_info = self.dehumidifier_commands['加湿']
                        response_text = "正在开启加湿模式"

            # 如果仍然没有匹配到命令，返回提示
            if command_info is None:
                response = "请告诉我具体的加湿器操作，比如：打开加湿器、关闭加湿器、开启除湿模式、开启净化模式、开启加湿模式等"
                return response

            # 发送WebSocket消息 - 严格按照提供的格式
            success = self.send_websocket_message('dehumidifier_control', {
                'assetId': self.dehumidifier_asset_id,
                'command': command_info['command'],
                'port': self.dehumidifier_port,
                'switchOnOrOff': command_info['switchOnOrOff']
            }, original_text)

            if success:
                self.logger.info(f"✅ 加湿器控制命令发送成功: {command_info} - {response_text}")
                return response_text
            else:
                error_msg = "加湿器控制命令发送失败，请稍后重试"
                return error_msg

        except Exception as e:
            self.logger.error(f"❌ 加湿器控制处理失败: {e}")
            error_msg = "处理加湿器控制时出现错误"
            return error_msg

    def _correct_rodent_repeller_text(self, text):
        """修正除鼠器相关的同音字和常见识别错误 - 增强版"""
        if not text:
            return text

        # 扩展的同音字映射表
        rodent_corrections = {
            # 设备名称同音字 - 大幅扩展
            '出除数': '除鼠器',
            '出鼠器': '除鼠器',
            '储鼠器': '除鼠器',
            '驱鼠器': '除鼠器',
            '除鼠': '除鼠器',
            '驱鼠': '除鼠器',
            '出鼠': '除鼠器',
            '除数': '除鼠器',
            '处暑': '除鼠器',
            '出书': '除鼠器',
            '鼠器': '除鼠器',
            '除鼠机': '除鼠器',
            '驱鼠机': '除鼠器',
            '老鼠器': '除鼠器',
            '区属': '除鼠器',
            '区属器': '除鼠器',
            '取数': '除鼠器',
            '取数器': '除鼠器',
            '取书': '除鼠器',
            '取书器': '除鼠器',
            '处鼠': '除鼠器',
            '处暑器': '除鼠器',
            '储鼠': '除鼠器',
            '储鼠机': '除鼠器',
            '鼠': '除鼠器',  # 单独一个"鼠"字也认为是除鼠器
            '鼠设备': '除鼠器',
            '鼠机': '除鼠器',
            '老鼠设备': '除鼠器',
            '大老鼠器': '除鼠器',
            '小老鼠器': '除鼠器',
            '耗子器': '除鼠器',
            '打鼠器': '除鼠器',
            '灭鼠器': '除鼠器',
            '防鼠器': '除鼠器',
            '抗鼠器': '除鼠器',
            '楚楚': '除鼠器',  # 新增：楚楚
            '楚楚器': '除鼠器',

            # 树/数相关同音字
            '树': '鼠',
            '数': '鼠',
            '树器': '除鼠器',
            '数器': '除鼠器',
            '打树': '打鼠',
            '打数': '打鼠',
            '开树': '开鼠',
            '开数': '开鼠',
            '开树器': '开除鼠器',
            '开数器': '开除鼠器',
            '开老鼠': '开除鼠器',
            '开大老鼠': '开除鼠器',
            '开小老鼠': '开除鼠器',
            '开耗子': '开除鼠器',

            # 打开相关同音字 - 大幅扩展
            '开': '打开',
            '开启': '打开',
            '启动': '打开',
            '开起': '打开',
            '开动': '打开',
            '开始': '打开',
            '开关': '打开',
            '开开': '打开',
            '开了': '打开',
            '开咯': '打开',
            '开啦': '打开',
            '开吧': '打开',
            '开嘛': '打开',
            '开呀': '打开',
            '开哦': '打开',
            '代开': '打开',  # 新增：代开
            '大开': '打开',  # 新增：大开

            # 驱鼠/除鼠相关同音字 - 大幅扩展
            '驱鼠': '除鼠器',
            '去鼠': '除鼠器',
            '区鼠': '除鼠器',
            '曲鼠': '除鼠器',
            '屈鼠': '除鼠器',
            '瞿鼠': '除鼠器',
            '渠鼠': '除鼠器',
            '取鼠': '除鼠器',
            '趣鼠': '除鼠器',
            '趋鼠': '除鼠器',
            '躯鼠': '除鼠器',

            # 属/鼠相关同音字 - 专门处理"打开*属"模式
            '属': '鼠',
            '述': '鼠',
            '束': '鼠',
            '术': '鼠',
            '树': '鼠',
            '数': '鼠',
            '署': '鼠',
            '蜀': '鼠',
            '薯': '鼠',
            '暑': '鼠',
            '书': '鼠',
            '舒': '鼠',
            '梳': '鼠',
            '疏': '鼠',
            '输': '鼠',
            '叔': '鼠',
            '淑': '鼠',
            '孰': '鼠',
            '塾': '鼠',
            '赎': '鼠',
            '秫': '鼠',
            '黍': '鼠',
            '墅': '鼠',
            '庶': '鼠',
            '漱': '鼠',
            '恕': '鼠',
            '戍': '鼠',
            '澍': '鼠',
            '鉥': '鼠',
            '腧': '鼠',

            # 其他同音字和常见错误
            '开属': '开鼠',
            '开述': '开鼠',
            '开束': '开鼠',
            '开术': '开鼠',
            '开树': '开鼠',
            '开数': '开鼠',
            '开署': '开鼠',
            '开蜀': '开鼠',
            '开薯': '开鼠',
            '开暑': '开鼠',
            '开书': '开鼠',
            '开输': '开鼠',
            '开舒': '开鼠',
            '开梳': '开鼠',
            '开疏': '开鼠',
            '开叔': '开鼠',
            '开淑': '开鼠',
            '开塾': '开鼠',
            '开澍': '开鼠',

            # 打属/打鼠相关
            '打属': '打鼠',
            '打述': '打鼠',
            '打束': '打鼠',
            '打术': '打鼠',
            '打树': '打鼠',
            '打数': '打鼠',
            '打署': '打鼠',
            '打蜀': '打鼠',
            '打薯': '打鼠',
            '打暑': '打鼠',
            '打书': '打鼠',
            '打输': '打鼠',

            # 除属/除鼠相关
            '除属': '除鼠',
            '除述': '除鼠',
            '除束': '除鼠',
            '除术': '除鼠',
            '除数': '除鼠',
            '除暑': '除鼠',
            '除书': '除鼠',
            '除输': '除鼠',

            # 驱属/驱鼠相关
            '驱属': '驱鼠',
            '驱述': '驱鼠',
            '驱束': '驱鼠',
            '驱术': '驱鼠',
            '驱暑': '驱鼠',
            '驱书': '驱鼠',
            '驱输': '驱鼠',
        }

        # 进行同音字替换
        corrected_text = text
        for error, correction in rodent_corrections.items():
            if error in corrected_text:
                corrected_text = corrected_text.replace(error, correction)
                self.logger.info(f"🎯 同音字纠正: '{error}' -> '{correction}'，文本: {text} -> {corrected_text}")

        # 特殊处理：如果包含"开"+"属"相关的组合，直接认为是"打开除鼠器"
        # 模式1：开 + 任何字符 + 属（或同音字）
        if re.search(r'开[^鼠]*属', corrected_text):
            corrected_text = '打开除鼠器'
            self.logger.info(f"🎯 模式匹配替换: 检测到'开...属'模式，替换为'打开除鼠器'")

        # 模式2：打开 + 任何字符 + 属（或同音字）
        elif re.search(r'打开[^鼠]*属', corrected_text):
            corrected_text = '打开除鼠器'
            self.logger.info(f"🎯 模式匹配替换: 检测到'打开...属'模式，替换为'打开除鼠器'")

        # 模式3：开 + 任何字符 + 鼠
        elif re.search(r'开[^鼠]*鼠', corrected_text):
            corrected_text = '打开除鼠器'
            self.logger.info(f"🎯 模式匹配替换: 检测到'开...鼠'模式，替换为'打开除鼠器'")

        # 模式4：打 + 任何字符 + 属
        elif re.search(r'打[^鼠]*属', corrected_text):
            corrected_text = '打开除鼠器'
            self.logger.info(f"🎯 模式匹配替换: 检测到'打...属'模式，替换为'打开除鼠器'")

        # 模式5：打 + 任何字符 + 鼠
        elif re.search(r'打[^鼠]*鼠', corrected_text):
            corrected_text = '打开除鼠器'
            self.logger.info(f"🎯 模式匹配替换: 检测到'打...鼠'模式，替换为'打开除鼠器'")

        # 模式6：启动 + 任何字符 + 属
        elif re.search(r'启动[^鼠]*属', corrected_text):
            corrected_text = '打开除鼠器'
            self.logger.info(f"🎯 模式匹配替换: 检测到'启动...属'模式，替换为'打开除鼠器'")

        # 模式7：开启 + 任何字符 + 属
        elif re.search(r'开启[^鼠]*属', corrected_text):
            corrected_text = '打开除鼠器'
            self.logger.info(f"🎯 模式匹配替换: 检测到'开启...属'模式，替换为'打开除鼠器'")

        # 模式8：如果文本以"打开"开头且包含"属"的同音字
        if corrected_text.startswith('打开') and any(char in corrected_text[2:] for char in ['属', '述', '束', '术', '树', '数', '署', '蜀', '薯', '暑', '书']):
            corrected_text = '打开除鼠器'
            self.logger.info(f"🎯 模式匹配替换: '打开'开头且包含'属'的同音字，替换为'打开除鼠器'")

        # 模式9：如果文本以"开"开头且包含"属"的同音字
        if corrected_text.startswith('开') and any(char in corrected_text[1:] for char in ['属', '述', '束', '术', '树', '数', '署', '蜀', '薯', '暑', '书']):
            corrected_text = '打开除鼠器'
            self.logger.info(f"🎯 模式匹配替换: '开'开头且包含'属'的同音字，替换为'打开除鼠器'")

        return corrected_text

    def _is_explicit_device_control(self, text):
        """判断是否为明确的设备控制命令，不需要语义纠正 - 增强版本"""
        if not text:
            return False

        # 明确的设备控制命令模式（包含同音字）
        explicit_patterns = [
            # 打开柜子相关
            r'打开第?[一二两三四五六七八九十\d]+列?柜子',
            r'打开柜子',
            r'开启柜子',
            r'启动柜子',
            # 🔥 新增：支持不完整的打开命令
            r'打开第?[一二两三四五六七八九十\d]+列?',
            r'打开第?[一二两三四五六七八九十\d]+',
            # 关闭柜子相关
            r'关闭第?[一二两三四五六七八九十\d]+列?柜子',
            r'关闭柜子',
            r'关柜子',
            r'关掉柜子',
            # 通风相关
            r'打开通风',
            r'开启通风',
            r'关闭通风',
            r'关通风',
            # 空调相关
            r'打开?空调',
            r'关闭?空调',
            r'空调开机',
            r'空调关机',
            r'空调制冷',
            r'空调制热',
            r'空调除湿',
            r'制冷\d+度',
            r'制热\d+度',
            r'除湿\d+度',
            r'空调调到\d+度',
            r'空调设置为\d+度',
            # 加湿器控制相关 - 扩展
            r'打开?加湿器',
            r'关闭?加湿器',
            r'加湿器开机',
            r'加湿器关机',
            r'开启除湿',
            r'关闭除湿',
            r'开启净化',
            r'关闭净化',
            r'开启加湿',
            r'关闭加湿',
            r'打开一体机',
            r'关闭一体机',
            r'打开温湿度一体机',
            r'关闭温湿度一体机',
            r'打开温度一体机',
            r'关闭温度一体机',
            r'打开湿度一体机',
            r'关闭湿度一体机',
            # 除鼠器控制相关 - 更新
            r'关闭?除鼠器',
            r'除鼠器关闭',
            r'除鼠器低频',
            r'除鼠器高频',
            r'打开除鼠器',
            r'打开除鼠设备',
            r'打开驱鼠设备',
            r'低频模式',
            r'高频模式',
            r'总开关关闭',
            # 同音字版本
            r'关闭?出除数',
            r'关闭?出鼠器',
            r'打开出除数',
            r'打开出鼠器',
            r'打开楚楚',
            r'除鼠设备',
            r'驱鼠设备',
            r'高品模式',
            r'高平模式',
            r'低品模式',
            r'低平模式',
            # 温度调节相关
            r'温度调到[一二两三四五六七八九十\d]+度',
            r'温度设置为[一二两三四五六七八九十\d]+度',
            r'调节温度到[一二两三四五六七八九十\d]+度',
            # 状态查询
            r'查询状态',
            r'查看状态',
            r'状态查询',
            r'状态查看',
        ]

        for pattern in explicit_patterns:
            if re.search(pattern, text):
                return True

        return False


    def _handle_rodent_repeller_control_websocket(self, text, original_text):
        """处理除鼠器控制 - 更宽松的匹配逻辑，识别各种变体表达"""
        try:
            cleaned_text = self._clean_text(text)
            # 增强的同音字处理 - 将各种变体转换为标准词汇
            cleaned_text = self._correct_rodent_repeller_text(cleaned_text)

            self.logger.info(f"🐭 处理除鼠器控制命令: '{text}' -> '{cleaned_text}'")

            # 映射用户命令到除鼠器命令
            command_info = None
            response_text = ""

            # 🔥 关键修改：优先匹配关闭命令
            # 关闭命令 - 匹配各种表达方式
            if any(word in cleaned_text for word in ['关闭', '关', '关掉', '停止', '关毕', '关闭除鼠器', '关除鼠器', '关闭驱鼠', '关驱鼠',
                                                     '关闭除鼠设备', '关闭老鼠器', '关除鼠设备', '关老鼠器']):
                command_info = self.rodent_repeller_commands['关闭']
                response_text = "正在关闭除鼠器"

            # 高频命令 - 只有当明确提到"高频"时才执行
            elif any(word in cleaned_text for word in ['高频', '高频模式', '除鼠器高频', '高品', '高平', '高频率']):
                command_info = self.rodent_repeller_commands['高频']
                response_text = "正在设置除鼠器为高频模式"

            # 低频命令 - 包括"打开除鼠器"等默认情况
            elif any(word in cleaned_text for word in ['低频', '低频模式', '除鼠器低频', '低品', '低平', '低频率']):
                command_info = self.rodent_repeller_commands['低频']
                response_text = "正在设置除鼠器为低频模式"

            # 🔥 如果没有精确匹配，优先处理"打开"相关命令
            if command_info is None:
                # 1. 处理"打开"、"开"等动词（优先级较高）
                if any(word in cleaned_text for word in ['打开除鼠器', '开除鼠器', '开启除鼠器', '启动除鼠器',
                                                         '打开除鼠', '开除鼠', '开启除鼠', '启动除鼠',
                                                         '打开老鼠器', '开老鼠器', '开启老鼠器', '启动老鼠器',
                                                         '打开驱鼠器', '开驱鼠器', '启动驱鼠器']):
                    # 默认打开并设置为低频模式
                    command_info = self.rodent_repeller_commands['低频']
                    response_text = "正在打开除鼠器并设置为低频模式"
                    self.logger.info(f"🎯 动词+设备名识别成功: {cleaned_text}")

                # 2. 🔥 新增：处理包含"属"的同音字模式
                elif any(char in cleaned_text for char in ['属', '述', '束', '术', '树', '数', '署', '蜀', '薯', '暑', '书']) and \
                        any(word in cleaned_text for word in ['打开', '开', '开启', '启动']):
                    # 包含"属"的同音字和打开动作，认为是打开除鼠器
                    command_info = self.rodent_repeller_commands['低频']
                    response_text = "正在打开除鼠器并设置为低频模式"
                    self.logger.info(f"🎯 '属'同音字+动词识别成功: {cleaned_text}")

                # 3. 处理设备名称但没有明确操作的情况
                elif any(word in cleaned_text for word in ['除鼠器', '驱鼠器', '除鼠设备', '驱鼠设备', '老鼠器', '鼠器', '鼠设备']):
                    # 默认打开并设置为低频模式
                    command_info = self.rodent_repeller_commands['低频']
                    response_text = "正在打开除鼠器并设置为低频模式"
                    self.logger.info(f"🎯 设备名识别成功: {cleaned_text}")

                # 4. 处理提到老鼠的情况 - 默认为低频
                elif any(word in cleaned_text for word in ['老鼠', '鼠', '耗子', '大老鼠', '小老鼠']):
                    # 默认打开并设置为低频模式
                    command_info = self.rodent_repeller_commands['低频']
                    response_text = "正在打开除鼠器并设置为低频模式"
                    self.logger.info(f"🎯 鼠类关键词识别成功: {cleaned_text}")

                # 5. 🔥 新增：处理"楚楚"等同音字
                elif '楚楚' in cleaned_text and any(word in cleaned_text for word in ['打开', '开', '开启', '启动']):
                    command_info = self.rodent_repeller_commands['低频']
                    response_text = "正在打开除鼠器并设置为低频模式"
                    self.logger.info(f"🎯 '楚楚'识别成功: {cleaned_text}")

            # 如果仍然没有匹配到命令，返回提示
            if command_info is None:
                response = "请告诉我具体的除鼠器操作，比如：打开除鼠器、关闭除鼠器、低频模式、高频模式"
                return response

            # 发送WebSocket消息 - 严格按照提供的格式
            success = self.send_websocket_message('shu_control', {
                'assetId': self.rodent_repeller_asset_id,
                'command': command_info['command']
            }, original_text)

            if success:
                self.logger.info(f"✅ 除鼠器控制命令发送成功: {command_info} - {response_text}")
                return response_text
            else:
                error_msg = "除鼠器控制命令发送失败，请稍后重试"
                return error_msg

        except Exception as e:
            self.logger.error(f"❌ 除鼠器控制处理失败: {e}")
            error_msg = "处理除鼠器控制时出现错误"
            return error_msg

    def _get_smart_fallback_response(self, user_input):
        """获取智能备用回复"""
        user_input_lower = user_input.lower()

        # 根据用户输入内容提供相关的备用回复
        if any(word in user_input_lower for word in ['笑话', '搞笑', '幽默', '笑']):
            jokes = [
                "为什么档案柜不会说谎？因为它总是有'锁'在身呀！📁",
                "问：什么档案最受欢迎？答：你正在查询的那一份呀~",
                "有一天，档案柜对文件说：'别担心，我会好好保管你的！'",
                "为什么电脑要去医院？因为它有'病毒'了！"
            ]
            return random.choice(jokes)

        elif any(word in user_input_lower for word in ['天气', '温度', '冷', '热']):
            return "小智是档案专家，天气的话建议你看看天气预报哦~ 不过我可以帮你调节室内温度！"

        elif any(word in user_input_lower for word in ['时间', '几点', '日期']):
            current_time = datetime.now().strftime("%Y年%m月%d日 %H点%M分")
            return f"现在是{current_time}，今天也是努力工作的一天呢~"

        elif any(word in user_input_lower for word in ['你好', '您好', 'hello', 'hi']):
            return "哎~ 你好呀！在聊天模式里我们可以畅所欲言哦~"

        elif any(word in user_input_lower for word in ['谢谢', '感谢']):
            return "不客气呀~ 能帮到你小智也很开心！"

        else:
            # 通用的友好回复
            fallbacks = [
                "这个问题很有趣呢~ 小智正在努力学习中！",
                "哎呀，小智对这个问题还不太熟悉，换个话题怎么样？",
                "我们聊点别的吧~ 比如档案管理或者设备控制？",
                "小智还在成长中，这个问题有点难倒我了~",
                "哈哈，这个话题好有意思，不过小智还在学习中呢~"
            ]
            return random.choice(fallbacks)


    # 修改 command_handler.py 中的 _is_archive_query_by_name 方法

    def _is_archive_query_by_name(self, text):
        """判断是否为按名称或编号查询档案命令 - 增强版"""
        if not text:
            return False

        # 使用原始文本（包含空格）进行匹配
        text_with_spaces = text
        cleaned_text = self._clean_text(text)

        self.logger.info(f"🔍 档案查询检测 - 原始文本: '{text}', 清洗后: '{cleaned_text}'")

        # 档案查询模式 - 扩展版本，支持名称和编号查询
        archive_patterns = [
            # 名称查询模式
            r'查\s*(?:询)?\s*(?:一下)?\s*档案名称为\s*(.+?)\s*的\s*(?:档案)?',
            r'查\s*(?:询|找)?\s*(?:一下)?\s*(.+?)\s*的\s*档案',
            r'我\s*(?:想|想要|要)\s*查\s*(?:询|找)?\s*(?:一下)?\s*(.+?)\s*的\s*档案',
            r'查\s*(.+?)\s*的?\s*信息',
            r'查\s*(.+?)\s*的?\s*资料',
            r'找\s*(.+?)\s*的?\s*档案',
            r'搜索\s*(.+?)\s*的?\s*档案',
            r'显示\s*(.+?)\s*的?\s*信息',
            r'显示\s*(.+?)\s*的?\s*档案',
            r'查看\s*(.+?)\s*的?\s*档案',
            r'查询\s*(.+?)\s*的?\s*档案',
            r'查找\s*(.+?)\s*的?\s*档案',

            # 编号查询模式
            r'查\s*(?:询)?\s*(?:一下)?\s*档案编号为\s*(.+?)\s*的\s*(?:档案)?',
            r'查\s*(?:询|找)?\s*(?:一下)?\s*编号\s*(.+?)\s*的\s*档案',
            r'查\s*(?:询|找)?\s*(?:一下)?\s*编号\s*[:：]?\s*(.+?)\s*(?:的档案)?',
            r'编号\s*(.+?)\s*的\s*档案',
            r'编号\s*[:：]?\s*(.+?)\s*的档案',
        ]

        # 尝试匹配各种档案查询模式
        archive_match = None
        for pattern in archive_patterns:
            archive_match = re.search(pattern, text_with_spaces)
            if archive_match:
                self.logger.info(f"✅ 档案查询匹配成功，模式: {pattern}")
                break

        if archive_match:
            query_value = archive_match.group(1).strip()
            self.logger.info(f"📌 提取到查询值: {query_value}")
            return True

        # 扩展匹配模式，支持更多表达方式
        archive_keywords = ['查询', '查找', '搜索', '查一下', '找一下', '查', '显示', '查看']
        info_keywords = ['档案', '信息', '资料', '记录']

        has_archive_keyword = any(keyword in cleaned_text for keyword in archive_keywords)
        has_info_keyword = any(keyword in cleaned_text for keyword in info_keywords)

        # 如果包含查询关键词和信息关键词，则认为是档案查询
        if has_archive_keyword and has_info_keyword:
            # 尝试提取查询值（可能是名称或编号）
            # 先尝试提取编号
            code_match = re.search(r'编号\s*[:：]?\s*(\S+)', cleaned_text)
            if code_match:
                query_value = code_match.group(1).strip()
                if query_value:
                    self.logger.info(f"📌 提取到档案编号: {query_value}")
                    return True

            # 尝试提取档案名称
            name_match = re.search(r'查[询找]?(.+?)(?:的?[档案信息资料])', cleaned_text)
            if name_match:
                name = name_match.group(1).strip()
                if name and len(name) >= 2:  # 至少2个字符
                    self.logger.info(f"📌 提取到档案名称: {name}")
                    return True

        # 简单匹配：包含"查询"和常见档案编号格式
        # 档案编号通常包含字母、数字、横线等
        if '查询' in cleaned_text or '查' in cleaned_text:
            # 尝试匹配常见的编号格式
            # 格式如：2024-001, ABC123, DA-2024-001等
            code_formats = [
                r'[A-Za-z0-9]+[-_][A-Za-z0-9]+',  # 带分隔符的编号
                r'[A-Za-z]{2,}\d+',  # 字母+数字，如DA2024001
                r'\d{4}[-_]\d{3}',  # 年-序号，如2024-001
            ]

            for pattern in code_formats:
                code_match = re.search(pattern, cleaned_text)
                if code_match:
                    code = code_match.group()
                    self.logger.info(f"📌 检测到档案编号格式: {code}")
                    return True

        # 如果文本较短，直接作为查询值
        if has_archive_keyword and len(cleaned_text) <= 15:
            # 移除查询关键词后的文本作为查询值
            for keyword in archive_keywords:
                if keyword in cleaned_text:
                    query_value = cleaned_text.replace(keyword, "").strip()
                    if query_value and len(query_value) >= 2:
                        self.logger.info(f"📌 短文本作为查询值: {query_value}")
                        return True

        return False

    def _handle_archive_query_by_name_websocket(self, text, original_text):
        """处理按名称或编号查询档案 - 只发送查询意图到前端，不查询数据库"""
        try:
            text_with_spaces = original_text  # 使用原始文本进行匹配
            cleaned_text = self._clean_text(text)

            self.logger.info(f"📁 处理档案查询: '{text}' -> '{cleaned_text}'")

            # 提取查询值（可能是名称或编号）
            query_value = self._extract_archive_query_value(text_with_spaces, cleaned_text)

            if not query_value:
                return "请告诉我您要查询什么档案？例如：查询张三的档案，或者查询编号2024-001的档案"

            # 🔥 关键修改：只发送查询意图给前端，不查询数据库
            self.logger.info(f"📤 发送查询意图到前端: {query_value}")

            # 发送WebSocket消息给前端，告知用户正在查询档案
            success = self.send_websocket_message('query_record', {
                'name': query_value
            }, text_with_spaces)

            if success:
                # 🔥🔥🔥 关键修复：正确设置等待选择状态
                self.conversation_state.update({
                    'current_context': 'archive_query',
                    'last_query_type': 'query_record',
                    'last_query_time': datetime.now(),
                    'last_query_params': {
                        'query_value': query_value,
                        'original_text': text_with_spaces
                    },
                    'expecting_selection': True,  # 🔥 设置为True，等待用户选择
                    'last_query_results': []  # 暂时为空，由前端填充
                })

                self.logger.info(f"✅ 设置等待选择状态: {self.conversation_state['expecting_selection']}")

                # 返回友好的响应，提示用户可以选择
                responses = [
                    f"好的，正在为您查询档案信息，请稍后...",
                    f"收到，马上为您查找档案,请稍后...",
                    f"正在查询的档案，请稍等..."
                ]
                response = random.choice(responses)
                return response
            else:
                error_msg = "查询请求发送失败，请稍后重试"
                return error_msg

        except Exception as e:
            self.logger.error(f"❌ 档案查询处理失败: {e}")
            error_msg = "处理查询时出现错误"
            return error_msg

    def _extract_archive_query_value(self, text_with_spaces, cleaned_text):
        """提取档案查询值（名称或编号）- 增强版：处理语音识别错误和口吃"""
        try:
            # 首先尝试匹配明确的编号查询
            code_patterns = [
                r'档案编号为\s*(.+?)\s*的',
                r'编号为\s*(.+?)\s*的档案',
                r'编号\s*(.+?)\s*的档案',
                r'编号\s*[:：]?\s*(.+?)\s*的档案',
                r'查.*?编号\s*[:：]?\s*(.+)',
                # 新增：处理"编号为0567"这种格式
                r'编号为\s*(\w+)\s*档案',
                r'编号\s*为\s*(\w+)',
                r'编号\s*(\w+)',
            ]

            for pattern in code_patterns:
                match = re.search(pattern, text_with_spaces)
                if match:
                    code = match.group(1).strip()
                    if code:
                        # 清理code中的非编号字符
                        # 移除"档案"、"呃"、"干"、"为"等干扰词
                        code = re.sub(r'[档案呃干为。，、]', '', code)

                        # 处理重复部分：查找数字并取最长连续数字
                        # 从code中提取所有数字序列
                        numbers = re.findall(r'\d+', code)
                        if numbers:
                            # 取最长的数字序列
                            longest_number = max(numbers, key=len)
                            self.logger.info(f"📌 模式匹配提取到档案编号: {longest_number}")
                            return longest_number
                        else:
                            # 如果没有数字，直接返回清理后的code
                            self.logger.info(f"📌 模式匹配提取到档案编号: {code}")
                            return code

            # 直接在原始文本中查找连续的数字串
            # 优先查找4位及以上数字（比如0567）
            number_pattern = r'\b(\d{3,})\b'
            number_matches = re.findall(number_pattern, text_with_spaces)

            if number_matches:
                # 选择最长的数字串
                longest_number = max(number_matches, key=len)
                self.logger.info(f"📌 提取到最长数字串作为编号: {longest_number}")
                return longest_number

            # 如果没找到3位以上数字，尝试查找任何数字
            any_number_pattern = r'(\d+)'
            any_number_matches = re.findall(any_number_pattern, text_with_spaces)

            if any_number_matches:
                # 选择最长的数字串
                longest_number = max(any_number_matches, key=len)
                self.logger.info(f"📌 提取到数字作为编号: {longest_number}")
                return longest_number

            # 尝试匹配名称查询
            name_patterns = [
                r'档案名称为\s*(.+?)\s*的',
                r'查\s*(?:询|找)?\s*(?:一下)?\s*(.+?)\s*的\s*档案',
                r'我\s*(?:想|想要|要)\s*查\s*(?:询|找)?\s*(?:一下)?\s*(.+?)\s*的\s*档案',
                r'查\s*(.+?)\s*的?\s*(?:信息|资料|档案)',
            ]

            for pattern in name_patterns:
                match = re.search(pattern, text_with_spaces)
                if match:
                    name = match.group(1).strip()
                    if name:
                        # 清理名字中的干扰词
                        name = re.sub(r'[档案呃干为。，、]', '', name)
                        if name and len(name) >= 2:  # 至少2个字符
                            self.logger.info(f"📌 提取到档案名称: {name}")
                            return name

            # 如果以上都没提取到，尝试从清洗后的文本中提取
            # 移除常见的查询前缀
            query_prefixes = ['查询', '查一下', '查找', '搜索', '查', '找', '编号', '档案编号']
            remaining_text = cleaned_text
            for prefix in query_prefixes:
                if remaining_text.startswith(prefix):
                    remaining_text = remaining_text[len(prefix):]
                    break

            # 移除常见的后缀
            query_suffixes = ['的档案', '档案', '的信息', '的资料', '为', '呃', '干']
            for suffix in query_suffixes:
                if remaining_text.endswith(suffix):
                    remaining_text = remaining_text[:-len(suffix)]

            # 清理空白字符
            remaining_text = remaining_text.strip()

            if remaining_text:
                # 尝试从剩余文本中提取数字
                numbers_in_remaining = re.findall(r'\d+', remaining_text)
                if numbers_in_remaining:
                    longest_number = max(numbers_in_remaining, key=len)
                    self.logger.info(f"📌 从剩余文本中提取数字编号: {longest_number}")
                    return longest_number

                self.logger.info(f"📌 从剩余文本中提取查询值: {remaining_text}")
                return remaining_text

            return None

        except Exception as e:
            self.logger.error(f"❌ 提取档案查询值失败: {e}")
            return None

    def _handle_with_ollama_enhanced(self, text):
        """使用增强的AI处理 - 直接使用AI回复，不进行额外处理"""
        try:
            if not hasattr(self, 'ollama_client') or not self.ollama_client:
                response = "AI服务暂不可用，请检查系统配置"
                # 发送WebSocket消息
                self.send_websocket_message('ai_response', {'response': response}, text)
                return response

            if not self.ollama_client.is_service_available():
                # 提供更具体的错误信息
                response = "AI服务连接失败，请确保Ollama服务正在运行"
                # 发送WebSocket消息
                self.send_websocket_message('ai_response', {'response': response}, text)
                return response

            self.logger.info(f"🚀 增强AI处理: {text}")

            # 直接使用AI处理，不进行语义纠正
            ollama_response = self.ollama_client.send_chat_message(text)

            # 直接使用AI的回复，不进行额外过滤或处理
            if ollama_response:
                self.logger.info(f"✅ AI处理成功: {ollama_response}")
                # 发送WebSocket消息
                self.send_websocket_message('ai_response', {'response': ollama_response}, text)
                return ollama_response
            else:
                # 如果AI回复为空，返回连接错误提示
                response = "AI服务响应异常，请稍后重试或检查服务状态"
                # 发送WebSocket消息
                self.send_websocket_message('ai_response', {'response': response}, text)
                return response

        except Exception as e:
            self.logger.error(f"❌ AI处理异常: {e}")
            response = "处理请求时出现错误，请检查AI服务状态"
            # 发送WebSocket消息
            self.send_websocket_message('ai_response', {'response': response}, text)
            return response

    def _handle_exit_command(self, text, original_text=None):
        """处理退出命令 - 增强版：支持退出聊天模式"""
        self.logger.info(f"🚪 执行退出命令处理: {text}")

        # 如果在聊天模式中，先退出聊天模式
        if self.chat_mode:
            response = self._exit_chat_mode()
            self.is_exited = True

            # 发送WebSocket消息给前端
            if self.socketio:
                self.socketio.emit('conversation_ended', {
                    "message": response,
                    "timestamp": time.time(),
                    "duration": time.time() - (self.chat_start_time if self.chat_start_time else time.time())
                })
                self.logger.info("✅ 已发送conversation_ended消息到前端")

            return response

        self.is_exited = True

        responses = [
            "好的，小智先退下啦，需要的时候随时叫我~",
            "再见啦，有事随时喊小智哦~",
            "小智去休息啦，想我了就说'小智'~",
            "好的，下次见~ 记得叫'小智'唤醒我哦~"
        ]
        response = random.choice(responses)

        # 重置对话状态
        self.reset_conversation_state()

        return response

    def _clean_text(self, text):
        """清洗文本：移除空格、语气词、干扰词和表情符号 - 修复版"""
        if not text:
            return ""

        # 第一步：移除表情符号和特殊符号
        # 匹配常见的表情符号和特殊字符
        cleaned = re.sub(r'[^\w\u4e00-\u9fa5\s]', '', text)

        # 第二步：移除常见的语气词和干扰词
        filler_words = [
            '啊', '呢', '吧', '呀', '哦', '嗯', '那个', '这个', '然后', '就是',
            '啦', '嘛', '哟', '呃', '哎', '喂', '哈', '哼', '哇', '呐'
        ]

        # 移除语气词
        for word in filler_words:
            cleaned = cleaned.replace(word, "")

        # 第三步：修正常见的语音识别错误 - 增强设备控制相关修正
        common_errors = {
            '相子': '柜子',
            '箱子': '柜子',
            '贵子': '柜子',
            '柜了': '柜子',
            '柜勒': '柜子',
            '柜啦': '柜子',
            '关毕': '关闭',
            '完毕': '关闭',
            '关掉': '关闭',
            '打开': '打开',
            '开启': '打开',
            '关闭': '关闭',
            '停止': '关闭',
            '类': '列',
        }

        # 关键修复：先修正常见错误，再处理空格
        for error, correction in common_errors.items():
            cleaned = cleaned.replace(error, correction)

        # 第四步：移除所有空格
        cleaned = re.sub(r'\s+', '', cleaned).strip()

        # 记录清洗前后的文本
        if text != cleaned:
            self.logger.info(f"🧹 文本清洗: '{text}' -> '{cleaned}'")

        return cleaned

    def _handle_device_control_websocket(self, text, original_text):
        """处理设备控制命令 - 严格按照app.py的WebSocket格式"""
        try:
            text_lower = text.lower()
            self.logger.info(f"🔧 处理设备控制命令: {text}")

            # 处理单独的"打开"或"关闭"命令
            if text in ['打开', '开启', '启动']:
                response = "哎~ 您想打开什么设备呢？可以说打开加湿器，打开空调，打开第几列柜子，或者打开通风系统~"
                self.send_websocket_message('ai_response', {'response': response}, original_text)
                return response
            elif text in ['关闭', '关', '关掉', '停止']:
                response = "哎~ 您想关闭什么设备呢？可以说关闭加湿器，关闭空调，关闭第几列柜子，或者关闭通风系统~"
                self.send_websocket_message('ai_response', {'response': response}, original_text)
                return response

            # 加湿器控制 - 优先处理
            elif any(word in text_lower for word in ['加湿器', '除湿', '净化', '加湿']):
                self.logger.info("💧 识别为加湿器控制命令")
                return self._handle_dehumidifier_control_websocket(text, original_text)

            # 空调控制
            elif any(word in text_lower for word in ['空调', '制冷', '制热']):
                self.logger.info("❄️ 识别为空调控制命令")
                return self._handle_air_conditioner_control_websocket(text, original_text)

            # 除鼠器控制 - 新增
            elif any(word in text_lower for word in ['除鼠器', '驱鼠器', '除鼠', '驱鼠', '老鼠']):
                self.logger.info("🐭 识别为除鼠器控制命令")
                return self._handle_rodent_repeller_control_websocket(text, original_text)

            # 温湿度控制
            temperature_keywords = ['温度', '湿度', '调节', '设置', '度', '调到', '调制', '调至']
            if any(word in text_lower for word in temperature_keywords):
                self.logger.info("🌡️ 识别为温湿度控制命令")
                return self._handle_temperature_control_websocket(text, original_text)

            # 通风控制
            elif any(word in text_lower for word in ['通风', '换气']):
                self.logger.info("💨 识别为通风控制命令")
                return self._handle_ventilation_control_websocket(text, original_text)

            # 档案柜控制 - 更精确的匹配
            cabinet_keywords = ['柜子', '档案柜', '相子', '箱子', '贵子', '柜了']
            has_cabinet_keyword = any(word in text for word in cabinet_keywords)

            # 只有当明确提到柜子相关词汇时才认为是档案柜控制
            if has_cabinet_keyword:
                self.logger.info("📁 识别为档案柜控制命令")
                return self._handle_cabinet_control_websocket(text, original_text)

            # 或者包含列号的操作（如"打开第三列"）
            elif any(word in text for word in ['第', '列']) and any(word in text for word in ['打开', '关闭', '开', '关']):
                self.logger.info("📁 识别为带列号的柜子控制命令")
                return self._handle_cabinet_control_websocket(text, original_text)

            # 状态查询
            elif any(word in text_lower for word in ['状态', '查看', '监控']):
                self.logger.info("📊 识别为状态查询命令")
                return self._handle_status_query_websocket(text, original_text)

            # 默认使用AI处理
            else:
                self.logger.info("🤖 未明确匹配设备类型，使用AI处理")
                return self._handle_with_ollama_directly(text)

        except Exception as e:
            self.logger.error(f"❌ 设备控制处理失败: {e}")
            error_msg = "处理设备控制时出现错误"
            return error_msg

    def _handle_dehumidifier_control_websocket(self, text, original_text):
        """处理加湿器控制 - 严格按照提供的格式"""
        try:
            cleaned_text = self._clean_text(text)
            text_lower = cleaned_text.lower()

            self.logger.info(f"💧 处理加湿器控制命令: '{text}' -> '{cleaned_text}'")

            # 映射用户命令到加湿器命令
            command_info = None
            response_text = ""

            # 开机命令
            if any(word in cleaned_text for word in ['开机', '打开加湿器', '启动加湿器']):
                command_info = self.dehumidifier_commands['开机']
                response_text = "正在为您打开加湿器"

            # 关机命令
            elif any(word in cleaned_text for word in ['关机', '关闭加湿器', '关加湿器']):
                command_info = self.dehumidifier_commands['关机']
                response_text = "正在为您关闭加湿器"

            # 除湿命令
            elif '除湿' in cleaned_text:
                command_info = self.dehumidifier_commands['除湿']
                response_text = "正在开启除湿功能"

            # 净化命令
            elif '净化' in cleaned_text:
                command_info = self.dehumidifier_commands['净化']
                response_text = "正在开启净化功能"

            # 加湿命令
            elif '加湿' in cleaned_text:
                command_info = self.dehumidifier_commands['加湿']
                response_text = "正在开启加湿功能"

            # 如果没有精确匹配，尝试智能匹配
            if command_info is None:
                if any(word in cleaned_text for word in ['打开', '开启', '启动']):
                    # 默认开机
                    command_info = self.dehumidifier_commands['开机']
                    response_text = "正在为您打开加湿器"
                elif any(word in cleaned_text for word in ['关闭', '关', '关掉']):
                    # 默认关机
                    command_info = self.dehumidifier_commands['关机']
                    response_text = "正在为您关闭加湿器"

            # 如果仍然没有匹配到命令，返回提示
            if command_info is None:
                response = "请告诉我具体的加湿器操作，比如：打开加湿器、关闭加湿器、除湿、净化、加湿等"
                return response

            # 发送WebSocket消息 - 严格按照提供的格式
            success = self.send_websocket_message('dehumidifier_control', {
                'assetId': self.dehumidifier_asset_id,
                'command': command_info['command'],
                'port': self.dehumidifier_port,
                'switchOnOrOff': command_info['switchOnOrOff']
            }, original_text)

            if success:
                self.logger.info(f"✅ 加湿器控制命令发送成功: {command_info} - {response_text}")
                return response_text
            else:
                error_msg = "加湿器控制命令发送失败，请稍后重试"
                return error_msg

        except Exception as e:
            self.logger.error(f"❌ 加湿器控制处理失败: {e}")
            error_msg = "处理加湿器控制时出现错误"
            return error_msg

    def _handle_air_conditioner_control_websocket(self, text, original_text):
        """处理空调控制 - 严格按照提供的格式"""
        try:
            cleaned_text = self._clean_text(text)
            text_lower = cleaned_text.lower()

            self.logger.info(f"❄️ 处理空调控制命令: '{text}' -> '{cleaned_text}'")

            # 映射用户命令到空调命令
            command = None
            response_text = ""

            # 开机命令
            if any(word in cleaned_text for word in ['开机', '打开空调', '启动空调']):
                command = 0
                response_text = "正在为您打开空调"

            # 关机命令
            elif any(word in cleaned_text for word in ['关机', '关闭空调', '关空调']):
                command = 1
                response_text = "正在为您关闭空调"

            # 制冷命令
            elif '制冷18' in cleaned_text or '制冷18度' in cleaned_text:
                command = 2
                response_text = "正在设置空调为制冷18度"
            elif '制冷20' in cleaned_text or '制冷20度' in cleaned_text:
                command = 3
                response_text = "正在设置空调为制冷20度"
            elif '制冷22' in cleaned_text or '制冷22度' in cleaned_text:
                command = 4
                response_text = "正在设置空调为制冷22度"

            # 除湿命令
            elif '除湿25' in cleaned_text or '除湿25度' in cleaned_text:
                command = 5
                response_text = "正在设置空调为除湿25度"

            # 制热命令
            elif '制热20' in cleaned_text or '制热20度' in cleaned_text:
                command = 6
                response_text = "正在设置空调为制热20度"
            elif '制热22' in cleaned_text or '制热22度' in cleaned_text:
                command = 7
                response_text = "正在设置空调为制热22度"
            elif '制热24' in cleaned_text or '制热24度' in cleaned_text:
                command = 8
                response_text = "正在设置空调为制热24度"

            # 如果没有精确匹配，尝试智能匹配
            if command is None:
                if '制冷' in cleaned_text:
                    # 默认制冷22度
                    command = 4
                    response_text = "正在设置空调为制冷22度"
                elif '制热' in cleaned_text:
                    # 默认制热22度
                    command = 7
                    response_text = "正在设置空调为制热22度"
                elif '除湿' in cleaned_text:
                    # 默认除湿25度
                    command = 5
                    response_text = "正在设置空调为除湿25度"
                elif any(word in cleaned_text for word in ['打开', '开启', '启动']):
                    # 默认开机
                    command = 0
                    response_text = "正在为您打开空调"
                elif any(word in cleaned_text for word in ['关闭', '关', '关掉']):
                    # 默认关机
                    command = 1
                    response_text = "正在为您关闭空调"

            # 如果仍然没有匹配到命令，返回提示
            if command is None:
                response = "请告诉我具体的空调操作，比如：打开空调、关闭空调、制冷22度、制热24度等"
                return response

            # 发送WebSocket消息 - 严格按照提供的格式
            success = self.send_websocket_message('air_control', {
                'assetId': self.air_conditioner_asset_id,
                'command': command,
                'port': self.air_conditioner_port
            }, original_text)

            if success:
                self.logger.info(f"✅ 空调控制命令发送成功: {command} - {response_text}")
                return response_text
            else:
                error_msg = "空调控制命令发送失败，请稍后重试"
                return error_msg

        except Exception as e:
            self.logger.error(f"❌ 空调控制处理失败: {e}")
            error_msg = "处理空调控制时出现错误"
            return error_msg


    def _handle_temperature_control_websocket(self, text, original_text):
        """处理温湿度控制 - 严格按照app.py格式"""
        try:
            text_lower = text.lower()

            # 提取温度值
            temperature = self._extract_temperature(text)

            # 判断是升温还是降温
            if '提高' in text_lower or '升温' in text_lower or '调高' in text_lower or '热' in text_lower:
                action = "increase"
                if not temperature:
                    # 如果没有指定温度，询问要升高多少度
                    self.conversation_state.update({
                        'waiting_for_temperature': True,
                        'pending_action': 'increase',
                        'pending_context': 'temperature'
                    })
                    response = "请问您希望升高多少度呢？可以说数字或中文数字，比如：5度、五度"
                    return response
            elif '降低' in text_lower or '降温' in text_lower or '调低' in text_lower or '冷' in text_lower:
                action = "decrease"
                if not temperature:
                    # 如果没有指定温度，询问要降低多少度
                    self.conversation_state.update({
                        'waiting_for_temperature': True,
                        'pending_action': 'decrease',
                        'pending_context': 'temperature'
                    })
                    response = "请问您希望降低多少度呢？可以说数字或中文数字，比如：5度、五度"
                    return response
            else:
                action = "set"
                if not temperature:
                    # 如果没有指定温度，询问具体温度
                    self.conversation_state.update({
                        'waiting_for_temperature': True,
                        'pending_action': 'set',
                        'pending_context': 'temperature'
                    })
                    response = "请问您要调节到多少度呢？可以说数字或中文数字，比如：25度、二十五度"
                    return response

            # 如果已经有温度值，直接执行
            if temperature:
                # 发送WebSocket消息 - 严格按照app.py格式
                success = self.send_websocket_message('control_thermo_hygro_sensor', {
                    'action': action,
                    'temperature': temperature
                }, original_text)
                if success:
                    action_text = {
                        'increase': '升高温度',
                        'decrease': '降低温度',
                        'set': '调节温度到'
                    }.get(action, '调节温度到')

                    # 更智能友好的回复
                    if action == 'set':
                        response = f"好的，正在为您{action_text}{temperature}度"
                    else:
                        response = f"好的，正在为您{action_text}{temperature}度"

                    return response
                else:
                    return "温湿度控制命令发送失败"

        except Exception as e:
            print(f"❌ 温湿度控制处理失败: {e}")
            return "处理温湿度控制时出现错误"

    def _handle_ventilation_control_websocket(self, text, original_text):
        """处理通风控制 - 严格按照app.py格式"""
        try:
            # 判断动作
            if any(word in text for word in ['打开', '开启', '启动']):
                action = "on"
                action_text = "开启通风系统"
            elif any(word in text for word in ['关闭', '停止']):
                action = "off"
                action_text = "关闭通风系统"
            else:
                action = "toggle"
                action_text = "调节通风系统"

            # 发送WebSocket消息 - 严格按照app.py格式
            success = self.send_websocket_message('control_air_conditioner', {
                'action': action
            }, original_text)
            if success:
                # 更智能友好的回复
                response = f"好的，正在为您{action_text}"
                return response
            else:
                return "通风控制命令发送失败"
        except Exception as e:
            print(f"❌ 通风控制处理失败: {e}")
            return "处理通风控制时出现错误"

    def _handle_status_query_websocket(self, text, original_text):
        """处理状态查询 - 严格按照app.py格式"""
        try:
            # 发送WebSocket消息 - 严格按照app.py格式
            success = self.send_websocket_message('query_cabinet_status', {
                'command': text
            }, original_text)
            if success:
                response = "好的，正在为您查询设备状态，请稍候"
                return response
            else:
                return "状态查询命令发送失败"
        except Exception as e:
            print(f"❌ 状态查询处理失败: {e}")
            return "处理状态查询时出现错误"

    def _handle_cabinet_control_websocket(self, text, original_text):
        """处理档案柜控制 - 严格按照app.py格式"""
        try:
            text_lower = text.lower()
            self.logger.info(f"📁 处理档案柜控制: '{text}'")

            # 提取动作（关闭命令优先）
            close_keywords = ['关闭', '关', '关掉', '关上', '关毕', '完毕']
            has_close = any(keyword in text_lower for keyword in close_keywords)
            action = 'close' if has_close else 'open'
            action_text = "关闭" if action == 'close' else "打开"

            # 严格按照app.py逻辑：关闭命令不需要列号，直接关闭所有柜子
            if action == 'close':
                # 发送关闭命令 - 严格按照app.py格式
                success = self.send_websocket_message('close_cabinet', {
                    'action': 'off'  # 使用'action'参数，值为'off'
                }, original_text)
                if success:
                    response = "好的，正在为您关闭所有档案柜"
                    return response
                else:
                    error_msg = "关闭命令发送失败，请稍后重试"
                    return error_msg

            # 打开命令需要列号
            column_number = self._extract_column_number(text)
            self.logger.info(f"🔢 提取列号结果: {column_number}")

            if not column_number:
                self.logger.info("❓ 打开命令未指定列号，询问用户")
                self.conversation_state.update({
                    'waiting_for_column': True,
                    'pending_action': action,
                    'pending_context': 'cabinet_control'
                })
                response = "请问您要打开哪一列柜子？例如：第三列、3列"
                return response

            # 有列号时执行打开控制
            success = self.send_websocket_message('open_cabinet', {
                'colNo': column_number  # 使用'colNo'参数与app.py一致
            }, original_text)

            # 修复：添加响应返回
            if success:
                response = f"好的，正在为您打开第{column_number}列柜子"
                return response
            else:
                error_msg = "打开命令发送失败，请稍后重试"
                return error_msg

        except Exception as e:
            self.logger.error(f"❌ 档案柜控制失败: {e}")
            error_msg = "处理柜子控制时出现错误"
            return error_msg

    def _extract_temperature(self, text):
        """提取温度值 - 支持中文数字和阿拉伯数字"""
        try:
            # 中文数字到阿拉伯数字的映射
            chinese_number_map = {
                '零': '0', '一': '1', '二': '2', '两': '2', '三': '3', '四': '4', '五': '5',
                '六': '6', '七': '7', '八': '8', '九': '9', '十': '10',
                '十一': '11', '十二': '12', '十三': '13', '十四': '14', '十五': '15',
                '十六': '16', '十七': '17', '十八': '18', '十九': '19', '二十': '20',
                '二十一': '21', '二十二': '22', '二十三': '23', '二十四': '24', '二十五': '25',
                '二十六': '26', '二十七': '27', '二十八': '28', '二十九': '29', '三十': '30'
            }

            # 匹配模式：支持中文数字和阿拉伯数字
            patterns = [
                r'(\d+)度',           # 25度
                r'(\d+)摄氏度',        # 25摄氏度
                r'(\d+)°',            # 25°
                r'([零一二两三四五六七八九十]+)度',      # 二十五度
                r'([零一二两三四五六七八九十]+)摄氏度',   # 二十五摄氏度
                r'([零一二两三四五六七八九十]+)°'        # 二十五°
            ]

            for pattern in patterns:
                match = re.search(pattern, text)
                if match:
                    number_str = match.group(1)

                    # 如果是中文数字，转换为阿拉伯数字
                    if number_str in chinese_number_map:
                        temperature = chinese_number_map[number_str]
                        self.logger.info(f"✅ 中文数字转换: {number_str} -> {temperature}")
                        return temperature
                    elif number_str.isdigit():
                        self.logger.info(f"✅ 提取到温度: {number_str}")
                        return number_str

            # 如果没有匹配到模式，尝试直接提取数字
            digit_match = re.search(r'[零一二两三四五六七八九十\d]+', text)
            if digit_match:
                number_str = digit_match.group()
                if number_str in chinese_number_map:
                    temperature = chinese_number_map[number_str]
                    self.logger.info(f"✅ 宽松模式中文数字转换: {number_str} -> {temperature}")
                    return temperature
                elif number_str.isdigit():
                    self.logger.info(f"✅ 宽松模式提取到温度: {number_str}")
                    return number_str

            return None

        except Exception as e:
            self.logger.error(f"提取温度失败: {e}")
            return None

    def _handle_column_input(self, text, original_text):
        """处理列号输入 - 严格按照app.py格式"""
        try:
            self.logger.info(f"🔍 处理列号输入，原始文本: {text}")

            # 获取待处理的动作
            action = self.conversation_state.get('pending_action', 'open')  # 默认打开

            # 如果是关闭命令，不需要列号，直接关闭所有柜子
            if action == 'close':
                # 重置状态
                self.conversation_state.update({
                    'waiting_for_column': False,
                    'pending_action': None,
                    'pending_context': None
                })
                # 关闭所有柜子 - 严格按照app.py格式
                success = self.send_websocket_message('close_cabinet', {
                    'action': 'off'
                }, original_text)
                if success:
                    response = "好的，正在为您关闭所有档案柜"
                    return response
                else:
                    return "关闭命令发送失败"

            # 打开命令需要列号
            column_number = self._extract_column_number(text)
            self.logger.info(f"🔍 提取到的列号: {column_number}")

            if column_number:
                # 重置状态
                self.conversation_state.update({
                    'waiting_for_column': False,
                    'pending_action': None,
                    'pending_context': None
                })
                # 发送打开消息 - 严格按照app.py格式
                success = self.send_websocket_message('open_cabinet', {
                    'colNo': column_number  # 使用'colNo'参数
                }, original_text)
            else:
                # 如果没有提取到列号，继续询问（不重置状态）
                self.logger.warning(f"❌ 未提取到列号，文本: {text}")
                response = "抱歉，我没有听清楚列号。请告诉我您要打开哪一列柜子？例如：第三列、3列"
                return response

        except Exception as e:
            self.logger.error(f"❌ 列号输入处理失败: {e}")
            # 异常时才重置状态
            self.conversation_state.update({
                'waiting_for_column': False,
                'pending_action': None,
                'pending_context': None
            })
            return "处理柜子控制时出现错误"

    def _extract_column_number(self, text):
        """提取列号信息 - 智能语义理解版"""
        try:
            # 首先处理常见的错别字和同音字
            text = text.replace("相子", "柜子").replace("箱子", "柜子").replace("贵子", "柜子")
            text = text.replace("类", "列").replace("号", "列").replace("个", "列")  # 增强容错

            # 中文数字到阿拉伯数字的映射 - 扩展版本
            chinese_to_digit = {
                '零': '0', '一': '1', '二': '2', '两': '2', '三': '3', '四': '4',
                '五': '5', '六': '6', '七': '7', '八': '8', '九': '9', '十': '10',
                '十一': '11', '十二': '12', '十三': '13', '十四': '14', '十五': '15',
                '十六': '16', '十七': '17', '十八': '18', '十九': '19', '二十': '20',
                '二十一': '21', '二十二': '22', '二十三': '23', '二十四': '24', '二十五': '25',
                '二十六': '26', '二十七': '27', '二十八': '28', '二十九': '29', '三十': '30'
            }

            # 增强匹配模式：支持多种表达方式
            patterns = [
                # 标准模式
                r'第([一二两三四五六七八九十]+)[列柜]',
                r'([一二两三四五六七八九十]+)[列柜]',
                r'第(\d+)[列柜]',
                r'(\d+)[列柜]',
                # 容错模式
                r'第([一二两三四五六七八九十]+)类',
                r'([一二两三四五六七八九十]+)类',
                r'第([一二两三四五六七八九十]+)号',
                r'([一二两三四五六七八九十]+)号',
                r'第([一二两三四五六七八九十]+)个',
                r'([一二两三四五六七八九十]+)个',
                # 动作+数字模式
                r'打开([一二两三四五六七八九十]+)',
                r'打开(\d+)',
                r'开([一二两三四五六七八九十]+)',
                r'开(\d+)',
                r'关闭([一二两三四五六七八九十]+)',
                r'关闭(\d+)',
                r'关([一二两三四五六七八九十]+)',
                r'关(\d+)',
                # 纯数字模式
                r'第([一二两三四五六七八九十]+)',
                r'第(\d+)',
            ]

            column_found = None
            for pattern in patterns:
                col_match = re.search(pattern, text)
                if col_match:
                    number_str = col_match.group(1)
                    # 如果是中文数字，转换为阿拉伯数字
                    if number_str in chinese_to_digit:
                        column_found = chinese_to_digit[number_str]
                    elif number_str.isdigit():
                        column_found = number_str

                    if column_found:
                        self.logger.info(f"✅ 提取到列号: {column_found}，匹配模式: {pattern}")
                        break

            # 如果没找到，尝试更宽松的匹配
            if not column_found:
                # 直接匹配数字
                digit_match = re.search(r'[一二两三四五六七八九十\d]+', text)
                if digit_match:
                    number_str = digit_match.group()
                    if number_str in chinese_to_digit:
                        column_found = chinese_to_digit[number_str]
                    elif number_str.isdigit():
                        column_found = number_str
                    if column_found:
                        self.logger.info(f"✅ 宽松模式提取到列号: {column_found}")

            # 调试信息：记录提取过程
            self.logger.info(f"🔍 列号提取过程: 原始文本='{text}', 提取结果='{column_found}'")

            return column_found

        except Exception as e:
            self.logger.error(f"提取列号失败: {e}")
            return None

    def _handle_selection(self, text, original_text):
        """处理用户选择 - 增强版本：支持更多表达方式"""
        try:
            # 记录详细的调试信息
            self.logger.info(f"🎯 开始处理选择命令: '{text}' (原始: '{original_text}')")

            # 提取选择序号
            selection_index = self._extract_selection_index(text)

            self.logger.info(f"🔢 提取到的选择序号: {selection_index}")

            if selection_index is None:
                # 🔥 关键修复：如果无法提取选择序号，重置选择状态
                self.conversation_state['expecting_selection'] = False
                self.logger.warning("❌ 无法提取选择序号，已重置选择状态")

                # 尝试更宽松的匹配
                if '二' in text or '两' in text:
                    selection_index = 2
                elif '三' in text:
                    selection_index = 3
                elif '四' in text:
                    selection_index = 4
                elif '五' in text:
                    selection_index = 5
                elif '六' in text:
                    selection_index = 6
                elif '七' in text:
                    selection_index = 7
                elif '八' in text:
                    selection_index = 8
                elif '九' in text:
                    selection_index = 9
                elif '十' in text:
                    selection_index = 10
                elif '第一条' in text or '第一个' in text or '首选' in text:
                    selection_index = 1

            if selection_index is None:
                # 如果还是无法提取，询问用户并重置状态
                self.logger.warning("❌ 无法提取选择序号，重置选择状态")
                self.conversation_state['expecting_selection'] = False
                return "请告诉我您要选择第几条？例如：第一条、第二个，或者直接说数字"

            # 发送选择消息给前端 - 严格按照app.py格式
            self.logger.info(f"📤 发送选择消息到前端: index={selection_index-1}")

            success = self.send_websocket_message('select_record', {
                'index': selection_index - 1  # 转为0基索引
            }, original_text)

            if success:
                # 重置选择状态
                self.conversation_state['expecting_selection'] = False
                self.conversation_state['available_options'] = []

                # 友好的响应
                response = f"好的，已选择第{selection_index}条记录"
                self.logger.info(f"✅ 选择处理成功: {response}")
                return response
            else:
                error_msg = "选择命令发送失败，请稍后重试"
                self.logger.error(f"❌ {error_msg}")
                return error_msg

        except Exception as e:
            self.logger.error(f"❌ 选择处理失败: {e}", exc_info=True)
            error_msg = "处理选择时出现错误"
            return error_msg

    def _extract_selection_index(self, text):
        """提取选择序号"""
        try:
            # 中文数字映射
            chinese_numbers = {
                '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
                '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
                '第一': 1, '第二': 2, '第三': 3, '第四': 4, '第五': 5,
                '第六': 6, '第七': 7, '第八': 8, '第九': 9, '第十': 10,
                '十一': 11, '十二': 12, '十三': 13, '十四': 14, '十五': 15,
                '十六': 16, '十七': 17, '十八': 18, '十九': 19, '二十': 20
            }
            # 匹配模式
            patterns = [
                r'第([一二三四五六七八九十]+)条',
                r'第([一二三四五六七八九十]+)个',
                r'([一二三四五六七八九十]+)条',
                r'([一二三四五六七八九十]+)个',
                r'选择第([一二三四五六七八九十]+)条',
                r'选择第([一二三四五六七八九十]+)个',
                r'第(\d+)条',
                r'第(\d+)个',
                r'选择第(\d+)条',
                r'选择第(\d+)个',
                r'(\d+)条',
                r'(\d+)个'
            ]
            for pattern in patterns:
                match = re.search(pattern, text)
                if match:
                    number_str = match.group(1)
                    # 中文数字转换
                    if number_str in chinese_numbers:
                        return chinese_numbers[number_str]
                    elif number_str.isdigit():
                        return int(number_str)
            # 简单匹配
            if '第一条' in text or '第一个' in text or '首选' in text or '第一个' in text:
                return 1
            elif '第二条' in text or '第二个' in text:
                return 2
            elif '第三条' in text or '第三个' in text:
                return 3
            elif '第四条' in text or '第四个' in text:
                return 4
            elif '第五条' in text or '第五个' in text:
                return 5
            return None
        except Exception as e:
            print(f"❌ 提取选择序号失败: {e}")
            return None


    def reset_conversation_state(self):
        """重置对话状态"""
        self.conversation_state = {
            'current_context': None,
            'last_query_type': None,
            'last_query_results': [],
            'expecting_selection': False,
            'available_options': [],
            'last_query_params': {},
            'waiting_for_temperature': False,
            'waiting_for_column': False,  # 新增：等待列号输入
            'pending_action': None,
            'pending_context': None
        }


    def _init_jieba(self):
        """初始化jieba分词，添加自定义词汇"""
        # 添加常见人名到词典
        common_names = ['张三', '李四', '王五', '赵六', '钱七', '孙八', '周九', '吴十']
        for name in common_names:
            jieba.add_word(name, freq=1000, tag='nr')
            # 添加除鼠器控制词汇 - 更新（包括同音字）
        rodent_repeller_words = [
            '除鼠器', '驱鼠器', '老鼠', '驱鼠', '低频', '高频', '总开关关闭',
            '关闭除鼠器', '除鼠器关闭', '除鼠器低频', '除鼠器高频',
            # 同音字词汇 - 大幅扩展
            '出除数', '出鼠器', '储鼠器', '出鼠', '除鼠设备', '驱鼠设备',
            '鼠器', '鼠设备', '老鼠器', '大老鼠器', '小老鼠器', '耗子器',
            '打开楚楚', '楚楚器', '楚楚',  # 新增：楚楚相关
            '打鼠器', '灭鼠器', '防鼠器', '抗鼠器',
            '树器', '数器', '开树器', '开数器',
            '开老鼠', '开大老鼠', '开小老鼠', '开耗子',
            '开鼠', '打鼠', '开树', '打树', '开数', '打数',
            # 属的同音字系列
            '属', '述', '束', '术', '树', '数', '署', '蜀', '薯', '暑', '书', '舒',
            '开属', '开述', '开束', '开术', '开树', '开数', '开署', '开蜀', '开薯', '开暑', '开书',
            '打属', '打述', '打束', '打术', '打树', '打数', '打署', '打蜀', '打薯', '打暑', '打书',
            '除属', '除述', '除束', '除数', '除暑', '除书',
            '驱属', '驱述', '驱束', '驱暑', '驱书'
        ]
        for word in rodent_repeller_words:
            jieba.add_word(word, freq=1000, tag='n')
        # 添加唤醒词
        for wake_word in WAKE_WORDS:
            jieba.add_word(wake_word, freq=2000, tag='n')
        # 添加命令关键词
        command_words = ['查询', '查找', '搜索', '显示', '列出', '查一下', '找一下']
        for cmd in command_words:
            jieba.add_word(cmd, freq=1500, tag='v')
        # 添加时间相关词汇
        time_words = ['时间', '几点', '现在', '日期', '今天', '钟点', '什么时候']
        for time_word in time_words:
            jieba.add_word(time_word, freq=1000, tag='n')
        # 添加年份相关词汇
        year_words = ['年', '年份', '年度', '哪年', '什么时候入职']
        for year_word in year_words:
            jieba.add_word(year_word, freq=800, tag='n')
        # 添加档案柜控制词汇
        cabinet_words = ['打开', '关闭', '开启', '启动', '停止', '档案柜', '柜子', '列']
        for cabinet_word in cabinet_words:
            jieba.add_word(cabinet_word, freq=1000, tag='v')
        # 添加基础对话词汇
        basic_conversation = ['你叫什么', '你是谁', '你几岁', '你多大', '介绍自己', '自我介绍']
        for word in basic_conversation:
            jieba.add_word(word, freq=1000, tag='n')
        # 添加中文数字词汇
        chinese_numbers = ['一', '二', '两', '三', '四', '五', '六', '七', '八', '九', '十',
                           '十一', '十二', '十三', '十四', '十五', '十六', '十七', '十八', '十九', '二十']
        for num in chinese_numbers:
            jieba.add_word(num, freq=800, tag='m')

        temperature_words = ['度', '摄氏度', '温度', '升温', '降温', '调高', '调低']
        for word in temperature_words:
            jieba.add_word(word, freq=800, tag='n')

        # 添加中文数字
        chinese_numbers_extended = [
            '零', '一', '二', '两', '三', '四', '五', '六', '七', '八', '九', '十',
            '十一', '十二', '十三', '十四', '十五', '十六', '十七', '十八', '十九', '二十',
            '二十一', '二十二', '二十三', '二十四', '二十五', '二十六', '二十七', '二十八', '二十九', '三十'
        ]
        for num in chinese_numbers_extended:
            jieba.add_word(num, freq=800, tag='m')

        # 添加空调控制词汇
        air_conditioner_words = [
            '空调', '制冷', '制热', '除湿', '开机', '关机',
            '制冷18度', '制冷20度', '制冷22度',
            '制热20度', '制热22度', '制热24度',
            '除湿25度'
        ]
        for word in air_conditioner_words:
            jieba.add_word(word, freq=1000, tag='n')

        # 添加加湿器控制词汇 - 扩展
        dehumidifier_words = [
            '加湿器', '除湿', '净化', '加湿',
            '打开加湿器', '关闭加湿器', '加湿器开机', '加湿器关机',
            '一体机', '温湿度一体机', '湿度一体机', '温度一体机',
            '打开一体机', '关闭一体机', '打开温湿度一体机', '关闭温湿度一体机'
        ]
        for word in dehumidifier_words:
            jieba.add_word(word, freq=1000, tag='n')

    def _is_pure_wakeup_call(self, text):
        """判断是否为纯唤醒呼叫 - 正则表达式简化版"""
        if not text:
            return False

        # 定义打招呼词语和"小智"的同音字
        greeting_words = ['你好', '您好', '嗨', '嘿', '喂', '哈喽', 'hello', 'hi']
        xiaozhi_variants = ['小智', '小知', '小之', '小志', '小只', '小指', '小枝', '小纸', '小直', '小稚']

        # 构建正则表达式模式
        # 匹配：打招呼词 + 0或多个任意字符 + "小智"同音字
        # 或者："小智"同音字 + 0或多个任意字符 + 打招呼词
        greeting_pattern = '|'.join(greeting_words)
        xiaozhi_pattern = '|'.join(xiaozhi_variants)

        # 构建完整的正则表达式
        pattern = f'({greeting_pattern}).*?({xiaozhi_pattern})|({xiaozhi_pattern}).*?({greeting_pattern})'

        # 使用正则表达式匹配（使用参数text而不是未定义的cleaned_text）
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            self.logger.info(f"🎯 正则匹配到纯唤醒词: '{text}' -> 匹配组: {match.groups()}")
            return True

        # 保留原有的短文本检查作为备用
        if len(text) <= 4:
            wake_indicators = xiaozhi_variants + greeting_words
            for indicator in wake_indicators:
                if indicator in text:
                    self.logger.info(f"🎯 短文本检测到唤醒词特征: '{indicator}' 在 '{text}' 中")
                    return True

        self.logger.info(f"❌ 不是纯唤醒词: '{text}'")
        return False


    def _get_greeting_response(self):
        """小爱风格问候回复 - 增强版本"""
        import random

        # 获取当前时间
        current_hour = datetime.now().hour

        # 根据时间段选择不同的问候语
        if 5 <= current_hour < 12:
            time_greeting = "早上好"
        elif 12 <= current_hour < 14:
            time_greeting = "中午好"
        elif 14 <= current_hour < 18:
            time_greeting = "下午好"
        elif 18 <= current_hour < 22:
            time_greeting = "晚上好"
        else:
            time_greeting = "你好"

        # 小爱同学风格回复
        greetings = [
            f"哎~ {time_greeting}呀~ 我是小智，很高兴为你服务哦~ 请问需要查询档案信息，还是控制档案柜呢？",
            f"哎~ {time_greeting}~ 小智来啦~ 可以帮你查询档案或控制柜子，尽管问哦~",
            f"哎~ {time_greeting}呀~ 小智随时为你待命，有什么可以帮忙的吗？",
            f"在呢~ {time_greeting}~ 我是你的智能助手小智，请问有什么需要？",
            f"哎~ {time_greeting}~ 小智在这里，需要查询档案还是控制设备呢？",
            f"来啦~ {time_greeting}呀~ 我是小智，档案查询、柜子控制都可以找我哦~",
            f"嗯~ {time_greeting}~ 小智已就位，请下达指令吧~"
        ]

        return random.choice(greetings)

    def _handle_with_ollama_directly(self, text):
        """直接使用Ollama处理命令 - 直接使用AI回复"""
        try:
            if not hasattr(self, 'ollama_client') or not self.ollama_client:
                response = "AI服务暂不可用"
                # 发送WebSocket消息
                self.send_websocket_message('ai_response', {'response': response}, text)
                return response

            if not self.ollama_client.is_service_available():
                response = "无法连接到AI服务，请检查服务状态"
                # 发送WebSocket消息
                self.send_websocket_message('ai_response', {'response': response}, text)
                return response

            self.logger.info(f"🚀 直接调用AI处理: {text}")

            # 直接调用AI，不进行语义纠正
            ollama_response = self.ollama_client.send_message(text)

            # 直接使用AI的回复
            if ollama_response:
                self.logger.info(f"✅ AI处理成功: {ollama_response}")
                # 更新对话历史
                if hasattr(self, 'conversation_history'):
                    self.conversation_history.append({"role": "user", "content": text})
                    self.conversation_history.append({"role": "assistant", "content": ollama_response})
                    # 限制历史记录长度
                    if len(self.conversation_history) > 8:
                        self.conversation_history = self.conversation_history[-8:]
                # 发送WebSocket消息
                self.send_websocket_message('ai_response', {'response': ollama_response}, text)
                return ollama_response
            else:
                response = "抱歉，我没有理解您的意思"
                # 发送WebSocket消息
                self.send_websocket_message('ai_response', {'response': response}, text)
                return response
        except Exception as e:
            self.logger.error(f"❌ AI处理异常: {e}")
            response = "处理请求时出现错误"
            # 发送WebSocket消息
            self.send_websocket_message('ai_response', {'response': response}, text)
            return response

    def _extract_column_number(self, text):
        """提取列号信息 - 增强版：支持错别字和口语化表达"""
        try:
            # 首先处理常见的错别字和同音字
            text = text.replace("相子", "柜子").replace("箱子", "柜子").replace("贵子", "柜子")

            # 中文数字到阿拉伯数字的映射
            chinese_to_digit = {
                '一': '1', '二': '2', '两': '2', '三': '3', '四': '4',
                '五': '5', '六': '6', '七': '7', '八': '8', '九': '9', '十': '10',
                '十一': '11', '十二': '12', '十三': '13', '十四': '14', '十五': '15',
                '十六': '16', '十七': '17', '十八': '18', '十九': '19', '二十': '20'
            }

            # 增强匹配模式：支持错别字和更灵活的表达
            patterns = [
                r'第([一二两三四五六七八九十]+)[列柜箱相贵]',      # 第二列/第二柜/第二箱（容错）
                r'([一二两三四五六七八九十]+)[列柜箱相贵]',        # 三列/三柜（容错）
                r'第(\d+)[列柜箱相贵]',                          # 第2列/第2柜（容错）
                r'(\d+)[列柜箱相贵]',                            # 3列/3柜（容错）
                r'第([一二两三四五六七八九十]+)号',               # 第二号
                r'([一二两三四五六七八九十]+)号',                 # 三号
                r'第(\d+)号',                                   # 第2号
                r'(\d+)号',                                     # 3号
                r'打开([一二两三四五六七八九十]+)',               # 打开二
                r'打开(\d+)',                                   # 打开2
                r'开([一二两三四五六七八九十]+)',                 # 开二
                r'开(\d+)',                                     # 开2
                r'第([一二两三四五六七八九十]+)',                 # 第三（只有数字）
                r'第(\d+)',                                     # 第3（只有数字）
            ]

            column_found = None
            for pattern in patterns:
                col_match = re.search(pattern, text)
                if col_match:
                    number_str = col_match.group(1)
                    # 如果是中文数字，转换为阿拉伯数字
                    if number_str in chinese_to_digit:
                        column_found = chinese_to_digit[number_str]
                    elif number_str.isdigit():
                        column_found = number_str

                    if column_found:
                        self.logger.info(f"✅ 提取到列号: {column_found}，匹配模式: {pattern}")
                        break

            # 如果没找到，尝试更宽松的匹配
            if not column_found:
                # 直接匹配数字
                digit_match = re.search(r'[一二两三四五六七八九十\d]+', text)
                if digit_match:
                    number_str = digit_match.group()
                    if number_str in chinese_to_digit:
                        column_found = chinese_to_digit[number_str]
                    elif number_str.isdigit():
                        column_found = number_str
                    if column_found:
                        self.logger.info(f"✅ 宽松模式提取到列号: {column_found}")

            return column_found

        except Exception as e:
            self.logger.error(f"提取列号失败: {e}")
            return None


    def cleanup(self):
        """安全清理资源"""
        self.is_cleaning_up = True
        self.reset_conversation_state()
        # 等待所有活动线程完成
        for thread in self.active_threads:
            try:
                if thread.is_alive():
                    thread.join(timeout=2.0)  # 最多等待2秒
            except Exception as e:
                self.logger.error(f"等待线程结束失败: {e}")
        # 清理资源
        try:
            if hasattr(self, 'db_query'):
                self.db_query.close()
        except Exception as e:
            self.logger.error(f"关闭数据库查询失败: {e}")
        try:
            if hasattr(self, 'archive_manager'):
                self.archive_manager.close()
        except Exception as e:
            self.logger.error(f"关闭档案管理器失败: {e}")
        self.logger.info("命令处理器资源已清理")