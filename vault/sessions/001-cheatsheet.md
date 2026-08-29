---
title: 1회차 커닝페이퍼
description: 리허설·당일에 옆에 띄워놓고 그대로 치는 용도. 설명은 001-plan.md에 있다
session: 1
chapters: [2, 3]
tags: [cheatsheet]
---

# 1회차 커닝페이퍼

**설명 없음. 명령어와 질문만.** "왜"가 필요하면 [[001-plan]]을 연다.

> **시작 전 5분: [[001-overview]] 를 팀원과 함께 본다.**

한 대에서 진행한다. 총 2시간 30분.

> 오늘 답하는 질문: **"느리다"고 할 때, 어디가 느린지 어떻게 찾는가**
>
> B급  = DB 안에서 찾는 법 (쿼리 하나 단위)
> A-1 = 서버 전체에서 찾는 법 (부하 걸었을 때)
> A-2 = 찾았으면 고쳐본다. 근데 고치는 것도 함정이 있다

### 결과 나오면 뭐라고 하나

> **설명하려고 하지 마라. 어긋난 걸 짚기만 한다.**
>
> - "위는 Index Scan인데 아래는 Seq Scan이네. 뭐가 달랐지?"
> - "부하는 올리는데 TPS가 안 오르네. 근데 p95는 올라가"
> - "인덱스 걸었는데 더 느려졌네"
>
> 답은 둘이 같이 찾는다. Host가 답을 갖고 있을 필요 없다.
> 개념 설명이 필요하면 그때 책을 편다. 외워서 하지 않는다.

> **배수를 인용하지 말 것.**
> B-3이 회차 간 1,788배 → 128배로 요동쳤고(OS 페이지 캐시), 풀 실험도 25% 편차가 있다.
> "3배" "100배" 대신 **"빨라진다 / 느려진다 / 안 변한다"** 방향만 말한다.

### 원복 규칙 — 실험이 만든 건 그 실험 끝나면 바로 지운다

| 실험 | 만드는 것 | 지우는 시점 |
|---|---|---|
| B-1 | `movie_id_str` 칼럼 + `idx_rating_movie_str` | **B-1 직후 (`VACUUM FULL` 필수)** |
| B-4 | `idx_test_reversed` / `user_updated` 인덱스를 지움 | **B-4 직후** |
| A-2 ⑥ | `idx_user_rating__updated` | **A-2 직후** |
| A-2 ⑦ | `movies.rating_count`, `rating_sum` | **A-2 직후** |

> 이전 실험이 남긴 칼럼·인덱스가 다음 실험의 실행계획을 바꾼다.
> 테이블 구조가 바뀌면 옵티마이저 판단도 바뀐다.

**B-1만 `VACUUM FULL`이 필요하다.** `UPDATE` 503만 건이 테이블을 735MB로
부풀리는데 칼럼만 지워서는 안 돌아온다. 나머지는 인덱스만 만들므로 불필요.

---

## 시작 전 확인 (10분)

```bash
cd C:/seolmin/backend-study/lab/docker && docker compose up -d
docker compose ps
```
→ `lab-postgres` `lab-prometheus` `lab-grafana` `lab-docker-stats-exporter` 4개 Up

```bash
docker exec lab-postgres psql -U lab -d labdb -c "
SELECT 'movies' t, count(*) FROM movies
UNION ALL SELECT 'user_rating', count(*) FROM user_rating;"
```
→ `19701` / `5030000`

```bash
docker exec lab-postgres psql -U lab -d labdb -c "VACUUM user_rating;"
docker exec lab-postgres psql -U lab -d labdb -c "ANALYZE user_rating;"
docker exec lab-postgres psql -U lab -d labdb -c "
SELECT last_vacuum, last_analyze FROM pg_stat_user_tables WHERE relname='user_rating';"
```
→ 둘 다 오늘 날짜. **VACUUM 빠지면 B-3이 실패한다.**

```bash
docker exec lab-postgres psql -U lab -d labdb -c "\di"
```
→ **5줄이 정상.** `genres_pkey` `movies_pkey` `movie_genres_pkey`(기본키, 항상 있음)
\+ `idx_user_rating__movie_rating` `idx_user_rating__user_updated`(베이스라인)

개수가 아니라 **없어야 할 게 섞였나**를 본다. 아래 셋이 보이면 원복 안 된 것:
`idx_rating_movie_str`(B-1) · `idx_test_reversed`(B-4) · `idx_user_rating__updated`(A-2)

섞여 있으면:
```bash
cd C:/seolmin/backend-study/lab/sql
docker exec -i lab-postgres psql -U lab -d labdb < 99_cleanup.sql
docker exec -i lab-postgres psql -U lab -d labdb < 04_indexes.sql
```

앱 띄우기:
```bash
cd C:/seolmin/backend-study/lab/app && ./gradlew bootRun
```
```bash
curl "http://localhost:8080/lab/movies?limit=1"
curl -s http://localhost:8080/actuator/prometheus | grep hikaricp_connections_max
```
→ JSON 나오고 `max=10.0`

Grafana: http://localhost:3000 → `lab` 폴더 → **A-1 한 화면**

→ **3번 패널에 `max`·`idle` 선이 10에 그려져 있으면 정상.**
   `pending`·`active`는 0, 4번(DB CPU)도 0이라 바닥에 눌려 안 보이는 게 맞다.
   **유휴 상태에서 3·4번이 평평한 게 정상이다.** 부하를 걸어야 움직인다.

