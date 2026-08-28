---
title: 1회차 실험 명세
description: 2·3장 회차에서 실제로 돌릴 실험의 조건과 절차. 리허설과 당일 모두 이 문서를 따른다
session: 1
chapters: [2, 3]
host: 설민
tags: [plan]
---

# 1회차 실험 명세

## 공통 조건

모든 실험에 적용한다. 노트에 이 블록을 복사해서 실제 값을 채운다.

```
DB      : PostgreSQL 16, CPU 2, mem 2g
앱      : Spring Boot, CPU 2, mem 1g, HikariCP 기본 10
데이터  : movies 19,701 / genres 19 / movie_genres 47,104 / user_rating 5,030,000
워밍업  : 60초 (JVM JIT. 이 구간 결과는 버린다)
판정    : before/after 3배 이상 차이나면 성공
```

데이터 건수는 2026-08-28 파일럿 기준 실측값이다. `lab/README.md`에 적었던
예상치(19,731 / 49 / 144,741)와 다르다 — genres는 단순 오기, movie_genres는
원본 덤프 세 파일의 export 시각이 서로 달라서(최대 45분 차이) 생긴 실제
데이터 불일치다. 자세한 내용은 `lab/sql/README.md` 참고.

`ANALYZE user_rating;` 을 시딩 후, 그리고 인덱스를 바꿀 때마다 실행한다.
통계가 오래되면 옵티마이저가 옛날 정보로 판단해서 실행계획이 이상하게 나온다.

**테스트 ID (2026-08-28 파일럿 기준 — 재시딩하면 값이 바뀐다. `00_find_test_ids.sql`로 다시 찾을 것)**

```
헤비ID     : 36     (5,000건)
라이트ID   : 46401  (17건)
인기영화ID : 60300  (10,339건 평점)
```

---

# B급 — EXPLAIN 4개 (각 5분)

부하 없이 쿼리 한 번씩. 준비는 쿼리 써두는 게 전부다.

## B-1. 타입이 다른 칼럼 조인 (워밍업용)

**보여줄 것:** 인덱스가 있는데도 안 탄다

Moha 원본에는 varchar↔int 조인이 없으므로 실습용 칼럼을 하나 만든다.

**주의: 캐스팅 방향이 핵심이다.** 캐스팅이 인덱스 없는 쪽 컬럼에 걸리면
인덱스가 정상적으로 탄다 — "안 탄다"를 보여주려면 캐스팅이 반드시
**인덱스가 걸린 컬럼**(`movie_id_str`) 쪽에 있어야 한다.
2026-08-28 파일럿에서 `r.movie_id_str = m.movie_id::varchar`로 썼다가
인덱스가 잘 타버려서 걸렸다 — `m.movie_id`(인덱스 없음) 쪽을 캐스팅했기 때문.

```sql
ALTER TABLE user_rating ADD COLUMN movie_id_str varchar(20);
UPDATE user_rating SET movie_id_str = movie_id::text;
CREATE INDEX idx_rating_movie_str ON user_rating(movie_id_str);
ANALYZE user_rating;

-- 인덱스를 타는 쪽 (movie_id_str에 직접 비교, 실존하는 movie_id로)
EXPLAIN ANALYZE
SELECT * FROM user_rating WHERE movie_id_str = '60300';

-- 타입이 안 맞는 쪽: 캐스팅이 인덱스 걸린 컬럼(movie_id_str)에 걸린다
EXPLAIN ANALYZE
SELECT r.* FROM user_rating r JOIN movies m ON r.movie_id_str::int = m.movie_id
WHERE m.movie_id = 60300;
```

**볼 것:** `Seq Scan`(또는 `Parallel Seq Scan`)이 뜨는지, `Filter`에 타입 변환이 걸려 있는지

쿼리에 쓰는 movie_id는 실제로 존재하는 값이어야 한다(`42`는 이 데이터셋에 없어서
두 쿼리 다 0행이 나와 비교가 안 됐다). `00_find_test_ids.sql`로 확인한 값을 쓴다.

## B-2. 선택도 — 전환점 찾기

