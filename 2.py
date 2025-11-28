import requests
import json
import time
import re

class ChatAPI:
    def __init__(self, api_key, base_url=None):
        self.api_key = api_key
        # 尝试多个可能的URL
        self.base_urls = [
            "http://pmo.suresource.com.cn:18880/v1/chat-messages",
            "http://pmo.suresource.com.cn/v1/chat-messages",
            "https://pmo.suresource.com.cn/v1/chat-messages"
        ]
        if base_url:
            self.base_urls.insert(0, base_url)

    def test_connection(self, url_index=0):
        """测试网络连接"""
        test_url = self.base_urls[url_index].replace("/v1/chat-messages", "")
        print(f"测试连接: {test_url}")

        try:
            start_time = time.time()
            response = requests.get(test_url, timeout=10)
            elapsed_time = time.time() - start_time

            print(f"✓ 连接成功! 状态码: {response.status_code}, 响应时间: {elapsed_time:.2f}秒")
            return True
        except Exception as e:
            print(f"✗ 连接失败: {e}")
            return False

    def test_auth(self, url_index=0):
        """测试API认证"""
        url = self.base_urls[url_index]
        headers = {"Authorization": f"Bearer {self.api_key}"}

        print(f"测试认证: {url}")

        try:
            # 发送一个简单的HEAD请求测试认证
            response = requests.head(url, headers=headers, timeout=10)
            if response.status_code == 401:
                print("✗ 认证失败: API密钥无效")
                return False
            elif response.status_code == 404:
                print("✗ 端点不存在: 请检查URL路径")
                return False
            else:
                print(f"✓ 认证测试通过! 状态码: {response.status_code}")
                return True
        except Exception as e:
            print(f"✗ 认证测试失败: {e}")
            return False

    def call_api(self, query, inputs=None, user="", conversation_id="", files=None):
        """调用聊天API（非流式）"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        data = {
            "inputs": inputs or {},
            "query": query,
            "response_mode": "blocking",  # 阻塞模式，等待完整响应
            "conversation_id": conversation_id,
            "user": user,
            "files": files or []
        }

        # 尝试所有可能的URL
        for i, url in enumerate(self.base_urls):
            print(f"\n尝试URL [{i+1}/{len(self.base_urls)}]: {url}")

            try:
                print("发送请求中...")
                start_time = time.time()

                response = requests.post(
                    url=url,
                    headers=headers,
                    json=data,  # 使用json参数自动序列化
                    timeout=(10, 30)  # (连接超时, 读取超时)
                )

                elapsed_time = time.time() - start_time
                print(f"响应状态码: {response.status_code}, 响应时间: {elapsed_time:.2f}秒")

                if response.status_code == 200:
                    result = response.json()
                    print("✓ 请求成功!")
                    return result
                else:
                    print(f"HTTP错误: {response.status_code} - {response.text}")
                    # 继续尝试下一个URL

            except requests.exceptions.Timeout as e:
                print(f"✗ 请求超时: {e}")
            except requests.exceptions.ConnectionError as e:
                print(f"✗ 连接错误: {e}")
            except requests.exceptions.HTTPError as e:
                print(f"✗ HTTP错误: {e}")
            except Exception as e:
                print(f"✗ 其他错误: {type(e).__name__}: {e}")

        # 所有URL都失败
        return {"error": "所有URL尝试失败，请检查网络连接、API密钥和端点地址"}

    def extract_documents(self, content):
        """从内容中提取文档名称"""
        # 使用正则表达式匹配文档名称
        # 匹配以 .docx, .xlsx, .pdf 等结尾的文件名
        pattern = r'([^，,\s]+\.(docx|xlsx|pdf|txt|doc|ppt|pptx))'
        matches = re.findall(pattern, content, re.IGNORECASE)

        # 提取完整的文件名
        documents = [match[0] for match in matches]

        return documents

    def get_documents(self, query):
        """直接获取文档列表"""
        result = self.call_api(query, user="abc-123")

        if "error" in result:
            return {"error": result["error"]}

        # 提取内容
        content = ""
        if "answer" in result:
            content = result["answer"]
        elif "content" in result:
            content = result["content"]
        else:
            # 如果没有找到标准字段，尝试查找任何包含文档名称的文本
            content_str = json.dumps(result, ensure_ascii=False)
            content = content_str

        # 提取文档名称
        documents = self.extract_documents(content)

        return documents

    def diagnose(self):
        """运行完整诊断"""
        print("=" * 50)
        print("开始API诊断...")
        print("=" * 50)

        # 测试第一个URL的连接
        if not self.test_connection(0):
            print("\n尝试备用URL...")
            for i in range(1, len(self.base_urls)):
                if self.test_connection(i):
                    break
            else:
                print("所有URL连接测试失败!")
                return False

        print("\n" + "-" * 50)

        # 测试认证
        if not self.test_auth(0):
            print("\n尝试备用URL认证...")
            for i in range(1, len(self.base_urls)):
                if self.test_auth(i):
                    break
            else:
                print("所有URL认证测试失败!")
                return False

        print("\n" + "-" * 50)
        print("✓ 诊断完成，API配置正常")
        return True


def main():
    # 配置API密钥
    API_KEY = "app-P6KF8MQ795fLV9ueHEa8Pf5s"

    # 创建API客户端
    api_client = ChatAPI(API_KEY)

    # 运行诊断
    if not api_client.diagnose():
        print("诊断失败，请检查配置后重试")
        return

    print("\n" + "=" * 50)
    print("开始API调用测试...")
    print("=" * 50)

    # 测试查询
    query = "电能表"

    # 直接获取文档列表
    documents = api_client.get_documents(query)

    print("\n" + "=" * 50)
    print("提取的文档列表:")
    print("=" * 50)

    if "error" in documents:
        print(f"错误: {documents['error']}")
    elif documents:
        for i, doc in enumerate(documents, 1):
            print(f"{i}. {doc}")
    else:
        print("未找到文档")


# 简化版本 - 只获取文档列表
def get_document_list(api_key, query):
    """简化函数：直接获取文档列表"""
    api_client = ChatAPI(api_key)
    return api_client.get_documents(query)


if __name__ == "__main__":
    main()

    # 或者直接使用简化版本
    # API_KEY = "app-P6KF8MQ795fLV9ueHEa8Pf5s"
    # query = "电能表"
    # documents = get_document_list(API_KEY, query)
    # print("文档列表:", documents)