→ 1번 패널은 위 `curl`을 칠 때마다 잠깐 솟았다 내려온다. 그것도 정상.

값이 진짜 안 들어오는지 의심되면 Grafana 말고 여기서 확인:
```bash
curl -s -G http://localhost:9090/api/v1/query --data-urlencode 'query=hikaricp_connections_max'
curl -s -G http://localhost:9090/api/v1/query --data-urlencode 'query=dockerstats_cpu_usage_ratio{name="lab-postgres"}'
```
→ `"value":[...,"10"]` / `"value":[...,"0"]` 처럼 나오면 들어오고 있는 것

### 합의하고 시작 (2분)

> **오늘 절대값은 안 믿는다. 같은 기계에서 조건만 바꾼 상대 비교만 본다.**
> "우리 서버 몇 TPS"는 의미 없다. "풀을 바꿨더니 어느 쪽으로 움직였나"만 본다.

### 오늘 쓰는 ID

아래 SQL·curl 명령에 이 숫자들이 그대로 박혀 있다.

| | ID | 쓰는 곳 |
|---|---|---|
| 헤비 유저 | `36` (5,000건) | B-2, B-4 |
| 라이트 유저 | `46401` (17건) | B-2 |
| 인기 영화 | `60300` (10,339건) | B-1, B-3, A-2 ⑦ |
| 비인기 영화 | `16710` (109건) | A-2 ⑦ |

**`03_seed_ratings.sql`을 다시 돌렸다면** 이 숫자들을 새로 찾아서
아래 명령들의 숫자를 갈아끼운다. 재시딩 안 했으면 건너뛴다.

```bash
cd C:/seolmin/backend-study/lab/sql
docker exec -i lab-postgres psql -U lab -d labdb < 00_find_test_ids.sql
```

시딩이 `random()`을 써서 **어느 영화에 몇 건이 몰리는지가 매번 달라진다.**
유저 쪽은 잘 안 바뀐다 — `user_id ≤ 100`이 헤비, `10,101` 이상이 라이트로 고정 설계다.

---

## B급 4개 (20분)

> 네 개 다 같은 얘기다 — **인덱스가 있어도 안 먹는 경우들.**

### B-1 타입 다른 칼럼 조인 (5분) · 3장 「타입이 다른 칼럼 조인 주의」

> 보여주는 것: **타입이 안 맞으면** 인덱스가 무용지물이 된다

**비교 조건 — 변수는 하나뿐이다**

| | 쿼리 ①  | 쿼리 ② |
|---|---|---|
| 하는 일 | 영화 60300의 평점 전부 가져오기 | (똑같음) |
| 형태 | `user_rating` ⋈ `movies` 조인 | **조인 (고정)** |
| 조인 칼럼 | `r.movie_id` (bigint) | **`r.movie_id_str::int` (varchar→int)** ← 변수 |
| 인덱스 | 양쪽 다 있음 | 양쪽 다 있음 (고정) |

**준비** — 실습용 문자열 칼럼과 인덱스를 만든다 (한 번에 실행, 약 30초)
```bash
docker exec lab-postgres psql -U lab -d labdb -c "
ALTER TABLE user_rating ADD COLUMN movie_id_str varchar(20);
UPDATE user_rating SET movie_id_str = movie_id::text;
CREATE INDEX idx_rating_movie_str ON user_rating(movie_id_str);
ANALYZE user_rating;"
```

**① 타입 같음 (bigint ↔ bigint)** — 영화 60300에 달린 평점을 조인으로 가져온다
```bash
docker exec lab-postgres psql -U lab -d labdb -c "
EXPLAIN ANALYZE SELECT r.* FROM user_rating r JOIN movies m
ON r.movie_id = m.movie_id WHERE m.movie_id = 60300;"
```

**② 타입 다름 (varchar→int ↔ bigint)** — 완전히 같은 결과를 문자열 칼럼으로 조인
```bash
docker exec lab-postgres psql -U lab -d labdb -c "
EXPLAIN ANALYZE SELECT r.* FROM user_rating r JOIN movies m
ON r.movie_id_str::int = m.movie_id WHERE m.movie_id = 60300;"
```

👉 가리킬 곳

| | ① 타입 같음 | ② 타입 다름 |
|---|---|---|
| 스캔 | `Bitmap Index Scan on idx_user_rating__movie_rating` | **`Parallel Seq Scan`** |
| Filter | 없음 | `((movie_id_str)::integer = 60300)` |
| 버린 행 | — | `Rows Removed by Filter: 1,673,220` |

❓ **"차이는 `movie_id` 하나뿐인데 왜 아래만 인덱스를 못 탈까?"**

**B-1 원복 — 여기서 바로 한다** (한 번에 실행, 약 10초)
```bash
cd C:/seolmin/backend-study/lab/sql
docker exec -i lab-postgres psql -U lab -d labdb < 99_cleanup.sql
docker exec lab-postgres psql -U lab -d labdb -c "VACUUM FULL user_rating;"
docker exec -i lab-postgres psql -U lab -d labdb < 04_indexes.sql
docker exec lab-postgres psql -U lab -d labdb -c "ANALYZE user_rating;"
docker exec lab-postgres psql -U lab -d labdb -c "
SELECT pg_size_pretty(pg_relation_size('user_rating'));"
```
→ **367 MB 근처면 정상.** 735MB면 `VACUUM FULL`이 안 된 것.
안 하면 B-2 전환점이 36% → 10%로 바뀐다.

