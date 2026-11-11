# OpenDART 원격 MCP 서버

PC용 OpenDART MCP 서버(`server.py`, 도구 18개)를 그대로 Vercel에 올려
핸드폰·웹의 Claude에서도 PC와 똑같이 쓰게 해 주는 서버입니다.

- `api/server.py`, `api/dart_catalog.py` : PC 버전 원본 그대로 (수정 없음)
- `api/index.py` : 원격 접속용 래퍼 (MCP HTTP 엔드포인트 + 다운로드 링크)

## 환경변수
| 이름 | 필수 | 설명 |
|---|---|---|
| `DART_API_KEY` | 필수 | OpenDART 인증키 40자리 |
| `MCP_TOKEN` | 선택 | 넣으면 접속 주소가 `/mcp/<값>` 으로 바뀝니다 |

## 커넥터 주소
`https://<배포주소>/mcp` (MCP_TOKEN을 넣었다면 `https://<배포주소>/mcp/<MCP_TOKEN>`)

## PC 버전과 다른 점
- 엑셀·XBRL은 다운로드 폴더 대신 **다운로드 링크**로 받습니다 (7일 유효, 서명된 링크).
- 캐시는 서버 임시 폴더에 잠깐만 남습니다. 오늘 호출 수(server_status)는 대략적인 값입니다.