**최초 설계(헤비 vs 라이트 유저 비교)는 2026-08-28 파일럿에서 실패했다.**
헤비 유저도 5,000/5,030,000 = 0.1%라 라이트 유저(17건)와 마찬가지로
그냥 Index Scan을 탔다. `user_id`는 값이 10만 개가 넘는 컬럼이라
애초에 어떤 한 값을 찍어도 선택도가 매우 높다 — 두 값을 비교하는 걸로는
Seq Scan 전환점이 안 보인다. 그래서 **"두 값 비교"가 아니라
"조회 대상 비율을 올려가며 전환점을 찾는" 실험으로 바꾼다.**

**2026-08-28 파일럿에서 검증 완료.** 실행계획은 2단계가 아니라 **3단계**로 바뀐다 —
Index Scan → Bitmap Heap Scan → Seq Scan. 아래 쿼리와 실측 비율로 재확정했다
(원안의 "약 30%"는 user_id 1~1000을 300건/명 균등으로 잘못 계산한 값이었다.
1~100이 헤비(5,000건/명)라 실제로는 15.31%밖에 안 된다).

```sql
EXPLAIN ANALYZE SELECT * FROM user_rating WHERE user_id = 36;                    -- 0.10%
EXPLAIN ANALYZE SELECT * FROM user_rating WHERE user_id BETWEEN 1 AND 10;        -- 0.99%
EXPLAIN ANALYZE SELECT * FROM user_rating WHERE user_id BETWEEN 1 AND 100;       -- 9.94%
EXPLAIN ANALYZE SELECT * FROM user_rating WHERE user_id BETWEEN 1 AND 1100;      -- 15.90% (전환 직전)
EXPLAIN ANALYZE SELECT * FROM user_rating WHERE user_id BETWEEN 1 AND 1150;      -- 16.20% (전환 직후)
EXPLAIN ANALYZE SELECT * FROM user_rating WHERE user_id BETWEEN 1 AND 2000;      -- 21.27%
```

`SELECT movie_id, rating`이 아니라 `SELECT *`로 검증했다 — 이 쿼리는 어차피
`user_id`로 필터링하므로 `(movie_id, rating)` 인덱스의 커버링 효과와 무관해서
컬럼을 좁혀도 결과가 달라지지 않는다.

**실측 결과 (user_rating 5,030,000건 기준):**

| 비율 | 쿼리 | 스캔 방식 | 실제 rows | 추정 rows | Execution Time |
|---|---|---|---|---|---|
| 0.10% | `= 36` | Index Scan | 5,000 | 4,844 | 16.7ms |
| 0.99% | `BETWEEN 1 AND 10` | Index Scan | 50,000 | 54,622 | 29.1ms |
| 9.94% | `BETWEEN 1 AND 100` | Bitmap Heap Scan | 500,000 | 534,798 | 431.5ms |
| 15.90% | `BETWEEN 1 AND 1100` | Bitmap Heap Scan | 800,000 | 823,351 | — |
| **16.20%** | `BETWEEN 1 AND 1150` | **Seq Scan** | 815,000 | 837,033 | 240.5ms |
| 21.27% | `BETWEEN 1 AND 2000` | Seq Scan | 1,070,000 | 1,090,199 | 617.3ms |

**전환점: 전체의 약 16%.** (`vault/raw/2026-08-28_pilot_b2_ratio_rehearsal.txt`에 전문 있음.
1150 이후 5,000/10,000/20,000/50,000까지도 전부 Seq Scan을 재확인함)

**볼 것:**
- Index Scan → Bitmap Heap Scan → Seq Scan, 3단계 전환이 실제로 보이는가
- 16% 부근에서 조회 대상을 살짝만 늘려도(1100 → 1150) 계획이 바뀌는 것 —
  "조금씩 나빠지는 게 아니라 어느 순간 뚝 떨어진다"는 걸 보여주는 지점
- 옵티마이저 `rows` 추정치와 실제 `rows` 값의 차이가 비율이 커질수록 어떻게 변하는가
  (추정 오차가 5~7% 수준으로 비교적 정확함 — `ANALYZE`를 직전에 실행해서다)

