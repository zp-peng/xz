from flask import Flask, request, jsonify
import requests
import json

# --- 创建 Flask 应用 ---
app = Flask(__name__)

# --- 配置信息 ---
# 目标上传 API 的 URL
TARGET_API_URL = 'http://192.168.1.221/v1/files/upload'
# 工作流运行 API 的 URL
WORKFLOW_API_URL = 'http://192.168.1.221/v1/workflows/run'
# 工作流 API 的认证 Token
WORKFLOW_API_KEY = 'app-BlcNrYszyCM0OHIBzmNIfOy3'
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

def upload_audio_to_target(file_obj, file_name: str) -> dict:
    """
    内部函数：将上传的音频文件转发到目标 API
    """
    # 1. 验证文件格式
    file_ext = file_name.split('.')[-1].lower()
    if file_ext not in SUPPORTED_AUDIO_FORMATS:
        supported_formats = ', '.join(SUPPORTED_AUDIO_FORMATS.keys())
        return {'success': False, 'error': f'不支持的音频格式: {file_ext}。仅支持: {supported_formats}'}

    # 2. 构造目标 API 的请求参数
    headers = {
        'Authorization': f'Bearer {WORKFLOW_API_KEY}'
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

def run_workflow_and_extract_text(api_key, upload_file_id):
    """
    运行工作流并提取文本内容
    """
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
        "user": USER_ID
    }

    try:
        response = requests.post(
            url=WORKFLOW_API_URL,
            headers=headers,
            json=data,
            timeout=30
        )

        if response.status_code == 200:
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
                                    return {
                                        'success': True,
                                        'text': final_text,
                                        'message': '文本提取成功'
                                    }

                        except json.JSONDecodeError as e:
                            return {'success': False, 'error': f'JSON解析错误: {e}'}

            if not final_text:
                return {'success': False, 'error': '未找到 workflow_finished 事件中的文本内容'}

        else:
            return {'success': False, 'error': f'工作流请求失败，状态码: {response.status_code}', 'response': response.text}

    except requests.exceptions.RequestException as e:
        return {'success': False, 'error': f'请求工作流异常: {e}'}

# --- 定义接口 ---
@app.route('/uploadAudio', methods=['POST'])
def upload_audio_endpoint():
    """
    上传音频文件接口
    """
    # 从form-data中获取上传的文件
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

@app.route('/runWorkflow', methods=['POST'])
def run_workflow_endpoint():
    """
    运行工作流接口 - 直接接收文件，自动上传并运行工作流
    """
    # 从form-data中获取上传的文件
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

    # 1. 先上传文件获取文件ID
    upload_result = upload_audio_to_target(uploaded_file, file_name)
    if not upload_result['success']:
        return jsonify(upload_result), 400

    # 2. 从上传结果中获取文件ID
    upload_file_id = upload_result['target_response']['id']

    # 3. 运行工作流并提取文本
    workflow_result = run_workflow_and_extract_text(WORKFLOW_API_KEY, upload_file_id)

    # 4. 返回最终结果
    return jsonify(workflow_result), 200 if workflow_result['success'] else 400

# --- 运行服务 ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)