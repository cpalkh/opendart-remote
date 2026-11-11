"""
OpenDART 원격 MCP 서버 (Vercel용 래퍼)

PC용 server.py(도구 18개)를 손대지 않고 그대로 불러와서, 핸드폰·웹의 Claude가
인터넷으로 접속할 수 있게 HTTP(MCP Streamable HTTP, 무상태 JSON) 엔드포인트로 열어 줍니다.

- 도구 목록·설명·동작은 PC 버전과 동일합니다.
- 엑셀/XBRL 파일은 서버에 남지 않습니다. 대신 '다운로드 링크'를 돌려주고,
  링크를 누르는 순간 같은 조회를 다시 실행해서 파일을 내려줍니다(서명 링크, 7일 유효).

환경변수 (Vercel → Settings → Environment Variables)
  DART_API_KEY  (필수) OpenDART 인증키 40자리
  MCP_TOKEN     (선택) 설정하면 접속 주소가 /mcp/<MCP_TOKEN> 으로 바뀝니다(주소를 아는 사람만 사용).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import shutil
import sys
import tempfile
import time
import uuid
import zlib
from pathlib import Path
from typing import Any
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# 서버리스는 /tmp만 쓸 수 있음. server.py를 불러오기 전에 지정
TMP = Path(tempfile.gettempdir())
os.environ.setdefault("DART_CACHE_DIR", str(TMP / "opendart-cache"))
os.environ.setdefault("DART_OUTPUT_DIR", str(TMP / "opendart-out"))

import server as S  # noqa: E402  (PC용 server.py 그대로)

from starlette.applications import Starlette  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import JSONResponse, PlainTextResponse, Response  # noqa: E402
from starlette.routing import Route  # noqa: E402

PROTOCOL_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]
FILE_TOOLS = {"export_financial_excel", "export_table_excel", "download_xbrl"}
HIDDEN_ARGS = {"output_dir"}          # 원격에서는 의미 없는 인자(PC 폴더 경로)
LINK_TTL = 7 * 86400
MAX_LINK_CHARS = 12000                # 이보다 긴 링크는 브라우저/서버 한도에 걸릴 수 있음

INSTRUCTIONS = (
    "OpenDART(금융감독원 전자공시) 원격 서버. PC용 opendart 서버와 같은 도구 18개.\n"
    "회사 지정은 회사명·종목코드·고유번호(8자리) 모두 가능, 이름이 겹치면 search_company로 고유번호 확인.\n"
    "엑셀/XBRL 도구는 파일 대신 download_url을 돌려준다. 사용자에게 그 링크를 그대로 보여 주면 "
    "핸드폰·PC 브라우저에서 눌러 내려받을 수 있다(7일 유효)."
)


# ---------------------------------------------------------------------------
# 이벤트 루프가 바뀌면(서버리스 재사용) httpx 클라이언트·락을 새로 만든다
# ---------------------------------------------------------------------------
_loop_id: int | None = None


def _fresh_loop_guard() -> None:
    global _loop_id
    lid = id(asyncio.get_running_loop())
    if _loop_id != lid:
        _loop_id = lid
        S.DART._client = None
        S.DART._sem = None
        S.DART._lock = None
        S._corps_lock = None


# ---------------------------------------------------------------------------
# 서명 다운로드 링크
# ---------------------------------------------------------------------------
def _secret() -> bytes:
    key = os.environ.get("LINK_SECRET") or os.environ.get("DART_API_KEY", "")
    return hashlib.sha256(("opendart-link|" + key).encode()).digest()


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _make_link(base_url: str, tool: str, args: dict) -> str | None:
    payload = json.dumps({"t": tool, "a": args, "e": int(time.time()) + LINK_TTL},
                         ensure_ascii=False, separators=(",", ":")).encode()
    d = _b64e(zlib.compress(payload, 9))
    sig = _b64e(hmac.new(_secret(), d.encode(), hashlib.sha256).digest()[:18])
    url = f"{base_url}/dl?d={d}&s={sig}"
    return url if len(url) <= MAX_LINK_CHARS else None


def _read_link(d: str, s: str) -> dict:
    want = _b64e(hmac.new(_secret(), d.encode(), hashlib.sha256).digest()[:18])
    if not hmac.compare_digest(want, s):
        raise PermissionError("링크 서명이 맞지 않습니다.")
    obj = json.loads(zlib.decompress(_b64d(d)))
    if obj.get("e", 0) < time.time():
        raise PermissionError("링크가 만료되었습니다(7일). Claude에게 다시 요청하세요.")
    if obj.get("t") not in FILE_TOOLS:
        raise PermissionError("허용되지 않은 링크입니다.")
    return obj


def _base_url(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


# ---------------------------------------------------------------------------
# 도구 실행
# ---------------------------------------------------------------------------
async def _call_raw(name: str, args: dict) -> str:
    _fresh_loop_guard()
    ctx = S.mcp.get_context()
    res = await S.mcp._tool_manager.call_tool(name, args, context=ctx, convert_result=False)
    return res if isinstance(res, str) else json.dumps(res, ensure_ascii=False, default=str)


async def _run_file_tool(name: str, args: dict) -> tuple[Path, Path]:
    """파일 도구를 임시 폴더에 실행하고 (파일경로, 임시폴더) 반환."""
    work = TMP / "opendart-dl" / uuid.uuid4().hex
    work.mkdir(parents=True, exist_ok=True)
    out = await _call_raw(name, dict(args, output_dir=str(work)))
    try:
        info = json.loads(out)
    except Exception:
        info = {}
    f = info.get("file") if isinstance(info, dict) else None
    if not f or not Path(f).exists():
        shutil.rmtree(work, ignore_errors=True)
        raise RuntimeError(out[:500])
    return Path(f), work


async def _call_tool(name: str, args: dict, base_url: str) -> str:
    args = {k: v for k, v in (args or {}).items() if k not in HIDDEN_ARGS}
    if name not in FILE_TOOLS:
        return await _call_raw(name, args)

    # 파일 도구: 한 번 실행해서 결과 요약을 만들고, 파일은 링크로
    try:
        path, work = await _run_file_tool(name, args)
    except RuntimeError as e:
        return str(e)
    size_kb = round(path.stat().st_size / 1024, 1)
    fname = path.name
    shutil.rmtree(work, ignore_errors=True)
    link = _make_link(base_url, name, args)
    result: dict[str, Any] = {"file_name": fname, "size_kb": size_kb}
    if link:
        result["download_url"] = link
        result["안내"] = "이 링크를 사용자에게 그대로 보여 주세요. 누르면 엑셀/zip이 내려받아집니다(7일 유효)."
    else:
        result["안내"] = ("표가 너무 커서 다운로드 링크를 만들 수 없습니다. 같은 데이터를 조회 도구로 가져와 "
                        "Claude가 직접 엑셀 파일을 만들어 주세요.")
    return json.dumps(result, ensure_ascii=False)


_TOOLS_CACHE: list[dict] | None = None


async def _tools_list() -> list[dict]:
    global _TOOLS_CACHE
    if _TOOLS_CACHE is None:
        tools = []
        for t in await S.mcp.list_tools():
            schema = json.loads(json.dumps(t.inputSchema))
            props = schema.get("properties", {})
            for h in HIDDEN_ARGS:
                props.pop(h, None)
            if "required" in schema:
                schema["required"] = [r for r in schema["required"] if r not in HIDDEN_ARGS]
            desc = (t.description or "").replace("(기본: 다운로드 폴더)", "(원격: 다운로드 링크로 제공)")
            item = {"name": t.name, "description": desc, "inputSchema": schema}
            if t.annotations:
                item["annotations"] = t.annotations.model_dump(exclude_none=True)
            tools.append(item)
        _TOOLS_CACHE = tools
    return _TOOLS_CACHE


# ---------------------------------------------------------------------------
# JSON-RPC (MCP Streamable HTTP, 무상태)
# ---------------------------------------------------------------------------
def _rpc_result(id_, result):
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _rpc_error(id_, code, msg):
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": msg}}


async def _handle(msg: dict, base_url: str) -> dict | None:
    method, id_, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if id_ is None:          # notification (initialized 등)
        return None
    try:
        if method == "initialize":
            req_v = params.get("protocolVersion")
            ver = req_v if req_v in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
            return _rpc_result(id_, {
                "protocolVersion": ver,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "opendart-remote", "version": S.VERSION},
                "instructions": INSTRUCTIONS,
            })
        if method == "ping":
            return _rpc_result(id_, {})
        if method == "tools/list":
            return _rpc_result(id_, {"tools": await _tools_list()})
        if method == "tools/call":
            name = params.get("name")
            if name not in {t["name"] for t in await _tools_list()}:
                return _rpc_error(id_, -32602, f"알 수 없는 도구: {name}")
            try:
                text = await _call_tool(name, params.get("arguments") or {}, base_url)
                return _rpc_result(id_, {"content": [{"type": "text", "text": text}], "isError": False})
            except Exception as e:  # 도구 내부 오류는 결과로 돌려줌
                return _rpc_result(id_, {"content": [{"type": "text", "text": f"오류: {type(e).__name__}: {e}"}],
                                         "isError": True})
        if method in ("resources/list", "prompts/list"):
            return _rpc_result(id_, {method.split("/")[0]: []})
        return _rpc_error(id_, -32601, f"지원하지 않는 메서드: {method}")
    except Exception as e:
        return _rpc_error(id_, -32603, f"{type(e).__name__}: {e}")


def _token_ok(request: Request) -> bool:
    want = os.environ.get("MCP_TOKEN", "").strip()
    got = request.path_params.get("token", "")
    return (not want) or hmac.compare_digest(want, got)


async def mcp_endpoint(request: Request) -> Response:
    if not _token_ok(request):
        return PlainTextResponse("Not Found", status_code=404)
    if request.method == "GET":
        return PlainTextResponse("Method Not Allowed", status_code=405, headers={"Allow": "POST"})
    if request.method == "DELETE":
        return Response(status_code=200)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(_rpc_error(None, -32700, "JSON 파싱 오류"), status_code=400)
    base = _base_url(request)
    if isinstance(body, list):
        outs = [r for r in [await _handle(m, base) for m in body] if r is not None]
        return JSONResponse(outs) if outs else Response(status_code=202)
    out = await _handle(body, base)
    if out is None:
        return Response(status_code=202)
    return JSONResponse(out)


async def download(request: Request) -> Response:
    try:
        obj = _read_link(request.query_params.get("d", ""), request.query_params.get("s", ""))
    except Exception as e:
        return PlainTextResponse(f"다운로드할 수 없습니다: {e}", status_code=403)
    try:
        path, work = await _run_file_tool(obj["t"], obj["a"])
    except Exception as e:
        return PlainTextResponse(f"파일을 만들지 못했습니다: {e}", status_code=500)
    data = path.read_bytes()
    name = path.name
    shutil.rmtree(work, ignore_errors=True)
    mime = ("application/zip" if name.endswith(".zip")
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    return Response(data, media_type=mime, headers={
        "Content-Disposition": f"attachment; filename=\"download{Path(name).suffix}\"; filename*=UTF-8''{quote(name)}",
        "Cache-Control": "no-store",
    })


async def home(request: Request) -> Response:
    key = "설정됨" if os.environ.get("DART_API_KEY") else "없음(Vercel 환경변수 DART_API_KEY를 넣고 Redeploy)"
    path = "/mcp/<MCP_TOKEN>" if os.environ.get("MCP_TOKEN") else "/mcp"
    return PlainTextResponse(f"OpenDART 원격 MCP 서버 v{S.VERSION}\nAPI 키: {key}\n커넥터 주소: 이 사이트 주소 + {path}\n")


app = Starlette(routes=[
    Route("/", home),
    Route("/mcp", mcp_endpoint, methods=["GET", "POST", "DELETE"]),
    Route("/mcp/{token}", mcp_endpoint, methods=["GET", "POST", "DELETE"]),
    Route("/dl", download),
])
