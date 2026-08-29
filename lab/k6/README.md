# k6

> ⚠ ponytail 끄고 작업할 것 — 의도적 복잡도 (`CLAUDE.md` ponytail 섹션 참고)

도착률(arrival rate) 기반으로 짠다. 이유는 `lab/README.md` ⑦ 참고.

| 파일 | 실험 | 바꾸는 것 |
|---|---|---|
| `offset-vs-cursor.js` | 오프셋 페이징 vs 커서 페이징 | `-e MODE=offset\|cursor` |
| `pool-size.js` | 커넥션 풀 크기 (2 / 10 / 50) | `application.yml` + `-e POOL=` |
| `timeout-amplification.js` | 타임아웃 길이와 재시도 증폭 | `application.yml` + `-e COND=A\|B` |

공통 환경변수

```
-e TARGET_HOST=192.168.0.12:8080   # 기본 localhost:8080. 당일 두 대면 노트북 A의 IP
-e PROFILE=rehearsal               # 기본 session. 리허설(한 대)은 부하를 낮춘다
```

공통 규칙
- 워밍업 60초는 타협하지 않는다 (JVM JIT). 이 구간 결과는 버린다
- `dropped_iterations`를 제일 먼저 확인한다. 0이 아니면 그 실험은 무효
- 평균이 아니라 p95를 본다
- `http_req_duration`이 아니라 `http_req_waiting`을 본다

`handleSummary`로 요약을 덮어쓰지 않는다. k6 기본 요약이 그대로 나와야
`vault/raw/`에 원본이 남는다.

## 부하 수준을 README ⑦과 다르게 잡은 이유

`lab/README.md` ⑦의 예시는 **50 → 100 → 200 → 400 → 800 rps**다.
그 숫자를 그대로 쓰면 이 실험들은 측정이 안 된다.

세 스크립트가 모두 쓰는 `/lab/ratings?offset=4900000&limit=10` 은
2026-08-29 실측으로 **한 건에 1.226초**다. 책의 산술 모델을 적용하면

```
최대 TPS = 커넥션 풀 크기 / 쿼리 실행 시간
풀 10  ->  10 / 1.226 = 8.2 TPS
```

이론상 최대가 8 TPS인데 첫 단계부터 50 rps를 부으면 시작하자마자 무너진다.
**"어디서 꺾이는지"가 아니라 "처음부터 안 된다"만 보인다.**
그래서 도착률을 쿼리 비용에 맞춰 다시 잡았다.

그런데 이 8.2 TPS라는 계산도 틀렸다. **DB가 `cpus:2`라서 실제 상한은
풀 크기가 아니라 DB CPU가 정한다.** 실측 지속 가능 처리량은 0.55~0.73 TPS다.

| 스크립트 | 램프 (session) | 근거 |
|---|---|---|
| `offset-vs-cursor.js` | 1 → 2 → 4 → 8 | 실측 지속 가능치(약 0.7 TPS)를 가로지른다 |
| `pool-size.js` | 1 → 2 → 4 → 8 | 〃 |
| `timeout-amplification.js` | 2 → 5 → 10 | 포화가 목적이라 확실히 넘긴다 |

워밍업 도착률도 20 rps가 아니라 1 rps다. 20 rps로 워밍업하면
워밍업 구간에서 이미 포화돼서 JIT 워밍업이 아니라 그냥 과부하가 된다.
**60초라는 길이는 그대로 지킨다.**

### 파일럿에서 두 번 틀렸다

**1차 — 워밍업 3 rps에서 무너졌다.**
단건 1.16초 × 풀 10 = 8 TPS라고 계산하고 워밍업을 3 rps로 잡았는데,
워밍업 구간에서 VU가 54개까지 쌓이고 30초 타임아웃이 났다.
그 산수에 DB CPU가 빠져 있었다. 이게 `001-plan.md` A-1 ②가 말하는
**"이 계산은 반드시 틀린다"의 실제 사례**다. 회차에서 그대로 쓸 수 있다.

**2차 — 가벼운 쿼리로 바꿨더니 아무 일도 안 일어났다.**
풀을 변수로 만들려고 6ms 쿼리(`userId=36&offset=4000`)로 바꾸고
25 → 50 → 100 rps를 돌렸더니 p95 4.06ms, **VU 최대 1개**, dropped 0.
100 rps × 6ms = 동시성 0.6이라 풀 2로도 남아돈다.
**동시성이 풀 크기를 넘지 않으면 풀은 변수가 되지 않는다.**
그래서 무거운 쿼리로 되돌렸다.

## 엔드포인트별 실측 비용 (2026-08-29, 유휴 상태 단건, 풀 10)

부하 수준을 다시 잡을 때 쓰라고 남긴다.

| 엔드포인트 | 평균 |
|---|---|
| `/lab/ratings?offset=4900000&limit=10` | 1.16 s |
| `/lab/ratings?offset=1000000&limit=10` | 0.79 s |
| `/lab/ratings?offset=50000&limit=10` | 0.82 s |
| `/lab/ratings?cursorUpdatedAt=...` (깊음) | 0.11 s |
| `/lab/movies/60300/stats` | 6.2 ms |
| `/lab/ratings?userId=36&offset=4000&limit=10` | 6.3 ms |
| `/lab/movies/16710/stats` | 12.9 ms |

**중요:** 이 단건 값으로 도착률을 정하면 안 된다. 위 표는 경쟁이 없을 때의
값이고, 동시에 여러 건이 들어오면 DB CPU(2코어)를 나눠 쓰느라 훨씬 나빠진다.

무거운 쿼리 6건을 동시에 던졌을 때 실측 (풀만 바꿔가며):

| 풀 | 6건 완료 | 처리량 |
|---|---|---|
| 2 | 8.26 s | **0.73 TPS** |
| 10 | 10.39 s | 0.58 TPS |
| 50 | 10.94 s | 0.55 TPS |

풀을 25배 키웠는데 처리량이 늘기는커녕 약간 줄었다.
`pool-size.js`의 주제가 이것이다.

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