### B-2 선택도 (5분) · 3장 「선택도를 고려한 인덱스 칼럼 선택」

> 보여주는 것: **너무 많이 읽으면** DB가 인덱스를 스스로 포기한다.
> 그런데 **"몇 %부터"라는 고정된 답은 없다.**

**비교 조건 — 쿼리는 똑같다. 조회 범위만 넓어진다**

| 단계 | 조건 | 행수 | 비율 |
|---|---|---|---|
| 1 | `user_id = 46401` (라이트 유저) | 17 | 0.0003% |
| 2 | `user_id = 36` (헤비 유저) | 5,000 | 0.10% |
| 3 | `user_id BETWEEN 1 AND 4500` | 1,820,000 | 36.2% ← 경계 |
| 4 | `user_id BETWEEN 1 AND 8000` | 2,870,000 | 57.1% |

**1단계** — 평점 17건짜리 라이트 유저 한 명을 조회한다
```bash
docker exec lab-postgres psql -U lab -d labdb -c "
EXPLAIN ANALYZE SELECT * FROM user_rating WHERE user_id = 46401;"
```
→ `Index Scan`

**2단계** — 평점 5,000건짜리 헤비 유저 한 명을 조회한다
```bash
docker exec lab-postgres psql -U lab -d labdb -c "
EXPLAIN ANALYZE SELECT * FROM user_rating WHERE user_id = 36;"
```
→ `Bitmap Heap Scan`

❓ **"이건 몇 % 정도일 것 같아? 어느 쪽으로 갈까?"** ← 3단계 치기 전에

**3단계 (경계)** — 전체의 약 36%. **같은 명령을 세 번 연속 친다**
```bash
docker exec lab-postgres psql -U lab -d labdb -c "
EXPLAIN SELECT * FROM user_rating WHERE user_id BETWEEN 1 AND 4500;"
```
```bash
docker exec lab-postgres psql -U lab -d labdb -c "
EXPLAIN SELECT * FROM user_rating WHERE user_id BETWEEN 1 AND 4500;"
```
```bash
docker exec lab-postgres psql -U lab -d labdb -c "
EXPLAIN SELECT * FROM user_rating WHERE user_id BETWEEN 1 AND 4500;"
```

👉 **`cost` 숫자를 본다.** 두 계획이 1% 안쪽으로 붙어 있다.

2026-08-30 같은 날 같은 테이블 크기(367MB)에서 두 번 쟀는데 **선택이 뒤집혔다.**

```
오전  Bitmap Heap Scan  cost=46366.52..120563.96   <- 선택됨 (5회 모두)
      Seq Scan          cost=    0.00..122459.40

오후  Seq Scan          cost=    0.00..122461.05   <- 선택됨 (3회 모두)
      Bitmap Heap Scan  cost=47128.71..121774.25   (강제로 재보면 오히려 싸다)
```

사이에 한 일은 B-1을 돌렸다 원복한 것뿐이다.

❓ **"세 번 다 같았어? 두 계획 cost 차이가 몇 %야?"**

> **한 자리에서 세 번 치면 보통 같게 나온다.** 갈리는 건 통계가 바뀌는 순간
> (autovacuum이 돌 때, 테이블을 건드린 직후)이다.
> 안 갈려도 상관없다 — **cost가 1% 차이라는 것 자체**가 보여줄 거리다.
> 이 지점은 "인덱스를 쓰는 게 맞나"를 DB도 확신하지 못하는 구간이다.

**4단계** — 전체의 57%. 여기는 흔들리지 않는다 (3회 확인)
```bash
docker exec lab-postgres psql -U lab -d labdb -c "
EXPLAIN ANALYZE SELECT * FROM user_rating WHERE user_id BETWEEN 1 AND 8000;"
```
→ `Seq Scan`

**메시지**

> **"몇 %부터 인덱스를 포기한다"는 고정된 답이 없다.**
> 옵티마이저가 매번 비용을 계산해서 판단하고, 경계 근처에서는
> 같은 쿼리도 결과가 달라진다.
> 전환점은 데이터 양뿐 아니라 **테이블이 디스크에 어떻게 놓여 있느냐,
> 통계가 언제 갱신됐느냐**에 따라 움직인다.
> 실제로 같은 DB에서 16.2% → 10.5% → 36.2%로 세 번 다르게 나왔다.

**B-2는 만든 게 없다. 원복 불필요.**

### B-3 커버링 인덱스 (5분) · 3장 「커버링 인덱스 활용하기」

> 보여주는 것: **컬럼 하나 더 요구하면** 테이블을 읽으러 간다

**비교 조건 — WHERE는 같다. SELECT 목록만 다르다**

| | 쿼리 ① | 쿼리 ② |
|---|---|---|
| WHERE | `movie_id = 60300` | 똑같음 (고정) |
| SELECT | `movie_id, rating` | `movie_id, rating, **updated_at**` ← 변수 |
| 인덱스 | `(movie_id, rating)` | 똑같음 (고정) |

