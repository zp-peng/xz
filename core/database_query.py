# core/database_query.py
import sqlite3
import mysql.connector
from mysql.connector import Error
import pandas as pd
from config.settings import settings
from utils.logger import setup_logger
from core.semantic_analyzer import SemanticAnalyzer

class DatabaseQuery:
    def __init__(self):
        self.logger = setup_logger("database_query")
        self.semantic_analyzer = SemanticAnalyzer()
        self.connection = None
        self.db_type = "sqlite"  # 默认使用SQLite

        # 初始化数据库连接
        self._init_database()

    def _init_database(self):
        """初始化数据库连接 - 更健壮的版本"""
        try:
            # 首先尝试连接MySQL
            self.connection = mysql.connector.connect(
                host=settings.database_config['host'],
                port=settings.database_config['port'],
                user=settings.database_config['user'],
                password=settings.database_config['password'],
                database=settings.database_config['database']
            )
            self.db_type = "mysql"
            self._create_sample_tables()
            self.logger.info("✅ MySQL数据库连接成功")

        except Error as e:
            self.logger.warning(f"⚠️ MySQL连接失败: {e}")
            self.logger.info("🔄 尝试连接SQLite...")

            try:
                # 尝试连接SQLite
                self.connection = sqlite3.connect("archive_management.db")
                self.db_type = "sqlite"
                self._create_sample_tables()
                self.logger.info("✅ SQLite数据库连接成功")

            except Exception as e:
                self.logger.warning(f"⚠️ SQLite连接失败: {e}")
                self.logger.info("🔄 使用内存SQLite数据库")
                try:
                    self.connection = sqlite3.connect(":memory:")
                    self.db_type = "sqlite"
                    self._create_sample_tables()
                    self.logger.info("✅ 内存SQLite数据库连接成功")
                except Exception as e:
                    self.logger.error(f"❌ 所有数据库连接都失败: {e}")
                    self.connection = None

    def _create_sample_tables(self):
        """创建示例数据表 - 修复MySQL语法问题"""
        if not self.connection:
            self.logger.warning("❌ 数据库连接不可用，跳过创建表")
            return

        try:
            cursor = self.connection.cursor()

            # 根据数据库类型使用不同的SQL语法
            if self.db_type == "mysql":
                # MySQL语法
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        age INT,
                        department VARCHAR(255),
                        salary DECIMAL(10,2),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS products (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        category VARCHAR(255),
                        price DECIMAL(10,2),
                        stock INT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS sales (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        product_id INT,
                        user_id INT,
                        quantity INT,
                        sale_date DATE,
                        amount DECIMAL(10,2),
                        FOREIGN KEY (product_id) REFERENCES products (id),
                        FOREIGN KEY (user_id) REFERENCES users (id)
                    )
                ''')
            else:
                # SQLite语法
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        age INTEGER,
                        department TEXT,
                        salary REAL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS products (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        category TEXT,
                        price REAL,
                        stock INTEGER,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS sales (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        product_id INTEGER,
                        user_id INTEGER,
                        quantity INTEGER,
                        sale_date DATE,
                        amount REAL,
                        FOREIGN KEY (product_id) REFERENCES products (id),
                        FOREIGN KEY (user_id) REFERENCES users (id)
                    )
                ''')

            # 插入示例数据
            self._insert_sample_data(cursor)

            self.connection.commit()
            self.logger.info("✅ 示例数据表创建成功")

        except Exception as e:
            self.logger.error(f"❌ 创建数据表失败: {e}")
            if self.connection:
                self.connection.rollback()

    def _insert_sample_data(self, cursor):
        """插入示例数据"""
        # 检查是否已有数据
        try:
            if self.db_type == "mysql":
                cursor.execute("SELECT COUNT(*) FROM users")
            else:
                cursor.execute("SELECT COUNT(*) FROM users")

            if cursor.fetchone()[0] == 0:
                # 插入用户数据
                users = [
                    ('张三', 28, '技术部', 15000),
                    ('李四', 32, '销售部', 12000),
                    ('王五', 25, '技术部', 13000),
                    ('赵六', 30, '市场部', 11000),
                    ('钱七', 35, '管理部', 20000),
                    ('孙八', 29, '技术部', 14000),
                    ('周九', 31, '销售部', 12500)
                ]

                if self.db_type == "mysql":
                    cursor.executemany(
                        "INSERT INTO users (name, age, department, salary) VALUES (%s, %s, %s, %s)",
                        users
                    )
                else:
                    cursor.executemany(
                        "INSERT INTO users (name, age, department, salary) VALUES (?, ?, ?, ?)",
                        users
                    )

                # 插入产品数据
                products = [
                    ('笔记本电脑', '电子产品', 5999.0, 50),
                    ('智能手机', '电子产品', 3999.0, 100),
                    ('办公椅', '家具', 899.0, 30),
                    ('咖啡机', '家电', 1299.0, 20),
                    ('书籍', '文化用品', 59.0, 200),
                    ('显示器', '电子产品', 1999.0, 40)
                ]

                if self.db_type == "mysql":
                    cursor.executemany(
                        "INSERT INTO products (name, category, price, stock) VALUES (%s, %s, %s, %s)",
                        products
                    )
                else:
                    cursor.executemany(
                        "INSERT INTO products (name, category, price, stock) VALUES (?, ?, ?, ?)",
                        products
                    )

                # 插入销售数据
                sales = [
                    (1, 1, 2, '2024-10-01', 11998.0),
                    (2, 2, 1, '2024-10-02', 3999.0),
                    (3, 3, 5, '2024-10-03', 4495.0),
                    (4, 4, 3, '2024-10-04', 3897.0),
                    (5, 5, 10, '2024-10-05', 590.0),
                    (6, 1, 1, '2024-10-06', 1999.0),
                    (2, 3, 2, '2024-10-07', 7998.0)
                ]

                if self.db_type == "mysql":
                    cursor.executemany(
                        "INSERT INTO sales (product_id, user_id, quantity, sale_date, amount) VALUES (%s, %s, %s, %s, %s)",
                        sales
                    )
                else:
                    cursor.executemany(
                        "INSERT INTO sales (product_id, user_id, quantity, sale_date, amount) VALUES (?, ?, ?, ?, ?)",
                        sales
                    )
        except Exception as e:
            self.logger.error(f"❌ 插入示例数据失败: {e}")

    def execute_query(self, query, params=None):
        """执行SQL查询"""
        if not self.connection:
            self.logger.warning("❌ 数据库连接不可用")
            return {"error": "数据库连接不可用"}

        try:
            if self.db_type == "mysql":
                cursor = self.connection.cursor(dictionary=True)
            else:
                self.connection.row_factory = sqlite3.Row
                cursor = self.connection.cursor()

            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)

            if query.strip().upper().startswith('SELECT'):
                results = cursor.fetchall()

                # 转换为字典列表
                if self.db_type == "mysql":
                    return results
                else:
                    return [dict(row) for row in results]
            else:
                self.connection.commit()
                return {"affected_rows": cursor.rowcount}

        except Exception as e:
            self.logger.error(f"❌ 查询执行失败: {e}")
            return {"error": str(e)}

    def semantic_query(self, natural_language):
        """基于语义的自然语言查询"""
        try:
            # 分析语义
            analysis = self.semantic_analyzer.analyze_query(natural_language)

            # 生成SQL查询
            sql_query = self.semantic_analyzer.generate_sql_query(analysis)

            # 执行查询
            result = self.execute_query(sql_query)

            return {
                'analysis': analysis,
                'sql_query': sql_query,
                'result': result
            }

        except Exception as e:
            self.logger.error(f"❌ 语义查询失败: {e}")
            return {"error": str(e)}

    def natural_language_query(self, question):
        """自然语言查询处理（兼容旧版本）"""
        # 使用新的语义查询
        semantic_result = self.semantic_query(question)

        if 'error' in semantic_result:
            # 如果语义查询失败，回退到原来的关键词匹配
            return self._fallback_keyword_query(question)

        return semantic_result['result']

    def _fallback_keyword_query(self, question):
        """回退到关键词查询"""
        question_lower = question.lower()

        # 用户相关查询
        if any(keyword in question_lower for keyword in ['用户', '员工', '人员', '同事']):
            if '数量' in question_lower or '多少' in question_lower:
                return self.execute_query("SELECT COUNT(*) as count FROM users")
            elif '部门' in question_lower:
                return self.execute_query("SELECT department, COUNT(*) as count FROM users GROUP BY department")
            elif '工资' in question_lower or '薪资' in question_lower:
                if '平均' in question_lower:
                    return self.execute_query("SELECT AVG(salary) as avg_salary FROM users")
                elif '最高' in question_lower:
                    return self.execute_query("SELECT name, MAX(salary) as max_salary FROM users")
                elif '最低' in question_lower:
                    return self.execute_query("SELECT name, MIN(salary) as min_salary FROM users")
                else:
                    return self.execute_query("SELECT name, salary FROM users ORDER BY salary DESC")
            else:
                return self.execute_query("SELECT * FROM users LIMIT 10")

        # 产品相关查询
        elif any(keyword in question_lower for keyword in ['产品', '商品', '物品']):
            if '数量' in question_lower or '多少' in question_lower:
                return self.execute_query("SELECT COUNT(*) as count FROM products")
            elif '类别' in question_lower or '分类' in question_lower:
                return self.execute_query("SELECT category, COUNT(*) as count FROM products GROUP BY category")
            elif '价格' in question_lower:
                if '平均' in question_lower:
                    return self.execute_query("SELECT AVG(price) as avg_price FROM products")
                elif '最高' in question_lower:
                    return self.execute_query("SELECT name, MAX(price) as max_price FROM products")
                elif '最低' in question_lower:
                    return self.execute_query("SELECT name, MIN(price) as min_price FROM products")
                else:
                    return self.execute_query("SELECT name, price FROM products ORDER BY price DESC")
            elif '库存' in question_lower:
                return self.execute_query("SELECT name, stock FROM products WHERE stock < 50 ORDER BY stock ASC")
            else:
                return self.execute_query("SELECT * FROM products LIMIT 10")

        # 销售相关查询
        elif any(keyword in question_lower for keyword in ['销售', '订单', '交易']):
            if '总额' in question_lower or '总金额' in question_lower:
                return self.execute_query("SELECT SUM(amount) as total_sales FROM sales")
            elif '最近' in question_lower or '最新' in question_lower:
                return self.execute_query("SELECT p.name, s.quantity, s.amount, s.sale_date FROM sales s JOIN products p ON s.product_id = p.id ORDER BY s.sale_date DESC LIMIT 5")
            else:
                return self.execute_query("SELECT p.name as product_name, u.name as user_name, s.quantity, s.amount, s.sale_date FROM sales s JOIN products p ON s.product_id = p.id JOIN users u ON s.user_id = u.id ORDER BY s.sale_date DESC LIMIT 10")

        # 默认返回数据库表信息
        else:
            tables = self.get_table_info()
            return {"tables": tables, "message": "请指定要查询的具体内容"}

    def get_table_info(self, table_name=None):
        """获取表结构信息"""
        if not self.connection:
            return {"error": "数据库连接不可用"}

        try:
            if table_name:
                if self.db_type == "mysql":
                    query = f"DESCRIBE {table_name}"
                else:
                    query = f"PRAGMA table_info({table_name})"

                return self.execute_query(query)
            else:
                # 获取所有表名
                if self.db_type == "mysql":
                    query = "SHOW TABLES"
                else:
                    query = "SELECT name FROM sqlite_master WHERE type='table'"

                tables = self.execute_query(query)
                table_list = []

                for table in tables:
                    table_name = list(table.values())[0] if table else None
                    if table_name:
                        table_list.append(table_name)

                return table_list

        except Exception as e:
            self.logger.error(f"❌ 获取表信息失败: {e}")
            return {"error": str(e)}

    def format_query_result(self, result):
        """格式化查询结果"""
        if isinstance(result, dict) and 'error' in result:
            return f"查询错误: {result['error']}"

        if not result:
            return "没有找到相关数据"

        # 如果是表列表
        if isinstance(result, list) and all(isinstance(item, str) for item in result):
            return f"数据库中有以下表: {', '.join(result)}"

        # 如果是数据结果
        if isinstance(result, list) and len(result) > 0:
            # 获取列名
            columns = list(result[0].keys())

            # 构建结果字符串
            output = f"找到 {len(result)} 条记录:\n"

            for i, row in enumerate(result[:10]):  # 最多显示10条
                output += f"\n记录 {i+1}:\n"
                for col in columns:
                    output += f"  {col}: {row[col]}\n"

            if len(result) > 10:
                output += f"\n... 还有 {len(result) - 10} 条记录未显示"

            return output

        return str(result)

    def close(self):
        """关闭数据库连接"""
        if self.connection:
            self.connection.close()
            self.logger.info("数据库连接已关闭")