**#미실험:** Index Scan → Bitmap Heap Scan 전환점(1%~10% 사이)은 이번엔 안 좁혔다.
필요하면 당일 전에 추가로 찾아본다.

## B-3. 커버링 인덱스

**보여줄 것:** 필요한 칼럼이 전부 인덱스에 있으면 테이블을 안 읽는다

**전제조건 — 반드시 먼저 실행:**
```sql
VACUUM user_rating;
```
**시딩 직후에는 `ANALYZE`만으로 부족하다.** 대량 INSERT 후 visibility map이
채워지지 않은 상태라 `Index Only Scan`이 아예 안 나오고 `Bitmap Heap Scan`으로만
나온다(2026-08-28 파일럿에서 확인). `VACUUM`을 빼면 이 실습은 실패한다.

`(movie_id, rating)` 인덱스가 이미 있다.

```sql
-- 인덱스만으로 끝나는 쿼리
EXPLAIN ANALYZE
SELECT movie_id, rating FROM user_rating WHERE movie_id = <인기영화ID>;

-- 테이블을 읽어야 하는 쿼리 (updated_at이 인덱스에 없음)
EXPLAIN ANALYZE
SELECT movie_id, rating, updated_at FROM user_rating WHERE movie_id = <인기영화ID>;
```

**볼 것:** `Index Only Scan` vs `Index Scan`, `Heap Fetches` 수치

## B-4. 단일 vs 복합 인덱스 (컬럼 순서)

**보여줄 것:** 같은 두 칼럼이라도 순서에 따라 다르다

```sql
-- 기준: (user_id, updated_at DESC) 인덱스 있는 상태
EXPLAIN ANALYZE
SELECT * FROM user_rating
WHERE user_id = <헤비ID> AND updated_at >= '2026-01-01'
ORDER BY updated_at DESC LIMIT 100;

-- 인덱스를 지우고 다시
DROP INDEX idx_user_rating__user_updated;
ANALYZE user_rating;
-- 같은 쿼리 재실행

-- 순서를 뒤집어서
CREATE INDEX idx_test_reversed ON user_rating(updated_at DESC, user_id);
ANALYZE user_rating;
-- 같은 쿼리 재실행

-- 네 번째 조건: ORDER BY / LIMIT을 뺀 같은 조건 (idx_test_reversed 있는 상태에서)
EXPLAIN ANALYZE
SELECT * FROM user_rating
WHERE user_id = <헤비ID> AND updated_at >= '2026-01-01';
```

**볼 것:** 네 조건의 실행 시간과 스캔 행 수

**2026-08-28 파일럿에서 나온, 계획에 없던 발견:**
`ORDER BY updated_at DESC LIMIT 100`이 있으면 컬럼 순서를 뒤집은 인덱스
(`updated_at DESC, user_id`)도 기존 인덱스와 거의 차이가 안 났다(2.3ms vs 2.7ms).
`updated_at DESC`가 이미 정렬 순서와 일치해서, LIMIT이 스캔을 일찍 끊어주기 때문으로
보인다(가설). 책은 "컬럼 순서가 중요하다"까지만 말하지만, 실측하면
**"ORDER BY와 인덱스 선두 컬럼이 일치하는지에 따라 달라진다"**가 나온다.
네 번째 조건(ORDER BY 없이)에서 이 가설이 맞는지 확인한다 — LIMIT의 조기 종료
효과가 없어지면 순서를 뒤집은 인덱스가 진짜로 나빠지는지가 이 회차의 예측 소재다.
둘 다 "뒤집으면 무조건 나빠진다"고 예측할 가능성이 높은데, 조건에 따라 틀린다.

실험이 끝나면 원래 인덱스를 복구한다.

---

# A-1. 느린 쿼리가 서버를 무너뜨리는 과정

2장 5개 절 + 3장 1개 절이 여기 묶인다.
(처리량 / 병목 지점 / 커넥션 풀 크기 / 커넥션 대기 시간 / 쿼리 타임아웃 / 오프셋 조회)