인덱스가 `(movie_id, rating)`이라 ①이 원하는 값은 **인덱스 안에 다 있다.**
②의 `updated_at`은 인덱스에 없어서 테이블을 찾아가야 한다.

**① 인덱스만으로 끝나는 쿼리** — 영화 60300의 평점 값만 가져온다
```bash
docker exec lab-postgres psql -U lab -d labdb -c "
EXPLAIN ANALYZE SELECT movie_id, rating FROM user_rating WHERE movie_id = 60300;"
```

**② 칼럼 하나만 더 요구** — 같은 조건에 `updated_at`을 추가로 가져온다
```bash
docker exec lab-postgres psql -U lab -d labdb -c "
EXPLAIN ANALYZE SELECT movie_id, rating, updated_at FROM user_rating WHERE movie_id = 60300;"
```

👉 가리킬 곳

| | ① | ② |
|---|---|---|
| 스캔 | **`Index Only Scan`** | `Bitmap Heap Scan` |
| 테이블 접근 | `Heap Fetches: 0` | `Heap Blocks: exact=...` (수천 개) |

❓ **"칼럼 하나 더 달라고 했을 뿐인데 왜 테이블을 읽으러 갈까?"**

**B-3은 만든 게 없다. 원복 불필요.**

### B-4 복합 인덱스 컬럼 순서 (5분) · 3장 「단일 인덱스와 복합 인덱스」

> 보여주는 것: **컬럼 순서**가 중요한데, 쿼리 모양에 따라 안 중요할 수도 있다

#### 구조 먼저 — 총 4번 실행한다

쿼리 2개 × 인덱스 2개. **쿼리는 바뀌지 않는다. 바뀌는 건 인덱스 컬럼 순서뿐이다.**

| | 인덱스 ① `(user_id, updated_at DESC)` | 인덱스 ② `(updated_at DESC, user_id)` |
|---|---|---|
| 쿼리 A (ORDER BY + LIMIT) | **1번** | **3번** |
| 쿼리 B (정렬 없음) | **2번** | **4번** |

**쿼리 설명**

- **쿼리 A** — 36번 사용자의 2026년 이후 평점 중 **최신 100개**
- **쿼리 B** — 같은 조건, **정렬 없이 전부**

WHERE 절은 완전히 같다. 차이는 `ORDER BY updated_at DESC LIMIT 100` 뿐이다.

**인덱스 설명**

- **①** `(user_id, updated_at DESC)` — 전화번호부가 **성 → 이름** 순
- **②** `(updated_at DESC, user_id)` — **이름 → 성** 순

`user_id`로 찾을 땐 ①이 유리하다. 하지만 `ORDER BY updated_at`이 있으면
②도 쓸모가 생긴다 — 이미 시간순이라 최신부터 걷다가 100개 채우면 멈춘다.
**LIMIT이 없으면 멈출 수 없어서 전체를 훑는다.**

❓ **"순서를 뒤집으면 나빠질까? 두 쿼리 다 똑같이?"** ← 여기서 글로 적는다

#### 1번 — 인덱스 ① · 쿼리 A (ORDER BY + LIMIT)
```bash
docker exec lab-postgres psql -U lab -d labdb -c "
EXPLAIN ANALYZE SELECT * FROM user_rating
WHERE user_id = 36 AND updated_at >= '2026-01-01'
ORDER BY updated_at DESC LIMIT 100;"
```

#### 2번 — 인덱스 ① · 쿼리 B (정렬 없음)
```bash
docker exec lab-postgres psql -U lab -d labdb -c "
EXPLAIN ANALYZE SELECT * FROM user_rating
WHERE user_id = 36 AND updated_at >= '2026-01-01';"
```

#### 인덱스 갈아끼우기
```bash
docker exec lab-postgres psql -U lab -d labdb -c "
CREATE INDEX idx_test_reversed ON user_rating(updated_at DESC, user_id);
DROP INDEX idx_user_rating__user_updated;
ANALYZE user_rating;"
```

> **원래 인덱스를 지우는 이유:** 둘 다 있으면 DB가 좋은 쪽을 골라 써서
> 뒤집은 효과가 안 보인다.

#### 3번 — 인덱스 ② · 쿼리 A (1번과 완전히 같은 쿼리)
```bash
docker exec lab-postgres psql -U lab -d labdb -c "
EXPLAIN ANALYZE SELECT * FROM user_rating
WHERE user_id = 36 AND updated_at >= '2026-01-01'
ORDER BY updated_at DESC LIMIT 100;"
```

#### 4번 — 인덱스 ② · 쿼리 B (2번과 완전히 같은 쿼리)
```bash
docker exec lab-postgres psql -U lab -d labdb -c "
EXPLAIN ANALYZE SELECT * FROM user_rating
WHERE user_id = 36 AND updated_at >= '2026-01-01';"
```

👉 결과표 (2026-08-29 실측 — **방향만 본다**)

| | 쿼리 A (ORDER BY) | 쿼리 B (없음) |
|---|---|---|
| 인덱스 ① | 1.4ms | 0.9ms |
| 인덱스 ② | 2.3ms | 93.8ms |
| | **거의 안 변함** | **크게 나빠짐** |

❓ **"왜 한쪽만 크게 나빠졌지? 두 쿼리 차이가 뭐였지?"**
(정답 미리 말하지 말 것)

