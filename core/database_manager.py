# core/database_manager.py
import mysql.connector
from config.settings import settings
import logging
from datetime import datetime

class DatabaseManager:
    def __init__(self):
        """初始化数据库管理器 - 更健壮的版本"""
        self.logger = logging.getLogger("database_manager")
        self.connection = None
        self.connect()

    def connect(self):
        """连接到MySQL数据库 - 更健壮的版本"""
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
            self.logger.warning(f"⚠️ MySQL数据库连接失败: {e}")
            self.logger.info("ℹ️ 系统将使用SQLite或模拟数据")
            return False

    def execute_query(self, query, params=None):
        """执行查询并返回结果 - 更健壮的版本"""
        if not self.connection:
            self.logger.warning("❌ 数据库连接不可用")
            return None

        try:
            cursor = self.connection.cursor(dictionary=True)
            cursor.execute(query, params or ())
            result = cursor.fetchall()
            cursor.close()
            return result
        except Exception as e:
            self.logger.error(f"❌ 查询执行失败: {e}")
            return None

    def execute_update(self, query, params=None):
        """执行更新操作 - 更健壮的版本"""
        if not self.connection:
            self.logger.warning("❌ 数据库连接不可用")
            return False

        try:
            cursor = self.connection.cursor()
            cursor.execute(query, params or ())
            self.connection.commit()
            cursor.close()
            return True
        except Exception as e:
            self.logger.error(f"❌ 更新执行失败: {e}")
            if self.connection:
                self.connection.rollback()
            return False

    def log_interaction(self, role, content, response):
        """记录交互日志 - 更健壮的版本"""
        if not self.connection:
            return False

        try:
            cursor = self.connection.cursor()

            # 创建交互日志表（如果不存在）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS interaction_logs (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    role VARCHAR(20) NOT NULL COMMENT '角色: user/assistant',
                    content TEXT COMMENT '用户输入或助手回复内容',
                    response TEXT COMMENT '助手回复内容',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) COMMENT '交互日志表'
            ''')

            # 插入日志记录
            cursor.execute(
                "INSERT INTO interaction_logs (role, content, response) VALUES (%s, %s, %s)",
                (role, content, response)
            )

            self.connection.commit()
            cursor.close()
            self.logger.info(f"✅ 交互日志记录成功: {role}")
            return True

        except Exception as e:
            self.logger.warning(f"⚠️ 记录交互日志失败: {e}")
            return False

    def close(self):
        """关闭数据库连接"""
        if self.connection and self.connection.is_connected():
            self.connection.close()
            self.logger.info("✅ 数据库连接已关闭")