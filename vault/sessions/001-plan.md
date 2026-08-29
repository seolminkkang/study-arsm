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

**비교 조건 — 변수는 조인 칼럼의 타입 하나뿐이다.**

2026-08-30에 한 번 더 고쳤다. 이전 안은 ①이 단일 테이블 조회,
②가 조인이라 **조건이 두 개 달랐다** — 타입 때문인지 조인 때문인지 구분이 안 됐다.
**둘 다 조인으로 맞추고 타입만 변수로 남긴다.**

| | 쿼리 ① | 쿼리 ② |
|---|---|---|
| 형태 | `user_rating` ⋈ `movies` | 조인 (고정) |
| 조인 칼럼 | `r.movie_id` (bigint) | `r.movie_id_str::int` (varchar→int) ← **변수** |
| 결과 | 영화 60300의 평점 10,339건 | 똑같음 |

```sql
ALTER TABLE user_rating ADD COLUMN movie_id_str varchar(20);
UPDATE user_rating SET movie_id_str = movie_id::text;
CREATE INDEX idx_rating_movie_str ON user_rating(movie_id_str);
ANALYZE user_rating;

-- ① 타입 같음 (bigint : bigint)
EXPLAIN ANALYZE
SELECT r.* FROM user_rating r JOIN movies m
ON r.movie_id = m.movie_id WHERE m.movie_id = 60300;

-- ② 타입 다름 (varchar->int : bigint)
EXPLAIN ANALYZE
SELECT r.* FROM user_rating r JOIN movies m
ON r.movie_id_str::int = m.movie_id WHERE m.movie_id = 60300;
```

**실측 (2026-08-30)**

| | ① 타입 같음 | ② 타입 다름 |
|---|---|---|
| 스캔 | `Bitmap Index Scan on idx_user_rating__movie_rating` | `Parallel Seq Scan` |
| Filter | 없음 | `((movie_id_str)::integer = 60300)` |
| 버린 행 | — | `Rows Removed by Filter: 1,673,220` |
| Execution | 약 230ms | 약 472ms |

쿼리에 쓰는 movie_id는 실제로 존재하는 값이어야 한다(`42`는 이 데이터셋에 없어서
두 쿼리 다 0행이 나와 비교가 안 됐다). `00_find_test_ids.sql`로 확인한 값을 쓴다.

**끝나면 즉시 원복 + `VACUUM FULL`.** `UPDATE` 503만 건이 테이블을 735MB로
부풀리고, 그대로 두면 B-2 전환점이 바뀐다(아래 B-2 참고).

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
EXPLAIN ANALYZE SELECT * FROM user_rating WHERE user_id = 46401;                 -- 0.0003% (Index Scan)
EXPLAIN ANALYZE SELECT * FROM user_rating WHERE user_id = 36;                    -- 0.10%
EXPLAIN ANALYZE SELECT * FROM user_rating WHERE user_id BETWEEN 1 AND 100;       -- 9.94%
EXPLAIN ANALYZE SELECT * FROM user_rating WHERE user_id BETWEEN 1 AND 4000;      -- 33.20% (전환 직전)
EXPLAIN ANALYZE SELECT * FROM user_rating WHERE user_id BETWEEN 1 AND 4500;      -- 36.18% (전환 직후)
EXPLAIN ANALYZE SELECT * FROM user_rating WHERE user_id BETWEEN 1 AND 5000;      -- 39.17%
```

`SELECT movie_id, rating`이 아니라 `SELECT *`로 검증했다 — 이 쿼리는 어차피
`user_id`로 필터링하므로 `(movie_id, rating)` 인덱스의 커버링 효과와 무관해서
컬럼을 좁혀도 결과가 달라지지 않는다.

**실측 결과 (user_rating 5,030,000건 기준):**

| 비율 | 쿼리 | 스캔 방식 | 실제 rows |
|---|---|---|---|
| 0.0003% | `= 46401` (라이트 유저) | **Index Scan** | 17 |
| 0.10% | `= 36` (헤비 유저) | Bitmap Heap Scan | 5,000 |
| 0.99% | `BETWEEN 1 AND 10` | Bitmap Heap Scan | 50,000 |
| 9.94% | `BETWEEN 1 AND 100` | Bitmap Heap Scan | 500,000 |
| 27.24% | `BETWEEN 1 AND 3000` | Bitmap Heap Scan | 1,370,000 |
| 33.20% | `BETWEEN 1 AND 4000` | Bitmap Heap Scan | 1,670,000 |
| **36.18%** | `BETWEEN 1 AND 4500` | **Seq Scan** | 1,820,000 |
| 39.17% | `BETWEEN 1 AND 5000` | Seq Scan | 1,970,000 |

`Index Scan`은 라이트 유저(17행)에서만 나온다. 2026-08-29에는 헤비 유저(5,000행)도
`Index Scan`이었는데 `VACUUM FULL` 후 `Bitmap Heap Scan`으로 바뀌었다 —
테이블을 다시 쓰면서 한 유저의 행이 연속 페이지에 모인 영향으로 보인다(#가설).

**전환점: 전체의 약 36%** (깨끗한 테이블 기준, 2026-08-30 재측정).

### 발견 — "몇 %부터"라는 고정된 답이 없다 (책에 없는 내용)

2026-08-30에 **같은 날, 같은 테이블 크기(367MB), 같은 쿼리**로 두 번 쟀는데
`BETWEEN 1 AND 4500`(36.2%)의 선택이 뒤집혔다.

```
오전  Bitmap Heap Scan  cost=46366.52..120563.96   <- 선택됨 (5회 모두 동일)
      Seq Scan          cost=    0.00..122459.40

