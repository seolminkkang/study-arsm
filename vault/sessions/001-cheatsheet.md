---
title: 1회차 커닝페이퍼
description: 리허설·당일에 옆에 띄워놓고 그대로 치는 용도. 설명은 001-plan.md에 있다
session: 1
chapters: [2, 3]
tags: [cheatsheet]
---

# 1회차 커닝페이퍼

**설명 없음. 명령어와 질문만.** "왜"가 필요하면 [[001-plan]]을 연다.

한 대에서 진행한다. 총 2시간 30분.

> **배수를 인용하지 말 것.**
> B-3이 회차 간 1,788배 → 128배로 요동쳤고(OS 페이지 캐시), 풀 실험도 25% 편차가 있다.
> "3배" "100배" 대신 **"빨라진다 / 느려진다 / 안 변한다"** 방향만 말한다.

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
→ `idx_user_rating__movie_rating` `idx_user_rating__user_updated` 2개만. 더 있으면:
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
→ 4패널 중 3번(pending)·4번(DB CPU)에 선이 그려지면 정상

### 합의하고 시작 (2분)

> **오늘 절대값은 안 믿는다. 같은 기계에서 조건만 바꾼 상대 비교만 본다.**
> "우리 서버 몇 TPS"는 의미 없다. "풀을 바꿨더니 어느 쪽으로 움직였나"만 본다.

### 오늘 쓰는 ID

```
헤비 유저   36      (5,000건)
라이트 유저 46401   (17건)
인기 영화   60300   (10,339건)
비인기 영화 16710   (109건)
```
바뀌었으면:
```bash
cd C:/seolmin/backend-study/lab/sql
docker exec -i lab-postgres psql -U lab -d labdb < 00_find_test_ids.sql
```

---

## B급 4개 (20분)

### B-1 타입 다른 칼럼 조인 (5분)

```bash
docker exec lab-postgres psql -U lab -d labdb -c "
ALTER TABLE user_rating ADD COLUMN movie_id_str varchar(20);
UPDATE user_rating SET movie_id_str = movie_id::text;
CREATE INDEX idx_rating_movie_str ON user_rating(movie_id_str);
ANALYZE user_rating;"
```

```bash
docker exec lab-postgres psql -U lab -d labdb -c "
EXPLAIN ANALYZE SELECT * FROM user_rating WHERE movie_id_str = '60300';"
```
```bash
docker exec lab-postgres psql -U lab -d labdb -c "
EXPLAIN ANALYZE SELECT r.* FROM user_rating r JOIN movies m ON r.movie_id_str::int = m.movie_id
WHERE m.movie_id = 60300;"
```

👉 가리킬 곳: 위는 `Bitmap Index Scan`, 아래는 `Parallel Seq Scan` + `Filter: ((movie_id_str)::integer = 60300)`

❓ **"인덱스가 분명히 있는데 왜 아래는 안 탔을까?"**

### B-2 선택도 전환점 (5분)

```bash
docker exec lab-postgres psql -U lab -d labdb -c "
EXPLAIN ANALYZE SELECT * FROM user_rating WHERE user_id = 36;"
docker exec lab-postgres psql -U lab -d labdb -c "
EXPLAIN ANALYZE SELECT * FROM user_rating WHERE user_id BETWEEN 1 AND 100;"
docker exec lab-postgres psql -U lab -d labdb -c "
EXPLAIN ANALYZE SELECT * FROM user_rating WHERE user_id BETWEEN 1 AND 1100;"
docker exec lab-postgres psql -U lab -d labdb -c "
EXPLAIN ANALYZE SELECT * FROM user_rating WHERE user_id BETWEEN 1 AND 1150;"
```

👉 가리킬 곳: `Index Scan` → `Bitmap Heap Scan` → (1100) `Bitmap` → (1150) `Seq Scan`

❓ **"1100에서 1150으로 50명 늘렸을 뿐인데 왜 계획이 통째로 바뀌지?"**

### B-3 커버링 인덱스 (5분)

```bash
docker exec lab-postgres psql -U lab -d labdb -c "
EXPLAIN ANALYZE SELECT movie_id, rating FROM user_rating WHERE movie_id = 60300;"
docker exec lab-postgres psql -U lab -d labdb -c "
EXPLAIN ANALYZE SELECT movie_id, rating, updated_at FROM user_rating WHERE movie_id = 60300;"
```

👉 가리킬 곳: 위 `Index Only Scan` + `Heap Fetches: 0` / 아래 `Bitmap Heap Scan` + `Heap Blocks: exact=9315`

❓ **"칼럼 하나 더 달라고 했을 뿐인데 왜 테이블을 읽으러 갈까?"**

