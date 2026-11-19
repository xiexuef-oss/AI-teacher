"""独立解析进程入口；只接收本机父进程 JSON；可选 DOC 转换器使用独立受限配置。"""

import base64
import json
import sys

from tutor_api.services.document_doc_convert import convert_doc
from tutor_api.services.document_extract import (
    DocumentParseError,
    ParseLimits,
    extract,
    render_preview,
)


def main():
    try:
        request = json.load(sys.stdin)
        limits = ParseLimits(**request["limits"])
        data = base64.b64decode(request["content"], validate=True)
        converted_doc = request["kind"] == "doc"
        if converted_doc:
            data = convert_doc(data, request.get("doc_converter"), limits, request["timeout"])
            request["kind"] = "docx"
        if request["operation"] == "extract":
            result = {"pages": extract(data, request["kind"], limits)}
            if converted_doc:
                for page in result["pages"]:
                    page["warnings"].append(
                        "\u5df2\u5c06 DOC \u8f6c\u6362\u4e3a DOCX\uff1b\u7248\u5f0f\u3001\u516c\u5f0f\u548c\u5a92\u4f53\u9700\u5bf9\u7167\u539f\u6587\u4ef6\u4eba\u5de5\u6838\u5bf9\u3002"
                    )
        else:
            result = {
                "png": base64.b64encode(
                    render_preview(
                        data,
                        request["kind"],
                        request["page"],
                        limits,
                        request.get("media_index"),
                    )
                ).decode("ascii")
            }
    except DocumentParseError as error:
        result = {"error": {"code": error.code, "message": error.message}}
    except Exception:
        result = {"error": {"code": "parse_failed", "message": "文件无法安全解析，请检查原文件"}}
    sys.stdout.write(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