오후  Seq Scan          cost=    0.00..122461.05   <- 선택됨 (3회 모두 동일)
      Bitmap Heap Scan  cost=47128.71..121774.25   (강제로 재보면 오히려 싸다)
```

사이에 한 일은 B-1을 돌렸다 원복한 것뿐이다.
**두 계획의 비용이 1% 안쪽으로 붙어 있어서** 통계가 조금만 흔들려도 결과가 바뀐다.

한 자리에서 연속으로 세 번 치면 대개 같게 나온다. 갈리는 건 통계가 바뀌는
순간이다 — autovacuum이 도는 중이거나 테이블을 막 건드린 직후.

**그래서 회차 메시지를 이렇게 잡는다.**

> "몇 %부터 인덱스를 포기한다"는 고정된 답이 없다.
> 옵티마이저가 매번 비용을 계산해서 판단하고, 경계 근처에서는
> 같은 쿼리도 결과가 달라진다.
> 전환점은 데이터 양뿐 아니라 **테이블이 디스크에 어떻게 놓여 있느냐,
> 통계가 언제 갱신됐느냐**에 따라 움직인다.

**진행은 4단계로 한다.** 3단계에서 같은 명령을 세 번 연속 친다.

| 단계 | 조건 | 행수 | 비율 | 결과 |
|---|---|---|---|---|
| 1 | `user_id = 46401` | 17 | 0.0003% | `Index Scan` |
| 2 | `user_id = 36` | 5,000 | 0.10% | `Bitmap Heap Scan` |
| 3 | `BETWEEN 1 AND 4500` | 1,820,000 | 36.2% | **경계 — 갈릴 수 있다** |
| 4 | `BETWEEN 1 AND 8000` | 2,870,000 | 57.1% | `Seq Scan` (3회 확인, 안정) |

4단계 값은 "확실히 Seq Scan이 나오는 값"을 찾으려고 5000/8000/20000/50000/90000을
각각 3회씩 돌려서 정했다. 전부 안정적으로 `Seq Scan`이다.

### ⚠ 전환점은 고정된 숫자가 아니다 — 2026-08-30에 세 번 다르게 나왔다

같은 데이터, 같은 인덱스, 같은 쿼리인데 **테이블 물리 상태에 따라 전환점이 3배 넘게 움직인다.**

| 상태 | 테이블 | 페이지 | 전환점 |
|---|---|---|---|
| 2026-08-28 최초 측정 (부분 부풀림) | 미기록 | 미기록 | 15.9~16.2% |
| **B-1 직후** (부풀림 + `movie_id_str` 있음) | 735 MB | 94,019 | **10.5~10.8%** |
| **VACUUM FULL 후** (깨끗) | 327 MB | 41,917 | **33.2~36.2%** |

원인은 **B-1이 테이블을 2배로 부풀린다**는 것이다.
`UPDATE user_rating SET movie_id_str = movie_id::text` 가 5,030,000행을 전부
다시 쓰면서 원본이 죽은 튜플로 남는다. 일반 `VACUUM`은 재사용 표시만 하고
파일을 안 줄인다. **`VACUUM FULL`이라야 회수된다**(5.6초).

부풀면 같은 행 수가 더 많은 페이지에 흩어진다. 인덱스 스캔은 찾은 행마다
힙 페이지를 찾아가므로 흩어질수록 비싸지고, 그래서 옵티마이저가 **더 낮은
비율에서 인덱스를 포기한다.** (#가설 — 비용 모델을 직접 뜯어보진 않았다)

**진행 순서상 반드시 지킬 것:** B-1 다음에 B-2를 하므로,
B-1이 끝나면 `99_cleanup.sql` → **`VACUUM FULL user_rating;`** → `04_indexes.sql`
→ `ANALYZE` 를 거쳐야 위 33~36% 숫자가 재현된다.
`99_cleanup.sql`만으로는 부족하다.

**그리고 이 현상 자체가 좋은 소재다.** "16%"를 외우게 하면 안 된다.
같은 DB에서 어제 16%, 오늘 10%, 청소하니 36%가 나왔다 —
**전환점은 데이터 양이 아니라 테이블이 디스크에 어떻게 놓여 있느냐가 정한다.**

전문: `vault/raw/2026-08-30_b2_transition_shift_rehearsal.txt`

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

**2026-08-29 재현 확인.** 커버링 0.779ms(`Heap Fetches: 0`) vs 비커버링 99.831ms.
VACUUM은 전날 실행분이 그대로 유효했다 — 매번 다시 돌릴 필요는 없고,
**시딩을 새로 했을 때만** 필수다.

**단, 배율은 인용하지 않는다.** 08-28에는 1,788배(0.735ms vs 1314ms), 08-29에는
128배(0.779ms vs 99.8ms)가 나왔다. 비커버링 쪽이 OS 페이지 캐시 상태에 따라
1314ms → 99ms로 요동친다. 방향(커버링이 빠르다)만 안정적이므로 당일에도
"몇 배"가 아니라 `Heap Fetches: 0`과 `Heap Blocks: exact=9315`의 대비로 설명한다.

**옵티마이저 추정치도 같이 본다.** 08-29 첫 실행에서 추정 252 vs 실제 10,339으로
41배 과소추정이 나왔다. `ANALYZE user_rating;` 후 12,264으로 정상화됐다.
원인은 `movie_id=60300`이 MCV(most common values, 자주 나오는 값 100개 목록)에
들어 있느냐다 — 목록에 있으면 실제 빈도를 알고, 없으면
`전체행수 / n_distinct = 5,030,000 / 15,601 ≈ 322`로 일반 추정한다.
이번엔 추정이 틀려도 스캔 방식은 안 바뀌었지만, B-2의 16% 경계 근처에서는
이 오차가 계획을 바꿀 수 있다. **회차 시작 전에 `ANALYZE`를 한 번 돌리고 들어간다.**

## B-4. 단일 vs 복합 인덱스 (컬럼 순서)

**보여줄 것:** 같은 두 칼럼이라도 순서에 따라 다르다.
그리고 **"얼마나 다른지는 쿼리 모양이 정한다."**

**2026-08-29에 6개 조합을 전부 측정해서 확정했다.** 인덱스 3상태 × 쿼리 2종으로
돌린다 — 쿼리를 한 종류만 돌리면 결론이 정반대로 나온다.

```sql
-- 두 가지 쿼리 모양
-- Q_ordered
SELECT * FROM user_rating
WHERE user_id = <헤비ID> AND updated_at >= '2026-01-01'
ORDER BY updated_at DESC LIMIT 100;

