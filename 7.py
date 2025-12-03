import requests
import json
import re

def run_workflow_and_extract_text(api_key, upload_file_id):
    url = "http://192.168.1.221/v1/workflows/run"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    data = {
        "inputs": {
            "file": [
                {
                    "transfer_method": "local_file",
                    "upload_file_id": upload_file_id,
                    "type": "audio"
                }
            ]
        },
        "response_mode": "streaming",
        "user": "abc-123"
    }

    print("请求详情:")
    print(f"URL: {url}")
    print(f"Data: {json.dumps(data, indent=2)}")

    try:
        response = requests.post(
            url=url,
            headers=headers,
            json=data,
            timeout=30
        )

        print(f"\n响应状态码: {response.status_code}")

        if response.status_code == 200:
            print("✅ 请求成功!")
            print("开始接收流式响应...\n")

            final_text = None

            for line in response.iter_lines(decode_unicode=True):
                if line:
                    # 检查是否是 workflow_finished 事件
                    if '"event": "workflow_finished"' in line:
                        try:
                            # 提取 JSON 数据
                            json_str = line.replace('data: ', '')
                            data_obj = json.loads(json_str)

                            # 获取 outputs.text
                            if 'data' in data_obj and 'outputs' in data_obj['data']:
                                final_text = data_obj['data']['outputs'].get('text', '')

                                if final_text:
                                    # 直接输出中文文本（JSON会自动处理Unicode转义）
                                    print("=" * 50)
                                    print("📝 提取的文本内容:")
                                    print("=" * 50)
                                    print(final_text)
                                    print("=" * 50)

                                    return final_text

                        except json.JSONDecodeError as e:
                            print(f"JSON解析错误: {e}")

            if not final_text:
                print("未找到 workflow_finished 事件中的文本内容")
                return None

        else:
            print("❌ 请求失败!")
            print(f"响应内容: {response.text}")
            return None

    except requests.exceptions.RequestException as e:
        print(f"❌ 请求异常: {e}")
        return None

# 使用示例
if __name__ == "__main__":
    API_KEY = "app-BlcNrYszyCM0OHIBzmNIfOy3"
    UPLOAD_FILE_ID = "c393cada-0041-40eb-a97d-dbf0474bb450"

    result = run_workflow_and_extract_text(API_KEY, UPLOAD_FILE_ID)

    if result:
        print(f"\n🎉 最终提取的中文文本: {result}")