### B-4 복합 인덱스 컬럼 순서 (5분)

```bash
docker exec lab-postgres psql -U lab -d labdb -c "
EXPLAIN ANALYZE SELECT * FROM user_rating
WHERE user_id = 36 AND updated_at >= '2026-01-01' ORDER BY updated_at DESC LIMIT 100;"
docker exec lab-postgres psql -U lab -d labdb -c "
EXPLAIN ANALYZE SELECT * FROM user_rating
WHERE user_id = 36 AND updated_at >= '2026-01-01';"
```

```bash
docker exec lab-postgres psql -U lab -d labdb -c "
CREATE INDEX idx_test_reversed ON user_rating(updated_at DESC, user_id);
DROP INDEX idx_user_rating__user_updated;
ANALYZE user_rating;"
```
→ 위 두 쿼리 다시 실행

❓ **"순서를 뒤집으면 나빠질까? ORDER BY가 있을 때랑 없을 때 같을까?"**
(정답 미리 말하지 말 것 — ORDER BY 있으면 거의 안 변하고, 없으면 크게 나빠진다)

**B급 끝나면 원복:**
```bash
cd C:/seolmin/backend-study/lab/sql
docker exec -i lab-postgres psql -U lab -d labdb < 99_cleanup.sql
docker exec -i lab-postgres psql -U lab -d labdb < 04_indexes.sql
docker exec lab-postgres psql -U lab -d labdb -c "\di"
```
→ 인덱스 2개로 돌아왔는지 확인

---

## A-1 관찰 (25분)

Grafana **A-1 한 화면** 띄워놓고 시작.

```bash
cd C:/seolmin/backend-study/lab/k6
export K6_PROMETHEUS_RW_SERVER_URL=http://localhost:9090/api/v1/write
export K6_PROMETHEUS_RW_TREND_STATS="p(95),p(99),avg,max"

k6 run -o experimental-prometheus-rw -e POOL=10 -e PROFILE=rehearsal pool-size.js \
  | tee ../../vault/raw/$(date +%F)_exp-001_session_k6-pool10.txt
```
소요 4분. 워밍업 1분은 버린다.

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

### 앱 재시작 (Windows)

`pkill`은 안 먹는다. 이걸 쓴다:

```bash
powershell.exe -NoProfile -Command "Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id \$_.OwningProcess -Force }"
```

풀 크기는 재빌드 없이 JVM 인자로:
```bash
cd C:/seolmin/backend-study/lab/app
java -Dspring.datasource.hikari.maximum-pool-size=2 -jar build/libs/lab-app-0.0.1.jar
```
확인:
```bash
curl -s http://localhost:8080/actuator/prometheus | grep hikaricp_connections_max
```

### 풀 2 / 10 / 50 (각 5분)

```bash
# --- 풀 2 ---
k6 run -o experimental-prometheus-rw -e POOL=2 -e PROFILE=rehearsal pool-size.js \
  | tee ../../vault/raw/$(date +%F)_exp-001_session_k6-pool2.txt

# --- 풀 50 ---
k6 run -o experimental-prometheus-rw -e POOL=50 -e PROFILE=rehearsal pool-size.js \
  | tee ../../vault/raw/$(date +%F)_exp-001_session_k6-pool50.txt
```

👉 가리킬 곳: Grafana 3번 패널의 `active`가 풀 크기까지 차고 `pending`이 쌓인다. 1번(TPS)은 세 번 다 비슷하다.

❓ **"예측 맞았어? 풀을 25배 키웠는데 처리량이 왜 안 늘지?"**

### 타임아웃 증폭 (10분)

```bash
# 조건 A — 30초
powershell.exe -NoProfile -Command "Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id \$_.OwningProcess -Force }"
cd C:/seolmin/backend-study/lab/app
java -Dspring.datasource.hikari.connection-timeout=30000 -jar build/libs/lab-app-0.0.1.jar
```
```bash
cd C:/seolmin/backend-study/lab/k6
k6 run -o experimental-prometheus-rw -e COND=A -e PROFILE=rehearsal timeout-amplification.js \
  | tee ../../vault/raw/$(date +%F)_exp-001_session_k6-timeoutA.txt
```

```bash
# 조건 B — 1초
powershell.exe -NoProfile -Command "Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id \$_.OwningProcess -Force }"
cd C:/seolmin/backend-study/lab/app
java -Dspring.datasource.hikari.connection-timeout=1000 -jar build/libs/lab-app-0.0.1.jar
```
```bash
cd C:/seolmin/backend-study/lab/k6
k6 run -o experimental-prometheus-rw -e COND=B -e PROFILE=rehearsal timeout-amplification.js \
  | tee ../../vault/raw/$(date +%F)_exp-001_session_k6-timeoutB.txt
```

