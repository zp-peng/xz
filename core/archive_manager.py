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
        """查询档案 - 统一查询所有相关字段"""
        try:
            self.logger.info(f"档案查询: {query_text}")

            # 清理查询文本
            query_value = self._clean_query_text(query_text)

            if not query_value:
                return {
                    'success': False,
                    'error': '请提供档案名称或编号进行查询',
                    'results': []
                }

            # 执行查询
            if self.connection and self.connection.is_connected():
                return self._execute_double_query(query_value)
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

    def _clean_query_text(self, text):
        """清理查询文本 - 移除常见的前缀和后缀，并提取关键信息"""
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

        # 特别处理"为"和"是"连接的情况，如"接线方式为三相三线"
        # 正则表达式匹配：XXX为YYY 或 XXX是YYY 的形式
        pattern = r'(.+?)(?:为|是)(.+)$'
        match = re.match(pattern, text)

        if match:
            # 获取关键字前的描述部分（如"接线方式"）和实际值（如"三相三线"）
            description = match.group(1).strip()
            actual_value = match.group(2).strip()

            self.logger.info(f"📝 检测到描述性查询: '{description}' 为/是 '{actual_value}'")

            # 如果描述包含"接线方式"，我们只提取实际值
            if '接线方式' in description:
                text = actual_value
                self.logger.info(f"📝 提取接线方式值: '{text}'")
            else:
                # 其他情况，也使用实际值
                text = actual_value

        return text

    def _execute_double_query(self, query_value):
        """执行双重查询 - 先查询转换后的阿拉伯数字，再查询原始中文数字"""
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

            print(f"📝 [DEBUG] 查询值转换: '{query_value}' -> '{converted_value}'")

            # 定义查询函数，用于执行单次查询
            def execute_single_query(search_value):
                query = """
                    SELECT DISTINCT ta.*
                    FROM `t_archives` ta
                    LEFT JOIN t_archives_attachment taa ON ta.id = taa.archives_id
                    WHERE ta.is_del = '0'
                    AND (
                        -- 档案表字段
                        ta.title LIKE CONCAT('%', %s, '%')
                        OR ta.dang_num LIKE CONCAT('%', %s, '%')
                    )
                    ORDER BY ta.create_time DESC
                """
                # 参数数量和占位符数量必须一致：2个占位符，2个参数
                cursor.execute(query, (search_value, search_value))
                return cursor.fetchall()

            # 第一次查询：使用转换后的阿拉伯数字
            results1 = execute_single_query(converted_value)
            print(f"📊 [DEBUG] 第一次查询结果数量: {len(results1)}")

            # 第二次查询：使用原始中文数字
            results2 = execute_single_query(query_value)

            # 合并两次查询结果并去重
            all_results = results1 + results2

            # 去重（按标题和编号）
            unique_results = []
            seen_keys = set()

            for result in all_results:
                key = f"{result.get('title', '')}_{result.get('dang_num', '')}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    unique_results.append(result)

            print(f"📊 [DEBUG] 去重后结果数量: {len(unique_results)}")

            # 如果双重查询没有结果，则尝试通过文档查询接口查找
            if len(unique_results) == 0:
                print(f"🔍 [DEBUG] 双重查询无结果，尝试通过文档查询接口查找: '{query_value}'")
                try:
                    # 尝试导入主应用中的文档查询函数
                    import requests
                    import json

                    # 构建请求参数
                    request_data = {'query_text': query_value}
                    print(f"📤 [DEBUG] 发送文档查询请求参数: {json.dumps(request_data, ensure_ascii=False)}")

                    # 调用文档查询接口
                    response = requests.post(
                        'http://localhost:5000/api/documents/query',
                        json=request_data,
                        timeout=10
                    )

                    print(f"📥 [DEBUG] 文档查询接口响应状态码: {response.status_code}")

                    if response.status_code == 200:
                        data = response.json()
                        print(f"📥 [DEBUG] 文档查询接口返回原始数据: {json.dumps(data, ensure_ascii=False)}")

                        if data.get('success') and data.get('documents'):
                            documents = data.get('documents', [])
                            print(f"📄 [DEBUG] 文档查询接口解析后返回 {len(documents)} 个文档: {documents}")

                            # 对每个文档名进行查询
                            document_results = []
                            for doc_name in documents:
                                # 清理文档名
                                import re
                                # 移除 "数字. " 格式的前缀
                                doc_name_clean = re.sub(r'^\d+\.\s*', '', doc_name)
                                # 移除括号及括号内的内容（如"(激光熔覆)"）
                                doc_name_clean = re.sub(r'\([^)]*\)', '', doc_name_clean)
                                # 移除文件扩展名
                                doc_name_without_ext = doc_name_clean.split('.')[0] if '.' in doc_name_clean else doc_name_clean
                                # 移除前后空格
                                doc_name_without_ext = doc_name_without_ext.strip()

                                print(f"🔍 [DEBUG] 原始文档名: '{doc_name}'")

                                # 查询档案表（使用name字段）
                                name_query = """
                                    SELECT DISTINCT ta.*
                                    FROM `t_archives` ta
                                    LEFT JOIN t_archives_attachment taa ON ta.id = taa.archives_id
                                    WHERE ta.is_del = '0'
                                    AND taa.name LIKE CONCAT('%', %s, '%')
                                    ORDER BY ta.create_time DESC
                                """
                                cursor.execute(name_query, (doc_name_without_ext,))
                                doc_results = cursor.fetchall()

                                if doc_results:
                                    print(f"🔍 [DEBUG] 根据文档名 '{doc_name_without_ext}' 查询到 {len(doc_results)} 条档案记录")
                                    document_results.extend(doc_results)

                            # 如果通过文档名查询到结果，合并并去重
                            if document_results:
                                # 去重
                                seen_doc_keys = set()
                                unique_doc_results = []

                                for result in document_results:
                                    key = f"{result.get('title', '')}_{result.get('dang_num', '')}"
                                    if key not in seen_doc_keys:
                                        seen_doc_keys.add(key)
                                        unique_doc_results.append(result)

                                print(f"📊 [DEBUG] 文档查询最终去重后结果数量: {len(unique_doc_results)}")

                                # 返回文档查询的结果 - 保持与SQL查询完全一致的结构
                                cursor.close()
                                return {
                                    'success': True,
                                    'query_value': query_value,
                                    'converted_value': converted_value,
                                    'results': unique_doc_results,
                                    'count': len(unique_doc_results),
                                    'query_type': 'double'  # 保持一致的查询类型
                                }
                            else:
                                print("❌ [DEBUG] 文档查询接口返回文档名，但未在档案表中找到对应记录")
                        else:
                            error_msg = data.get('error', '未知错误')
                            print(f"❌ [DEBUG] 文档查询接口调用失败: {error_msg}")
                    else:
                        response_text = response.text[:500] if response.text else "无响应内容"
                        print(f"❌ [DEBUG] 文档查询接口HTTP错误: {response.status_code}, 响应内容: {response_text}")
                except requests.exceptions.Timeout:
                    print("❌ [DEBUG] 调用文档查询接口超时")
                except requests.exceptions.ConnectionError:
                    print("❌ [DEBUG] 无法连接到文档查询接口，请确保主应用已启动")
                except json.JSONDecodeError as e:
                    print(f"❌ [DEBUG] 文档查询接口返回JSON解析失败: {e}")
                except Exception as e:
                    print(f"❌ [DEBUG] 调用文档查询接口异常: {e}")
                    import traceback
                    traceback.print_exc()

            cursor.close()

            return {
                'success': True,
                'query_value': query_value,
                'converted_value': converted_value,
                'results': unique_results,
                'count': len(unique_results),
                'query_type': 'double'  # 标记使用了双重查询
            }

        except Exception as e:
            print(f"❌ [DEBUG] 数据库查询失败: {e}")
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
        query_value = archive_result.get('query_value', '')
        converted_value = archive_result.get('converted_value', '')

        if not results:
            return f"没有找到包含'{query_value}'或'{converted_value}'的档案信息"

        if len(results) == 1:
            archive = results[0]
            # 返回简洁的档案信息，去掉表情符号和缩进
            return f"档案名称：{archive.get('title', '未知')}，档案编号：{archive.get('dang_num', '未知')}，创建时间：{archive.get('create_time', '未知')}"
        else:
            # 返回图片中的格式："为您找到X条相关档案，请选择要查看哪一条"
            return f"为您找到{len(results)}条相关档案，请选择要查看哪一条"

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