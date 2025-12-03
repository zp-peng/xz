import requests
import json
import re

# 固定的API密钥
API_KEY = "app-P6KF8MQ795fLV9ueHEa8Pf5s"

class DocumentAPI:
    def __init__(self):
        # 使用固定的API_KEY
        self.api_key = API_KEY
        self.base_url = "http://pmo.suresource.com.cn:18880/v1/chat-messages"

    def call_api(self, query, user="abc-123"):
        """调用聊天API获取响应"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        data = {
            "inputs": {},
            "query": query,
            "response_mode": "blocking",
            "conversation_id": "",
            "user": user,
            "files": []
        }

        try:
            response = requests.post(
                url=self.base_url,
                headers=headers,
                json=data,
                timeout=(10, 30)
            )

            if response.status_code == 200:
                result = response.json()
                return {"success": True, "data": result}
            else:
                return {
                    "success": False,
                    "error": f"API请求失败，状态码: {response.status_code}",
                    "response_text": response.text
                }

        except requests.exceptions.Timeout:
            return {"success": False, "error": "请求超时，请检查网络连接"}
        except requests.exceptions.ConnectionError:
            return {"success": False, "error": "连接失败，请检查URL地址"}
        except Exception as e:
            return {"success": False, "error": f"请求异常: {str(e)}"}

    def extract_documents(self, content):
        """从内容中提取文档名称"""
        pattern = r'([^，,\s]+\.(docx|xlsx|pdf|txt|doc|ppt|pptx))'
        matches = re.findall(pattern, content, re.IGNORECASE)
        documents = [match[0] for match in matches]
        return documents

    def get_documents(self, query, user="abc-123"):
        """获取文档列表接口 - 核心功能"""
        result = self.call_api(query, user=user)

        if not result.get("success"):
            return {"success": False, "error": result.get("error")}

        data = result.get("data", {})

        # 提取内容
        content = ""
        if "answer" in data:
            content = data["answer"]
        elif "content" in data:
            content = data["content"]
        else:
            # 如果没有找到标准字段，尝试查找任何包含文档名称的文本
            content_str = json.dumps(data, ensure_ascii=False)
            content = content_str

        # 提取文档名称
        documents = self.extract_documents(content)

        return {"success": True, "documents": documents, "count": len(documents), "query": query}


# 简化接口函数
def query_documents(query, user="abc-123"):
    """
    查询文档接口（简化版）

    参数:
    - query: 查询字符串
    - user: 用户标识，可选，默认为"abc-123"

    返回:
    - dict: 包含success, documents, count, query, error等字段
    """
    api_client = DocumentAPI()
    return api_client.get_documents(query, user)


def get_document_list(query, user="abc-123"):
    """
    快速获取文档列表

    参数:
    - query: 查询字符串
    - user: 用户标识，可选

    返回:
    - list: 文档名称列表，失败时返回空列表
    """
    result = query_documents(query, user)
    return result.get("documents", []) if result.get("success") else []


if __name__ == "__main__":


    # 或者直接使用
    query = "接线方式三项三线"
    result = query_documents(query)
    print(f"查询结果: {result}")