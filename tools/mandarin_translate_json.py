# -*- coding:utf-8 -*-
"""
翻译和JSON处理模块
实现文本翻译和结果保存为JSON格式的功能
"""

import base64
import hashlib
import hmac
import json
import time
import requests
import os
import re
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

# Try to import timezone, use alternative approach if not available
try:
    from datetime import timezone

    UTC_AVAILABLE = True
except ImportError:
    UTC_AVAILABLE = False

# 导入共享凭据管理器
from tools.credentials_manager import credentials_manager

# 导入语音识别功能
from tools.mandarin_asr import speech_to_text


def set_credentials(app_id: str, api_key: str, api_secret: str):
    """
    设置讯飞API的认证凭据
    :param app_id: 应用ID
    :param api_key: API密钥
    :param api_secret: API密钥密钥
    """
    credentials_manager.set_credentials(app_id, api_key, api_secret)


class TranslationResult:
    def __init__(self):
        # 存储翻译结果
        self.full_translation = ""
        # 存储分段翻译结果
        self.segment_translations: Dict[int, str] = {}
        # 存储错误信息
        self.transcription_error_message = ""


class TranslationAPI(object):
    def __init__(self, host: str):
        self.transcription_error_message = ""

        # 从共享凭据管理器获取认证信息
        if not credentials_manager.is_configured():
            self.transcription_error_message = (
                "讯飞API凭据未配置，请先设置app_id、api_key和api_secret"
            )
            return

        app_id, api_key, api_secret = credentials_manager.get_credentials()

        # 应用ID（到控制台获取）
        self.APPID = app_id
        # 接口APISercet（到控制台机器翻译服务页面获取）
        self.Secret = api_secret
        # 接口APIKey（到控制台机器翻译服务页面获取）
        self.APIKey = api_key

        # 以下为POST请求
        self.Host = host
        self.RequestUri = "/v2/ots"
        # 设置url
        self.url = "https://" + host + self.RequestUri
        self.HttpMethod = "POST"
        self.Algorithm = "hmac-sha256"
        self.HttpProto = "HTTP/1.1"

        # 设置当前时间，使用 compatible method based on Python version
        if UTC_AVAILABLE:
            curTime_utc = datetime.now(timezone.utc)
        else:
            curTime_utc = datetime.utcnow()
        self.Date = self.httpdate(curTime_utc)
        # 设置业务参数
        # 语种列表参数值请参照接口文档：https://www.xfyun.cn/doc/nlp/niutrans/API.html
        self.Text = ""
        self.BusinessArgs = {
            "from": "auto",
            "to": "zh",
        }

    def hashlib_256(self, res: str) -> str:
        m = hashlib.sha256(bytes(res.encode(encoding="utf-8"))).digest()
        result = "SHA-256=" + base64.b64encode(m).decode(encoding="utf-8")
        return result

    def httpdate(self, dt: datetime) -> str:
        """
        Return a string representation of a date according to RFC 1123
        (HTTP/1.1).

        The supplied date must be in UTC.

        """
        weekday = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][dt.weekday()]
        month = [
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        ][dt.month - 1]
        return "%s, %02d %s %04d %02d:%02d:%02d GMT" % (
            weekday,
            dt.day,
            month,
            dt.year,
            dt.hour,
            dt.minute,
            dt.second,
        )

    def generateSignature(self, digest: str) -> str:
        signatureStr = "host: " + self.Host + "\n"
        signatureStr += "date: " + self.Date + "\n"
        signatureStr += (
            self.HttpMethod + " " + self.RequestUri + " " + self.HttpProto + "\n"
        )
        signatureStr += "digest: " + digest
        signature = hmac.new(
            bytes(self.Secret.encode(encoding="utf-8")),
            bytes(signatureStr.encode(encoding="utf-8")),
            digestmod=hashlib.sha256,
        ).digest()
        result = base64.b64encode(signature)
        return result.decode(encoding="utf-8")

    def init_header(self, data: str) -> Dict[str, str]:
        digest = self.hashlib_256(data)
        sign = self.generateSignature(digest)
        authHeader = (
            'api_key="%s", algorithm="%s", '
            'headers="host date request-line digest", '
            'signature="%s"' % (self.APIKey, self.Algorithm, sign)
        )
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Method": "POST",
            "Host": self.Host,
            "Date": self.Date,
            "Digest": digest,
            "Authorization": authHeader,
        }
        return headers

    def get_body(self) -> str:
        content = str(base64.b64encode(self.Text.encode("utf-8")), "utf-8")
        postdata = {
            "common": {"app_id": self.APPID},
            "business": self.BusinessArgs,
            "data": {
                "text": content,
            },
        }
        body = json.dumps(postdata)
        return body

    def call_url(self) -> Optional[str]:
        if self.APPID == "" or self.APIKey == "" or self.Secret == "":
            error_msg = (
                "Appid 或APIKey 或APISecret 为空！请打开demo代码，填写相关信息。"
            )
            print(error_msg)
            self.transcription_error_message = error_msg
            return None
        else:
            body = self.get_body()
            headers = self.init_header(body)
            try:
                response = requests.post(
                    self.url, data=body, headers=headers, timeout=8
                )
                status_code = response.status_code
                if status_code != 200:
                    # 鉴权失败
                    error_msg = (
                        "Http请求失败，状态码："
                        + str(status_code)
                        + "，错误信息："
                        + response.text
                    )
                    print(error_msg)
                    print(
                        "请根据错误信息检查代码，接口文档：https://www.xfyun.cn/doc/nlp/niutrans/API.html"
                    )
                    self.transcription_error_message = error_msg
                    return None
                else:
                    # 鉴权成功
                    respData = json.loads(response.text)
                    print("翻译结果:", respData)
                    # 以下仅用于调试
                    code = str(respData["code"])
                    if code != "0":
                        error_msg = (
                            "请前往https://www.xfyun.cn/document/error-code?code="
                            + code
                            + "查询解决办法"
                        )
                        print(error_msg)
                        self.transcription_error_message = error_msg
                        return None
                    else:
                        # 输出翻译结果
                        translation = respData["data"]["result"]["trans_result"]["dst"]
                        print(f"翻译结果: {translation}")
                        return translation
            except requests.exceptions.RequestException as e:
                error_msg = f"网络请求异常: {e}"
                print(error_msg)
                self.transcription_error_message = error_msg
                return None


