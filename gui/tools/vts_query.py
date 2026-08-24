# -*- coding: utf-8 -*-
# gui/tools/vts_query.py
# VTS 参数查询工具：独立建立短连接，授权并查询当前模型参数

import json
import time

import websocket


def query_vts_parameters(emote_cfg: dict, timeout: float = 6.0):
    """查询 VTS 当前模型的参数列表。

    :param emote_cfg: config.yml 的 emote 节点
    :param timeout: 单次连接/接收超时（秒）
    :return: (ok, payload)
        ok=True 时 payload 为 dict：
            {
              "model_name", "model_id",
              "live2d_parameters": [{"name","value","min","max","default"}],
              "tracking_parameters": [{"name","added_by","value","min","max","default"}],
            }
        ok=False 时 payload 为错误信息字符串
    """
    emote_cfg = emote_cfg or {}

    url = f"ws://{emote_cfg.get('vtuber_websocket', '127.0.0.1:8001')}"
    plugin_name = emote_cfg.get("vtuber_pluginName", "") or "MeowlisisVtsQuery"
    plugin_dev = emote_cfg.get("vtuber_pluginDeveloper", "") or "Meowlisis"
    token = emote_cfg.get("vtuber_authenticationToken", "") or ""

    ws = None
    try:
        ws = websocket.create_connection(url, timeout=timeout)

        # 1) 认证
        rid_auth = _rid("auth")
        ws.send(json.dumps({
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": rid_auth,
            "messageType": "AuthenticationRequest",
            "data": {
                "pluginName": plugin_name,
                "pluginDeveloper": plugin_dev,
                "authenticationToken": token,
            },
        }))

        auth_resp = _wait_for(ws, "AuthenticationResponse", rid_auth, timeout)
        if auth_resp is None:
            return False, "等待 VTS 认证响应超时"
        if auth_resp.get("messageType") == "APIError":
            return False, auth_resp.get("data", {}).get("message", "VTS 返回 API 错误")
        if not (auth_resp.get("data") or {}).get("authenticated", False):
            return False, "VTS 认证失败，请检查插件名/开发者/令牌"

        # 2) 查询当前模型的 Live2D 参数（嘴部/身体等模型参数）
        rid_live2d = _rid("live2d")
        ws.send(json.dumps({
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": rid_live2d,
            "messageType": "Live2DParameterListRequest",
            "data": {},
        }))
        live2d_resp = _wait_for(ws, "Live2DParameterListResponse", rid_live2d, timeout)
        if live2d_resp is None:
            return False, "等待 VTS 模型参数列表响应超时"
        if live2d_resp.get("messageType") == "APIError":
            return False, live2d_resp.get("data", {}).get("message", "VTS 返回 API 错误")

        live2d_data = live2d_resp.get("data") or {}
        model_name = live2d_data.get("modelName", "")
        model_id = live2d_data.get("modelID", "")
        live2d_params = _norm_params(
            live2d_data.get("parameters") or [],
            include_added_by=False,
        )

        # 3) 查询 tracking 参数（FaceAngleX 等默认追踪参数 + 插件自定义参数）
        rid_tracking = _rid("tracking")
        ws.send(json.dumps({
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": rid_tracking,
            "messageType": "InputParameterListRequest",
            "data": {},
        }))
        tracking_resp = _wait_for(ws, "InputParameterListResponse", rid_tracking, timeout)
        tracking_params = []
        if tracking_resp is not None and tracking_resp.get("messageType") != "APIError":
            tdata = tracking_resp.get("data") or {}
            tracking_params = _norm_params(
                (tdata.get("defaultParameters") or []) + (tdata.get("customParameters") or []),
                include_added_by=True,
            )
        elif tracking_resp is not None and tracking_resp.get("messageType") == "APIError":
            # tracking 参数查询失败不影响主结果
            pass

        return True, {
            "model_name": model_name,
            "model_id": model_id,
            "live2d_parameters": live2d_params,
            "tracking_parameters": tracking_params,
        }

    except Exception as e:
        return False, f"连接 VTS 失败: {e}"
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass


def _norm_params(raw, include_added_by: bool):
    """统一参数条目结构"""
    out = []
    for p in raw or []:
        if not isinstance(p, dict):
            continue
        name = p.get("name")
        if not name:
            continue
        item = {
            "name": name,
            "value": p.get("value"),
            "min": p.get("min"),
            "max": p.get("max"),
            "default": p.get("defaultValue"),
        }
        if include_added_by:
            item["added_by"] = p.get("addedBy", "")
        out.append(item)
    return out


def _rid(prefix: str) -> str:
    return f"vts_{prefix}_{int(time.time() * 1000)}"


def _wait_for(ws, message_type: str, request_id: str, timeout: float):
    """循环接收直到匹配目标 messageType，忽略无关消息；APIError 直接返回；超时返回 None"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        remaining = deadline - time.time()
        try:
            ws.settimeout(max(0.1, remaining))
            raw = ws.recv()
        except Exception:
            return None
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except Exception:
            continue
        if not isinstance(msg, dict):
            continue
        mt = msg.get("messageType")
        if mt == "APIError":
            return msg
        if mt == message_type:
            rid = msg.get("requestID")
            if rid and request_id and rid != request_id:
                continue
            return msg
    return None