-- Q_plain  (ORDER BY / LIMIT 없음)
SELECT * FROM user_rating
WHERE user_id = <헤비ID> AND updated_at >= '2026-01-01';
```

세 가지 인덱스 상태에서 위 두 쿼리를 각각 `EXPLAIN ANALYZE` 한다.

```sql
-- 상태 A: 기준 (user_id, updated_at DESC)  ← 04_indexes.sql 그대로

-- 상태 B: 인덱스 없음
DROP INDEX idx_user_rating__user_updated;
ANALYZE user_rating;

-- 상태 C: 순서를 뒤집음
CREATE INDEX idx_test_reversed ON user_rating(updated_at DESC, user_id);
ANALYZE user_rating;
```

**실측 결과 (헤비ID=36, user_rating 5,030,000건)**

| 인덱스 상태 | Q_ordered | Q_plain |
|---|---|---|
| A 기준 `(user_id, updated_at DESC)` | 1.418 ms | 0.927 ms |
| B 인덱스 없음 | 180.516 ms | 144.375 ms |
| C 순서 뒤집음 `(updated_at DESC, user_id)` | 2.277 ms | 93.838 ms |
| **A 대비 C** | **1.6배** | **101배** |

**이게 이 회차의 예측 소재다.** 둘 다 "순서를 뒤집으면 나빠진다"고 예측할
가능성이 높은데, `ORDER BY ... LIMIT`이 붙어 있으면 **거의 차이가 없다**(1.6배).
같은 인덱스, 같은 조건인데 `ORDER BY`와 `LIMIT`을 떼는 순간 101배로 벌어진다.

**숫자로 설명되는 이유** (08-29 확인)
- `updated_at >= '2026-01-01'` 조건에 걸리는 행이 3,876,969건 — **전체의 77.1%**다.
- 그중 `user_id = 36`은 3,887건, 즉 그 77.1% 안에서 **0.1%**뿐이다.
- 상태 C의 인덱스는 선두 컬럼이 `updated_at`이라, 저 77.1%를 인덱스에서
  전부 훑고 나서 `user_id`로 걸러내야 한다 → `Bitmap Index Scan`만 81.3ms.
- `ORDER BY updated_at DESC LIMIT 100`이 붙으면 인덱스를 정렬된 순서대로
  걸어가다가 100건을 채우는 순간 멈출 수 있다(조기 종료). 그래서 77.1%를
  훑는 비용이 아예 발생하지 않는다.
- 참고: C의 `Q_plain`(93.8ms)도 인덱스가 아예 없는 B(144.4ms)보다는 빠르다.
  "순서가 틀린 인덱스"가 "인덱스 없음"보다는 낫다.

**볼 것:** 여섯 조합의 실행 시간, 스캔 방식, 그리고 C-2의 `Heap Blocks: exact=47` —
힙 접근은 적은데 느리다. 비용이 테이블이 아니라 **인덱스를 훑는 데서** 나온다는 증거다.

실험이 끝나면 `99_cleanup.sql` → `04_indexes.sql` 순으로 원래 인덱스를 복구한다.

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

**원안은 2026-08-29 파일럿에서 실패했다.**

```
before: GET /lab/ratings?userId=X&offset=4000&limit=10   <- 차이가 안 난다
```

`(user_id, updated_at DESC)` 인덱스가 있어서 특정 유저 안에서는 오프셋을
아무리 키워도 싸다. 실측으로 offset=0이 4.1ms, offset=4900이 4.9ms — 1.2배다.
판정 기준(1.5배 미만은 실패)에 못 미친다.

**전체 목록 기준으로 바꾼다.** userId를 빼면 인덱스를 못 타서 5백만 행을
정렬해야 하고, 거기서 오프셋 비용이 드러난다.

```
before: GET /lab/ratings?offset=4900000&limit=10
after:  GET /lab/ratings?cursorUpdatedAt=2024-10-01T00:00:00Z&limit=10
```

커서 값이 `cursorId`가 아니라 `cursorUpdatedAt`인 이유: `user_rating`에는
대리키가 없다. 정렬 기준이 `updated_at`이므로 커서도 타임스탬프다.

### 실측 (2026-08-29, 유휴 상태 단건)

| 조건 | `updated_at` 인덱스 없음 | 있음 |
|---|---|---|
| before: `offset=4900000` | 1.16 s | **8.5 s** |
| after: `cursorUpdatedAt` (깊음) | 0.11 s | **5.7 ms** |
| 배수 | 10배 | **1,500배** |

**인덱스를 걸면 오프셋이 오히려 7배 느려진다**(1.16초 → 8.5초).
인덱스가 생기니 옵티마이저가 Index Scan으로 바꾸는데, 4,900,000건을
인덱스로 훑으면서 매 건 힙을 찾아가느라 순차 스캔보다 나빠진다.
이게 이 회차에서 제일 직관에 안 맞는 숫자다. **예측 소재로 쓴다** —
"인덱스를 걸면 빨라진다"고 예측할 텐데 절반만 맞는다.

인덱스는 베이스라인(`04_indexes.sql`)에 넣지 않았다. 실험 조건 그 자체다.

```sql
CREATE INDEX idx_user_rating__updated ON user_rating(updated_at DESC);
ANALYZE user_rating;
-- 끝나면 99_cleanup.sql이 지운다
```

### 또 하나 — 오프셋 깊이는 생각보다 안 중요하다

| offset | 시간 |
|---|---|
| 50,000 | 0.82 s |
| 200,000 | 0.74 s |
| 500,000 | 0.75 s |
| 1,000,000 | 0.79 s |
| 4,900,000 | 1.16 s |

5만이든 100만이든 거의 같다. **비용의 대부분은 건너뛰기가 아니라
5백만 행 정렬**이다(`updated_at` 인덱스가 없어서). 깊이가 문제라고
말하기 쉬운데 실측은 다르게 나온다.

부하 시나리오는 `lab/k6/offset-vs-cursor.js`. ③④의 숫자와 직접 비교한다.

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
- [ ] 회차 시작 직전에 `ANALYZE user_rating;`을 돌렸는가
      (안 돌리면 추정치가 41배까지 틀어진다 — 2026-08-29 B-3에서 확인)
- [ ] B급 4개 쿼리가 전부 실행되고, 실행계획에 차이가 보이는가
      → **B-1~B-4 전부 2026-08-28~29 파일럿에서 검증 완료.**
        `vault/raw/2026-08-28_pilot_b1~b4_rehearsal.txt`,
        `vault/raw/2026-08-28_pilot_b2_ratio_rehearsal.txt`,
        `vault/raw/2026-08-29_pilot_b3_b4_rehearsal.txt`
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
