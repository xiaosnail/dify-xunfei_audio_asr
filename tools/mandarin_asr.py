# -*- coding:utf-8 -*-
"""
语音识别功能模块
实现音频文件的语音识别功能
"""

import _thread as thread
import time
from time import mktime
import websocket
import base64
import datetime
import hashlib
import hmac
import json
import ssl
from typing import List, Dict, Any, Optional

# Try to import timezone, use alternative approach if not available
from datetime import datetime

try:
    from datetime import timezone

    UTC_AVAILABLE = True
except ImportError:
    UTC_AVAILABLE = False
from urllib.parse import urlencode
from wsgiref.handlers import format_date_time
import requests
import os

# 导入共享凭据管理器
from tools.credentials_manager import credentials_manager

STATUS_FIRST_FRAME = 0  # 第一帧的标识
STATUS_CONTINUE_FRAME = 1  # 中间帧标识
STATUS_LAST_FRAME = 2  # 最后一帧的标识


class SpeechRecognitionResult:
    def __init__(self):
        # 存储识别结果
        self.recognized_text = ""

        # 存储所有语义单元的结构化数据
        self.semantic_segments: List[Dict[str, Any]] = []
        # 存储词级详细信息
        self.word_details: List[Dict[str, Any]] = []
        # 存储错误信息
        self.error_message = ""


