import re
import jieba
import jieba.posseg as pseg
from collections import defaultdict
from utils.logger import setup_logger

class SemanticAnalyzer:
    def __init__(self):
        self.logger = setup_logger("semantic_analyzer")

        # 加载专业词汇
        self._load_custom_words()

        # 定义语义模式
        self.semantic_patterns = self._init_semantic_patterns()

        # 定义数据库表和字段映射
        self.table_mapping = {
            '用户': 'users',
            '员工': 'users',
            '人员': 'users',
            '同事': 'users',
            '产品': 'products',
            '商品': 'products',
            '物品': 'products',
            '销售': 'sales',
            '订单': 'sales',
            '交易': 'sales'
        }

        self.field_mapping = {
            # 用户表字段
            '姓名': 'name',
            '名字': 'name',
            '年龄': 'age',
            '部门': 'department',
            '工资': 'salary',
            '薪资': 'salary',
            '薪水': 'salary',

            # 产品表字段
            '产品名': 'name',
            '名称': 'name',
            '类别': 'category',
            '分类': 'category',
            '价格': 'price',
            '价钱': 'price',
            '库存': 'stock',
            '数量': 'stock',

            # 销售表字段
            '销售量': 'quantity',
            '数量': 'quantity',
            '金额': 'amount',
            '总额': 'amount',
            '销售日期': 'sale_date',
            '日期': 'sale_date'
        }

        self.operation_mapping = {
            '查询': 'SELECT',
            '查找': 'SELECT',
            '搜索': 'SELECT',
            '统计': 'COUNT',
            '计算': 'CALCULATE',
            '平均': 'AVG',
            '平均值': 'AVG',
            '最高': 'MAX',
            '最大': 'MAX',
            '最低': 'MIN',
            '最小': 'MIN',
            '总和': 'SUM',
            '总数': 'SUM'
        }

    def _load_custom_words(self):
        """加载自定义词汇"""
        custom_words = {
            '用户表': ['users', '用户', '员工'],
            '产品表': ['products', '产品', '商品'],
            '销售表': ['sales', '销售', '订单'],
            '技术部': ['技术部门', '研发部'],
            '销售部': ['销售部门', '市场部'],
            '平均工资': ['平均薪资', '平均薪水'],
            '销售总额': ['总销售额', '总金额']
        }

        for word, variants in custom_words.items():
            jieba.add_word(word)
            for variant in variants:
                jieba.add_word(variant)

    def _init_semantic_patterns(self):
        """初始化语义模式"""
        return {
            'count_query': [
                r'有多少(.+)',
                r'(.+)的数量',
                r'统计(.+)',
                r'计算(.+)总数'
            ],
            'detail_query': [
                r'显示(.+)',
                r'列出(.+)',
                r'查看(.+)',
                r'查询(.+)',
                r'找(.+)'
            ],
            'statistical_query': [
                r'(.+)的平均值',
                r'平均(.+)',
                r'(.+)的最高值',
                r'最高(.+)',
                r'(.+)的最低值',
                r'最低(.+)',
                r'(.+)的总和',
                r'总(.+)'
            ],
            'conditional_query': [
                r'(.+)的(.+)',
                r'在(.+)的(.+)',
                r'属于(.+)的(.+)',
                r'(.+)部门(.+)'
            ],
            'comparison_query': [
                r'(.+)大于(.+)',
                r'(.+)超过(.+)',
                r'(.+)少于(.+)',
                r'(.+)低于(.+)'
            ]
        }

    def analyze_query(self, text):
        """分析查询语义"""
        self.logger.info(f"分析查询语义: {text}")

        # 分词和词性标注
        words = pseg.cut(text)
        word_list = []
        pos_list = []

        for word, pos in words:
            word_list.append(word)
            pos_list.append(pos)

        # 提取关键信息
        analysis_result = {
            'original_text': text,
            'words': word_list,
            'pos_tags': pos_list,
            'tables': self._extract_tables(word_list),
            'fields': self._extract_fields(word_list),
            'operations': self._extract_operations(word_list),
            'conditions': self._extract_conditions(text, word_list),
            'query_type': self._determine_query_type(text),
            'limit': self._extract_limit(text)
        }

        self.logger.info(f"语义分析结果: {analysis_result}")
        return analysis_result

    def _extract_tables(self, words):
        """提取表名"""
        tables = []
        for word in words:
            if word in self.table_mapping:
                tables.append(self.table_mapping[word])
        return list(set(tables))  # 去重

    def _extract_fields(self, words):
        """提取字段名"""
        fields = []
        for word in words:
            if word in self.field_mapping:
                fields.append(self.field_mapping[word])
        return list(set(fields))

    def _extract_operations(self, words):
        """提取操作类型"""
        operations = []
        for word in words:
            if word in self.operation_mapping:
                operations.append(self.operation_mapping[word])
        return operations

    def _extract_conditions(self, text, words):
        """提取查询条件"""
        conditions = {}

        # 部门条件
        department_keywords = ['技术部', '销售部', '市场部', '管理部', '部门']
        for dept in department_keywords:
            if dept in text:
                conditions['department'] = dept.replace('部', '')
                break

        # 类别条件
        category_keywords = ['电子产品', '家具', '家电', '文化用品']
        for category in category_keywords:
            if category in text:
                conditions['category'] = category
                break

        # 数值条件
        number_pattern = r'(\d+)'
        numbers = re.findall(number_pattern, text)
        if numbers:
            if '大于' in text or '超过' in text:
                conditions['greater_than'] = numbers[0]
            elif '少于' in text or '低于' in text:
                conditions['less_than'] = numbers[0]

        return conditions

    def _determine_query_type(self, text):
        """确定查询类型"""
        text_lower = text.lower()

        if any(word in text_lower for word in ['多少', '数量', '统计', '总数']):
            return 'COUNT'
        elif any(word in text_lower for word in ['平均']):
            return 'AVG'
        elif any(word in text_lower for word in ['最高', '最大']):
            return 'MAX'
        elif any(word in text_lower for word in ['最低', '最小']):
            return 'MIN'
        elif any(word in text_lower for word in ['总和', '总']):
            return 'SUM'
        else:
            return 'SELECT'

    def _extract_limit(self, text):
        """提取限制数量"""
        limit_patterns = [
            r'前(\d+)个',
            r'前(\d+)条',
            r'显示(\d+)个',
            r'显示(\d+)条'
        ]

        for pattern in limit_patterns:
            match = re.search(pattern, text)
            if match:
                return int(match.group(1))

        return 10  # 默认限制

    def generate_sql_query(self, analysis_result):
        """根据语义分析生成SQL查询"""
        query_type = analysis_result['query_type']
        tables = analysis_result['tables']
        fields = analysis_result['fields']
        conditions = analysis_result['conditions']
        limit = analysis_result['limit']

        if not tables:
            return "SELECT '请指定要查询的表' as info"

        # 确定主表
        main_table = tables[0]

        # 构建基础查询
        if query_type == 'COUNT':
            sql = f"SELECT COUNT(*) as count FROM {main_table}"
        elif query_type == 'AVG':
            if fields:
                field = fields[0]
                sql = f"SELECT AVG({field}) as avg_value FROM {main_table}"
            else:
                sql = f"SELECT COUNT(*) as count FROM {main_table}"
        elif query_type == 'MAX':
            if fields:
                field = fields[0]
                sql = f"SELECT MAX({field}) as max_value FROM {main_table}"
            else:
                sql = f"SELECT * FROM {main_table} ORDER BY id DESC LIMIT 1"
        elif query_type == 'MIN':
            if fields:
                field = fields[0]
                sql = f"SELECT MIN({field}) as min_value FROM {main_table}"
            else:
                sql = f"SELECT * FROM {main_table} ORDER BY id ASC LIMIT 1"
        elif query_type == 'SUM':
            if fields:
                field = fields[0]
                sql = f"SELECT SUM({field}) as total FROM {main_table}"
            else:
                sql = f"SELECT COUNT(*) as count FROM {main_table}"
        else:  # SELECT
            if fields:
                field_list = ', '.join(fields)
                sql = f"SELECT {field_list} FROM {main_table}"
            else:
                sql = f"SELECT * FROM {main_table}"

        # 添加条件
        where_conditions = []

        if 'department' in conditions:
            where_conditions.append(f"department = '{conditions['department']}'")

        if 'category' in conditions:
            where_conditions.append(f"category = '{conditions['category']}'")

        if 'greater_than' in conditions:
            if fields:
                field = fields[0]
                where_conditions.append(f"{field} > {conditions['greater_than']}")

        if 'less_than' in conditions:
            if fields:
                field = fields[0]
                where_conditions.append(f"{field} < {conditions['less_than']}")

        if where_conditions:
            sql += " WHERE " + " AND ".join(where_conditions)

        # 添加排序和限制
        if query_type == 'SELECT':
            if 'salary' in fields or 'price' in fields:
                sql += f" ORDER BY {fields[0]} DESC"
            sql += f" LIMIT {limit}"

        self.logger.info(f"生成的SQL查询: {sql}")
        return sql