## ① 느린 쿼리 만들기

```
GET /lab/ratings?userId=<헤비ID>&offset=0&limit=10
GET /lab/ratings?userId=<헤비ID>&offset=4000&limit=10
```

헤비 유저는 5,000건이므로 offset 4000까지 가능하다.
차이가 부족하면 전체 목록 기준으로 offset을 크게 잡는다.

```
GET /lab/ratings?offset=4900000&limit=10
```

**기록:** 쿼리 한 건 실행 시간 (ms). 다음 단계의 입력값이 된다.

## ② 이론 최대 TPS 계산 — 둘이 같이 산수

책의 공식을 그대로 쓴다.

```
최대 TPS = 커넥션 풀 크기 / 쿼리 실행 시간(초)

예) 풀 10, 쿼리 50ms  →  10 / 0.05 = 200 TPS
```

**이 값을 화이트보드나 노트에 크게 적어둔다.** ③에서 대조할 기준점이다.

여기가 이 회차의 핵심 설계다. 비전공자에게 직관적 예측은 불가능하지만,
책이 산술 모델을 주기 때문에 **예측이 산수로 가능해진다.**
그리고 이 계산은 반드시 틀린다 — 스레드 풀, 네트워크, GC, 직렬화가 다 빠진 이상적 모델이므로.

## ③ 실측

```javascript
// 도착률 기반. VU 기반이 아니다
warmup: constant-arrival-rate, 20 rps, 60s   // 버린다
ramp:   ramping-arrival-rate, 50 → 100 → 200 → 400 → 800, 각 60s
```

**볼 순서**
1. `dropped_iterations` — 0이 아니면 그 실험은 무효. maxVUs 부족인지 서버 포화인지 k6 쪽 CPU로 구분
2. 목표 rate vs 실제 `http_reqs` — 안 따라오기 시작하는 지점이 **포화점**
3. `http_req_waiting` — duration이 아니라 이걸 본다. 순수 서버 처리 시간
4. p95 / p99. **평균은 무시**

**②의 계산값과 대조한다.** 실측이 훨씬 낮게 나온다.
그 차이가 곧 "책이 생략한 것들"이고, 2장 나머지 절 전체가 그걸 설명한다.

## ④ 커넥션 풀 크기 바꾸기

```yaml
spring.datasource.hikari.maximum-pool-size: 2   →  10  →  50
```

앱 재시작이 필요하다. **재시작 시간을 미리 재둔다** (3회 × 재시작 시간).

**Grafana 3패널을 한 화면에**
```
1. TPS                              (k6)
2. p95 응답시간                     (k6)
3. hikaricp_connections_pending     (서버)
```

**하이라이트:** 1번이 안 오르는데 2번과 3번이 치솟는 순간.
"일할 CPU가 남는데 왜 대기하지?"라는 질문이 여기서 나온다.

풀 50에서는 오히려 나빠질 수 있다. 책이 말한 그대로다 —
DB CPU가 이미 높으면 풀을 늘리는 게 아니라 줄여야 한다.
DB 컨테이너 CPU 사용률도 같이 띄워둔다.

## ⑤ 재시도 증폭

책이 2장(커넥션 대기 시간)과 3장(쿼리 타임아웃)에서 **두 번 말하는 유일한 주제.**
저자가 제일 강조하고 싶은 것이다.

```yaml
# 조건 A
spring.datasource.hikari.connection-timeout: 30000

# 조건 B
spring.datasource.hikari.connection-timeout: 1000
```

k6 쪽에서 재시도를 켠다 (일정 시간 응답 없으면 취소하고 재요청).

**볼 것:** 조건 A에서 동시 요청 수가 눈덩이처럼 불어나는 것.
조건 B에서는 빠르게 에러를 받고 부하가 일정 수준으로 유지되는 것.

이게 왜 도착률 기반 부하가 필요한지도 동시에 보여준다.
VU 기반이었으면 "느려지면 부하도 줄어들어" 이 현상이 아예 안 보인다.

---

# A-2. 고치는 과정

