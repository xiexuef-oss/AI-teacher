"""Self-authored image fixtures; all provider HTTP uses MockTransport."""

import base64
import io
import json

import httpx
import pytest
from PIL import Image

from ai_gateway import InputPart, ProviderError, TaskType
from ai_gateway.providers import OpenAICompatAdapter
from support.gateway_fakes import make_request


def image_uri(format="PNG"):
    output = io.BytesIO()
    Image.new("RGB", (20, 10), "white").save(output, format=format)
    mime = "jpeg" if format == "JPEG" else "png"
    return "data:image/" + mime + ";base64," + base64.b64encode(output.getvalue()).decode("ascii")


def invoke(parts, handler):
    adapter = OpenAICompatAdapter(
        base_url="https://models.invalid/v1", api_key="fake", transport=httpx.MockTransport(handler)
    )
    return adapter.invoke(
        model="configured-test-model",
        request=make_request(TaskType.OCR_EXTRACT, input_parts=parts),
        timeout_s=2,
    )


@pytest.mark.parametrize("format", ["PNG", "JPEG"])
def test_images_are_multimodal_parts_once_and_not_system_text(format):
    uri = image_uri(format)
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"stem_text":"self authored","expressions":[]}'}}
                ]
            },
        )

    invoke(
        [
            InputPart(kind="text", text="self authored prompt"),
            InputPart(kind="image_ref", media_ref=uri),
        ],
        handler,
    )
    messages = seen[0]["messages"]
    assert uri not in messages[0]["content"]
    content = messages[1]["content"]
    assert isinstance(content, list)
    assert content[-1] == {"type": "image_url", "image_url": {"url": uri}}
    assert "self authored prompt" in content[0]["text"]
    assert uri not in content[0]["text"]
    assert json.dumps(messages).count(uri) == 1


@pytest.mark.parametrize(
    "uri",
    [
        None,
        "",
        "https://example.invalid/private.png",
        "http://127.0.0.1/private.png",
        "file:///C:/private.png",
        r"C:\private.png",
        "data:image/png;base64,not base64!",
        "data:image/gif;base64,R0lG",
        "data:image/png;base64,",
        "data:image/png;base64,YWJj",
        image_uri().replace("image/png", "image/jpeg"),
    ],
)
def test_invalid_images_rejected_before_http(uri):
    def handler(request):
        pytest.fail("invalid image must never reach HTTP")

    with pytest.raises(ProviderError) as error:
        invoke([InputPart(kind="image_ref", media_ref=uri)], handler)
    assert error.value.kind == "rejected"
    assert uri is None or uri not in str(error.value) or uri == ""


@pytest.mark.parametrize(
    "limit", ["MAX_IMAGE_BYTES", "MAX_TOTAL_IMAGE_BYTES", "MAX_IMAGE_PIXELS", "MAX_IMAGES"]
)
def test_image_resource_limits_reject_before_http(monkeypatch, limit):
    import ai_gateway.providers.openai_compat as adapter_module

    monkeypatch.setattr(adapter_module, limit, 1)
    uri = image_uri()
    parts = [InputPart(kind="image_ref", media_ref=uri)] * 2

    def handler(request):
        pytest.fail("oversized images must never reach HTTP")

    with pytest.raises(ProviderError) as error:
        invoke(parts, handler)
    assert error.value.kind == "rejected"


def test_multiple_images_keep_order_without_base64_in_text():
    from ai_gateway.prompts import build_messages

    uris = [image_uri("JPEG"), image_uri("PNG")]
    request = make_request(
        TaskType.OCR_EXTRACT,
        input_parts=[InputPart(kind="image_ref", media_ref=uri) for uri in uris],
    )
    content = build_messages(request)[1]["content"]
    assert [part["image_url"]["url"] for part in content[1:]] == uris
    assert all(uri not in content[0]["text"] for uri in uris)