👉 가리킬 곳: `req_attempts` ÷ `iterations` = 증폭 배수. `user_total_wait` p95.

❓ **"빨리 실패하는 쪽이 사용자를 더 오래 기다리게 할까, 덜 기다리게 할까?"**

---

## A-2 (25분)

### 오프셋 vs 커서 (15분)

앱을 기본 설정으로 되돌리고:
```bash
powershell.exe -NoProfile -Command "Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id \$_.OwningProcess -Force }"
cd C:/seolmin/backend-study/lab/app && java -jar build/libs/lab-app-0.0.1.jar
```

단건부터:
```bash
curl -s -o /dev/null -w "offset %{time_total}\n" "http://localhost:8080/lab/ratings?offset=4900000&limit=10"
curl -s -o /dev/null -w "cursor %{time_total}\n" "http://localhost:8080/lab/ratings?cursorUpdatedAt=2024-10-01T00:00:00Z&limit=10"
```
→ 약 1.2~1.5초 / 약 0.11~0.16초
(`curl -w` 문자열에 한글을 넣으면 콘솔에서 깨진다. 영문으로 둔다)

부하:
```bash
cd C:/seolmin/backend-study/lab/k6
k6 run -o experimental-prometheus-rw -e MODE=offset -e PROFILE=rehearsal offset-vs-cursor.js \
  | tee ../../vault/raw/$(date +%F)_exp-001_session_k6-offset.txt
k6 run -o experimental-prometheus-rw -e MODE=cursor -e PROFILE=rehearsal offset-vs-cursor.js \
  | tee ../../vault/raw/$(date +%F)_exp-001_session_k6-cursor.txt
```

### 인덱스 걸면? (10분)

❓ **"`updated_at`에 인덱스를 걸면 두 쿼리가 각각 어떻게 될까? 둘 다 빨라질까?"**

**적고 나서** 실행:
```bash
docker exec lab-postgres psql -U lab -d labdb -c "
CREATE INDEX idx_user_rating__updated ON user_rating(updated_at DESC);
ANALYZE user_rating;"
```
```bash
curl -s -o /dev/null -w "offset %{time_total}\n" "http://localhost:8080/lab/ratings?offset=4900000&limit=10"
curl -s -o /dev/null -w "cursor %{time_total}\n" "http://localhost:8080/lab/ratings?cursorUpdatedAt=2024-10-01T00:00:00Z&limit=10"
```
→ 오프셋 약 8.5초(**느려짐**) / 커서 약 5.7ms(빨라짐)

```bash
docker exec lab-postgres psql -U lab -d labdb -c "
EXPLAIN ANALYZE SELECT user_id, movie_id, rating, updated_at FROM user_rating
ORDER BY updated_at DESC LIMIT 10 OFFSET 4900000;"
```
👉 가리킬 곳: `Index Scan`으로 바뀐 것

❓ **"인덱스를 걸었는데 왜 오프셋만 느려졌을까?"**

**원복:**
```bash
docker exec lab-postgres psql -U lab -d labdb -c "DROP INDEX idx_user_rating__updated; ANALYZE user_rating;"
```

### ⑦ 통계 미리 집계 — **리허설에서 먼저 확인할 것** ⚠

아직 실측 안 했다. 리허설에서 차이가 나는지 보고, 안 나면 당일에 뺀다.

before (10회씩 재서 평균 — 1회 측정은 노이즈에 묻힌다):
```bash
for i in $(seq 1 10); do curl -s -o /dev/null -w "popular %{time_total}\n" "http://localhost:8080/lab/movies/60300/stats"; done
for i in $(seq 1 10); do curl -s -o /dev/null -w "rare    %{time_total}\n" "http://localhost:8080/lab/movies/16710/stats"; done
```
→ 사전측정 2회가 서로 뒤집혔다: 1차 6.2ms / 12.9ms, 2차 18.8ms / 7.1ms.
**둘 다 한 자릿수 ms라 노이즈에 묻힌다. 이대로면 실험이 안 된다.**

after(미리 집계) 준비 — 앱에 엔드포인트가 아직 없다:
```bash
docker exec lab-postgres psql -U lab -d labdb -c "
ALTER TABLE movies ADD COLUMN rating_count int DEFAULT 0;
ALTER TABLE movies ADD COLUMN rating_sum bigint DEFAULT 0;
UPDATE movies m SET rating_count = s.c, rating_sum = s.s
FROM (SELECT movie_id, count(*) c, sum(rating) s FROM user_rating GROUP BY movie_id) s
WHERE m.movie_id = s.movie_id;"
```

리허설 판정: 3배 이상이면 진행 / 1.5배 미만이면 당일에 뺀다.

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
