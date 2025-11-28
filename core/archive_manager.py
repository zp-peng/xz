# core/archive_manager.py
import mysql.connector
from config.settings import settings
import logging
from datetime import datetime
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

    def semantic_archive_query(self, text):
        """语义档案查询 - 修复版本"""
        try:
            self.logger.info(f"档案语义查询: {text}")

            # 分析查询意图
            analysis = self._analyze_archive_query(text)
            self.logger.info(f"查询分析结果: {analysis}")

            # 执行查询
            if self.connection and self.connection.is_connected():
                return self._query_database(analysis)
            else:
                return {
                    'success': False,
                    'error': '数据库连接失败',
                    'results': [],
                    'query_type': 'unknown'
                }

        except Exception as e:
            self.logger.error(f"档案查询失败: {e}")
            return {
                'success': False,
                'error': str(e),
                'results': [],
                'query_type': 'unknown'
            }

    def _analyze_archive_query(self, text):
        """分析档案查询意图 - 增强年份查询检测"""
        text_lower = text.lower()

        # 检测查询类型
        query_type = 'unknown'
        target = None
        filters = {}

        # 1. 档案柜控制检测
        cabinet_keywords = ['打开', '开启', '启动', '关闭', '停止']
        cabinet_objects = ['档案柜', '柜子', '列']

        if any(keyword in text for keyword in cabinet_keywords):
            if any(obj in text for obj in cabinet_objects):
                query_type = 'cabinet'
                # 提取动作
                if any(keyword in text for keyword in ['关闭', '停止']):
                    filters['action'] = 'close'
                else:
                    filters['action'] = 'open'

                # 提取列号
                col_patterns = [
                    r'第?(\d+)列',
                    r'(\d+)号柜',
                    r'柜子?(\d+)',
                    r'(\d+)号',
                    r'第?(\d+)号档案柜',
                ]

                column_found = None
                for pattern in col_patterns:
                    col_match = re.search(pattern, text)
                    if col_match:
                        column_found = col_match.group(1)
                        break

                if column_found:
                    filters['column'] = column_found
                    filters['has_column'] = True
                else:
                    filters['has_column'] = False
                    filters['need_column_prompt'] = True

                return {
                    'query_type': query_type,
                    'target': '档案柜控制',
                    'filters': filters,
                    'original_text': text
                }

        # 2. 年份查询检测 - 增强模式匹配
        year_patterns = [
            r'(\d{4})年档案',      # 2025年档案
            r'(\d{4})年',          # 2025年
            r'(\d{4})档案',        # 2025档案
            r'查询(\d{4})',        # 查询2025
            r'查找(\d{4})',        # 查找2025
            r'搜索(\d{4})',        # 搜索2025
            r'(\d{4})',           # 纯数字2025
            r'[一二三四五六七八九零]{2,4}年档案',  # 中文数字年份档案
            r'[一二三四五六七八九零]{2,4}年',      # 中文数字年份
            r'[2二][0零〇][2二][5五]年档案',      # 二零二五年档案
            r'入职时间.*(\d{4})',   # 入职时间2025
            r'入职.*(\d{4})',       # 入职2025
        ]

        detected_year = None
        for pattern in year_patterns:
            year_match = re.search(pattern, text)
            if year_match:
                raw_year = year_match.group(1) if year_match.groups() else year_match.group(0)
                # 转换中文数字年份
                if re.search(r'[一二三四五六七八九零]', raw_year):
                    detected_year = self._convert_chinese_year(raw_year)
                else:
                    detected_year = raw_year
                self.logger.info(f"🎯 检测到年份查询: {raw_year} -> {detected_year}")
                break

        if detected_year:
            query_type = 'year'
            filters['year'] = detected_year
            return {
                'query_type': query_type,
                'target': f"{filters['year']}年档案",
                'filters': filters,
                'original_text': text
            }

        # 3. 基础对话检测
        basic_conversation = ['你叫什么', '你是谁', '你几岁', '你多大', '介绍自己', '自我介绍']
        if any(conv in text for conv in basic_conversation):
            query_type = 'conversation'
            return {
                'query_type': query_type,
                'target': '基础对话',
                'filters': filters,
                'original_text': text
            }

        # 4. 人员查询
        if any(name in text for name in ['张三', '李四', '王五', '赵六', '钱七']):
            query_type = 'personnel'
            # 提取具体人名
            for name in ['张三', '李四', '王五', '赵六', '钱七']:
                if name in text:
                    target = name
                    filters['name'] = name
                    break

        # 5. 部门查询
        elif any(dept in text for dept in ['技术部', '人事部', '财务部', '市场部']):
            query_type = 'department'
            for dept in ['技术部', '人事部', '财务部', '市场部']:
                if dept in text:
                    target = dept
                    filters['department'] = dept
                    break
            # 如果是部门人员查询
            if any(word in text for word in ['人员', '员工', '成员']):
                query_type = 'personnel'
                filters['department'] = target

        # 6. 项目查询
        elif any(word in text for word in ['项目', '工程', '任务']):
            query_type = 'project'

        # 7. 如果没有明确目标，默认为人员查询
        else:
            query_type = 'personnel'
            if '查询' in text or '查找' in text or '搜索' in text:
                # 提取可能的查询对象
                words = text.replace('查询', '').replace('查找', '').replace('搜索', '').strip()
                if words and len(words) > 1:
                    target = words

        return {
            'query_type': query_type,
            'target': target,
            'filters': filters,
            'original_text': text
        }

    def _convert_chinese_year(self, chinese_year):
        """将中文数字年份转换为阿拉伯数字年份"""
        chinese_to_digit = {
            '零': '0', '一': '1', '二': '2', '三': '3', '四': '4',
            '五': '5', '六': '6', '七': '7', '八': '8', '九': '9'
        }

        try:
            # 移除"年"字
            chinese_year = chinese_year.replace('年', '')

            # 转换每个中文字符
            digit_year = ''
            for char in chinese_year:
                if char in chinese_to_digit:
                    digit_year += chinese_to_digit[char]
                else:
                    digit_year += char

            # 如果是2位数字，假设是20XX年
            if len(digit_year) == 2 and digit_year.isdigit():
                return '20' + digit_year
            elif len(digit_year) == 4 and digit_year.isdigit():
                return digit_year
            else:
                return '2025'  # 默认返回2025年

        except Exception as e:
            self.logger.error(f"中文年份转换失败: {e}")
            return '2025'  # 默认返回2025年

    def _query_database(self, analysis):
        """查询真实数据库 - 增强版本"""
        try:
            cursor = self.connection.cursor(dictionary=True)
            query_type = analysis['query_type']
            filters = analysis['filters']

            # 档案柜控制
            if query_type == 'cabinet':
                # 检查是否指定了列号
                if not filters.get('has_column', False):
                    return {
                        'success': False,
                        'query_type': 'cabinet',
                        'error': 'missing_column',
                        'message': '请告诉我您要打开哪一列柜子？例如：打开第3列档案柜',
                        'results': [],
                        'count': 0
                    }

                action = filters.get('action', 'open')
                column = filters.get('column', '未知')
                action_text = '打开' if action == 'open' else '关闭'

                # 这里可以连接实际的硬件控制
                control_result = self._control_cabinet_hardware(column, action)

                return {
                    'success': True,
                    'query_type': 'cabinet',
                    'results': [{
                        'column': column,
                        'status': action,
                        'message': f'第{column}列档案柜正在{action_text}',
                        'action': f'{action}_cabinet'
                    }],
                    'count': 1
                }

            # 年份查询 - 修复：基于创建时间查询并打印SQL日志
            elif query_type == 'year':
                year = filters['year']
                self.logger.info(f"📅 执行年份查询: {year}年")

                # 构建基于创建时间的查询
                query = """
                    SELECT * FROM personnel 
                    WHERE YEAR(create_time) = %s
                    ORDER BY create_time DESC
                """

                # 打印SQL日志
                self.logger.info(f"🔍 执行SQL查询: {query}")
                self.logger.info(f"🔍 查询参数: [{year}]")

                cursor.execute(query, (year,))
                results = cursor.fetchall()

                # 打印查询结果统计
                self.logger.info(f"📊 查询结果数量: {len(results)}")
                if results:
                    self.logger.info(f"📋 查询结果样例: {results[0]}")

                cursor.close()

                return {
                    'success': True,
                    'query_type': query_type,
                    'results': results,
                    'count': len(results),
                    'year': year  # 添加年份信息用于语音播报
                }

            # 人员查询
            elif query_type == 'personnel':
                if 'name' in filters:
                    # 查询具体人员
                    query = "SELECT * FROM personnel WHERE name = %s"
                    self.logger.info(f"🔍 执行人员查询SQL: {query}")
                    self.logger.info(f"🔍 查询参数: [{filters['name']}]")
                    cursor.execute(query, (filters['name'],))
                elif 'department' in filters:
                    # 查询部门人员
                    query = "SELECT * FROM personnel WHERE department = %s"
                    self.logger.info(f"🔍 执行部门查询SQL: {query}")
                    self.logger.info(f"🔍 查询参数: [{filters['department']}]")
                    cursor.execute(query, (filters['department'],))
                else:
                    # 查询所有人员
                    query = "SELECT * FROM personnel LIMIT 10"
                    self.logger.info(f"🔍 执行通用查询SQL: {query}")
                    cursor.execute(query)

            # 部门查询
            elif query_type == 'department':
                query = "SELECT * FROM departments"
                if 'department' in filters:
                    query += " WHERE name = %s"
                    self.logger.info(f"🔍 执行部门信息查询SQL: {query}")
                    self.logger.info(f"🔍 查询参数: [{filters['department']}]")
                    cursor.execute(query, (filters['department'],))
                else:
                    self.logger.info(f"🔍 执行所有部门查询SQL: {query}")
                    cursor.execute(query)

            # 项目查询
            elif query_type == 'project':
                query = "SELECT * FROM projects"
                self.logger.info(f"🔍 执行项目查询SQL: {query}")
                cursor.execute(query)

            # 获取结果
            if query_type not in ['cabinet', 'year']:  # cabinet和year类型已经返回了结果
                results = cursor.fetchall()
                self.logger.info(f"📊 查询结果数量: {len(results)}")
                if results:
                    self.logger.info(f"📋 查询结果样例: {results[0]}")
                cursor.close()
            else:
                results = []  # 对于cabinet和year类型，results已经在前面处理了

            return {
                'success': True,
                'query_type': query_type,
                'results': results,
                'count': len(results),
                'year': filters.get('year')  # 添加年份信息用于语音播报
            }

        except Exception as e:
            self.logger.error(f"数据库查询失败: {e}")
            if 'cursor' in locals():
                cursor.close()
            return {
                'success': False,
                'error': str(e),
                'results': [],
                'query_type': analysis['query_type']
            }


    def _control_cabinet_hardware(self, column, action):
        """控制档案柜硬件 - 模拟实现"""
        try:
            # 这里应该连接实际的硬件控制接口
            # 例如：串口通信、网络请求等

            # 模拟控制逻辑
            self.logger.info(f"控制档案柜: 第{column}列, 动作: {action}")

            # 模拟控制成功
            return {
                'success': True,
                'column': column,
                'action': action,
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

        except Exception as e:
            self.logger.error(f"档案柜控制失败: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def format_archive_results(self, archive_result):
        """格式化档案查询结果 - 增强版本"""
        if not archive_result.get('success', False):
            error_type = archive_result.get('error')
            if error_type == 'missing_column':
                return "请告诉我您要打开哪一列柜子？例如：打开第3列档案柜"
            return "查询档案时出现错误，请稍后再试"

        results = archive_result.get('results', [])
        query_type = archive_result.get('query_type', 'unknown')
        year = archive_result.get('year')  # 获取年份信息

        if not results:
            # 根据查询类型提供不同的无结果提示
            if query_type == 'year' and year:
                return f"没有找到{year}年的档案信息"
            return "没有找到相关的档案信息"

        # 档案柜控制结果格式化
        if query_type == 'cabinet':
            return self._format_cabinet_results(results, archive_result.get('filters', {}))
        elif query_type == 'year':
            return self._format_year_results(results, archive_result.get('filters', {}), year)
        # 原有的格式化逻辑
        elif query_type == 'personnel':
            return self._format_personnel_results(results)
        elif query_type == 'department':
            return self._format_department_results(results)
        elif query_type == 'project':
            return self._format_project_results(results)
        else:
            return self._format_generic_results(results)

    def _format_year_results(self, results, filters, year=None):
        """格式化年份查询结果 - 修复版本"""
        # 优先使用传入的year参数，其次使用filters中的year
        display_year = year if year else filters.get('year', '未知')

        if not results:
            return f"没有找到{display_year}年的档案信息"

        if len(results) == 1:
            person = results[0]
            return f"""📅 {display_year}年档案信息：
姓名：{person.get('name', '未知')}
部门：{person.get('department', '未知')}
职位：{person.get('position', '未知')}
工号：{person.get('employee_id', '未知')}
入职时间：{person.get('join_date', '未知')}
创建时间：{person.get('create_time', '未知')}"""
        else:
            output = f"找到 {len(results)} 份{display_year}年相关的档案：\n"
            for person in results:
                output += f"• {person.get('name', '未知')} - {person.get('department', '未知')} - {person.get('position', '未知')} - 创建：{person.get('create_time', '未知')}\n"
            return output

    def _format_personnel_results(self, results):
        """格式化人员查询结果"""
        if len(results) == 1:
            person = results[0]
            return f"""📋 人员档案信息：
姓名：{person.get('name', '未知')}
部门：{person.get('department', '未知')}
职位：{person.get('position', '未知')}
工号：{person.get('employee_id', '未知')}
入职时间：{person.get('join_date', '未知')}
状态：{person.get('status', '未知')}
电话：{person.get('phone', '未知')}
邮箱：{person.get('email', '未知')}"""
        else:
            output = f"找到 {len(results)} 位人员：\n"
            for person in results:
                output += f"• {person.get('name', '未知')} - {person.get('department', '未知')} - {person.get('position', '未知')}\n"
            return output

    def _format_department_results(self, results):
        """格式化部门查询结果"""
        if len(results) == 1:
            dept = results[0]
            return f"""🏢 部门信息：
部门名称：{dept.get('name', '未知')}
部门经理：{dept.get('manager', '未知')}
员工数量：{dept.get('employee_count', '未知')}
部门描述：{dept.get('description', '未知')}"""
        else:
            output = "部门列表：\n"
            for dept in results:
                output += f"• {dept.get('name', '未知')} - 经理：{dept.get('manager', '未知')} - 员工：{dept.get('employee_count', '未知')}人\n"
            return output

    def _format_project_results(self, results):
        """格式化项目查询结果"""
        output = "项目信息：\n"
        for project in results:
            output += f"""📁 项目：{project.get('project_name', '未知')}
  部门：{project.get('department', '未知')}
  负责人：{project.get('manager', '未知')}
  状态：{project.get('status', '未知')}
  周期：{project.get('start_date', '未知')} 至 {project.get('end_date', '未知')}
  描述：{project.get('description', '未知')}
  
"""
        return output

    def _format_cabinet_results(self, results, filters):
        """格式化档案柜控制结果"""
        if results and len(results) > 0:
            cabinet = results[0]
            action = filters.get('action', 'open')
            action_text = '打开' if action == 'open' else '关闭'
            return f"🗄️ {cabinet.get('message', f'档案柜正在{action_text}')}"
        return "档案柜操作完成"

    def _format_generic_results(self, results):
        """通用格式化"""
        return f"找到 {len(results)} 条记录：\n" + "\n".join([str(item) for item in results])

    def close(self):
        """关闭数据库连接"""
        if self.connection and self.connection.is_connected():
            self.connection.close()
            self.logger.info("✅ 档案管理器数据库连接已关闭")