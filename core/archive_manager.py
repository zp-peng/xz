# core/archive_manager.py
import mysql.connector
from config.settings import settings
import logging
import re

class ArchiveManager:
    def __init__(self):
        """初始化档案管理器"""
        self.logger = logging.getLogger("archive_manager")
        self.connection = None
        self.connect()

    def connect(self):
        """连接到MySQL数据库"""
        try:
            self.connection = mysql.connector.connect(
                host=settings.database_config['host'],
                port=settings.database_config['port'],
                user=settings.database_config['user'],
                password=settings.database_config['password'],
                database=settings.database_config['database']
            )
            self.logger.info("✅ MySQL数据库连接成功")
            return True
        except Exception as e:
            self.logger.error(f"❌ 数据库连接失败: {e}")
            return False

    def query_archive(self, query_text):
        """查询档案 - 支持名称和编号查询"""
        try:
            self.logger.info(f"档案查询: {query_text}")

            # 分析查询类型
            query_type, query_value = self._analyze_query(query_text)

            if not query_value:
                return {
                    'success': False,
                    'error': '请提供档案名称或编号进行查询',
                    'results': []
                }

            # 执行查询
            if self.connection and self.connection.is_connected():
                return self._execute_archive_query(query_type, query_value)
            else:
                return {
                    'success': False,
                    'error': '数据库连接失败',
                    'results': []
                }

        except Exception as e:
            self.logger.error(f"档案查询失败: {e}")
            return {
                'success': False,
                'error': str(e),
                'results': []
            }

    def _analyze_query(self, text):
        """分析查询意图 - 检测档案查询语义"""
        text = text.strip()

        # 清理查询前缀
        query_prefixes = [
            '帮我查询', '帮我查一下', '帮我找一下', '帮我搜索',
            '查询', '查一下', '查找', '找一下', '搜索',
            '查查', '查', '找', '搜'
        ]

        for prefix in query_prefixes:
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
                break

        # 清理查询后缀
        query_suffixes = ['的档案', '档案', '的资料', '的信息']
        for suffix in query_suffixes:
            if text.endswith(suffix):
                text = text[:-len(suffix)].strip()
                break

        # 如果清理后为空，返回未知
        if not text:
            return 'unknown', None

        # 检测档案编号查询
        code_patterns = [
            r'编号\s*[:：]?\s*([^\s]+)',   # 编号: 12345
            r'编号\s*([^\s]+)',            # 编号12345
            r'^[A-Za-z0-9\-_]+$'          # 纯编号，如: 2024-001
        ]

        for pattern in code_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                if len(match.groups()) > 0:
                    code = match.group(1).strip()
                else:
                    code = match.group(0).strip()

                if code and len(code) > 0:
                    return 'code', code

        # 将整个文本作为名称查询
        return 'name', text

    def _execute_archive_query(self, query_type, query_value):
        """执行档案查询 - 同时支持中文数字和阿拉伯数字"""
        try:
            cursor = self.connection.cursor(dictionary=True)

            # 中文数字到阿拉伯数字的映射
            chinese_number_map = {
                '零': '0', '一': '1', '二': '2', '两': '2', '三': '3', '四': '4',
                '五': '5', '六': '6', '七': '7', '八': '8', '九': '9', '十': '10',
                '十一': '11', '十二': '12', '十三': '13', '十四': '14', '十五': '15',
                '十六': '16', '十七': '17', '十八': '18', '十九': '19', '二十': '20',
                '二十一': '21', '二十二': '22', '二十三': '23', '二十四': '24', '二十五': '25',
                '二十六': '26', '二十七': '27', '二十八': '28', '二十九': '29', '三十': '30'
            }

            # 转换中文数字到阿拉伯数字
            converted_value = query_value
            for chinese, arabic in chinese_number_map.items():
                if chinese in query_value:
                    converted_value = converted_value.replace(chinese, arabic)
                    self.logger.info(f"📝 中文数字转换: {chinese} -> {arabic}, 转换后: {converted_value}")

            if query_type == 'name':
                # 按名称模糊查询，同时查询原始值和转换后的值
                query = """
                    SELECT DISTINCT ta.*
                    FROM `t_archives` ta
                    LEFT JOIN t_archives_attachment taa ON ta.id = taa.archives_id
                    WHERE ta.is_del = '0'
                    AND (
                        ta.title LIKE CONCAT('%', %s, '%')
                        OR taa.`name` LIKE CONCAT('%', %s, '%')
                        OR ta.title LIKE CONCAT('%', %s, '%')
                        OR taa.`name` LIKE CONCAT('%', %s, '%')
                    )
                    ORDER BY ta.create_time DESC
                """
                cursor.execute(query, (query_value, query_value, converted_value, converted_value))
            elif query_type == 'code':
                # 按编号模糊查询，同时查询原始值和转换后的值
                query = """
                    SELECT DISTINCT ta.*
                    FROM `t_archives` ta
                    LEFT JOIN t_archives_attachment taa ON ta.id = taa.archives_id
                    WHERE ta.is_del = '0'
                    AND (
                        ta.dang_num LIKE CONCAT('%', %s, '%')
                        OR ta.dang_num LIKE CONCAT('%', %s, '%')
                    )
                    ORDER BY ta.create_time DESC
                """
                cursor.execute(query, (query_value, converted_value))
            else:
                cursor.close()
                return {
                    'success': False,
                    'error': '无法识别查询类型',
                    'results': []
                }

            results = cursor.fetchall()
            cursor.close()

            self.logger.info(f"查询结果数量: {len(results)}")

            # 如果查询结果很多，可能需要去重（按标题和编号）
            unique_results = []
            seen_keys = set()

            for result in results:
                # 使用标题+编号作为唯一键
                key = f"{result.get('title', '')}_{result.get('dang_num', '')}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    unique_results.append(result)

            return {
                'success': True,
                'query_type': query_type,
                'query_value': query_value,
                'converted_value': converted_value,
                'results': unique_results,
                'count': len(unique_results)
            }

        except Exception as e:
            self.logger.error(f"数据库查询失败: {e}")
            if 'cursor' in locals():
                cursor.close()
            return {
                'success': False,
                'error': str(e),
                'results': []
            }

    def format_archive_results(self, archive_result):
        """格式化档案查询结果"""
        if not archive_result.get('success', False):
            return "查询档案时出现错误，请稍后再试"

        results = archive_result.get('results', [])
        query_type = archive_result.get('query_type', 'unknown')
        query_value = archive_result.get('query_value', '')

        if not results:
            if query_type == 'name':
                return f"没有找到名称包含'{query_value}'的档案"
            elif query_type == 'code':
                return f"没有找到编号为'{query_value}'的档案"
            else:
                return "没有找到相关的档案信息"

        if len(results) == 1:
            archive = results[0]
            return f"""📋 档案信息：
    档案名称：{archive.get('title', '未知')}
    档案编号：{archive.get('dang_num', '未知')}
    创建时间：{archive.get('create_time', '未知')}"""
        else:
            # 只返回简单的数量提示和选择指示
            return f"已为您找到{len(results)}条相关档案，请选择要查看哪一条"

    def query_attachment_by_archive_id(self, archive_id):
        """根据档案ID查询附件信息"""
        try:
            if not archive_id:
                return {
                    'success': False,
                    'error': '档案ID不能为空',
                    'results': []
                }

            if not self.connection or not self.connection.is_connected():
                # 尝试重新连接
                if not self.connect():
                    return {
                        'success': False,
                        'error': '数据库连接失败',
                        'results': []
                    }

            cursor = self.connection.cursor(dictionary=True)

            # 使用参数化查询防止SQL注入
            query = """
                SELECT * 
                FROM `t_archives_attachment` 
                WHERE archives_id = %s
                ORDER BY create_time DESC
            """

            cursor.execute(query, (archive_id,))
            results = cursor.fetchall()
            cursor.close()

            self.logger.info(f"查询附件成功，档案ID: {archive_id}, 附件数量: {len(results)}")

            return {
                'success': True,
                'archive_id': archive_id,
                'results': results,
                'count': len(results)
            }

        except mysql.connector.Error as e:
            self.logger.error(f"数据库查询失败: {e}")
            return {
                'success': False,
                'error': f"数据库查询失败: {str(e)}",
                'results': []
            }
        except Exception as e:
            self.logger.error(f"查询附件时发生异常: {e}")
            return {
                'success': False,
                'error': f"查询附件时发生异常: {str(e)}",
                'results': []
            }

    def close(self):
        """关闭数据库连接"""
        if self.connection and self.connection.is_connected():
            self.connection.close()
            self.logger.info("✅ 档案管理器数据库连接已关闭")