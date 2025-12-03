from flask import Flask, request, jsonify
import requests
import os

# --- 配置信息 ---
# 目标上传 API 的 URL
TARGET_API_URL = 'http://192.168.1.221/v1/files/upload'
# 目标 API 的认证 Token
AUTH_TOKEN = 'app-pbbSsl8Ipploan3tGwgZuiTY'
# 目标 API 要求的 user ID
USER_ID = 'abc-123'

# 支持的音频格式及其 MIME 类型
SUPPORTED_AUDIO_FORMATS = {
    'mp3': 'audio/mpeg',
    'wav': 'audio/wav',
    'flac': 'audio/flac',
    'm4a': 'audio/mp4',
    'ogg': 'audio/ogg',
    'aac': 'audio/aac',
    'wma': 'audio/x-ms-wma'
}

# --- 创建 Flask 应用 ---
app = Flask(__name__)

def upload_audio_to_target(file_obj, file_name: str) -> dict:
    """
    内部函数：将Apifox上传的音频文件转发到目标 API
    """
    # 1. 验证文件格式
    file_ext = file_name.split('.')[-1].lower()
    if file_ext not in SUPPORTED_AUDIO_FORMATS:
        supported_formats = ', '.join(SUPPORTED_AUDIO_FORMATS.keys())
        return {'success': False, 'error': f'不支持的音频格式: {file_ext}。仅支持: {supported_formats}'}

    # 2. 构造目标 API 的请求参数
    headers = {
        'Authorization': f'Bearer {AUTH_TOKEN}'
    }
    data = {
        'user': USER_ID
    }

    # 3. 转发文件到目标 API
    try:
        files = {
            'file': (file_name, file_obj, SUPPORTED_AUDIO_FORMATS[file_ext])
        }
        response = requests.post(
            TARGET_API_URL,
            headers=headers,
            data=data,
            files=files
        )

        # 4. 处理目标 API 的响应
        if response.status_code == 201:
            return {'success': True, 'message': '音频上传成功！', 'target_response': response.json()}
        else:
            return {
                'success': False,
                'error': '上传到目标 API 失败',
                'status_code': response.status_code,
                'target_error': response.text
            }

    except requests.exceptions.RequestException as e:
        return {'success': False, 'error': f'请求目标 API 网络异常: {e}'}
    except Exception as e:
        return {'success': False, 'error': f'未知错误: {e}'}

# --- 定义与你Apifox匹配的接口 ---
@app.route('/uploadAudio', methods=['POST'])
def upload_audio_endpoint():
    """
    匹配你Apifox的form-data格式：接收名为"file"的文件
    """
    # 从form-data中获取上传的文件（对应Apifox里的"file"参数）
    uploaded_file = request.files.get('file')
    if not uploaded_file:
        return jsonify({
            'success': False,
            'error': '请在form-data中上传名为"file"的音频文件'
        }), 400

    # 获取上传文件的文件名
    file_name = uploaded_file.filename
    if not file_name:
        return jsonify({
            'success': False,
            'error': '上传的文件无有效名称'
        }), 400

    # 转发文件到目标 API
    result = upload_audio_to_target(uploaded_file, file_name)

    # 返回最终响应
    return jsonify(result), 200 if result['success'] else 400

# --- 运行服务 ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)