**B-4 원복 — 여기서 바로 한다**
```bash
cd C:/seolmin/backend-study/lab/sql
docker exec -i lab-postgres psql -U lab -d labdb < 99_cleanup.sql
docker exec -i lab-postgres psql -U lab -d labdb < 04_indexes.sql
docker exec lab-postgres psql -U lab -d labdb -c "ANALYZE user_rating;"
docker exec lab-postgres psql -U lab -d labdb -c "\di"
```
→ 5줄(기본키 3 + 베이스라인 2). `idx_test_reversed`가 없어야 한다.
`VACUUM FULL`은 필요 없다 — 인덱스만 만들었으므로.

**B급 끝. 상태 확인만 한 번:**
```bash
docker exec lab-postgres psql -U lab -d labdb -c "\di"
docker exec lab-postgres psql -U lab -d labdb -c "
SELECT pg_size_pretty(pg_relation_size('user_rating'));"
```
→ 인덱스 5줄, 테이블 367MB 근처.
(원복은 B-1·B-4 각 실험 끝에 이미 했다. 여기서 또 할 필요 없다)

> 묶으면: 인덱스 걸었다고 끝이 아니다. 쿼리가 어떻게 생겼냐에 따라 달라진다.

---

> **여기까지 3장이었다. 이제 2장으로 간다. 부하를 걸어서 서버 전체를 본다.**

## A-1 관찰 (25분)

**2장 「처리량」「병목 지점」「커넥션 풀 크기」「커넥션 대기 시간」 + 3장 「쿼리 타임아웃」**

> 보여주는 것: **공식은 상한선일 뿐이고, 진짜 병목은 화면에서 찾아야 한다.**
> 흐름: 부하 → 처리량 안 오름 → 계산해보니 14배 차이 → 뭐가 빠졌지 →
>       DB CPU 197% → 풀을 늘리면? → 오히려 줄어듦

**비교 조건 — 앱 설정만 바꾼다. 부하도 쿼리도 고정**

| | 고정 | 변수 |
|---|---|---|
| 쿼리 | `/lab/ratings?offset=4900000&limit=10` (한 건 약 1.16초) | — |
| 부하 | 워밍업 1 rps 60초 → 1→2→4 rps 각 60초 | — |
| DB | CPU 2개, 메모리 2GB | — |
| 앱 설정 | — | **커넥션 풀 2 / 10 / 50** |
| 앱 설정 | — | **connection-timeout 30초 / 1초** |

Grafana **A-1 한 화면** 띄워놓고 시작.

**환경변수 (한 번만, 터미널 새로 열면 다시)**
```bash
cd C:/seolmin/backend-study/lab/k6
export K6_PROMETHEUS_RW_SERVER_URL=http://localhost:9090/api/v1/write
export K6_PROMETHEUS_RW_TREND_STATS="p(95),p(99),avg,max"
```

**기준 측정 (풀 10)** — 지금 앱이 풀 10이므로 그대로 돌린다. 4분
```bash
k6 run -o experimental-prometheus-rw -e POOL=10 -e PROFILE=rehearsal pool-size.js \
  | tee ../../vault/raw/$(date +%F)_exp-001_session_k6-pool10.txt
```
워밍업 1분 구간은 버린다.

❓ **"이 숫자들 중에 뭐가 이상해?"**

숫자 안 나오면 짚어줄 것 — Grafana 1번(TPS)은 평평한데 2번(p95)·3번(pending)은 올라간다. 4번(DB CPU)은 200% 근처.

---

## A-1 계산 (20분)

화이트보드에 크게:

```
최대 TPS = 커넥션 풀 크기 / 쿼리 실행 시간

쿼리 한 건 실행 시간부터 잰다
```

```bash
curl -s -o /dev/null -w "%{time_total}\n" "http://localhost:8080/lab/ratings?offset=4900000&limit=10"
```
→ 약 1.16초

```
풀 10 / 1.16초 = 8.6 TPS      <- 예측
실측                0.58 TPS   <- 방금 k6
                    약 14배 차이
```

❓ **"왜 이렇게 다를까? 계산에서 뭐가 빠졌지?"**

---

## A-1 예측 (15분)

**둘 다 글로 적는다.**

❓ **"풀을 50으로 올리면 처리량이 어떻게 될까? 숫자로 적어봐."**
❓ **"풀을 2로 줄이면?"**

적고 나서 실행으로 넘어간다. (실측값 미리 보여주지 말 것)

---

## A-1 실행 (25분)

> **앱 재시작 두 가지 주의**
> - `pkill`은 Windows에서 안 먹는다. 아래 PowerShell 명령을 쓴다.
> - 풀 크기·타임아웃은 **재빌드 없이 JVM `-D` 인자**로 바꾼다.
>   `application.yml`을 고치지 않으므로, `exp` 커밋 메시지에 어떤 인자로
>   돌렸는지 반드시 적어야 재현된다.
> - `java -jar`는 터미널을 붙잡는다. **k6는 새 터미널에서** 돌린다.

### 풀 2 → 풀 50 (각 5분)

**풀 2로 앱 재시작**
```bash
powershell.exe -NoProfile -Command "Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id \$_.OwningProcess -Force }"
cd C:/seolmin/backend-study/lab/app
java -Dspring.datasource.hikari.maximum-pool-size=2 -jar build/libs/lab-app-0.0.1.jar
```
새 터미널에서 확인 → `max=2.0`
```bash
curl -s http://localhost:8080/actuator/prometheus | grep "^hikaricp_connections_max"
```