3장 3개 절. (ID 기준 조회 / 미리 집계 / 전체 개수 세지 않기)

## ⑥ 커서 페이징으로 교체

```
before: GET /lab/ratings?userId=X&offset=4000&limit=10
after:  GET /lab/ratings?userId=X&cursorId=<마지막ID>&limit=10
```

같은 부하 시나리오를 다시 돌린다. ③④의 숫자와 직접 비교한다.

**볼 것:** 포화점이 어디로 이동했는지. 병목이 사라졌는지 다른 곳으로 옮겼는지.

## ⑦ 통계 API 미리 집계

```sql
-- before: 조회 시점에 센다
SELECT count(*), avg(rating) FROM user_rating WHERE movie_id = ?;

-- after: 미리 집계한 칼럼을 읽는다
ALTER TABLE movies ADD COLUMN rating_count int DEFAULT 0;
ALTER TABLE movies ADD COLUMN rating_sum bigint DEFAULT 0;
-- 배치로 한 번 채우고, 이후엔 평점 등록 시 증감
SELECT rating_count, rating_sum FROM movies WHERE movie_id = ?;
```

**인기 영화 vs 비인기 영화를 둘 다 측정한다.**
책이 말한 "데이터가 많아질수록 count 실행 시간이 증가한다"가 그대로 보인다.

책의 설문 예시(`0.01 + 0.1×30 + 0.05×30 = 4.51초`)와 대조하면 좋다.

---

# 리허설 (혼자, 한 대)

당일 전에 혼자 한 대로 전부 돌려본다. **부하는 낮게** — 한 대에서는
k6와 앱이 CPU를 두고 싸우므로 절대값을 믿을 수 없다.
100 rps 정도로 낮추면 상대 비교는 유효하다.

## 체크리스트

- [ ] DB 컨테이너 메모리가 2g인가 (1g면 `VACUUM`이 공유 메모리 부족으로 실패한다 —
      2026-08-28 파일럿에서 `could not resize shared memory segment` 에러로 확인)
- [ ] `shm_size`가 256mb 이상인가 (`docker-compose.yml`)
- [ ] 쿼리에 쓰는 ID(헤비ID/라이트ID/인기영화ID)가 실제로 존재하는 값인가
      (`00_find_test_ids.sql`로 재확인 — 시딩할 때마다 바뀐다)
- [ ] B급 4개 쿼리가 전부 실행되고, 실행계획에 차이가 보이는가
- [ ] A-1 ①의 쿼리가 충분히 느린가 (offset 0 대비 **3배 이상**)
- [ ] ②의 계산값과 ③의 실측값이 실제로 다른가 (같으면 실험이 무의미)
- [ ] 풀 크기를 바꿨을 때 Grafana 3패널이 눈에 띄게 움직이는가
- [ ] `dropped_iterations`가 0인가
- [ ] ⑤에서 재시도 증폭이 실제로 보이는가
- [ ] ⑥⑦의 after가 before보다 명확히 빠른가

## 시간 재두기

- [ ] 앱 재시작에 몇 초 걸리나 → ④에서 3회 필요
- [ ] 인덱스 DROP/CREATE에 몇 초 걸리나 (500만 건)
- [ ] 시나리오 1회 완주에 몇 분 걸리나 (워밍업 60초 + 램프 240초 = 최소 5분)

**④는 재시작 3회 + 시나리오 3회다.** 여기만 20분 넘게 걸릴 수 있으니
당일 시간 계산에 반드시 넣는다.

## 실패했을 때

| 차이 | 판정 | 조치 |
|---|---|---|
| 3배 이상 | 성공 | 그대로 진행 |
| 1.5~3배 | 애매 | offset을 더 크게, 또는 시딩 추가 |
| 1.5배 미만 | 실패 | 다른 실험으로 교체 |

당일에 차이가 안 나면 그 시간이 통째로 날아간다. **Host의 진짜 준비가 이것이다.**

## 화면 구성 정하기

리허설에서 준비할 것은 설명이 아니라 화면 구성이다.
Grafana에 어떤 패널을 어떤 순서로 띄울지 확정하고 대시보드를 저장해둔다.

