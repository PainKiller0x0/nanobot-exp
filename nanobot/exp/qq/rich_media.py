"""QQ rich-media upload and send helpers."""

from __future__ import annotations

from typing import Any

from nanobot.exp.qq.media_io import QQ_FILE_TYPE_IMAGE


def upload_endpoint(is_group: bool) -> tuple[str, str]:
    """Return (endpoint, id_key) for QQ rich-media upload."""
    if is_group:
        return "/v2/groups/{group_openid}/files", "group_openid"
    return "/v2/users/{openid}/files", "openid"


def build_upload_payload(
    *,
    chat_id: str,
    is_group: bool,
    file_type: int,
    file_data: str,
    file_name: str | None = None,
    srv_send_msg: bool = False,
) -> tuple[str, str, dict[str, Any]]:
    """Build the QQ base64 file upload route data and JSON payload."""
    endpoint, id_key = upload_endpoint(is_group)
    payload: dict[str, Any] = {
        id_key: chat_id,
        "file_type": file_type,
        "file_data": file_data,
        "srv_send_msg": srv_send_msg,
    }
    if file_type != QQ_FILE_TYPE_IMAGE and file_name:
        payload["file_name"] = file_name
    return endpoint, id_key, payload


async def post_base64file(
    http: Any,
    route_cls: Any,
    *,
    chat_id: str,
    is_group: bool,
    file_type: int,
    file_data: str,
    file_name: str | None = None,
    srv_send_msg: bool = False,
) -> Any:
    """Upload base64-encoded file and return QQ's compact Media object."""
    endpoint, id_key, payload = build_upload_payload(
        chat_id=chat_id,
        is_group=is_group,
        file_type=file_type,
        file_data=file_data,
        file_name=file_name,
        srv_send_msg=srv_send_msg,
    )
    route = route_cls("POST", endpoint, **{id_key: chat_id})
    result = await http.request(route, json=payload)
    if isinstance(result, dict) and "file_info" in result:
        return {"file_info": result["file_info"]}
    return result


async def post_media_message(
    api: Any,
    *,
    chat_id: str,
    is_group: bool,
    msg_id: str | None,
    msg_seq: int,
    media_obj: Any,
) -> None:
    """Send an uploaded media object as QQ msg_type=7."""
    if is_group:
        await api.post_group_message(
            group_openid=chat_id,
            msg_type=7,
            msg_id=msg_id,
            msg_seq=msg_seq,
            media=media_obj,
        )
        return

    await api.post_c2c_message(
        openid=chat_id,
        msg_type=7,
        msg_id=msg_id,
        msg_seq=msg_seq,
        media=media_obj,
    )


__all__ = [
    "build_upload_payload",
    "post_base64file",
    "post_media_message",
    "upload_endpoint",
]
