# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "mcp>=1.2,<2",
#     "httpx>=0.27",
#     "openpyxl>=3.1",
# ]
# ///
"""
OpenDART MCP 서버 v2 (개인용)

금융감독원 OpenDART 개발가이드의 API 85개(공시정보·정기보고서·재무·지분·주요사항·증권신고서)를
Claude에서 쓸 수 있게 해 주는 MCP 서버.

v2 변경점
- 비동기 + 병렬 호출(동시 6건, 초당 약 12건 제한) → 긴 검색도 빠르고, 한 요청이 다른 요청을 막지 않음
- 모든 응답 디스크 캐시 → 같은 조회 반복 시 API 한도 소모 없음, 중단된 긴 검색은 다시 부르면 이어서 끝남
- 한 번의 도구 호출은 최대 약 45초. 넘으면 끝난 부분만 돌려주고 남은 기간을 알려 줌
- 응답 필드를 한글 라벨로 변환
- 시장 전체 주요사항 스캔(예: 최근 1년 상장사 물적분할), 분기별 재무제표 엑셀, 아무 표나 엑셀로 저장

환경변수
  DART_API_KEY     (필수) OpenDART 인증키 40자리
  DART_OUTPUT_DIR  (선택) 파일 저장 폴더. 기본값: ~/Downloads
  DART_CACHE_DIR   (선택) 캐시 폴더. 기본값: 이 파일 옆의 .cache
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import re
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dart_catalog as CAT  # noqa: E402

# httpx 요청 로그에는 URL(=인증키)이 찍히므로 끔
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)

VERSION = "2.0.1"
API_BASE = "https://opendart.fss.or.kr/api"
CACHE_DIR = Path(os.environ.get("DART_CACHE_DIR") or HERE / ".cache")
OUTPUT_DIR = Path(os.environ.get("DART_OUTPUT_DIR") or Path.home() / "Downloads")
CONCURRENCY = 6
MIN_INTERVAL = 0.08          # 요청 시작 간 최소 간격(초)
TOOL_BUDGET = 45.0           # 도구 1회 호출 시간 예산(초). 브리지 제한 60초보다 짧게
MAX_OUT_CHARS = 90000

mcp = FastMCP("opendart")

# ---------------------------------------------------------------------------
# 공통 유틸
# ---------------------------------------------------------------------------

STATUS_MESSAGES = {
    "000": "정상", "010": "등록되지 않은 인증키입니다.", "011": "사용할 수 없는 인증키입니다.",
    "012": "접근할 수 없는 IP입니다.", "013": "조회된 데이터가 없습니다.", "014": "파일이 존재하지 않습니다.",
    "020": "요청 제한을 초과했습니다. 잠시 후(또는 내일) 다시 시도하세요.",
    "021": "조회 가능한 회사 개수(최대 100개)를 초과했습니다.", "100": "필드의 부적절한 값입니다.",
    "101": "부적절한 접근입니다.", "800": "시스템 점검 중입니다.", "900": "정의되지 않은 오류입니다.",
    "901": "개인정보 보유기간 만료로 사용할 수 없는 키입니다.",
}
REPORT_CODES = {
    "annual": "11011", "사업보고서": "11011", "연간": "11011", "4q": "11011", "11011": "11011",
    "half": "11012", "반기": "11012", "반기보고서": "11012", "2q": "11012", "11012": "11012",
    "q1": "11013", "1q": "11013", "1분기": "11013", "11013": "11013",
    "q3": "11014", "3q": "11014", "3분기": "11014", "11014": "11014",
}
REPORT_NAMES = {"11011": "사업보고서", "11012": "반기보고서", "11013": "1분기보고서", "11014": "3분기보고서"}
SJ_NAMES = {"BS": "재무상태표", "IS": "손익계산서", "CIS": "포괄손익계산서", "CF": "현금흐름표", "SCE": "자본변동표"}
MARKET_CODES = {"Y": "유가증권", "K": "코스닥", "N": "코넥스", "E": "기타"}


class DartError(Exception):
    def __init__(self, status: str, message: str = ""):
        self.status = status
        super().__init__(f"[{status}] {message or STATUS_MESSAGES.get(status, '알 수 없는 오류')}")


class Budget:
    def __init__(self, seconds: float = TOOL_BUDGET):
        self.end = time.monotonic() + seconds

    def left(self) -> float:
        return max(0.0, self.end - time.monotonic())


def _api_key() -> str:
    key = os.environ.get("DART_API_KEY", "").strip()
    if not key:
        raise DartError("010", "DART_API_KEY 환경변수가 없습니다. Claude 설정 파일의 env에 키를 넣어 주세요.")
    return key


def _report_code(report: str) -> str:
    code = REPORT_CODES.get(str(report).strip().lower())
    if not code:
        raise DartError("100", f"보고서 구분 '{report}'을(를) 알 수 없습니다. annual/half/q1/q3 중 하나를 쓰세요.")
    return code


def _fmt_date(d: str | None) -> str | None:
    if not d:
        return None
    d = re.sub(r"[^0-9]", "", str(d))
    if len(d) != 8:
        raise DartError("100", f"날짜 형식은 YYYYMMDD 또는 YYYY-MM-DD 입니다: {d}")
    return d


def _period(start_date: str | None, end_date: str | None, default_days: int) -> tuple[str, str]:
    end = _fmt_date(end_date) or date.today().strftime("%Y%m%d")
    bgn = _fmt_date(start_date) or (datetime.strptime(end, "%Y%m%d") - timedelta(days=default_days)).strftime("%Y%m%d")
    return (bgn, end) if bgn <= end else (end, bgn)


def _to_num(s: Any) -> float | int | None:
    if s is None:
        return None
    if isinstance(s, bool):
        return None
    if isinstance(s, (int, float)):
        return s
    s = str(s).strip().replace(",", "")
    if s in ("", "-"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        v = float(s)
    except ValueError:
        return None
    if neg:
        v = -v
    return int(v) if v.is_integer() else v


def _years(year: int | None, years: str | None) -> list[int]:
    if years:
        out: list[int] = []
        for part in str(years).replace(" ", "").split(","):
            if "-" in part or "~" in part:
                a, b = re.split(r"[-~]", part)[:2]
                a, b = int(a), int(b)
                out += list(range(min(a, b), max(a, b) + 1))
            elif part:
                out.append(int(part))
        return sorted(set(out))
    return [year or date.today().year - 1]


def _err(e: Exception) -> str:
    return json.dumps({"error": str(e)}, ensure_ascii=False)


def _out(obj: Any) -> str:
    text = json.dumps(obj, ensure_ascii=False, indent=1, default=str)
    if len(text) > MAX_OUT_CHARS:
        text = text[:MAX_OUT_CHARS] + "\n... (응답이 너무 길어 잘렸습니다. 조건을 좁히거나 save_excel/엑셀 도구를 쓰세요)"
    return text


def _labelize(key: str, row: dict, drop: tuple[str, ...] = ("corp_code", "status", "message"),
              max_len: int | None = None) -> dict:
    labels = CAT.labels_for(key)
    out: dict[str, Any] = {}
    for k, v in row.items():
        if k in drop or v is None:
            continue
        if isinstance(v, str):
            v = v.strip()
            if v in ("", "-"):
                continue
            if max_len and len(v) > max_len:
                v = v[:max_len] + "…"
        if k == "corp_cls":
            v = MARKET_CODES.get(v, v)
        label = labels.get(k, k)
        if label in out:
            label = f"{label}[{k}]"
        out[label] = v
    return out


# ---------------------------------------------------------------------------
# HTTP 클라이언트 (병렬·속도제한·캐시·사용량)
# ---------------------------------------------------------------------------


class Dart:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._sem: asyncio.Semaphore | None = None
        self._lock: asyncio.Lock | None = None
        self._last = 0.0
        self.calls_today = 0
        self.cache_hits = 0
        self._usage_day = date.today().isoformat()
        self._load_usage()

    def _usage_file(self) -> Path:
        return CACHE_DIR / "usage.json"

    def _load_usage(self) -> None:
        try:
            d = json.loads(self._usage_file().read_text(encoding="utf-8"))
            if d.get("day") == self._usage_day:
                self.calls_today = int(d.get("calls", 0))
        except Exception:
            pass

    def _save_usage(self) -> None:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            self._usage_file().write_text(json.dumps({"day": self._usage_day, "calls": self.calls_today}), encoding="utf-8")
        except Exception:
            pass

    def _count(self) -> None:
        today = date.today().isoformat()
        if today != self._usage_day:
            self._usage_day, self.calls_today = today, 0
        self.calls_today += 1
        if self.calls_today % 25 == 0:
            self._save_usage()

    def _ensure(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=True,
                                             limits=httpx.Limits(max_connections=CONCURRENCY + 2))
            self._sem = asyncio.Semaphore(CONCURRENCY)
            self._lock = asyncio.Lock()

    async def _throttle(self) -> None:
        assert self._lock is not None
        async with self._lock:
            wait = self._last + MIN_INTERVAL - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()

    @staticmethod
    def _cache_path(endpoint: str, params: dict) -> Path:
        raw = endpoint + "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))
        h = hashlib.sha1(raw.encode("utf-8")).hexdigest()
        return CACHE_DIR / "api" / h[:2] / f"{h}.json"

    @staticmethod
    def _cache_get(path: Path, ttl: float) -> dict | None:
        try:
            if ttl > 0 and path.exists() and time.time() - path.stat().st_mtime < ttl:
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return None

    @staticmethod
    def _cache_put(path: Path, data: dict) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    async def get_json(self, endpoint: str, params: dict[str, Any], ttl: float = 3600) -> dict:
        """JSON API. 캐시(ttl초) 우선. 오류 상태면 DartError (013 '없음'도 캐시)."""
        endpoint = endpoint.strip().lstrip("/").removesuffix(".json").removesuffix(".xml")
        q = {k: str(v) for k, v in params.items() if v not in (None, "")}
        cpath = self._cache_path(endpoint, q)
        data = self._cache_get(cpath, ttl)
        if data is not None:
            self.cache_hits += 1
        else:
            self._ensure()
            assert self._sem is not None and self._client is not None
            last_exc: Exception | None = None
            async with self._sem:
                for attempt in range(3):
                    await self._throttle()
                    try:
                        r = await self._client.get(f"{API_BASE}/{endpoint}.json", params=dict(q, crtfc_key=_api_key()))
                        self._count()
                        r.raise_for_status()
                        data = r.json()
                        break
                    except (httpx.TransportError, httpx.HTTPStatusError, ValueError) as e:
                        last_exc = e
                        await asyncio.sleep(1.0 * (attempt + 1))
            if data is None:
                raise DartError("900", f"OpenDART 접속 실패: {type(last_exc).__name__}")
            if str(data.get("status", "000")) in ("000", "013"):
                self._cache_put(cpath, data)
        st = str(data.get("status", "000"))
        if st != "000":
            raise DartError(st, data.get("message", ""))
        return data

    async def get_binary(self, endpoint: str, params: dict[str, Any], timeout: float = 120.0) -> bytes:
        self._ensure()
        assert self._sem is not None and self._client is not None
        q = {k: str(v) for k, v in params.items() if v not in (None, "")}
        async with self._sem:
            await self._throttle()
            r = await self._client.get(f"{API_BASE}/{endpoint}", params=dict(q, crtfc_key=_api_key()), timeout=timeout)
            self._count()
        r.raise_for_status()
        content = r.content
        if content[:2] != b"PK":
            text = content.decode("utf-8", errors="replace")
            m_status = re.search(r"<status>(\d+)</status>", text) or re.search(r'"status"\s*:\s*"(\d+)"', text)
            m_msg = re.search(r"<message>(.*?)</message>", text) or re.search(r'"message"\s*:\s*"(.*?)"', text)
            raise DartError(m_status.group(1) if m_status else "900", m_msg.group(1) if m_msg else text[:200])
        return content


DART = Dart()


async def _try(coro, empty=None):
    """013(데이터 없음)은 empty로 바꿔 주는 래퍼."""
    try:
        return await coro
    except DartError as e:
        if e.status == "013":
            return empty
        raise


def _ttl_for_period(end_de: str) -> float:
    return 600 if end_de >= date.today().strftime("%Y%m%d") else 86400


def _ttl_for_year(year: int) -> float:
    return 86400 if int(year) >= date.today().year - 1 else 30 * 86400


# ---------------------------------------------------------------------------
# 회사코드 (corpCode.xml)
# ---------------------------------------------------------------------------

_corps: list[dict[str, str]] | None = None
_corps_lock: asyncio.Lock | None = None


async def _load_corps(force: bool = False) -> list[dict[str, str]]:
    global _corps, _corps_lock
    if _corps is not None and not force:
        return _corps
    if _corps_lock is None:
        _corps_lock = asyncio.Lock()
    async with _corps_lock:
        if _corps is not None and not force:
            return _corps
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache = CACHE_DIR / "corp_codes.json"
        if not force and cache.exists() and time.time() - cache.stat().st_mtime < 7 * 86400:
            _corps = json.loads(cache.read_text(encoding="utf-8"))
            return _corps
        try:
            raw = await DART.get_binary("corpCode.xml", {})
        except Exception:
            if cache.exists():
                _corps = json.loads(cache.read_text(encoding="utf-8"))
                return _corps
            raise
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            xml_bytes = zf.read(zf.namelist()[0])
        root = ET.fromstring(xml_bytes)
        corps = [{
            "corp_code": (el.findtext("corp_code") or "").strip(),
            "corp_name": (el.findtext("corp_name") or "").strip(),
            "corp_eng_name": (el.findtext("corp_eng_name") or "").strip(),
            "stock_code": (el.findtext("stock_code") or "").strip(),
        } for el in root.iter("list")]
        cache.write_text(json.dumps(corps, ensure_ascii=False), encoding="utf-8")
        _corps = corps
        return corps


def _norm_name(s: str) -> str:
    return re.sub(r"\(주\)|㈜|주식회사|\s+|[.,&\-]", "", s.lower())


async def _search_corps(query: str, limit: int = 10) -> list[dict[str, str]]:
    corps = await _load_corps()
    q = query.strip()
    if re.fullmatch(r"\d{8}", q):
        return [c for c in corps if c["corp_code"] == q][:limit]
    if re.fullmatch(r"[0-9A-Z]{6}", q.upper()) and any(ch.isdigit() for ch in q):
        hit = [c for c in corps if c["stock_code"] == q.upper()]
        if hit:
            return hit[:limit]
    nq = _norm_name(q)
    scored = []
    for c in corps:
        n, ne = _norm_name(c["corp_name"]), _norm_name(c["corp_eng_name"])
        if n == nq or ne == nq:
            score = 0
        elif n.startswith(nq):
            score = 1
        elif nq in n or (nq and nq in ne):
            score = 2
        else:
            continue
        scored.append((score, 0 if c["stock_code"] else 1, len(c["corp_name"]), c))
    scored.sort(key=lambda t: t[:3])
    return [t[3] for t in scored[:limit]]


async def _resolve(corp: str) -> dict[str, str]:
    hits = await _search_corps(corp, limit=8)
    if not hits:
        raise DartError("013", f"'{corp}'에 해당하는 회사를 찾지 못했습니다. search_company로 먼저 찾아보세요.")
    exact = [h for h in hits if _norm_name(h["corp_name"]) == _norm_name(corp) or h["corp_code"] == corp
             or h["stock_code"] == corp.upper()]
    if exact:
        listed = [h for h in exact if h["stock_code"]]
        if len(listed) == 1 or len(exact) == 1:
            return (listed or exact)[0]
        cands = ", ".join(f"{h['corp_name']}({h['corp_code']}, 종목 {h['stock_code'] or '비상장'})" for h in exact)
        raise DartError("100", f"같은 이름의 회사가 여러 개입니다: {cands}. 고유번호(8자리)나 종목코드로 지정해 주세요.")
    if len(hits) == 1:
        return hits[0]
    cands = ", ".join(f"{h['corp_name']}({h['corp_code']}, 종목 {h['stock_code'] or '비상장'})" for h in hits)
    raise DartError("100", f"'{corp}'와 정확히 일치하는 회사가 없습니다. 후보: {cands}")


# ---------------------------------------------------------------------------
# 도구: 기업 / 카탈로그 / 상태
# ---------------------------------------------------------------------------


@mcp.tool()
async def search_company(query: str, limit: int = 10) -> str:
    """회사명(일부), 영문명, 6자리 종목코드 또는 8자리 DART 고유번호로 회사를 찾습니다.
    다른 도구의 corp 인자에는 회사명·종목코드·고유번호 무엇이든 쓸 수 있지만,
    이름이 겹칠 때는 여기서 찾은 고유번호(corp_code)를 쓰세요."""
    try:
        hits = await _search_corps(query, limit=max(1, min(limit, 50)))
        return _out({"count": len(hits), "results": [
            {"corp_code": h["corp_code"], "corp_name": h["corp_name"], "corp_eng_name": h["corp_eng_name"],
             "stock_code": h["stock_code"] or None, "listed": bool(h["stock_code"])} for h in hits]})
    except Exception as e:
        return _err(e)


@mcp.tool()
async def get_company_info(corp: str) -> str:
    """기업개황: 정식 회사명, 대표자, 법인구분(유가/코스닥/코넥스/기타), 업종코드, 설립일, 결산월, 주소,
    홈페이지, IR, 사업자등록번호 등."""
    try:
        c = await _resolve(corp)
        d = await DART.get_json("company", {"corp_code": c["corp_code"]}, ttl=7 * 86400)
        return _out({k: v for k, v in d.items() if k not in ("status", "message")})
    except Exception as e:
        return _err(e)


@mcp.tool()
async def list_dart_apis(group: str | None = None, query: str | None = None) -> str:
    """이 서버가 아는 OpenDART API 85개 목록(개발가이드 기준).
    group: DS001 공시정보 / DS002 정기보고서 주요정보 / DS003 재무정보 / DS004 지분공시 / DS005 주요사항보고서 / DS006 증권신고서
    query: 한글 키워드(예: '배당', '전환사채', '분할')로 찾기. 어떤 도구로 부르면 되는지(via)도 알려 줍니다."""
    via = {"periodic": "get_periodic_report(item=…)", "event": "get_major_events / scan_major_events",
           "corp": "get_ownership_reports / get_company_info", "special": "전용 도구"}
    items = CAT.find_endpoints(query) if query else list(CAT.ENDPOINTS.values())
    if group:
        items = [e for e in items if e["group"] == group.upper()]
    return _out({"count": len(items), "groups": CAT.GROUPS, "apis": [
        {"endpoint": e["key"], "group": e["group"], "name": e["name"], "keywords": e["aliases"],
         "via": "get_registration_statements" if e["group"] == "DS006" else via[e["kind"]]} for e in items]})


@mcp.tool()
async def server_status(clear_cache: bool = False) -> str:
    """서버 상태: 버전, API 키 설정 여부, 오늘 호출 수(일 한도 약 20,000건), 캐시 크기.
    clear_cache=True면 API 응답 캐시를 비웁니다(회사코드 목록은 유지)."""
    removed = 0
    api_dir = CACHE_DIR / "api"
    if clear_cache and api_dir.exists():
        for p in api_dir.rglob("*.json"):
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    files = list(api_dir.rglob("*.json")) if api_dir.exists() else []
    DART._save_usage()
    return _out({
        "version": VERSION, "api_key": "설정됨" if os.environ.get("DART_API_KEY") else "없음",
        "calls_today": DART.calls_today, "cache_hits_this_session": DART.cache_hits,
        "cache_files": len(files), "cache_mb": round(sum(p.stat().st_size for p in files) / 1e6, 1),
        "cache_removed": removed or None, "output_dir": str(OUTPUT_DIR), "cache_dir": str(CACHE_DIR),
    })


# ---------------------------------------------------------------------------
# 공시 검색
# ---------------------------------------------------------------------------


def _markets(market: str | None) -> list[str | None]:
    if not market:
        return [None]
    alias = {"listed": "Y,K", "상장": "Y,K", "상장사": "Y,K", "kospi": "Y", "유가": "Y", "유가증권": "Y",
             "코스피": "Y", "kosdaq": "K", "코스닥": "K", "konex": "N", "코넥스": "N", "all": "", "전체": ""}
    m = alias.get(market.strip().lower(), market.strip().upper())
    codes = [x.strip().upper() for x in m.split(",") if x.strip()]
    for x in codes:
        if x not in MARKET_CODES:
            raise DartError("100", f"market은 Y(유가), K(코스닥), N(코넥스), E(기타), listed(Y+K) 중에서: {market}")
    return codes or [None]


def _disc_item(x: dict) -> dict:
    return {
        "rcept_no": x.get("rcept_no"), "date": x.get("rcept_dt"), "corp_name": x.get("corp_name"),
        "corp_code": x.get("corp_code"), "stock_code": (x.get("stock_code") or "").strip() or None,
        "market": MARKET_CODES.get(x.get("corp_cls") or "", x.get("corp_cls")),
        "report_nm": re.sub(r"\s+", " ", x.get("report_nm") or "").strip(), "filer": x.get("flr_nm"),
        "remark": x.get("rm") or None,
        "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={x.get('rcept_no')}",
    }


def _windows(bgn: str, end: str, days: int) -> list[tuple[str, str]]:
    d0, d1 = datetime.strptime(bgn, "%Y%m%d"), datetime.strptime(end, "%Y%m%d")
    out, cur_end = [], d1
    while cur_end >= d0:
        cur_bgn = max(d0, cur_end - timedelta(days=days))
        out.append((cur_bgn.strftime("%Y%m%d"), cur_end.strftime("%Y%m%d")))
        cur_end = cur_bgn - timedelta(days=1)
    return out


async def _scan_list(base: dict, bgn: str, end: str, markets: list[str | None], pred, budget: Budget,
                     has_corp: bool) -> tuple[list[dict], dict]:
    """list.json을 기간 분할 + 모든 페이지 병렬로 훑어 pred(row)가 참인 것만 모음."""
    wins = _windows(bgn, end, 3650 if has_corp else 89)
    counter = {"scanned": 0}

    async def scan_window(mk, wb, we):
        params = dict(base, bgn_de=wb, end_de=we, page_count=100)
        if mk:
            params["corp_cls"] = mk
        ttl = _ttl_for_period(we)
        first = await _try(DART.get_json("list", dict(params, page_no=1), ttl=ttl))
        if not first:
            return []
        pages = [first]
        total = int(first.get("total_page") or 1)
        if total > 1:
            pages += await asyncio.gather(*[DART.get_json("list", dict(params, page_no=p), ttl=ttl)
                                            for p in range(2, total + 1)])
        rows = [x for pg in pages for x in pg.get("list", [])]
        counter["scanned"] += len(rows)
        return [x for x in rows if pred(x)]

    jobs = {asyncio.ensure_future(scan_window(mk, wb, we)): (mk, wb, we) for mk in markets for wb, we in wins}
    done, pending = await asyncio.wait(jobs.keys(), timeout=max(1.0, budget.left()))
    found: dict[str, dict] = {}
    errors = []
    for t in done:
        try:
            for x in t.result():
                found[x.get("rcept_no")] = x
        except Exception as e:
            errors.append(f"{jobs[t][1]}~{jobs[t][2]}: {e}")
    unscanned = []
    for t in pending:
        t.cancel()
        mk, wb, we = jobs[t]
        unscanned.append(f"{wb}~{we}" + (f"({MARKET_CODES.get(mk, mk)})" if mk else ""))
    items = sorted(found.values(), key=lambda x: (x.get("rcept_dt") or "", x.get("rcept_no") or ""), reverse=True)
    stats: dict[str, Any] = {"scanned": counter["scanned"], "unscanned_periods": sorted(unscanned) or None,
                             "errors": errors or None}
    if unscanned:
        stats["note"] = ("시간 제한(약 45초)으로 일부 기간을 못 훑었습니다. 같은 조건으로 다시 호출하면 "
                         "이미 받은 부분은 캐시에서 즉시 나오고 나머지를 이어서 훑습니다.")
    return items, stats


@mcp.tool()
async def search_disclosures(
    corp: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    disclosure_type: str | None = None,
    title_contains: str | None = None,
    market: str | None = None,
    final_only: bool = True,
    page: int = 1,
    page_size: int = 50,
    max_results: int = 300,
) -> str:
    """공시 목록 검색.
    - corp: 회사(생략하면 전체 회사)
    - start_date / end_date: YYYYMMDD 또는 YYYY-MM-DD (기본: 최근 1년, 회사·제목 미지정 시 최근 1주)
    - disclosure_type: A 정기공시, B 주요사항보고, C 발행공시, D 지분공시, E 기타공시, F 외부감사관련,
      G 펀드공시, H 자산유동화, I 거래소공시, J 공정위공시
      (세부유형 예: A001 사업보고서, A002 반기, A003 분기, B001 주요사항보고서, D001 주식등의대량보유, I001 수시공시)
    - title_contains: 보고서명에 이 단어가 들어간 것만(여러 개는 | 로, 공백 무시). 주면 기간 전체를
      3개월씩 나눠 모든 페이지를 병렬로 훑고 일치하는 것만 max_results건까지 돌려줍니다(page 무시).
    - market: Y 유가증권 / K 코스닥 / N 코넥스 / E 기타 / listed(유가+코스닥). 쉼표로 여러 개
    - final_only: 정정 전 원본 제외
    주요사항보고서의 '상세 내용'까지 필요하면 scan_major_events가 더 편합니다."""
    try:
        budget = Budget()
        bgn, end = _period(start_date, end_date, 365 if (corp or title_contains) else 7)
        base: dict[str, Any] = {"last_reprt_at": "Y" if final_only else "N"}
        if corp:
            base["corp_code"] = (await _resolve(corp))["corp_code"]
        if disclosure_type:
            t = disclosure_type.strip().upper()
            base["pblntf_ty"] = t[0]
            if len(t) > 1:
                base["pblntf_detail_ty"] = t
        markets = _markets(market)

        if not title_contains:
            if len(markets) > 1:
                raise DartError("100", "여러 시장을 한 번에 보려면 title_contains와 함께 쓰거나 시장별로 나눠 조회하세요.")
            if not corp and (datetime.strptime(end, "%Y%m%d") - datetime.strptime(bgn, "%Y%m%d")).days > 92:
                raise DartError("100", "회사 없이 목록을 볼 때는 3개월까지만 가능합니다. title_contains를 주면 자동으로 나눠 훑습니다.")
            params = dict(base, bgn_de=bgn, end_de=end, page_no=max(1, page), page_count=max(1, min(page_size, 100)))
            if markets[0]:
                params["corp_cls"] = markets[0]
            d = await _try(DART.get_json("list", params, ttl=_ttl_for_period(end)))
            if not d:
                return _out({"total_count": 0, "list": []})
            return _out({"page": d.get("page_no"), "total_pages": d.get("total_page"),
                         "total_count": d.get("total_count"), "list": [_disc_item(x) for x in d.get("list", [])]})

        words = [CAT.norm(w) for w in title_contains.split("|") if w.strip()]
        items, stats = await _scan_list(base, bgn, end, markets,
                                        lambda x: any(w in CAT.norm(x.get("report_nm", "")) for w in words),
                                        budget, bool(corp))
        return _out(dict({"period": f"{bgn}~{end}", "filter": title_contains, "match_count": len(items)}, **stats,
                         list=[_disc_item(x) for x in items[:max(1, max_results)]]))
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------------------
# 공시 원문
# ---------------------------------------------------------------------------


def _dart_xml_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<\s*(br|p|tr|title|section-\d|table|td|th|te|tu|li)[^>]*>", "\n", raw)
    raw = re.sub(r"(?i)</\s*(td|th|te|tu)\s*>", " | ", raw)
    raw = re.sub(r"<[^>]+>", "", raw)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")):
        raw = raw.replace(a, b)
    raw = re.sub(r"[ \t ]+", " ", raw)
    raw = re.sub(r" *\| *(\n|$)", r"\1", raw)
    raw = re.sub(r"\n\s*\n+", "\n\n", raw)
    return raw.strip()


async def _document_text(rcept_no: str) -> str:
    cache = CACHE_DIR / "docs" / f"{rcept_no}.txt"
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    raw = await DART.get_binary("document.xml", {"rcept_no": rcept_no})
    parts = []
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        for name in sorted(zf.namelist()):
            b = zf.read(name)
            for enc in ("utf-8", "euc-kr", "cp949"):
                try:
                    s = b.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                s = b.decode("utf-8", errors="replace")
            parts.append(f"===== [{name}] =====\n" + _dart_xml_to_text(s))
    text = "\n\n".join(parts)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(text, encoding="utf-8")
    return text


@mcp.tool()
async def get_disclosure_document(rcept_no: str, offset: int = 0, max_chars: int = 30000,
                                  keyword: str | None = None, table_of_contents: bool = False) -> str:
    """공시 원문(접수번호 14자리)을 텍스트로 읽습니다.
    - table_of_contents=True: 목차(제목줄과 위치 offset)만 돌려줌 → 원하는 장의 offset으로 다시 호출
    - keyword: 그 단어가 처음 나오는 곳부터(예: '배당', '주요 제품', '분할방법')
    - offset / max_chars: 긴 문서 이어 읽기"""
    try:
        text = await _document_text(rcept_no)
        total = len(text)
        if table_of_contents:
            toc = [{"offset": m.start(), "title": m.group(1).strip()} for m in re.finditer(
                r"(?m)^\s*((?:[IVX]{1,5}|\d{1,2}|[가-하])\s*[.)]\s*\S[^\n]{1,60})$", text)]
            return _out({"rcept_no": rcept_no, "total_chars": total, "toc": toc[:300]})
        if keyword:
            pos = text.find(keyword)
            if pos < 0:
                kw = keyword.replace(" ", "")
                pos = text.replace(" ", "").find(kw)
                if pos < 0:
                    return _out({"total_chars": total, "note": f"'{keyword}'이(가) 문서에 없습니다."})
                # 공백 제거 문자열 위치를 원문 위치로 대략 환산
                seen = 0
                for i, ch in enumerate(text):
                    if ch != " ":
                        if seen == pos:
                            pos = i
                            break
                        seen += 1
            offset = max(0, pos - 300)
        max_chars = max(1000, min(max_chars, 80000))
        chunk = text[offset: offset + max_chars]
        nxt = offset + len(chunk)
        return _out({"rcept_no": rcept_no, "total_chars": total, "offset": offset,
                     "next_offset": nxt if nxt < total else None, "text": chunk})
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------------------
# 정기보고서 주요정보 (DS002)
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_periodic_report(corp: str, item: str, year: int | None = None, years: str | None = None,
                              report: str = "annual") -> str:
    """정기보고서(사업·반기·분기) 주요정보 28종 + Ver2.0 2종. 여러 항목·여러 해를 한 번에 병렬 조회.
    - item: 쉼표로 여러 개. 예) '배당', '최대주주,소액주주', '직원', '임원', '임원개인보수', '상위5인',
      '자기주식', '주식총수', '증자', '감사의견', '감사용역', '비감사용역', '사외이사', '최대주주변동',
      '미등기임원보수', '임원전체보수', '임원보수승인', '임원보수유형', '타법인출자', '채무증권',
      '회사채', '기업어음', '단기사채', '신종자본증권', '조건부자본증권', '공모자금', '사모자금'
      item='목록' 이면 사용 가능한 항목 전체를 보여 줌
    - year: 사업연도(기본: 작년) / years: '2020-2024' 또는 '2022,2024' 처럼 여러 해
    - report: annual / half / q1 / q3"""
    try:
        if CAT.norm(item) in ("목록", "list", "all", "전체"):
            return _out([{"item": e["name"], "keywords": e["aliases"], "endpoint": e["key"]}
                         for e in CAT.ENDPOINTS.values() if e["group"] == "DS002"])
        c = await _resolve(corp)
        rc = _report_code(report)
        yrs = _years(year, years)
        eps = []
        for part in item.split(","):
            if not part.strip():
                continue
            found = CAT.find_endpoints(part, kinds=["periodic"], groups=["DS002"])
            if not found:
                raise DartError("100", f"'{part}' 항목을 모르겠습니다. item='목록'으로 확인하세요.")
            eps.append(found[0])

        async def one(ep, y):
            d = await _try(DART.get_json(ep["key"], {"corp_code": c["corp_code"], "bsns_year": y, "reprt_code": rc},
                                         ttl=_ttl_for_year(y)))
            return ep, y, (d or {}).get("list", [])

        results = await asyncio.gather(*[one(ep, y) for ep in eps for y in yrs])
        out: dict[str, dict] = {}
        for ep, y, rows in results:
            out.setdefault(ep["name"], {})[str(y)] = [
                _labelize(ep["key"], r, drop=("corp_code", "corp_cls", "corp_name", "rcept_no")) for r in rows] or "자료 없음"
        return _out({"company": c["corp_name"], "report": REPORT_NAMES[rc], "data": out})
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------------------
# 주요사항보고서 (DS005) / 증권신고서 (DS006)
# ---------------------------------------------------------------------------

_SUBTYPE_FILTERS = {"물적분할": ("cmpDvDecsn", "물적분할"), "인적분할": ("cmpDvDecsn", "인적분할")}


def _resolve_event(event: str) -> tuple[dict, str | None]:
    n = CAT.norm(event)
    if n in _SUBTYPE_FILTERS:
        key, sub = _SUBTYPE_FILTERS[n]
        return CAT.ENDPOINTS[key], sub
    found = CAT.find_endpoints(event, kinds=["event"], groups=["DS005"])
    if not found:
        raise DartError("100", f"'{event}'에 해당하는 주요사항을 모르겠습니다. list_dart_apis(group='DS005')로 확인하세요.")
    return found[0], None


def _title_matches(report_nm: str, ep: dict) -> bool:
    m = re.search(r"주요사항보고서\s*\((.*)\)\s*$", report_nm or "")
    target = CAT.norm(ep["name"])
    if m:
        return CAT.norm(m.group(1)) == target
    return target in CAT.norm(report_nm)


def _row_text(row: dict) -> str:
    return CAT.norm(" ".join(str(v) for v in row.values() if v))


@mcp.tool()
async def get_major_events(corp: str, event: str = "all", start_date: str | None = None,
                           end_date: str | None = None) -> str:
    """한 회사의 주요사항보고서 상세(36종). 기본 기간: 최근 1년.
    - event: 'all'(36종 전부 병렬 조회) 또는 키워드. 예) '유상증자', '전환사채', 'CB', 'BW', '자사주취득',
      '자사주처분', '합병', '분할', '물적분할', '분할합병', '감자', '무상증자', '타법인주식양수', '영업양수', '소송', '부도', '회생'
    필드는 한글 라벨로 돌려줍니다."""
    try:
        c = await _resolve(corp)
        bgn, end = _period(start_date, end_date, 365)
        if CAT.norm(event) in ("all", "전체"):
            eps, sub = [e for e in CAT.ENDPOINTS.values() if e["group"] == "DS005"], None
        else:
            ep, sub = _resolve_event(event)
            eps = [ep]

        async def one(ep):
            d = await _try(DART.get_json(ep["key"], {"corp_code": c["corp_code"], "bgn_de": bgn, "end_de": end},
                                         ttl=_ttl_for_period(end)))
            return ep, (d or {}).get("list", [])

        res = await asyncio.gather(*[one(ep) for ep in eps])
        out = {}
        for ep, rows in res:
            if sub:
                rows = [r for r in rows if CAT.norm(sub) in _row_text(r)]
            if rows:
                out[ep["name"]] = [dict(_labelize(ep["key"], r, drop=("corp_code", "corp_cls", "corp_name")),
                                        url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={r.get('rcept_no')}")
                                   for r in rows]
        return _out({"company": c["corp_name"], "period": f"{bgn}~{end}",
                     "checked": len(eps), "found": out or "해당 기간에 보고된 주요사항이 없습니다."})
    except Exception as e:
        return _err(e)


@mcp.tool()
async def scan_major_events(
    event: str,
    start_date: str | None = None,
    end_date: str | None = None,
    market: str = "listed",
    detail_contains: str | None = None,
    max_len: int = 300,
    save_excel: bool = False,
) -> str:
    """시장 전체에서 특정 주요사항보고서를 모으고 상세 내용까지 붙여 돌려줍니다.
    예) '최근 1년 상장사 물적분할' → event='물적분할'
    - event: '물적분할', '인적분할', '분할', '합병', '분할합병', '유상증자', '무상증자', '감자', 'CB', 'BW', 'EB',
      '자사주취득', '자사주처분', '타법인주식양수', '영업양수', '영업양도', '유형자산양수', '소송', '부도', '회생' 등
    - 기간: 기본 최근 1년 / market: listed(기본, 유가+코스닥), Y, K, N, E, all
    - detail_contains: 상세 내용에 이 단어가 있는 것만(예: '제3자배정', '운영자금')
    - max_len: 긴 서술형 항목을 이 글자수에서 자름
    - save_excel=True: 결과를 엑셀로 다운로드 폴더에 저장
    동작: 공시목록을 3개월씩 병렬로 훑어 해당 보고서를 찾고 → 회사별 상세 API를 병렬 호출.
    시간이 모자라면 끝난 부분만 돌려주며, 같은 조건으로 다시 부르면 캐시로 이어서 완료합니다."""
    try:
        budget = Budget()
        ep, sub = _resolve_event(event)
        filt = detail_contains or sub
        bgn, end = _period(start_date, end_date, 365)
        markets = _markets(market)
        items, stats = await _scan_list({"last_reprt_at": "Y", "pblntf_ty": "B", "pblntf_detail_ty": "B001"},
                                        bgn, end, markets, lambda x: _title_matches(x.get("report_nm", ""), ep),
                                        budget, False)
        corps = sorted({x["corp_code"] for x in items})
        # 정정공시의 원본이 기간 이전에 있을 수 있어 상세 조회는 1년 앞까지 넓힘
        detail_bgn = (datetime.strptime(bgn, "%Y%m%d") - timedelta(days=365)).strftime("%Y%m%d")

        async def detail(cc):
            d = await _try(DART.get_json(ep["key"], {"corp_code": cc, "bgn_de": detail_bgn, "end_de": end},
                                         ttl=_ttl_for_period(end)))
            return cc, (d or {}).get("list", [])

        details: dict[str, list] = {}
        missing_detail = 0
        if corps:
            jobs = [asyncio.ensure_future(detail(cc)) for cc in corps]
            done, pending = await asyncio.wait(jobs, timeout=max(3.0, budget.left()))
            for t in pending:
                t.cancel()
            for t in done:
                try:
                    cc, rows = t.result()
                    details[cc] = rows
                except Exception:
                    pass
            missing_detail = len(pending)
            if pending:
                stats["note"] = ((stats.get("note") or "") + f" 상세 조회 {len(pending)}개 회사가 시간 내에 끝나지 않았습니다."
                                 " 같은 조건으로 다시 부르면 캐시로 이어서 완료됩니다.").strip()

        # 1) 목록 항목별 상세 행 매칭
        matched: list[tuple[dict, dict | None]] = []
        for x in items:
            rows = details.get(x["corp_code"], [])
            row = next((r for r in rows if r.get("rcept_no") == x["rcept_no"]), None)
            if row is None and rows:
                # 정정공시로 접수번호가 다르면 날짜가 가장 가까운 것
                def dist(r, x=x):
                    try:
                        return abs((datetime.strptime(str(r.get("rcept_no", ""))[:8], "%Y%m%d")
                                    - datetime.strptime(x["rcept_dt"], "%Y%m%d")).days)
                    except ValueError:
                        return 10 ** 6
                row = min(rows, key=dist)
            matched.append((x, row))

        # 2) 상세가 비었거나 빈약한 건(철회 정정공시 등)은 원문으로 확인
        def sparse(row):
            if row is None:
                return True
            meaningful = [k for k, v in row.items() if k not in ("rcept_no", "corp_cls", "corp_code", "corp_name")
                          and isinstance(v, str) and v.strip() not in ("", "-", "예", "아니오")]
            return len(meaningful) < 3

        doc_text: dict[str, str] = {}
        need_doc = [x["rcept_no"] for x, row in matched if sparse(row)]
        if need_doc and budget.left() > 3:
            async def fetch_doc(rn):
                try:
                    return rn, await _document_text(rn)
                except Exception:
                    return rn, ""
            djobs = [asyncio.ensure_future(fetch_doc(rn)) for rn in need_doc]
            ddone, dpend = await asyncio.wait(djobs, timeout=max(2.0, budget.left()))
            for t in dpend:
                t.cancel()
            for t in ddone:
                rn, txt = t.result()
                doc_text[rn] = txt

        results = []
        withdrawn = 0
        for x, row in matched:
            status = None
            excerpt = None
            if sparse(row):
                txt = doc_text.get(x["rcept_no"], "")
                # 서식에 늘 들어 있는 '물적분할의 경우 …' 항목 제목은 판단에서 제외
                txt = re.sub(r"\d+\.\s*물적분할의\s*경우[^\n]*", "", txt)
                head = txt[:2500]
                if re.search(r"철회|절차\s*중단|취소", head):
                    status = "철회·중단"
                    m = re.search(r"(철회\s*내용|철회\s*사유|정정사유)", head)
                    excerpt = re.sub(r"\s+", " ", head[m.start(): m.start() + max_len] if m else head[:max_len]).strip()
                elif txt:
                    status = "상세 비어있음(원문 확인)"
                    m = re.search(r"분할방법|합병방법|증자방식|사채의 종류", txt)
                    excerpt = re.sub(r"\s+", " ", txt[m.start(): m.start() + max_len] if m else txt[:max_len]).strip()
                check_text = CAT.norm(txt[:8000]) if txt else ""
                if filt:
                    if not check_text:
                        continue          # 확인 불가 → 필터에서 제외(보수적)
                    if CAT.norm(filt) not in check_text:
                        continue
            elif filt and CAT.norm(filt) not in _row_text(row):
                continue
            item = _disc_item(x)
            item.pop("filer", None)
            item.pop("corp_code", None)
            item["status"] = status or "유효(최종 공시 기준)"
            if status == "철회·중단":
                withdrawn += 1
            if row and not sparse(row):
                item["detail"] = _labelize(ep["key"], row, drop=("corp_code", "corp_cls", "corp_name", "rcept_no"), max_len=max_len)
            else:
                item["detail"] = {"원문 발췌": excerpt} if excerpt else "상세 미확인"
            results.append(item)

        saved = None
        if save_excel and results:
            flat = []
            for r in results:
                base = {"접수일": r["date"], "회사명": r["corp_name"], "시장": r["market"], "종목코드": r["stock_code"],
                        "상태": r["status"], "보고서명": r["report_nm"], "링크": r["url"]}
                if isinstance(r["detail"], dict):
                    base.update(r["detail"])
                flat.append(base)
            saved = _save_table_xlsx(flat, f"{ep['name']}{'(' + filt + ')' if filt else ''} {bgn}~{end}",
                                     f"{CAT.norm(sub or ep['name'])}_{bgn}-{end}")
        return _out(dict({"event": ep["name"], "filter": filt, "period": f"{bgn}~{end}",
                          "market": [MARKET_CODES.get(m, m) for m in markets if m] or "전체",
                          "reports_found": len(items), "companies": len(corps), "match_count": len(results),
                          "withdrawn_count": withdrawn or None,
                          "detail_pending_companies": missing_detail or None, "excel": saved}, **stats, list=results))
    except Exception as e:
        return _err(e)


@mcp.tool()
async def get_registration_statements(corp: str, kind: str = "all", start_date: str | None = None,
                                      end_date: str | None = None) -> str:
    """증권신고서 요약(6종): 지분증권(유상증자·IPO), 채무증권(회사채), 증권예탁증권(DR), 합병, 주식의포괄적교환·이전, 분할.
    kind: 'all' 또는 '지분증권', '채무증권', '증권예탁증권', '합병', '교환', '분할'. 기본 기간 최근 1년."""
    try:
        c = await _resolve(corp)
        bgn, end = _period(start_date, end_date, 365)
        eps = [e for e in CAT.ENDPOINTS.values() if e["group"] == "DS006"]
        if CAT.norm(kind) not in ("all", "전체"):
            eps = [e for e in eps if CAT.norm(kind) in CAT.norm(e["name"] + "".join(e["aliases"]))]
            if not eps:
                raise DartError("100", f"'{kind}' 종류를 모르겠습니다.")

        async def one(ep):
            d = await _try(DART.get_json(ep["key"], {"corp_code": c["corp_code"], "bgn_de": bgn, "end_de": end},
                                         ttl=_ttl_for_period(end)))
            return ep, d or {}

        out = {}
        for ep, d in await asyncio.gather(*[one(e) for e in eps]):
            groups = d.get("group")
            if groups:
                out[ep["name"]] = {g.get("title") or f"그룹{i}": [_labelize(ep["key"], r, drop=("corp_code", "corp_cls", "corp_name"))
                                                                for r in g.get("list", [])] for i, g in enumerate(groups)}
            elif d.get("list"):
                out[ep["name"]] = [_labelize(ep["key"], r, drop=("corp_code", "corp_cls", "corp_name")) for r in d["list"]]
        return _out({"company": c["corp_name"], "period": f"{bgn}~{end}", "data": out or "해당 기간 증권신고서가 없습니다."})
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------------------
# 재무
# ---------------------------------------------------------------------------


async def _fetch_fs_all(corp_code: str, year: int, reprt_code: str, fs_div: str) -> tuple[list[dict], str]:
    order = [fs_div.upper()] + (["OFS"] if fs_div.upper() == "CFS" else ["CFS"])
    for fd in order:
        d = await _try(DART.get_json("fnlttSinglAcntAll", {"corp_code": corp_code, "bsns_year": year,
                                                            "reprt_code": reprt_code, "fs_div": fd},
                                     ttl=_ttl_for_year(year)))
        if d:
            return d.get("list", []), fd
    raise DartError("013", f"{year}년 {REPORT_NAMES[reprt_code]} 재무제표가 없습니다.")


@mcp.tool()
async def get_financial_statements(corp: str, year: int, report: str = "annual", fs_div: str = "CFS",
                                   statement: str | None = None) -> str:
    """단일회사 전체 재무제표(XBRL, 2015년 이후).
    - report: annual / half / q1 / q3 · fs_div: CFS 연결 / OFS 별도(연결이 없으면 자동 전환)
    - statement: BS 재무상태표, IS 손익, CIS 포괄손익, CF 현금흐름, SCE 자본변동 (생략 시 SCE 제외 전부)
    금액 단위 원. current=당기, prior=전기, prior2=전전기, *_cum=누적."""
    try:
        c = await _resolve(corp)
        rc = _report_code(report)
        rows, used = await _fetch_fs_all(c["corp_code"], year, rc, fs_div)
        want = statement.upper() if statement else None
        out: dict[str, list] = {}
        for r in rows:
            sj = r.get("sj_div")
            if (want and sj != want) or (not want and sj == "SCE"):
                continue
            item = {"account": r.get("account_nm"), "id": r.get("account_id")}
            if sj == "SCE" and r.get("account_detail") not in (None, "", "-"):
                item["detail"] = r.get("account_detail")
            for src, dst in (("thstrm_amount", "current"), ("thstrm_add_amount", "current_cum"),
                             ("frmtrm_amount", "prior"), ("frmtrm_add_amount", "prior_cum"),
                             ("bfefrmtrm_amount", "prior2")):
                v = _to_num(r.get(src))
                if v is not None:
                    item[dst] = v
            out.setdefault(f"{sj} {SJ_NAMES.get(sj, '')}", []).append(item)
        return _out({"company": c["corp_name"], "year": year, "report": REPORT_NAMES[rc],
                     "fs_div": "연결" if used == "CFS" else "별도",
                     "note": None if used == fs_div.upper() else f"요청한 {fs_div} 자료가 없어 {used}로 조회했습니다.",
                     "currency": rows[0].get("currency") if rows else None, "statements": out})
    except Exception as e:
        return _err(e)


@mcp.tool()
async def get_key_financials(corps: list[str], year: int, report: str = "annual") -> str:
    """여러 회사(최대 100개)의 주요 계정(매출액, 영업이익, 당기순이익, 자산·부채·자본총계 등) 비교.
    연결이 있으면 연결, 없으면 별도. 금융업은 제공되지 않을 수 있음."""
    try:
        rc = _report_code(report)
        resolved = await asyncio.gather(*[_resolve(x) for x in corps])
        codes = ",".join(c["corp_code"] for c in resolved)
        d = await DART.get_json("fnlttMultiAcnt", {"corp_code": codes, "bsns_year": year, "reprt_code": rc},
                                ttl=_ttl_for_year(year))
        by_corp: dict[str, dict] = {}
        for r in d.get("list", []):
            key = f"{r.get('corp_name') or r.get('corp_code')} ({'연결' if r.get('fs_div') == 'CFS' else '별도'})"
            by_corp.setdefault(key, {})[r.get("account_nm")] = {
                "current": _to_num(r.get("thstrm_amount")), "prior": _to_num(r.get("frmtrm_amount")),
                "prior2": _to_num(r.get("bfefrmtrm_amount"))}
        for k in list(by_corp):
            if k.endswith("(별도)") and k.replace("(별도)", "(연결)") in by_corp:
                del by_corp[k]
        return _out({"year": year, "report": REPORT_NAMES[rc], "unit": "원", "data": by_corp})
    except Exception as e:
        return _err(e)


RATIO_CODES = {"profitability": "M210000", "수익성": "M210000", "stability": "M220000", "안정성": "M220000",
               "growth": "M230000", "성장성": "M230000", "activity": "M240000", "활동성": "M240000"}
RATIO_NAMES = {"M210000": "수익성", "M220000": "안정성", "M230000": "성장성", "M240000": "활동성"}


@mcp.tool()
async def get_financial_ratios(corps: list[str], year: int, report: str = "annual", category: str = "all") -> str:
    """DART가 계산한 주요 재무지표(2023년 3분기 이후 자료). 회사 1개면 단일회사, 여러 개(최대 100)면 다중회사 API.
    category: 수익성 / 안정성 / 성장성 / 활동성 / all. 과거 연도는 재무제표 값으로 직접 계산하세요."""
    try:
        rc = _report_code(report)
        resolved = await asyncio.gather(*[_resolve(x) for x in corps])
        if category not in ("all", *RATIO_CODES):
            raise DartError("100", "category는 수익성/안정성/성장성/활동성/all 중 하나입니다.")
        cats = list(RATIO_NAMES) if category == "all" else [RATIO_CODES[category]]
        ep = "fnlttCmpnyIndx" if len(resolved) > 1 else "fnlttSinglIndx"
        codes = ",".join(c["corp_code"] for c in resolved)

        async def one(code):
            d = await _try(DART.get_json(ep, {"corp_code": codes, "bsns_year": year, "reprt_code": rc, "idx_cl_code": code},
                                         ttl=_ttl_for_year(year)))
            return code, (d or {}).get("list", [])

        res = await asyncio.gather(*[one(cd) for cd in cats])
        names = {c["corp_code"]: c["corp_name"] for c in resolved}
        out: dict[str, dict] = {}
        for code, rows in res:
            for x in rows:
                comp = names.get(x.get("corp_code"), x.get("corp_name") or x.get("corp_code"))
                out.setdefault(comp, {}).setdefault(RATIO_NAMES[code], {})[x.get("idx_nm")] = _to_num(x.get("idx_val"))
        return _out({"year": year, "report": REPORT_NAMES[rc], "ratios": out or "자료 없음(2023년 3분기 이후만 제공)"})
    except Exception as e:
        return _err(e)


@mcp.tool()
async def get_ownership_reports(corp: str, kind: str = "major", limit: int = 30) -> str:
    """수시 지분공시. kind: major = 5% 이상 대량보유 상황보고 / insider = 임원·주요주주 특정증권 소유상황.
    최근 것부터 limit건. (정기보고서 기준 최대주주는 get_periodic_report(item='최대주주'))"""
    try:
        c = await _resolve(corp)
        ep = "majorstock" if kind == "major" else "elestock"
        d = await _try(DART.get_json(ep, {"corp_code": c["corp_code"]}, ttl=3600))
        rows = sorted((d or {}).get("list", []), key=lambda x: x.get("rcept_dt", ""), reverse=True)[:max(1, limit)]
        return _out({"company": c["corp_name"], "kind": CAT.ENDPOINTS[ep]["name"],
                     "list": [_labelize(ep, r, drop=("corp_code", "corp_cls", "corp_name")) for r in rows] or "해당 보고가 없습니다."})
    except Exception as e:
        return _err(e)


@mcp.tool()
async def dart_api(endpoint: str, params: dict[str, Any] | None = None, korean_labels: bool = True) -> str:
    """OpenDART의 어떤 JSON API든 직접 호출(인증키 자동). list_dart_apis로 엔드포인트명을 확인하세요.
    - params의 corp_code에 회사명/종목코드를 넣어도 됨(쉼표로 여러 회사 가능)
    - reprt_code에 annual/half/q1/q3를 써도 됨 · 날짜는 YYYYMMDD
    - korean_labels=True면 응답 필드명을 한글로 바꿔 줌"""
    try:
        p = dict(params or {})
        key = endpoint.strip().removesuffix(".json").removesuffix(".xml")
        if "corp_code" in p and not re.fullmatch(r"\d{8}(,\d{8})*", str(p["corp_code"])):
            parts = [x.strip() for x in str(p["corp_code"]).split(",") if x.strip()]
            p["corp_code"] = ",".join([(await _resolve(x))["corp_code"] for x in parts])
        if "reprt_code" in p:
            p["reprt_code"] = _report_code(str(p["reprt_code"]))
        for k in ("bgn_de", "end_de"):
            if k in p:
                p[k] = _fmt_date(str(p[k]))
        d = await DART.get_json(key, p, ttl=600)
        d = {k: v for k, v in d.items() if k not in ("status", "message")}
        if korean_labels:
            if isinstance(d.get("list"), list):
                d["list"] = [_labelize(key, r, drop=()) if isinstance(r, dict) else r for r in d["list"]]
            if isinstance(d.get("group"), list):
                for g in d["group"]:
                    g["list"] = [_labelize(key, r, drop=()) for r in g.get("list", [])]
        return _out(d)
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------------------
# 엑셀
# ---------------------------------------------------------------------------


def _safe_filename(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", s).strip()[:120]


def _unique_path(out_dir: Path, base: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{base}.xlsx"
    n = 2
    while path.exists():
        path = out_dir / f"{base} ({n}).xlsx"
        n += 1
    return path


_NUMLIKE = re.compile(r"-?\d{1,3}(,\d{3})+(\.\d+)?|-?\d+(\.\d+)?")


def _save_table_xlsx(rows: list[dict], title: str, filename: str, columns: list[str] | None = None,
                     output_dir: str | None = None) -> str:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    cols = list(columns or [])
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    wb = Workbook()
    ws = wb.active
    ws.title = "data"
    ws["A1"] = title
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = f"출처: OpenDART · 생성 {datetime.now():%Y-%m-%d %H:%M} · {len(rows)}행"
    ws["A2"].font = Font(color="666666", size=9)
    fill, font = PatternFill("solid", fgColor="1F3A5F"), Font(bold=True, color="FFFFFF")
    for j, c in enumerate(cols, 1):
        cell = ws.cell(row=4, column=j, value=c)
        cell.fill, cell.font = fill, font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    widths = [min(max(len(str(c)) * 1.6, 10), 50) for c in cols]
    for i, r in enumerate(rows, 5):
        for j, c in enumerate(cols, 1):
            v = r.get(c)
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False)
            num = None
            codeish = bool(re.search(r"코드|번호|일자|일$|기일|date|code|_no|년월", str(c), re.I))
            if isinstance(v, str) and not codeish:
                s = v.strip()
                # 코드·날짜처럼 보이는 숫자(선행 0, 콤마 없는 6자리 이상)는 문자열 그대로
                plain_digits = re.fullmatch(r"-?\d+", s) is not None
                if (_NUMLIKE.fullmatch(s) and not re.fullmatch(r"0\d+", s)
                        and not (plain_digits and len(s.lstrip("-")) >= 6)):
                    num = _to_num(s)
            elif isinstance(v, (int, float)) and not isinstance(v, bool) and not codeish:
                num = v
            cell = ws.cell(row=i, column=j, value=num if num is not None else v)
            if num is not None:
                cell.number_format = "#,##0.##" if isinstance(num, float) else "#,##0"
            elif isinstance(v, str) and v.startswith("https://"):
                cell.hyperlink = v
                cell.font = Font(color="1F5FBF", underline="single")
            widths[j - 1] = min(max(widths[j - 1], len(str(v or "")) * 1.1), 60)
    for j, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = "C5" if len(cols) > 2 else "A5"
    ws.auto_filter.ref = f"A4:{get_column_letter(max(1, len(cols)))}{4 + len(rows)}"
    path = _unique_path(Path(output_dir).expanduser() if output_dir else OUTPUT_DIR, _safe_filename(filename))
    wb.save(path)
    return str(path)


@mcp.tool()
async def export_table_excel(rows: list[dict[str, Any]], title: str, filename: str | None = None,
                             columns: list[str] | None = None, output_dir: str | None = None) -> str:
    """아무 표(행 목록)나 엑셀로 저장합니다(기본: 다운로드 폴더). 다른 도구 결과를 정리해 저장할 때 사용.
    숫자 문자열은 숫자로, https 링크는 하이퍼링크로 바꾸고 필터·틀고정을 걸어 줍니다. columns로 열 순서 지정."""
    try:
        if not rows:
            raise DartError("100", "rows가 비어 있습니다.")
        path = _save_table_xlsx(rows, title, filename or title, columns, output_dir)
        return _out({"file": path, "rows": len(rows)})
    except Exception as e:
        return _err(e)


@mcp.tool()
async def download_xbrl(rcept_no: str, report: str = "annual", output_dir: str | None = None) -> str:
    """정기보고서의 재무제표 원본 XBRL 파일(zip)을 저장합니다(기본: 다운로드 폴더).
    rcept_no는 사업·반기·분기보고서의 접수번호(search_disclosures로 확인)."""
    try:
        rc = _report_code(report)
        raw = await DART.get_binary("fnlttXbrl.xml", {"rcept_no": rcept_no, "reprt_code": rc})
        out_dir = Path(output_dir).expanduser() if output_dir else OUTPUT_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"XBRL_{rcept_no}.zip"
        path.write_bytes(raw)
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            names = zf.namelist()
        return _out({"file": str(path), "files_in_zip": names[:30]})
    except Exception as e:
        return _err(e)


KEY_ACCOUNTS = [
    ("매출액", "IS", ["ifrs-full_Revenue", "ifrs_Revenue"], ["매출액", "수익(매출액)", "영업수익", "매출"]),
    ("매출원가", "IS", ["ifrs-full_CostOfSales", "ifrs_CostOfSales"], ["매출원가", "영업비용"]),
    ("매출총이익", "IS", ["ifrs-full_GrossProfit", "ifrs_GrossProfit"], ["매출총이익"]),
    ("영업이익", "IS", ["dart_OperatingIncomeLoss"], ["영업이익", "영업이익(손실)"]),
    ("법인세비용차감전순이익", "IS", ["ifrs-full_ProfitLossBeforeTax", "ifrs_ProfitLossBeforeTax"],
     ["법인세비용차감전순이익", "법인세비용차감전순이익(손실)"]),
    ("당기순이익", "IS", ["ifrs-full_ProfitLoss", "ifrs_ProfitLoss"], ["당기순이익", "당기순이익(손실)", "분기순이익", "반기순이익"]),
    ("지배주주순이익", "IS", ["ifrs-full_ProfitLossAttributableToOwnersOfParent", "ifrs_ProfitLossAttributableToOwnersOfParent"],
     ["지배기업의 소유주에게 귀속되는 당기순이익", "지배기업 소유주지분"]),
    ("자산총계", "BS", ["ifrs-full_Assets", "ifrs_Assets"], ["자산총계"]),
    ("유동자산", "BS", ["ifrs-full_CurrentAssets", "ifrs_CurrentAssets"], ["유동자산"]),
    ("현금및현금성자산", "BS", ["ifrs-full_CashAndCashEquivalents", "ifrs_CashAndCashEquivalents"], ["현금및현금성자산"]),
    ("부채총계", "BS", ["ifrs-full_Liabilities", "ifrs_Liabilities"], ["부채총계"]),
    ("유동부채", "BS", ["ifrs-full_CurrentLiabilities", "ifrs_CurrentLiabilities"], ["유동부채"]),
    ("자본총계", "BS", ["ifrs-full_Equity", "ifrs_Equity"], ["자본총계"]),
    ("지배주주지분", "BS", ["ifrs-full_EquityAttributableToOwnersOfParent", "ifrs_EquityAttributableToOwnersOfParent"],
     ["지배기업의 소유주에게 귀속되는 자본", "지배기업 소유주지분"]),
    ("영업활동현금흐름", "CF", ["ifrs-full_CashFlowsFromUsedInOperatingActivities", "ifrs_CashFlowsFromUsedInOperatingActivities"],
     ["영업활동현금흐름", "영업활동으로 인한 현금흐름"]),
    ("투자활동현금흐름", "CF", ["ifrs-full_CashFlowsFromUsedInInvestingActivities", "ifrs_CashFlowsFromUsedInInvestingActivities"],
     ["투자활동현금흐름", "투자활동으로 인한 현금흐름"]),
    ("재무활동현금흐름", "CF", ["ifrs-full_CashFlowsFromUsedInFinancingActivities", "ifrs_CashFlowsFromUsedInFinancingActivities"],
     ["재무활동현금흐름", "재무활동으로 인한 현금흐름"]),
]


def _row_key(r: dict) -> str:
    aid = (r.get("account_id") or "").strip()
    name = (r.get("account_nm") or "").strip()
    base = aid if aid and "미사용" not in aid else "nm:" + re.sub(r"\s", "", name)
    if r.get("sj_div") == "SCE":
        base += "|" + (r.get("account_detail") or "").strip()
    return base


def _cum(r: dict, rc: str) -> float | int | None:
    if rc == "11011":
        return _to_num(r.get("thstrm_amount"))
    v = _to_num(r.get("thstrm_add_amount"))
    return v if v is not None else _to_num(r.get("thstrm_amount"))


_PREV_Q = {"11012": "1Q", "11014": "2Q", "11011": "3Q"}


@mcp.tool()
async def export_financial_excel(
    corp: str,
    start_year: int,
    end_year: int | None = None,
    report: str = "annual",
    fs_div: str = "CFS",
    include_equity_changes: bool = False,
    output_dir: str | None = None,
) -> str:
    """재무제표를 여러 기간에 걸쳐 모아 엑셀(.xlsx)로 저장합니다(기본: 다운로드 폴더).
    시트: 요약(주요계정 + 비율·증가율 수식) / 재무상태표 / 손익계산서 / 포괄손익계산서 / 현금흐름표 (+자본변동표)
    - start_year~end_year: 사업연도 범위(2015년 이후, 최대 15년)
    - report: annual(연간) / half / q1 / q3 (해당 보고서만, 손익·현금흐름은 누적)
              quarterly = 분기별 시계열(1Q~4Q 단독분기 손익·현금흐름, 분기말 재무상태표. 4Q = 연간 − 3Q누적)
    - fs_div: CFS 연결 / OFS 별도(없으면 자동 전환)"""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter

        c = await _resolve(corp)
        end_year = end_year or start_year
        start_year, end_year = min(start_year, end_year), max(start_year, end_year)
        if end_year - start_year > 14:
            raise DartError("100", "한 번에 최대 15개 연도까지 받을 수 있습니다.")
        quarterly = str(report).strip().lower() in ("quarterly", "분기별", "분기")
        rcs = ["11013", "11012", "11014", "11011"] if quarterly else [_report_code(report)]
        years = list(range(start_year, end_year + 1))

        async def fetch(y, rc):
            try:
                rows, used = await _fetch_fs_all(c["corp_code"], y, rc, fs_div)
                return y, rc, rows, used
            except DartError as e:
                if e.status == "013":
                    return y, rc, None, None
                raise

        fetched = await asyncio.gather(*[fetch(y, rc) for y in years for rc in rcs])
        data = {(y, rc): (rows, used) for y, rc, rows, used in fetched if rows}
        if not data:
            raise DartError("013", "요청한 기간에 재무제표 자료가 없습니다.")

        qlabel = {"11013": "1Q", "11012": "2Q", "11014": "3Q", "11011": "4Q"}
        suffix = {"11011": "", "11012": " 반기", "11013": " 1Q", "11014": " 3Q"}
        periods: list[tuple[str, int, str]] = []
        for y in years:
            for rc in rcs:
                if quarterly:
                    periods.append((f"{y}.{qlabel[rc]}", y, rc))
                elif (y, rc) in data:
                    periods.append((f"{y}{suffix[rc]}", y, rc))
        while periods and (periods[-1][1], periods[-1][2]) not in data:
            periods.pop()
        while periods and (periods[0][1], periods[0][2]) not in data:
            periods.pop(0)
        labels = [p[0] for p in periods]
        skipped = [f"{y} {REPORT_NAMES[rc]}" for _, y, rc in periods if (y, rc) not in data]
        if not quarterly:
            skipped += [f"{y} {REPORT_NAMES[rc]}" for y, rc, rows, _ in fetched if not rows]

        sheets_order = ["BS", "IS", "CIS", "CF"] + (["SCE"] if include_equity_changes else [])
        table: dict[str, dict[str, dict]] = {sj: {} for sj in sheets_order}
        for idx in range(len(periods) - 1, -1, -1):
            label, y, rc = periods[idx]
            rows = (data.get((y, rc)) or (None, None))[0] or []
            for r in rows:
                sj = r.get("sj_div")
                if sj not in table:
                    continue
                row = table[sj].setdefault(_row_key(r), {
                    "name": (r.get("account_nm") or "").strip(), "detail": (r.get("account_detail") or "").strip(),
                    "id": (r.get("account_id") or "").strip(), "ord": _to_num(r.get("ord")) or 9999,
                    "first": idx, "vals": {}, "cum": {}, "raw": {}})
                row["cum"][label] = _cum(r, rc)
                row["raw"][label] = _to_num(r.get("thstrm_amount"))

        for sj, rows in table.items():
            for row in rows.values():
                for label, y, rc in periods:
                    if sj in ("BS", "SCE") or not quarterly:
                        row["vals"][label] = row["raw"].get(label) if sj in ("BS", "SCE") else row["cum"].get(label)
                        continue
                    cum = row["cum"].get(label)
                    if rc == "11013":
                        row["vals"][label] = cum
                        continue
                    prev = row["cum"].get(f"{y}.{_PREV_Q[rc]}")
                    if cum is not None and prev is not None:
                        row["vals"][label] = cum - prev
                    elif sj in ("IS", "CIS") and rc != "11011":
                        row["vals"][label] = row["raw"].get(label)   # 분기보고서 손익 '당기' = 3개월
                    else:
                        row["vals"][label] = None

        used_divs = {u for _, u in data.values()}
        div_label = "연결" if used_divs == {"CFS"} else ("별도" if used_divs == {"OFS"} else "연결·별도 혼재")
        mode_label = "분기별" if quarterly else REPORT_NAMES[rcs[0]]

        wb = Workbook()
        thin = Side(style="thin", color="D0D4DA")
        head_fill, head_font, bold = PatternFill("solid", fgColor="1F3A5F"), Font(bold=True, color="FFFFFF"), Font(bold=True)
        num_fmt, pct_fmt = '#,##0;[Red]-#,##0;"-"', '0.0%;[Red]-0.0%;"-"'

        def header(ws, cols, title):
            ws["A1"] = title
            ws["A1"].font = Font(bold=True, size=13)
            ws["A2"] = f"{c['corp_name']} · {div_label} · {mode_label} · 단위: 원 · 출처: OpenDART"
            ws["A2"].font = Font(color="666666", size=9)
            for i, h in enumerate(cols, 1):
                cell = ws.cell(row=4, column=i, value=h)
                cell.fill, cell.font = head_fill, head_font
                cell.alignment = Alignment(horizontal="center", vertical="center")
            ws.freeze_panes = "B5"

        summary = wb.active
        summary.title = "요약"
        header(summary, ["항목"] + labels, f"{c['corp_name']} 재무 요약")

        def find_row(sj_list, ids, names):
            for sj in sj_list:
                rows = table.get(sj) or {}
                for row in rows.values():
                    if row["id"] in ids:
                        return row
                for nm in names:
                    for row in rows.values():
                        if re.sub(r"\s", "", row["name"]) == re.sub(r"\s", "", nm):
                            return row
            return None

        srow: dict[str, int] = {}
        r_i = 5
        for label, sj, ids, names in KEY_ACCOUNTS:
            row = find_row(["IS", "CIS"] if sj == "IS" else [sj], ids, names)
            if row is None:
                continue
            summary.cell(row=r_i, column=1, value=label)
            for j, pl in enumerate(labels, 2):
                summary.cell(row=r_i, column=j, value=row["vals"].get(pl)).number_format = num_fmt
            srow[label] = r_i
            r_i += 1
        r_i += 1
        summary.cell(row=r_i, column=1, value="주요 비율 (수식)").font = bold
        r_i += 1

        def ratio(label, num, den):
            nonlocal r_i
            if num not in srow or den not in srow:
                return
            summary.cell(row=r_i, column=1, value=label)
            for j in range(2, len(labels) + 2):
                col = get_column_letter(j)
                summary.cell(row=r_i, column=j, value=f'=IFERROR({col}{srow[num]}/{col}{srow[den]},"")').number_format = pct_fmt
            r_i += 1

        def growth(label, base, lag):
            nonlocal r_i
            if base not in srow or len(labels) <= lag:
                return
            summary.cell(row=r_i, column=1, value=label)
            for j in range(2 + lag, len(labels) + 2):
                cur, prev = f"{get_column_letter(j)}{srow[base]}", f"{get_column_letter(j - lag)}{srow[base]}"
                summary.cell(row=r_i, column=j, value=f'=IFERROR({cur}/{prev}-1,"")').number_format = pct_fmt
            r_i += 1

        lag = 4 if quarterly else 1
        gl = "(전년동기비)" if quarterly else ""
        growth(f"매출액 증가율{gl}", "매출액", lag)
        growth(f"영업이익 증가율{gl}", "영업이익", lag)
        if quarterly:
            growth("매출액 증가율(전분기비)", "매출액", 1)
        ratio("매출총이익률", "매출총이익", "매출액")
        ratio("영업이익률", "영업이익", "매출액")
        ratio("순이익률", "당기순이익", "매출액")
        ratio("ROE(기말자본, 분기 연환산 안 함)" if quarterly else "ROE(기말자본 기준)",
              "지배주주순이익" if "지배주주순이익" in srow else "당기순이익",
              "지배주주지분" if "지배주주지분" in srow else "자본총계")
        ratio("ROA(기말자산 기준)", "당기순이익", "자산총계")
        ratio("부채비율", "부채총계", "자본총계")
        ratio("유동비율", "유동자산", "유동부채")
        if quarterly:
            summary.cell(row=r_i + 1, column=1, value="※ 손익·현금흐름은 단독 분기(4Q = 연간 − 3분기 누적), 재무상태표는 분기말 잔액입니다.").font = Font(color="999999", size=9)
        elif rcs[0] != "11011":
            summary.cell(row=r_i + 1, column=1, value="※ 손익·현금흐름은 해당 보고서의 누적 기준입니다.").font = Font(color="999999", size=9)
        summary.column_dimensions["A"].width = 30
        for j in range(2, len(labels) + 2):
            summary.column_dimensions[get_column_letter(j)].width = 19

        for sj in sheets_order:
            rows = table[sj]
            if not rows:
                continue
            ws = wb.create_sheet(SJ_NAMES[sj])
            is_sce = sj == "SCE"
            header(ws, ["계정"] + (["구성요소"] if is_sce else []) + labels + ["계정ID"], f"{c['corp_name']} {SJ_NAMES[sj]}")
            ordered = sorted(rows.values(), key=lambda x: (-x["first"], x["ord"]))
            v0 = 3 if is_sce else 2
            for ri, row in enumerate(ordered, 5):
                a = ws.cell(row=ri, column=1, value=row["name"])
                if re.search(r"총계|합계|^영업이익|순이익|현금흐름$|기말", row["name"]):
                    a.font = bold
                if is_sce:
                    ws.cell(row=ri, column=2, value="" if row["detail"] == "-" else row["detail"])
                for j, pl in enumerate(labels):
                    cell = ws.cell(row=ri, column=v0 + j, value=row["vals"].get(pl))
                    cell.number_format = num_fmt
                    cell.border = Border(bottom=thin)
                ws.cell(row=ri, column=v0 + len(labels), value=row["id"]).font = Font(color="999999", size=8)
            ws.column_dimensions["A"].width = 44
            if is_sce:
                ws.column_dimensions["B"].width = 30
            for j in range(len(labels)):
                ws.column_dimensions[get_column_letter(v0 + j)].width = 19
            ws.column_dimensions[get_column_letter(v0 + len(labels))].width = 36

        info = wb.create_sheet("정보")
        for i, (k, v) in enumerate([
            ("회사명", c["corp_name"]), ("고유번호", c["corp_code"]), ("종목코드", c["stock_code"] or "비상장"),
            ("기간 유형", mode_label), ("재무제표 구분", div_label),
            ("기간별 구분", ", ".join(f"{y} {REPORT_NAMES[rc]}:{'연결' if u == 'CFS' else '별도'}"
                                  for (y, rc), (_, u) in sorted(data.items()))),
            ("누락", "; ".join(skipped) or "없음"), ("생성 시각", datetime.now().strftime("%Y-%m-%d %H:%M")),
            ("출처", "금융감독원 OpenDART 단일회사 전체 재무제표 API (fnlttSinglAcntAll)"),
            ("유의", "각 기간 값은 해당 보고서의 당기 금액입니다. 이후 재작성된 수치와 다를 수 있습니다."),
        ], 1):
            info.cell(row=i, column=1, value=k).font = bold
            info.cell(row=i, column=2, value=v)
        info.column_dimensions["A"].width = 16
        info.column_dimensions["B"].width = 100

        yr = f"{years[0]}" if len(years) == 1 else f"{years[0]}-{years[-1]}"
        tag = "_분기별" if quarterly else suffix[rcs[0]].replace(" ", "_")
        path = _unique_path(Path(output_dir).expanduser() if output_dir else OUTPUT_DIR,
                            _safe_filename(f"{c['corp_name']}_재무제표_{yr}_{div_label}{tag}"))
        wb.save(path)
        return _out({
            "file": str(path), "company": c["corp_name"], "periods": labels, "fs_div": div_label, "mode": mode_label,
            "sheets": wb.sheetnames, "skipped": skipped or None,
            "summary_preview": {k: {pl: summary.cell(row=ri, column=j).value for j, pl in enumerate(labels, 2)}
                                for k, ri in srow.items() if k in ("매출액", "영업이익", "당기순이익", "자본총계")},
        })
    except Exception as e:
        return _err(e)


def main() -> None:
    if "--selftest" in sys.argv:
        print("버전:", VERSION, "/ API 키:", "설정됨" if os.environ.get("DART_API_KEY") else "없음")
        print(asyncio.run(search_company("삼성전자", 3)))
        return
    mcp.run()


if __name__ == "__main__":
    main()