def translate_text(segments: List[Dict[str, Any]]) -> Optional[Dict[int, str]]:
    """
    翻译文本段落
    :param segments: 语义段落列表
    :return: 每个段落的翻译结果字典
    """
    # 检测输入
    if not segments:
        return None

    print(f"\n开始翻译 {len(segments)} 个语义单元")

    # 为每个句子添加唯一标记
    marked_text = ""
    for segment in segments:
        # 使用特殊标记格式，确保翻译后能准确分割
        marker = f"[XF_SEGMENT_{segment['id']}]"
        marked_text += f"{marker}{segment['text']}"

    # 拼接带标记的文本进行翻译
    host = "ntrans.xfyun.cn"
    translation_result = TranslationResult()

    try:
        translator = TranslationAPI(host)
        translator.Text = marked_text
        full_translation = translator.call_url()

        # 检查是否有错误信息
        if translator.transcription_error_message:
            translation_result.transcription_error_message = (
                translator.transcription_error_message
            )
            raise Exception(translation_result.transcription_error_message)

    except Exception as e:
        error_msg = f"翻译API调用失败: {str(e)}"
        print(error_msg)
        translation_result.transcription_error_message = error_msg
        raise Exception(translation_result.transcription_error_message)

    if not full_translation:
        error_msg = "翻译失败，无法获取翻译结果"
        print(error_msg)
        translation_result.transcription_error_message = error_msg
        raise Exception(translation_result.transcription_error_message)

    # 提取每个标记点的翻译结果
    segment_translations = {}

    # 修复原代码中的逻辑错误：原代码中for循环内部变量作用域问题
    for segment in segments:
        marker = f"[XF_SEGMENT_{segment['id']}]"
        start_pos = full_translation.find(marker)

        if start_pos != -1:
            # 找到下一个标记或文本末尾
            next_marker = f"[XF_SEGMENT_{segment['id']+1}]"
            end_pos = full_translation.find(next_marker, start_pos)

            if end_pos == -1:
                end_pos = len(full_translation)

            # 提取翻译文本（去除标记）
            translation = full_translation[start_pos + len(marker) : end_pos].strip()
            segment_translations[segment["id"]] = translation
        else:
            # 如果找不到标记，使用原文
            segment_translations[segment["id"]] = segment["text"]

    translation_result.segment_translations = segment_translations
    return segment_translations