처음 25분은 설명 없이 "이 숫자 중에 뭐가 이상해?"만 하면 되므로,
설명 스크립트를 외울 필요는 없다.

---

# 당일 (두 대)

```
[노트북 A — 서버]        [노트북 B — 부하·모니터링]
postgres                  k6
spring app                prometheus
                          grafana
```

Prometheus를 B에 두는 이유: A의 CPU를 뺏지 않고,
k6 결과와 서버 메트릭을 B에서 한 화면에 볼 수 있다.

두 사람이 각각 "서버 쪽"과 "클라이언트 쪽"을 보게 되어 구도도 좋다.

## 시작 전 확인 (10분 잡아둘 것)

- [ ] B에서 `curl http://<A의IP>:8080/lab/ratings?userId=1` 이 열리는가
- [ ] Spring이 `0.0.0.0`에 바인딩돼 있는가 (`localhost`면 외부에서 안 보임)
- [ ] A의 방화벽이 8080을 막고 있지 않은가 (Windows Defender 기본 차단)
- [ ] 공유기에 AP 격리가 켜져 있지 않은가 (기기 간 통신 차단)
- [ ] Prometheus가 A의 `/actuator/prometheus`를 긁고 있는가
      (`prometheus.yml`의 target을 `localhost`가 아니라 A의 IP로)
- [ ] Grafana에 `hikaricp_connections_pending`이 보이는가

**IP는 환경변수로 뺀다.** DHCP라 재부팅하면 바뀔 수 있다.
```
k6 run -e TARGET_HOST=192.168.0.12 script.js
```

## 폴백 — 2대가 안 되면

부하를 100 rps로 낮추고 한 대에서 진행한다.
절대값은 못 믿지만 **같은 세션, 같은 기계에서의 before/after는 유효하다.**

이 점을 회차 시작할 때 명시적으로 합의하고 간다.
"우리 서버는 3000 TPS 나옵니다"는 스터디에서 의미가 없다.

## 진행

| 시간 | 내용 |
|---|---|
| 0:00–0:10 | 환경 확인, 절대값 vs 상대값 합의 |
| 0:10–0:25 | **B급 4개** — EXPLAIN 워밍업 |
| 0:25–0:50 | **관찰** — A-1 ①③ 실행. 숫자만 본다. "뭐가 이상해?" |
| 0:50–1:10 | **개념 도입** — ② 계산. 왜 실측이 낮은지. Host가 책 내용을 꺼냄 |
| 1:10–1:25 | **예측** — 풀 크기를 바꾸면? 둘 다 글로 적는다 |
| 1:25–1:50 | **실행** — ④⑤ |
| 1:50–2:00 | 노트 정리, 넘긴 절 확인, 다음 질문 |

A-2(⑥⑦)는 시간이 남으면. 안 되면 다음 회차 앞부분으로 넘긴다.

**②를 0:50에 두는 게 핵심이다.** 계산을 먼저 하면 답을 알고 실험하게 되고,
그러면 "역시 그렇네"로 끝난다. 실측을 먼저 보고 나서 계산해야
"왜 이렇게 다르지?"가 나온다.

---

# 회차 직후 30분

당일 진행표는 2:00에 끝나지만 여기서 바로 헤어지면 안 된다.
기억이 날아가기 전에 해야 할 것이 남아 있다.

1. `raw/`에 k6 출력, EXPLAIN 결과 전부 저장 (`vault/raw/README.md` 파일명 규칙대로)
2. `exp` 커밋 + 해시를 실험 노트에 기록 (`CLAUDE.md` git 섹션 참고)
3. 실험 노트의 "예측과의 차이" 채우기

**3번까지는 반드시 당일에 한다.** 예측이 맞았는지 틀렸는지에 대한 기억은
하루만 지나도 흐려진다. 나머지는 다음날 해도 된다.

4. `progress.md` 상태 갱신, `log.md` 한 줄 추가
5. 못 다룬 절에 `#미실험` 태그와 넘긴 사유(시간부족/재현위험/뒷장재등장) 적기
