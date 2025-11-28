# utils/logger.py
import logging
import os

def setup_logger(name, level=logging.INFO):
    """设置日志记录器 - 更健壮的版本"""
    try:
        # 确保logs目录存在
        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True)

        # 创建logger
        logger = logging.getLogger(name)
        logger.setLevel(level)

        # 避免重复添加handler
        if not logger.handlers:
            # 文件handler
            file_handler = logging.FileHandler(
                os.path.join(log_dir, f"{name}.log"),
                encoding='utf-8'
            )
            file_handler.setLevel(level)

            # 控制台handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(level)

            # 格式化器
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)

            # 添加handler
            logger.addHandler(file_handler)
            logger.addHandler(console_handler)

        return logger

    except Exception as e:
        # 如果日志设置失败，创建一个基础的logger
        print(f"⚠️ 日志设置失败: {e}，使用基础日志")
        logging.basicConfig(level=level, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        return logging.getLogger(name)