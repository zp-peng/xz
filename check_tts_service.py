# check_tts_service.py
import requests
import time
import sys

def check_tts_service():
    """检查 TTS 服务状态"""
    service_url = "http://localhost:8000"

    print("🔍 检查 Coqui TTS 服务状态...")

    max_retries = 10
    for i in range(max_retries):
        try:
            response = requests.get(f"{service_url}/health", timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get('initialized', False):
                    print("✅ Coqui TTS 服务运行正常")
                    return True
                else:
                    print("⚠️ TTS 服务未初始化完成")
            else:
                print(f"❌ 服务响应异常: {response.status_code}")
        except Exception as e:
            if i < max_retries - 1:
                print(f"⏳ 等待服务启动... ({i+1}/{max_retries})")
                time.sleep(2)
            else:
                print(f"❌ 无法连接到 Coqui TTS 服务: {e}")
                return False

    return False

if __name__ == "__main__":
    if check_tts_service():
        print("🎉 Coqui TTS 服务准备就绪")
        sys.exit(0)
    else:
        print("💥 Coqui TTS 服务未就绪")
        sys.exit(1)