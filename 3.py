import requests
import json

def get_datasets(api_key, page=1, limit=20):
    """
    获取数据集列表

    Args:
        api_key (str): API密钥
        page (int): 页码，默认为1
        limit (int): 每页数量，默认为20

    Returns:
        dict: API响应数据
    """
    # 请求URL
    url = "http://pmo.suresource.com.cn/v1/datasets"

    # 查询参数
    params = {
        'page': page,
        'limit': limit
    }

    # 请求头
    headers = {
        'Authorization': f'Bearer {api_key}'
    }

    try:
        # 发送GET请求
        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=30
        )

        # 打印请求信息（调试用）
        print(f"请求URL: {response.request.url}")
        print(f"请求头: {dict(response.request.headers)}")
        print(f"状态码: {response.status_code}")

        # 检查响应状态
        if response.status_code == 200:
            # 尝试解析JSON响应
            try:
                data = response.json()
                print("✅ 请求成功!")
                return data
            except json.JSONDecodeError:
                print(f"❌ JSON解析失败，响应内容: {response.text}")
                return None
        else:
            print(f"❌ 请求失败，状态码: {response.status_code}")
            print(f"响应内容: {response.text}")
            return None

    except requests.exceptions.RequestException as e:
        print(f"❌ 请求异常: {e}")
        return None


def get_datasets_with_retry(api_key, page=1, limit=20, max_retries=3):
    """
    带重试功能的获取数据集列表

    Args:
        api_key (str): API密钥
        page (int): 页码
        limit (int): 每页数量
        max_retries (int): 最大重试次数

    Returns:
        dict: API响应数据
    """
    for attempt in range(max_retries):
        print(f"第 {attempt + 1} 次尝试...")
        result = get_datasets(api_key, page, limit)

        if result is not None:
            return result

        if attempt < max_retries - 1:
            print(f"等待 2 秒后重试...")
            import time
            time.sleep(2)

    return None


# 使用示例
if __name__ == "__main__":
    # 替换为你的实际API密钥
    API_KEY = "dataset-kIhn2CEwDoRirG5NKxknVmdd"

    # 获取数据集列表
    result = get_datasets_with_retry(API_KEY, page=1, limit=20)

    if result:
        print("\n🎉 成功获取数据集列表!")
        print(json.dumps(result, indent=2, ensure_ascii=False))

        # 如果有数据，打印简要信息
        if 'data' in result and result['data']:
            datasets = result['data']
            print(f"\n📊 共获取到 {len(datasets)} 个数据集:")
            for i, dataset in enumerate(datasets, 1):
                print(f"  {i}. {dataset.get('name', '未知名称')} (ID: {dataset.get('id', '未知ID')})")
        else:
            print("📭 没有找到数据集")
    else:
        print("\n😞 获取数据集列表失败")