**풀 2 부하** (4분)
```bash
cd C:/seolmin/backend-study/lab/k6
k6 run -o experimental-prometheus-rw -e POOL=2 -e PROFILE=rehearsal pool-size.js \
  | tee ../../vault/raw/$(date +%F)_exp-001_session_k6-pool2.txt
```

**풀 50으로 앱 재시작**
```bash
powershell.exe -NoProfile -Command "Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id \$_.OwningProcess -Force }"
cd C:/seolmin/backend-study/lab/app
java -Dspring.datasource.hikari.maximum-pool-size=50 -jar build/libs/lab-app-0.0.1.jar
```

**풀 50 부하** (4분)
```bash
cd C:/seolmin/backend-study/lab/k6
k6 run -o experimental-prometheus-rw -e POOL=50 -e PROFILE=rehearsal pool-size.js \
  | tee ../../vault/raw/$(date +%F)_exp-001_session_k6-pool50.txt
```

👉 가리킬 곳: Grafana 3번 패널의 `active`가 풀 크기까지 차고 `pending`이 쌓인다.
**1번(TPS)은 세 번 다 비슷하다.**

참고 실측 (2026-08-29, 무거운 쿼리 6건 동시 — **방향만**)

| 풀 | 처리량 | 산술 모델 예측 |
|---|---|---|
| 2 | 0.73 TPS | 1.7 |
| 10 | 0.58 TPS | 8.6 |
| 50 | 0.55 TPS | 43.1 |

❓ **"예측 맞았어? 풀을 25배 키웠는데 처리량이 왜 안 늘지?"**

### 타임아웃 증폭 (10분)

**비교 조건 — 커넥션 타임아웃만 다르다**

| | 조건 A | 조건 B |
|---|---|---|
| `connection-timeout` | **30초** | **1초** ← 변수 |
| 풀 크기 | 10 (기본) | 10 (고정) |
| k6 재시도 | 켬 (3초 참았다 재요청, 최대 2회) | 똑같음 (고정) |
| 부하 | 2 → 5 rps | 똑같음 (고정) |

**조건 A — 앱 재시작 (타임아웃 30초)**
```bash
powershell.exe -NoProfile -Command "Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id \$_.OwningProcess -Force }"
cd C:/seolmin/backend-study/lab/app
java -Dspring.datasource.hikari.connection-timeout=30000 -jar build/libs/lab-app-0.0.1.jar
```

**조건 A 부하** (3분)
```bash
cd C:/seolmin/backend-study/lab/k6
k6 run -o experimental-prometheus-rw -e COND=A -e PROFILE=rehearsal timeout-amplification.js \
  | tee ../../vault/raw/$(date +%F)_exp-001_session_k6-timeoutA.txt
```

**조건 B — 앱 재시작 (타임아웃 1초)**
```bash
powershell.exe -NoProfile -Command "Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id \$_.OwningProcess -Force }"
cd C:/seolmin/backend-study/lab/app
java -Dspring.datasource.hikari.connection-timeout=1000 -jar build/libs/lab-app-0.0.1.jar
```

**조건 B 부하** (3분)
```bash
cd C:/seolmin/backend-study/lab/k6
k6 run -o experimental-prometheus-rw -e COND=B -e PROFILE=rehearsal timeout-amplification.js \
  | tee ../../vault/raw/$(date +%F)_exp-001_session_k6-timeoutB.txt
```

👉 가리킬 곳: `req_attempts` ÷ `iterations` = **증폭 배수**. 그리고 `user_total_wait` p95.

❓ **"빨리 실패하는 쪽이 사용자를 더 오래 기다리게 할까, 덜 기다리게 할까?"**

**A-1 원복 — 앱을 기본 설정으로**
```bash
powershell.exe -NoProfile -Command "Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id \$_.OwningProcess -Force }"
cd C:/seolmin/backend-study/lab/app
java -jar build/libs/lab-app-0.0.1.jar
```
→ `max=10.0` 확인. DB는 건드린 게 없으므로 SQL 원복 불필요.

---

> **다시 3장이다. 병목을 찾았으니 고쳐본다.**

## A-2 (25분)

**3장 「페이지 기준 목록 조회 대신 ID 기준 목록 조회」**

> 보여주는 것: **같은 인덱스가 한쪽은 빠르게, 한쪽은 느리게 만든다.**
> 흐름: 오프셋 느림 → "인덱스 걸면 되겠네" → 걸었더니 더 느려짐 → 왜? → 커서로 교체
> **이 회차의 하이라이트다.** 확신을 갖고 예측한 게 정반대로 나온다.

### 오프셋 vs 커서 (15분)

**비교 조건 — 가져오는 결과는 같다. 시작 위치를 찾는 방법만 다르다**

| | 오프셋 | 커서 |
|---|---|---|
| 하는 일 | 평점 목록 최신순, 490만 번째부터 10건 | 2024-10-01 이전 것 중 최신 10건 |
| 방법 | 앞의 490만 행을 **세면서 버린다** | 시작 위치를 **바로 찾는다** |
| 인덱스 | 없음 (1단계) → 있음 (2단계) | 없음 (1단계) → 있음 (2단계) ← 변수 |