class Ws_Param(object):
    # 初始化
    def __init__(
        self,
        APPID: str,
        APIKey: str,
        APISecret: str,
        AudioFile: str,
        language: str = "none",
    ):
        self.APPID = APPID
        self.APIKey = APIKey
        self.APISecret = APISecret
        self.AudioFile = AudioFile
        # 根据讯飞多语种语音识别接口文档配置参数
        self.iat_params = {
            "domain": "slm",
            "language": "mul_cn",
            "ln": language,
            "accent": "mandarin",
            "result": {"encoding": "utf8", "compress": "raw", "format": "json"},
        }

    # 生成url
    def create_url(self) -> str:
        url = "wss://iat.cn-huabei-1.xf-yun.com/v1"
        # 生成RFC1123格式的时间戳
        now = datetime.now()
        date = format_date_time(mktime(now.timetuple()))

        # 拼接字符串
        signature_origin = "host: " + "iat.cn-huabei-1.xf-yun.com" + "\n"
        signature_origin += "date: " + date + "\n"
        signature_origin += "GET " + "/v1 " + "HTTP/1.1"
        # 进行hmac-sha256进行加密
        signature_sha = hmac.new(
            self.APISecret.encode("utf-8"),
            signature_origin.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        signature_sha = base64.b64encode(signature_sha).decode(encoding="utf-8")

        authorization_origin = (
            'api_key="%s", algorithm="%s", headers="%s", signature="%s"'
            % (self.APIKey, "hmac-sha256", "host date request-line", signature_sha)
        )

        authorization = base64.b64encode(authorization_origin.encode("utf-8")).decode(
            encoding="utf-8"
        )
        # 将请求的鉴权参数组合为字典
        v = {
            "authorization": authorization,
            "date": date,
            "host": "iat.cn-huabei-1.xf-yun.com",
        }
        # 拼接鉴权参数，生成url
        url = url + "?" + urlencode(v)
        return url


# 收到websocket消息的处理
def on_message(ws, message):
    # 通过ws对象获取SpeechRecognitionResult实例
    result = ws.result_instance

    message = json.loads(message)
    code = message["header"]["code"]
    status = message["header"]["status"]
    if code != 0:
        # 获取详细的错误信息
        result.error_message = (
            f" message: {message['header']['message']} (code: {code})"
        )
        print("status:", status)
        print("message:", message)
        ws.close()
    else:
        payload = message.get("payload")
        if payload:
            text = payload["result"]["text"]
            text = json.loads(str(base64.b64decode(text), "utf8"))
            text_ws = text["ws"]

            segment_text = ""
            # 处理每个词
            for word_item in text_ws:
                cw = word_item["cw"][0]  # 取第一个候选词
                word = cw["w"]
                # bg表示起始帧偏移值，每帧=10ms
                begin_time = word_item.get("bg", 0) * 10  # 转换为毫秒

                # 根据讯飞文档说明，ed是保留字段，不能使用
                # 当bg=0时（标点符号或结果过长），无参考意义
                # 我们基于文本长度估算结束时间：每个字符约100ms
                if begin_time > 0 and len(word) > 0:
                    # 基于文本长度计算结束时间
                    end_time = begin_time + len(word) * 100
                else:
                    # 对于标点符号或特殊情况，使用默认估算
                    end_time = begin_time + len(word) * 100

                result.recognized_text += word

                segment_text += word
                # 获取语言信息
                language = cw.get("lg", "")  # 默认使用空字符串而不是unknown

                # 创建词项
                result.word_details.append(
                    {
                        "begin_time": begin_time,
                        "end_time": end_time,
                        "text": word,
                        "language": language,
                    }
                )

            # segment_text 有值才处理
            if segment_text.strip():
                segment_id = len(result.semantic_segments)
                segment_start_time = (
                    result.word_details[-len(text_ws)]["begin_time"]
                    if result.word_details
                    else 0
                )
                segment_end_time = (
                    result.word_details[-1]["end_time"] if result.word_details else 0
                )

                result.semantic_segments.append(
                    {
                        "id": segment_id,
                        "text": segment_text,
                        "begin_time": segment_start_time,
                        "end_time": segment_end_time,
                        "word_indices": [
                            len(result.word_details) - len(text_ws),
                            len(result.word_details) - 1,
                        ],
                    }
                )

        if status == 2:
            print("语音识别结束:", result.recognized_text)
            ws.close()


# 收到websocket错误的处理
def on_error(ws, error):
    # 解析错误信息，提取状态码和消息
    error_str = str(error)

    # 尝试提取状态码和消息内容
    status_code = None
    message_content = None

    # 查找状态码
    import re

    status_match = re.search(r"Handshake status (\d+)", error_str)
    if status_match:
        status_code = status_match.group(1)

    # 查找消息内容
    message_match = re.search(r'"message":"([^"]+)"', error_str)
    if message_match:
        message_content = message_match.group(1)

    # 构造详细的错误信息
    if status_code and message_content:
        detailed_error = f"WebSocket连接错误 {status_code}: {message_content}"
    elif status_code:
        detailed_error = f"WebSocket连接错误 {status_code}: {error_str}"
    elif message_content:
        detailed_error = f"WebSocket连接错误: {message_content}"
    else:
        detailed_error = f"WebSocket连接错误: {error_str}"

    # 通过ws对象获取SpeechRecognitionResult实例
    if hasattr(ws, "result_instance"):
        result = ws.result_instance
        result.error_message = f"{detailed_error}"
    else:
        # 如果没有result_instance属性，则直接打印错误
        print(f"WebSocket连接错误: {detailed_error}")


# 收到websocket关闭的处理
def on_close(ws, close_status_code, close_msg):
    print("### 语音识别连接已关闭 ###")


# 收到websocket连接建立的处理
def on_open(ws):
    def run(*args):
        try:
            # 通过ws对象获取SpeechRecognitionResult实例
            result = ws.result_instance
            ws_param = result.ws_param

            frameSize = 1280  # 每一帧的音频大小
            interval = 0.04  # 发送音频间隔(单位:s)
            status = STATUS_FIRST_FRAME  # 音频的状态信息，标识音频是第一帧，还是中间帧、最后一帧

            # 处理URL或本地文件路径
            temp_file = None
            if ws_param.AudioFile.startswith(
                "http://"
            ) or ws_param.AudioFile.startswith("https://"):
                # 如果是URL，先下载文件
                print(f"正在从URL下载音频文件: {ws_param.AudioFile}")

                # 添加重试机制
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        # 首先尝试正常验证SSL证书
                        try:
                            response = requests.get(
                                ws_param.AudioFile, stream=True, timeout=30
                            )
                        except requests.exceptions.SSLError:
                            # 如果SSL验证失败，给出警告并尝试跳过验证
                            print("警告：SSL证书验证失败，正在尝试跳过验证下载")
                            response = requests.get(
                                ws_param.AudioFile,
                                stream=True,
                                verify=False,
                                timeout=30,
                            )
                        response.raise_for_status()

                        # 创建临时文件
                        temp_file = "temp_audio_file_" + str(int(time.time())) + ".mp3"
                        with open(temp_file, "wb") as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)
                        audio_file_path = temp_file
                        print(f"音频文件已下载到: {audio_file_path}")
                        break  # 成功下载，跳出重试循环
                    except Exception as e:
                        print(
                            f"下载音频文件失败 (尝试 {attempt + 1}/{max_retries}): {e}"
                        )
                        if attempt < max_retries - 1:
                            print("等待2秒后重试...")
                            time.sleep(2)
                        else:
                            print("已达到最大重试次数，下载失败")
                            result.error_message = f"下载音频文件失败: {str(e)}"
                            return
            else:
                # 检查本地文件是否存在
                if not os.path.exists(ws_param.AudioFile):
                    error_msg = f"音频文件不存在: {ws_param.AudioFile}"
                    print(error_msg)
                    result.error_message = error_msg
                    return
                # 如果是本地文件路径，直接使用
                audio_file_path = ws_param.AudioFile

            with open(audio_file_path, "rb") as fp:
                while True:
                    # 检查WebSocket连接是否仍然打开
                    if not hasattr(ws, "sock") or ws.sock is None:
                        print("WebSocket连接已关闭，停止发送数据")
                        break

                    buf = fp.read(frameSize)
                    audio = str(base64.b64encode(buf), "utf-8")

                    # 文件结束
                    if not audio:
                        status = STATUS_LAST_FRAME
                    # 第一帧处理
                    if status == STATUS_FIRST_FRAME:
                        d = {
                            "header": {"status": 0, "app_id": ws_param.APPID},
                            "parameter": {"iat": ws_param.iat_params},
                            "payload": {
                                "audio": {
                                    "audio": audio,
                                    "sample_rate": 16000,
                                    "encoding": "lame",
                                }
                            },
                        }
                        try:
                            ws.send(json.dumps(d))
                            status = STATUS_CONTINUE_FRAME
                        except Exception as e:
                            print(f"发送数据时出错: {e}")
                            result.error_message = f"发送数据时出错: {str(e)}"
                            break
                    # 中间帧处理
                    elif status == STATUS_CONTINUE_FRAME:
                        d = {
                            "header": {"status": 1, "app_id": ws_param.APPID},
                            "payload": {
                                "audio": {
                                    "audio": audio,
                                    "sample_rate": 16000,
                                    "encoding": "lame",
                                }
                            },
                        }
                        try:
                            ws.send(json.dumps(d))
                        except Exception as e:
                            print(f"发送数据时出错: {e}")
                            result.error_message = f"发送数据时出错: {str(e)}"
                            break
                    # 最后一帧处理
                    elif status == STATUS_LAST_FRAME:
                        d = {
                            "header": {"status": 2, "app_id": ws_param.APPID},
                            "payload": {
                                "audio": {
                                    "audio": audio,
                                    "sample_rate": 16000,
                                    "encoding": "lame",
                                }
                            },
                        }
                        try:
                            ws.send(json.dumps(d))
                            break
                        except Exception as e:
                            print(f"发送数据时出错: {e}")
                            result.error_message = f"发送数据时出错: {str(e)}"
                            break

                    # 模拟音频采样间隔
                    time.sleep(interval)

            print("音频数据发送完成")

            # 清理临时文件
            if temp_file and os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                    print(f"临时文件已删除: {temp_file}")
                except Exception as e:
                    print(f"删除临时文件失败: {e}")

        except Exception as e:
            # 捕获所有未处理的异常
            error_msg = f"处理音频时发生未预期的错误: {str(e)}"
            print(error_msg)
            if hasattr(ws, "result_instance"):
                ws.result_instance.error_message = error_msg

    thread.start_new_thread(run, ())


