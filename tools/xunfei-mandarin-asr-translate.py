from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

# 导入自定义模块
from tools.mandarin_asr import speech_to_text
from tools.mandarin_translate_json import (
    set_credentials,
    # translate_text,
    translate_text_robust,
    create_json_result,
)

# 导入 logging 和自定义处理器
import logging
from dify_plugin.config.logger_format import plugin_logger_handler

# 使用自定义处理器设置日志
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(plugin_logger_handler)


def xunfei_mandarin_asr_translate(audio_file: str, language: str = "none") -> tuple:
    """
    处理语音识别和翻译的完整流程
    :param audio_file: 音频文件路径
    :param language: 识别语种，默认为"none"
    :return: (识别文本, 完整识别结果, 错误信息)的元组
    """
    print(f"开始语音识别，使用语言: {language}")

    # 执行语音识别
    try:
        recognition_result = speech_to_text(audio_file, language)
    except Exception as e:
        logger.error("语音识别失败 error: %s", str(e))
        return "", {}, f"语音识别失败: {str(e)}"

    # 执行文本翻译
    try:
        # segment_translations = translate_text(recognition_result.semantic_segments)
        segment_translations = translate_text_robust(
            recognition_result.semantic_segments
        )
    except Exception as e:
        segment_translations = {}
        logger.error("文本翻译失败 error: %s", str(e))
        return "", {}, f"文本翻译失败: {str(e)}"

    # 如果翻译失败，使用原文作为翻译结果
    full_translation = ""
    if segment_translations:
        for segment in recognition_result.semantic_segments:
            translation = segment_translations.get(segment["id"], segment["text"])
            full_translation += translation
    else:
        full_translation = recognition_result.recognized_text
        # 创建空的翻译字典
        segment_translations = {
            segment["id"]: segment["text"]
            for segment in recognition_result.semantic_segments
        }

    # 生成JSON结果文件
    translations_json = create_json_result(
        audio_file,
        recognition_result.recognized_text,
        full_translation,
        recognition_result.semantic_segments,
        recognition_result.word_details,
        segment_translations,
    )

    return full_translation, translations_json, ""


class XunfeiMandarinAsrTranslateTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        try:
            app_id = self.runtime.credentials["app_id"]
        except KeyError:
            raise Exception(
                "讯飞多语种语音识别大模型翻译获取 App ID 未配置或无效。请在插件设置中提供。"
            )
        try:
            api_key = self.runtime.credentials["api_key"]
        except KeyError:
            raise Exception(
                "讯飞多语种语音识别大模型翻译获取 API Key 未配置或无效。请在插件设置中提供。"
            )
        try:
            api_secret = self.runtime.credentials["api_secret"]
        except KeyError:
            raise Exception(
                "讯飞多语种语音识别大模型翻译获取 API Secret 未配置或无效。请在插件设置中提供。"
            )

        file_url = tool_parameters.get("file_url")
        if not file_url:
            raise Exception("音频文件链接不能为空。")

        audio_language = tool_parameters.get("audio_language")
        if not audio_language:
            raise Exception("音频语言不能为空。")

        # 将凭据传递给mandarin_translate_json模块
        set_credentials(app_id, api_key, api_secret)

        # 执行语音识别和翻译，不捕获异常，让错误信息通过返回值传递
        transcription_text, transcription, message = xunfei_mandarin_asr_translate(
            file_url, audio_language
        )

        yield self.create_variable_message(
            "result",
            {
                "transcription_text": transcription_text,
                "transcription": transcription,
                "transcription_error_message": message,
            },
        )