**단건 측정 — 오프셋**
```bash
curl -s -o /dev/null -w "offset %{time_total}\n" "http://localhost:8080/lab/ratings?offset=4900000&limit=10"
```
→ 약 1.2~1.5초

**단건 측정 — 커서**
```bash
curl -s -o /dev/null -w "cursor %{time_total}\n" "http://localhost:8080/lab/ratings?cursorUpdatedAt=2024-10-01T00:00:00Z&limit=10"
```
→ 약 0.11~0.16초

(`curl -w` 문자열에 한글을 넣으면 콘솔에서 깨진다. 영문으로 둔다)

**부하 — 오프셋** (4분)
```bash
cd C:/seolmin/backend-study/lab/k6
k6 run -o experimental-prometheus-rw -e MODE=offset -e PROFILE=rehearsal offset-vs-cursor.js \
  | tee ../../vault/raw/$(date +%F)_exp-001_session_k6-offset.txt
```

**부하 — 커서** (4분)
```bash
cd C:/seolmin/backend-study/lab/k6
k6 run -o experimental-prometheus-rw -e MODE=cursor -e PROFILE=rehearsal offset-vs-cursor.js \
  | tee ../../vault/raw/$(date +%F)_exp-001_session_k6-cursor.txt
```

### 인덱스 걸면? (10분)

❓ **"`updated_at`에 인덱스를 걸면 두 쿼리가 각각 어떻게 될까? 둘 다 빨라질까?"**

**적고 나서** 인덱스 생성 (약 10초)
```bash
docker exec lab-postgres psql -U lab -d labdb -c "
CREATE INDEX idx_user_rating__updated ON user_rating(updated_at DESC);
ANALYZE user_rating;"
```

**다시 재기 — 오프셋** (같은 명령, 인덱스만 생겼다)
```bash
curl -s -o /dev/null -w "offset %{time_total}\n" "http://localhost:8080/lab/ratings?offset=4900000&limit=10"
```
→ 약 8.5초 — **느려졌다**

**다시 재기 — 커서** (같은 명령)
```bash
curl -s -o /dev/null -w "cursor %{time_total}\n" "http://localhost:8080/lab/ratings?cursorUpdatedAt=2024-10-01T00:00:00Z&limit=10"
```
→ 약 5.7ms — 빨라졌다

**왜 그런지 실행계획으로** — 오프셋 쿼리가 뭘 하는지 본다
```bash
docker exec lab-postgres psql -U lab -d labdb -c "
EXPLAIN ANALYZE SELECT user_id, movie_id, rating, updated_at FROM user_rating
ORDER BY updated_at DESC LIMIT 10 OFFSET 4900000;"
```
👉 가리킬 곳: `Seq Scan` + 정렬이 아니라 **`Index Scan`으로 바뀌었다.**
인덱스를 490만 건 걸어가면서 매 건 테이블을 찾아간다.

| | 인덱스 없음 | 인덱스 있음 |
|---|---|---|
| 오프셋 | 약 1.2초 | **약 8.5초 (7배 나빠짐)** |
| 커서 | 약 0.11초 | 약 5.7ms (20배 좋아짐) |

❓ **"인덱스를 걸었는데 왜 오프셋만 느려졌을까?"**

**A-2 ⑥ 원복 — 여기서 바로 한다**
```bash
docker exec lab-postgres psql -U lab -d labdb -c "
DROP INDEX IF EXISTS idx_user_rating__updated;
ANALYZE user_rating;"
docker exec lab-postgres psql -U lab -d labdb -c "\di"
```
→ 5줄. `idx_user_rating__updated`가 없어야 한다.

### ⑦ 통계 미리 집계 — **리허설에서 먼저 확인할 것** ⚠

아직 실측 안 했다. 리허설에서 차이가 나는지 보고, 안 나면 당일에 뺀다.

**비교 조건**

| | before | after |
|---|---|---|
| 하는 일 | 영화 하나의 평점 개수·평균 | 똑같음 |
| 방법 | 조회할 때마다 `count(*)`로 **센다** | **미리 세둔 칼럼**을 읽는다 ← 변수 |
| 대상 | 인기(60300, 10,339건) / 비인기(16710, 109건) | 똑같음 (고정) |

**before — 인기 영화** (10회 평균. 1회로는 노이즈에 묻힌다)
```bash
for i in $(seq 1 10); do curl -s -o /dev/null -w "popular %{time_total}\n" "http://localhost:8080/lab/movies/60300/stats"; done
```

**before — 비인기 영화**
```bash
for i in $(seq 1 10); do curl -s -o /dev/null -w "rare %{time_total}\n" "http://localhost:8080/lab/movies/16710/stats"; done
```

→ 사전측정 2회가 서로 뒤집혔다: 1차 6.2ms / 12.9ms, 2차 18.8ms / 7.1ms.
**둘 다 한 자릿수 ms라 노이즈에 묻힌다. 이대로면 실험이 안 된다.**

**after 준비 — 집계 칼럼 만들고 채우기** (앱에 읽는 엔드포인트는 아직 없다)
```bash
docker exec lab-postgres psql -U lab -d labdb -c "
ALTER TABLE movies ADD COLUMN rating_count int DEFAULT 0;
ALTER TABLE movies ADD COLUMN rating_sum bigint DEFAULT 0;
UPDATE movies m SET rating_count = s.c, rating_sum = s.s
FROM (SELECT movie_id, count(*) c, sum(rating) s FROM user_rating GROUP BY movie_id) s
WHERE m.movie_id = s.movie_id;"
```