def speech_to_text(audio_file: str, language: str = "none") -> SpeechRecognitionResult:
    """
    语音识别主函数
    :param audio_file: 音频文件路径
    :param language: 识别语种，默认为"none"
    :return: 语音识别结果
    """
    # 创建实例以避免全局变量
    result = SpeechRecognitionResult()

    # 重置识别结果
    result.recognized_text = ""
    result.semantic_segments = []
    result.word_details = []

    # 从共享凭据管理器获取认证信息
    if not credentials_manager.is_configured():
        raise Exception("讯飞API凭据未配置，请先设置app_id、api_key和api_secret")

    app_id, api_key, api_secret = credentials_manager.get_credentials()

    # 使用共享凭据管理器中的认证信息
    result.ws_param = Ws_Param(
        APPID=app_id,
        APIKey=api_key,
        APISecret=api_secret,
        AudioFile=audio_file,
        language=language,
    )

    websocket.enableTrace(False)
    wsUrl = result.ws_param.create_url()
    ws = websocket.WebSocketApp(
        wsUrl, on_message=on_message, on_error=on_error, on_close=on_close
    )

    # 将result实例附加到ws对象，以便在回调中访问
    ws.result_instance = result
    ws.on_open = on_open

    # 添加更多连接选项以提高稳定性
    ws.run_forever(
        sslopt={"cert_reqs": ssl.CERT_NONE}, ping_interval=30, ping_timeout=10
    )

    # 检查是否有错误信息
    if result.error_message:
        raise Exception(result.error_message)

    return result
