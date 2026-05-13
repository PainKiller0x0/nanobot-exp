"""Tests for the nanobot-exp QQ rich-media Adapter."""

import pytest

from nanobot.exp.qq import rich_media
from nanobot.exp.qq.media_io import QQ_FILE_TYPE_FILE, QQ_FILE_TYPE_IMAGE


class _FakeRoute:
    def __init__(self, method: str, endpoint: str, **kwargs) -> None:
        self.method = method
        self.endpoint = endpoint
        self.kwargs = kwargs


class _FakeHttp:
    def __init__(self, result: dict) -> None:
        self.result = result
        self.calls: list[tuple[_FakeRoute, dict]] = []

    async def request(self, route: _FakeRoute, **kwargs):
        self.calls.append((route, kwargs))
        return self.result


def test_build_upload_payload_omits_file_name_for_images() -> None:
    endpoint, id_key, payload = rich_media.build_upload_payload(
        chat_id="user1",
        is_group=False,
        file_type=QQ_FILE_TYPE_IMAGE,
        file_data="abc",
        file_name="photo.png",
    )

    assert endpoint == "/v2/users/{openid}/files"
    assert id_key == "openid"
    assert "file_name" not in payload


def test_build_upload_payload_includes_file_name_for_files() -> None:
    endpoint, id_key, payload = rich_media.build_upload_payload(
        chat_id="group1",
        is_group=True,
        file_type=QQ_FILE_TYPE_FILE,
        file_data="abc",
        file_name="doc.pdf",
        srv_send_msg=True,
    )

    assert endpoint == "/v2/groups/{group_openid}/files"
    assert id_key == "group_openid"
    assert payload["file_name"] == "doc.pdf"
    assert payload["srv_send_msg"] is True


@pytest.mark.asyncio
async def test_post_base64file_filters_response_to_file_info() -> None:
    http = _FakeHttp({"file_info": "fi_123", "ttl": 3600})

    result = await rich_media.post_base64file(
        http,
        _FakeRoute,
        chat_id="user1",
        is_group=False,
        file_type=QQ_FILE_TYPE_FILE,
        file_data="abc",
        file_name="doc.pdf",
    )

    assert result == {"file_info": "fi_123"}
    route, kwargs = http.calls[0]
    assert route.method == "POST"
    assert route.endpoint == "/v2/users/{openid}/files"
    assert route.kwargs == {"openid": "user1"}
    assert kwargs["json"]["file_name"] == "doc.pdf"


class _FakeApi:
    def __init__(self) -> None:
        self.group_calls: list[dict] = []
        self.c2c_calls: list[dict] = []

    async def post_group_message(self, **kwargs) -> None:
        self.group_calls.append(kwargs)

    async def post_c2c_message(self, **kwargs) -> None:
        self.c2c_calls.append(kwargs)


@pytest.mark.asyncio
async def test_post_media_message_routes_group_and_c2c() -> None:
    api = _FakeApi()
    media_obj = {"file_info": "fi_123"}

    await rich_media.post_media_message(
        api,
        chat_id="group1",
        is_group=True,
        msg_id="m1",
        msg_seq=2,
        media_obj=media_obj,
    )
    await rich_media.post_media_message(
        api,
        chat_id="user1",
        is_group=False,
        msg_id="m2",
        msg_seq=3,
        media_obj=media_obj,
    )

    assert api.group_calls == [
        {
            "group_openid": "group1",
            "msg_type": 7,
            "msg_id": "m1",
            "msg_seq": 2,
            "media": media_obj,
        }
    ]
    assert api.c2c_calls == [
        {
            "openid": "user1",
            "msg_type": 7,
            "msg_id": "m2",
            "msg_seq": 3,
            "media": media_obj,
        }
    ]