def create_json_result(
    audio_file: str,
    recognized_text: str,
    full_translation: str,
    segments: List[Dict[str, Any]],
    word_details: List[Dict[str, Any]],
    segment_translations: Dict[int, str],
) -> str:
    """
    创建包含句子级翻译的JSON结果
    """
    # 获取安全的文件名
    # file_name = get_safe_filename(audio_file)

    # 构造句子结构
    sentence_list = []

    for i, segment in enumerate(segments):
        # 获取翻译
        translation = segment_translations.get(segment["id"], "")

        # 提取词级信息（如果可用）
        words = []
        if word_details and segment["word_indices"][0] < len(word_details):
            start_idx, end_idx = segment["word_indices"]
            words = word_details[start_idx : end_idx + 1]

        # 确定语言
        language = ""
        if words:
            lang_counter = {}
            for word in words:
                lang = word["language"]
                if lang:
                    lang_counter[lang] = lang_counter.get(lang, 0) + 1
            if lang_counter:
                language = max(lang_counter, key=lang_counter.get)

        sentence_item = {
            "begin_time": segment["begin_time"],
            "end_time": segment["end_time"],
            "source_text": segment["text"],
            "text": translation,
            "sentence_id": i + 1,
            "words": words,
            "language": language,
        }
        sentence_list.append(sentence_item)

    # 获取所有识别出的语言，过滤掉空字符串
    all_languages = []
    if word_details and len(word_details) > 0:
        all_languages = list(set([w["language"] for w in word_details]))

    # 过滤掉空字符串和None值
    all_languages = [lang for lang in all_languages if lang]

    # 如果没有识别出语言或过滤后为空，使用空数组
    if not all_languages:
        all_languages = []

    # 计算总时长 - 修复时长计算逻辑
    total_duration = 0

    # 优先使用词级信息计算总时长
    if word_details and len(word_details) > 0:
        # 确保获取最后一个有效词的结束时间
        for i in range(len(word_details) - 1, -1, -1):
            if "end_time" in word_details[i] and word_details[i]["end_time"] > 0:
                total_duration = word_details[i]["end_time"]
                break

    # 如果词级信息不可用或没有有效时间，使用语义片段信息
    if total_duration == 0 and segments and len(segments) > 0:
        # 确保获取最后一个有效片段的结束时间
        for i in range(len(segments) - 1, -1, -1):
            if "end_time" in segments[i] and segments[i]["end_time"] > 0:
                total_duration = segments[i]["end_time"]
                break

    # 最后回退到基于文本长度的估算
    if total_duration == 0 and recognized_text:
        total_duration = len(recognized_text) * 200

    print(f"总时长计算结果: {total_duration} 毫秒")

    # 构造JSON结构
    result = {
        "file_url": audio_file,
        "properties": {
            "audio_format": "mp3",
            "channels": [0],
            "original_sampling_rate": 16000,
            "original_duration_in_milliseconds": total_duration,
        },
        "transcripts": [
            {
                "channel_id": 0,
                "content_duration_in_milliseconds": total_duration,
                "source_text": recognized_text,
                "text": full_translation,
                "language": all_languages,
                "sentences": sentence_list,
            }
        ],
    }

    # 保存为JSON文件
    # output_file = f"{file_name}_result.json"
    # with open(output_file, "w", encoding="utf-8") as f:
    #     json.dump(result, f, ensure_ascii=False, indent=2)

    # print(f"结果已保存至: {output_file}")
    return result


def get_safe_filename(file_path: str) -> str:
    """
    从文件路径获取安全的文件名（去除特殊字符）
    :param file_path: 文件路径或URL
    :return: 安全的文件名
    """
    # 获取文件名（不含扩展名）
    if file_path.startswith("http://") or file_path.startswith("https://"):
        # 如果是URL，提取路径部分并获取文件名
        from urllib.parse import urlparse

        parsed_url = urlparse(file_path)
        file_name = os.path.basename(parsed_url.path)
        # 如果URL路径没有文件名，使用时间戳
        if not file_name or "." not in file_name:
            file_name = f"audio_{int(time.time())}"
    else:
        # 本地文件路径
        file_name = os.path.basename(file_path)

    # 移除扩展名
    file_name = os.path.splitext(file_name)[0]

    # 移除或替换不允许的字符
    # Windows不允许的字符: \ / : * ? " < > |
    file_name = re.sub(r'[\\/:*?"<>|]', "_", file_name)

    # 限制文件名长度
    if len(file_name) > 100:
        file_name = file_name[:100]

    # 如果处理后文件名为空，使用默认名称
    if not file_name:
        file_name = "audio_result"

    return file_name