**SQL로만 before/after 비교** (앱 엔드포인트가 없으므로)
```bash
docker exec lab-postgres psql -U lab -d labdb -c "
EXPLAIN ANALYZE SELECT count(*), avg(rating) FROM user_rating WHERE movie_id = 60300;"
```
```bash
docker exec lab-postgres psql -U lab -d labdb -c "
EXPLAIN ANALYZE SELECT rating_count, rating_sum FROM movies WHERE movie_id = 60300;"
```

리허설 판정: 3배 이상이면 진행 / 1.5배 미만이면 당일에 뺀다.

**A-2 ⑦ 원복**
```bash
cd C:/seolmin/backend-study/lab/sql
docker exec -i lab-postgres psql -U lab -d labdb < 99_cleanup.sql
docker exec -i lab-postgres psql -U lab -d labdb < 04_indexes.sql
docker exec lab-postgres psql -U lab -d labdb -c "ANALYZE user_rating; ANALYZE movies;"
docker exec lab-postgres psql -U lab -d labdb -c "\d movies"
```
→ `movies`에 `rating_count` / `rating_sum`이 없어야 한다.

---

## 정리 (10분)

raw는 위 `tee`로 이미 저장됨. 확인:
```bash
ls -la C:/seolmin/backend-study/vault/raw/ | grep $(date +%F)
```

EXPLAIN 결과 저장(콘솔에서 긁어서):
```bash
cd C:/seolmin/backend-study
# vault/raw/$(date +%F)_exp-001_session_explain-b1~b4.txt 로 붙여넣기
```

커밋:
```bash
git add -A
git commit -m "exp: 1회차 측정 — 풀 2/10/50, 타임아웃 A/B, 오프셋 vs 커서"
git log --oneline -1
```
해시를 실험 노트 frontmatter의 `commit:`에 적는다.

**당일 안에 반드시:** 실험 노트의 "예측과의 차이" 채우기.

---

## 막혔을 때

| 증상 | 대처 |
|---|---|
| 앱이 안 죽음 (`pkill` 무반응) | 위 PowerShell `Get-NetTCPConnection` 명령 사용 |
| `port 8080 already in use` | 같은 명령으로 죽이고 재시작 |
| B-3에서 `Index Only Scan` 안 뜸 | `VACUUM user_rating;` 안 했다 |
| `rows` 추정치가 실제와 수십 배 차이 | `ANALYZE user_rating;` |
| 20729 대시보드 전부 No data | `docker compose restart prometheus` |
| Grafana 패널에 k6 선 없음 | `K6_PROMETHEUS_RW_SERVER_URL` export 했나, `-o experimental-prometheus-rw` 붙였나 |
| `dropped_iterations` > 0 | **그 실행 결과 전부 무효.** 다시 돌린다 |
| EXPLAIN 시간이 앞 실행보다 몇 배 큼 | 앞 부하가 안 빠졌다. `SELECT count(*) FROM pg_stat_activity WHERE state='active';` 가 0인지 보고 재측정 |
| `VACUUM` 실패 (shared memory) | DB 컨테이너 메모리 2g인지 확인 |
| 인덱스가 이상하게 남음 | `lab/sql`에서 `99_cleanup.sql` → `04_indexes.sql` 순서로 |
| B-2 전환점이 표와 딴판 | B-1 뒤 `VACUUM FULL user_rating;` 안 했다. `pg_relation_size`가 약 370MB인지 확인 (735MB면 안 된 것) |
| 같은 쿼리인데 계획이 실행마다 바뀜 | autovacuum이 도는 중. `pg_stat_activity`에서 끝난 걸 보고 `ANALYZE` 후 재측정 |
| `psql: /tmp/xxx.sql: No such file` | `-f /tmp/…` 말고 `docker exec -i … < 파일` 방식으로 |

---

## 안 다루는 것 (질문 받으면 "이번엔 안 다뤄")

**2장**
- 수직/수평 확장 `시간부족`
- 최대 유휴 시간 / 유효성 검사 / 최대 유지 시간 `재현위험`
- 로컬 캐시 vs 리모트 캐시 `시간부족`
- 캐시 사전 적재 `시간부족`
- 캐시 무효화 `뒷장재등장` (6장)
- 응답 데이터 압축 `재현위험`
- 정적 자원과 브라우저 캐시 / CDN `환경없음`
- 대기 처리 `시간부족`

**3장**
- 인덱스는 필요한 만큼만 `시간부족`
- 오래된 데이터 삭제·분리 `재현위험`
- DB 장비 확장 `환경없음`
- 별도 캐시 서버 `시간부족`
- 복제 DB에서 조회하지 않기 `환경없음`
- 배치 쿼리 실행 시간 `시간부족`
- 테이블 변경은 신중하게 `재현위험`
- 실패와 트랜잭션 `뒷장재등장` (6장)

**B급인데 시간 없으면 넘길 것**
- 응답 시간 / 적중률과 삭제 규칙 / GC와 메모리 / 시간 기준 범위 제한 / 전체 개수 세지 않기 / DB 최대 연결 개수

넘긴 건 `progress.md`에 `#미실험`과 사유를 적는다.
