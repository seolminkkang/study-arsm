# k6

> ⚠ ponytail 끄고 작업할 것 — 의도적 복잡도 (`CLAUDE.md` ponytail 섹션 참고)

도착률(arrival rate) 기반으로 짠다. 이유는 `lab/README.md` ⑦ 참고.

| 파일 | 실험 |
|---|---|
| `offset-vs-cursor.js` | 오프셋 페이징 vs 커서 페이징 |
| `pool-size.js` | 커넥션 풀 크기 (2 / 10 / 50) |
| `timeout-amplification.js` | 타임아웃 길이와 재시도 증폭 |

공통 규칙
- 워밍업 60초는 타협하지 않는다 (JVM JIT). 이 구간 결과는 버린다
- `dropped_iterations`를 제일 먼저 확인한다. 0이 아니면 그 실험은 무효
- 평균이 아니라 p95를 본다

출력은 `vault/raw/`에 원본 그대로 저장한다.

## Prometheus remote write (Grafana에 k6 결과 올리기)

받는 쪽은 ⑥에서 준비해뒀다. `lab-prometheus`가
`--web.enable-remote-write-receiver` 로 떠 있다(2026-08-29 확인).

```bash
export K6_PROMETHEUS_RW_SERVER_URL=http://localhost:9090/api/v1/write
# 당일 두 대 구성이면 prometheus가 도는 노트북 B의 IP로.
# k6와 prometheus가 같은 노트북(B)에 있으므로 보통은 localhost 그대로다.

# p95를 Grafana에서 보려면 이게 필요하다. 기본값은 p(99) 하나뿐이라
# k6_http_req_duration_p95 시리즈가 아예 안 생긴다.
export K6_PROMETHEUS_RW_TREND_STATS="p(95),p(99),avg,max"

k6 run -o experimental-prometheus-rw script.js
```

Grafana 대시보드 **"A-1 한 화면"** 의 1번(TPS)·2번(p95) 패널이 이 값을 읽는다.
쿼리는 `k6_http_reqs_total`, `k6_http_req_duration_p95`다.
k6를 안 돌리는 동안 두 패널의 k6 계열은 비어 있는 게 정상이고,
같은 패널의 "서버" 계열은 앱만 떠 있으면 나온다.

**remote write는 `vault/raw/` 저장을 대체하지 않는다.** Prometheus 보존기간을
7일로 잡아놨고, 무엇보다 `raw/`는 두 사람이 직접 읽어야 하는 원본이다
(`CLAUDE.md` 지식의 세 층). 아래 저장 방법을 같이 쓴다.

## 결과 저장 방법

측정하고 결과를 안 남기는 실수가 제일 흔하다. **실행 전에 파일명을 먼저
정하고 시작한다.** (파일명 규칙은 `vault/raw/README.md` 참고)

```bash
# 방법 1: k6 자체 요약 export
k6 run --summary-export=vault/raw/2026-09-06_exp-001_session_k6.json script.js

# 방법 2: 콘솔 출력 전체를 그대로 저장 (요약 지표 외에 로그도 남기고 싶을 때)
k6 run script.js | tee vault/raw/2026-09-06_exp-001_session_k6.txt
```

파일명 규칙:
```
YYYY-MM-DD_exp-NNN_rehearsal_k6.txt   -- 리허설
YYYY-MM-DD_exp-NNN_session_k6.txt     -- 당일
```

리허설과 당일은 조건(한 대 vs 두 대, 부하 크기)이 다르므로 파일명으로
반드시 구분한다. 자세한 이유는 `vault/raw/README.md` 참고.
