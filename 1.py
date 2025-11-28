import requests
import json

class DifyDatasetAPI:
    def __init__(self, api_key, base_url="https://api.dify.ai/v1"):
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {
            'Authorization': f'Bearer {api_key}'
        }

    def update_document_by_file(self, dataset_id, document_id, file_path,
                                name="Dify",
                                indexing_technique="high_quality",
                                process_rule=None):
        """
        通过文件更新知识库文档

        Args:
            dataset_id (str): 数据集ID
            document_id (str): 文档ID
            file_path (str): 文件路径
            name (str): 文档名称
            indexing_technique (str): 索引技术，可选 "high_quality" 或 "economy"
            process_rule (dict): 处理规则配置

        Returns:
            dict: API响应结果
        """

        # 构建请求URL
        url = f"{self.base_url}/datasets/{dataset_id}/documents/{document_id}/update_by_file"

        # 默认处理规则
        if process_rule is None:
            process_rule = {
                "rules": {
                    "pre_processing_rules": [
                        {"id": "remove_extra_spaces", "enabled": True},
                        {"id": "remove_urls_emails", "enabled": True}
                    ],
                    "segmentation": {
                        "separator": "###",
                        "max_tokens": 500
                    }
                },
                "mode": "custom"
            }

        # 构建data参数
        data_config = {
            "name": name,
            "indexing_technique": indexing_technique,
            "process_rule": process_rule
        }

        # 准备文件和数据
        files = {
            'file': (open(file_path, 'rb'))
        }

        data = {
            'data': (None, json.dumps(data_config), 'text/plain')
        }

        try:
            # 发送请求
            response = requests.post(
                url,
                headers=self.headers,
                files=files,
                data=data
            )

            # 检查响应
            response.raise_for_status()

            return response.json()

        except requests.exceptions.RequestException as e:
            print(f"请求失败: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"响应内容: {e.response.text}")
            return None
        finally:
            # 确保文件被关闭
            if 'file' in files:
                files['file'].close()


# 使用示例
def main():
    # 初始化API客户端
    api_key = "your_api_key_here"
    client = DifyDatasetAPI(api_key)

    # 参数
    dataset_id = "your_dataset_id"
    document_id = "your_document_id"
    file_path = "/path/to/your/file.pdf"  # 替换为实际文件路径

    # 调用接口
    result = client.update_document_by_file(
        dataset_id=dataset_id,
        document_id=document_id,
        file_path=file_path,
        name="我的文档",
        indexing_technique="high_quality"
    )

    if result:
        print("文档更新成功:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("文档更新失败")


# 更简洁的使用方式
def simple_update(api_key, dataset_id, document_id, file_path):
    """简化版的更新函数"""
    url = f"https://api.dify.ai/v1/datasets/{dataset_id}/documents/{document_id}/update_by_file"

    headers = {
        'Authorization': f'Bearer {api_key}'
    }

    data_config = {
        "name": "Dify",
        "indexing_technique": "high_quality",
        "process_rule": {
            "rules": {
                "pre_processing_rules": [
                    {"id": "remove_extra_spaces", "enabled": True},
                    {"id": "remove_urls_emails", "enabled": True}
                ],
                "segmentation": {
                    "separator": "###",
                    "max_tokens": 500
                }
            },
            "mode": "custom"
        }
    }

    files = {
        'file': open(file_path, 'rb')
    }

    data = {
        'data': (None, json.dumps(data_config), 'text/plain')
    }

    try:
        response = requests.post(url, headers=headers, files=files, data=data)
        response.raise_for_status()
        return response.json()
    finally:
        files['file'].close()


if __name__ == "__main__":
    main()