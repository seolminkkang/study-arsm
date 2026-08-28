# lab — 실험 환경

Moha Cinema 프로젝트의 **DB 스키마와 영화 데이터만 재활용**하고,
앱은 최소한으로 새로 만든다.

## 왜 기존 앱을 안 쓰는가

원본 Moha 백엔드에는 OAuth, JWT, Security, WebFlux, MyBatis, 추천 서비스(FastAPI)가
얽혀 있다. 부하를 걸면 응답 시간에 Security 필터 체인과 프레임워크 초기화가 다 섞여서
"쿼리가 느린 건지 다른 게 느린 건지" 구분이 안 된다.

성능 실험은 병목을 하나만 만들어놓고 그게 이동하는 걸 봐야 한다.
병목 후보가 여러 개면 실험이 성립하지 않는다.

원본은 건드리지 않는다. 사본에서 작업한다.

## 구축 순서

앞이 막히면 뒤가 다 막히는 순서로 배열했다.

### ① PostgreSQL 컨테이너 + 스키마

실습 전용 DB를 새로 띄운다. 개발 DB를 쓰지 않는다.
인덱스를 지웠다 걸었다 하고 500만 건을 밀어넣을 것이므로 분리돼야 한다.

필요한 테이블은 4개.

```sql
movies       (movie_id, title, original_title, release_date,
              runtime, director, vote_count, poster_path)
genres       (genre_id, name)
movie_genres (movie_id, genre_id)
user_rating  (user_id, movie_id, rating, created_at, updated_at)
```

**반드시 제외할 것**
- `movies.overview` — 82MB 덤프의 대부분. 실험에 무관
- `movies.movie_vector vector(256)` — pgvector 확장이 필요해진다. 실험에 무관
- `movies.keywords`, `genre_cache`, `status`, `attempt_count` 등 파이프라인 칼럼
- `user_account` — FK 없이 `user_id`를 숫자로 쓴다. FK가 없으면 대량 INSERT가 훨씬 빠르다

### ② 영화 데이터 로드

원본 덤프 위치 (원본 프로젝트의 `exec/sql_dump/`):
```
movies/moha_movies_*.sql        19,701건
movies/moha_genres_*.sql             19건
movies/moha_movie_genres_*.sql  144,696건  (movies에 실제 있는 movie_id만 남기면 47,104건)
```

실측치다(2026-08-28). movie_genres는 원본 세 덤프 파일의 export 시각이 서로 달라서
(최대 45분 차이) movies 정리 이후 값과 안 맞는 movie_id를 다수 참조한다 —
자세한 내용은 `lab/sql/README.md` 참고.

PostgreSQL `COPY ... FROM stdin` 형식이다. 칼럼을 골라 뽑아야 하므로
awk로 `COPY` 블록만 추출해서 필요한 칼럼 인덱스만 남기는 방식이 무난하다.

영화는 실제 데이터를 그대로 쓴다. 제목이 진짜라서 쿼리 짜고 결과 보기가 훨씬 쉽다.
`title = 'random text 847293'`과 `title = '스트립퍼 배심원'`은 디버깅 난이도가 다르다.

### ③ user_rating 시딩 — 500만 건

원본은 583건뿐이라 증폭이 필요하다.

**개수보다 분포가 중요하다.** 균등 분포로 넣으면 3장의 "선택도" 절이
실습에서 통째로 죽는다. 누구를 조회하든 건수가 같아지기 때문이다.

양쪽 다 치우치게 한다.

```
사용자 10만 명
- 헤비   100명  → 각 5,000건   (50만)
- 중간   1만 명 → 각 300건     (300만)
- 라이트 9만 명 → 각 17건      (150만)

영화 쪽 쏠림
- 인기 영화 200편에 평점의 40%
- 나머지는 롱테일

created_at
- 최근 몇 달에 몰리게 (시간 범위 제한 실습용)
```

사용자 쪽 쏠림은 `(user_id, updated_at)` 인덱스 실습용이고,
영화 쪽 쏠림은 선택도 실습용이다. 둘 다 필요하다.

JPA로 한 건씩 넣으면 몇 시간 걸린다. `generate_series`로 한 방에 넣는다.

**넣고 나서 반드시 `ANALYZE user_rating;`** — 통계가 갱신되지 않으면
옵티마이저가 옛날 정보로 판단해서 실행계획이 이상하게 나온다.
"인덱스가 안 타네?"의 흔한 원인이다.

### ④ EXPLAIN 찍어보기 — 여기서 3장 실습이 이미 가능

앱도 Grafana도 없이 3장의 절반이 확인된다.
- 인덱스 유무 비교
- 오프셋 vs 커서
- 커버링 인덱스
- 타입 다른 칼럼 조인

⑤ 이후가 막혀도 스터디는 굴러간다.

### ⑤ 스프링 앱 — 파일 5개

```
LabApplication.java
LabController.java     조회 API 4개
LabRepository.java     쿼리
application.yml        DB 연결 + Actuator 노출
build.gradle
```

의존성 5개면 충분하다.
```
spring-boot-starter-web
spring-boot-starter-data-jpa
spring-boot-starter-actuator
io.micrometer:micrometer-registry-prometheus
org.postgresql:postgresql
```

Security 없음, JWT 없음, OAuth 없음, MyBatis 없음, WebFlux 없음.
`userId`는 토큰이 아니라 쿼리 파라미터로 받는다. 인증이 개입할 여지를 없앤다.

**엔드포인트 4개** — 3장 목차에 대응한다.

| 엔드포인트 | 실험 대상 | 책 |
|---|---|---|
| `GET /lab/movies?offset=&limit=` | 오프셋 페이징 | ID 기준 목록 조회 |
| `GET /lab/movies?cursorId=&limit=` | 커서 페이징 (개선안) | 〃 |
| `GET /lab/ratings?userId=&from=&to=` | 복합 인덱스, 선택도 | 인덱스 설계 |
| `GET /lab/movies/{id}/stats` | count 집계 vs 미리 집계 | 전체 개수 세지 않기 |

HikariCP 커넥션 획득 시간 히스토그램을 보려면 이 설정이 필요하다.
```yaml
spring:
  datasource:
    hikari:
      metrics-tracker-factory: MicrometerMetricsTrackerFactory
```

컨테이너 자원은 명시적으로 제한한다. 안 하면 노트북 발열로 CPU 클럭이
내려가는 순간 숫자가 다 바뀌어서 재현이 안 된다.
```yaml
deploy:
  resources:
    limits:
      cpus: "2"
      memory: 1g
```

### ⑥ Prometheus + Grafana

Grafana 대시보드 **20729 (Spring Boot JDBC & HikariCP)**.
범용 4701보다 이 목적에 맞는다. Spring Boot 3.x 지원.

봐야 할 메트릭
- `hikaricp_connections_pending` — 커넥션 못 얻어 대기 중
- `hikaricp_connections_active` / `idle`
- `tomcat_threads_busy`
- `jvm_gc_pause_seconds`
- `http_server_requests_seconds` — **k6가 본 시간과의 차이가 곧 큐 대기 시간**

**k6 결과와 서버 메트릭을 같은 Grafana 시간축에 올린다.**
`K6_PROMETHEUS_RW_SERVER_URL`로 remote write.

두 그래프가 다른 화면에 있으면 "그런가 보다" 하고 넘어간다.
한 화면에서 TPS 곡선이 꺾이는 시점과 pending이 치솟는 시점이 겹치는 걸 봐야
인과가 몸으로 들어온다.

### ⑦ k6

**도착률(arrival rate) 기반으로 짠다. VU 기반이 아니다.**

VU 100개로 부하를 주면 서버가 느려질 때 VU도 응답을 기다리느라 다음 요청을
안 보낸다. 즉 서버가 느려지면 부하도 줄어들어 스스로를 보호해버린다.
그러면 포화점이 드러나지 않는다. 실제 사용자는 서버가 느리다고 요청을 멈추지 않는다.

이 책의 2장 커넥션 대기 시간 절과 3장 쿼리 타임아웃 절이 같은 얘기를 한다:
느려지면 사용자가 재시도해서 부하가 오히려 **늘어난다**.
그 현상은 도착률 기반으로만 관측된다.

```javascript
export const options = {
  scenarios: {
    warmup: {                          // JVM JIT. 이 구간은 버린다
      executor: 'constant-arrival-rate',
      rate: 20, timeUnit: '1s', duration: '60s',
      preAllocatedVUs: 50,
      tags: { phase: 'warmup' },
    },
    ramp: {                            // 계단식 — 포화점이 어디서 오는지
      executor: 'ramping-arrival-rate',
      startTime: '60s',
      startRate: 50, timeUnit: '1s',
      preAllocatedVUs: 100, maxVUs: 2000,
      stages: [
        { target: 100, duration: '60s' },
        { target: 200, duration: '60s' },
        { target: 400, duration: '60s' },
        { target: 800, duration: '60s' },
      ],
      tags: { phase: 'ramp' },
    },
  },
  thresholds: {
    'http_req_failed': ['rate<0.01'],
    'dropped_iterations': ['count<100'],
  },
};
```

**결과에서 볼 순서**

1. `dropped_iterations` — 0이 아니면 목표 부하를 못 만든 것이고,
   그 실험의 다른 숫자는 전부 무효다. maxVUs 부족(스크립트 문제)인지
   서버 포화(진짜 결과)인지 k6 쪽 CPU를 보고 구분한다
2. 목표 rate vs 실제 `http_reqs` — 안 따라오기 시작하는 지점이 **포화점**
3. `http_req_waiting` — `http_req_duration`이 아니라 이걸 본다.
   duration은 blocked+connecting+tls+sending+**waiting**+receiving의 합이고,
   순수 서버 처리 시간은 waiting이다.
   connecting이 크면 서버가 느린 게 아니라 커넥션을 새로 맺는 것이고,
   처방이 완전히 다르다(4장 HTTP 커넥션 풀)
4. p95 / p99. **평균은 무시한다.** 커넥션 풀이 모자라면 대부분은 빠르고
   일부만 대기하는데 평균이 그걸 뭉갠다

## 부하 생성기 위치

k6와 앱을 같은 노트북에서 돌리면 **CPU를 두고 서로 싸운다.**
부하를 올리면 k6가 CPU를 먹어서 앱이 느려지는데, 이건 앱이 느려진 게 아니라
노트북이 느려진 거다. 모르고 진행하면 "풀 50이 더 느리네?"라는 틀린 결론에 도달한다.

**2인 스터디의 이점을 쓴다.** 한 명 노트북에 앱+DB, 다른 노트북에서 k6.
같은 공유기면 지연은 무시할 수준이다.
그리고 두 사람이 각각 "서버 쪽"과 "클라이언트 쪽"을 보게 되어 구도도 좋다.

여의치 않으면 **절대값을 버리고 상대값만 본다.** "우리 서버는 3000 TPS"는
스터디에서 의미가 없다. 같은 세션, 같은 기계에서 노브만 바꿨을 때의
before/after만 유효하다고 첫 회차에 못 박고 시작한다.

## 파일럿 — 정식 실험 전 반드시

혼자 미리 돌려서 확인할 것은 하나다.

> **before/after 차이가 눈에 띄게 나는가**

| 차이 | 판정 |
|---|---|
| 3배 이상 | 좋음 |
| 1.5~3배 | 애매. 데이터 늘리거나 조건 조정 |
| 1.5배 미만 | 실패. 다른 실험으로 교체 |

당일에 처음 돌리면 안 된다. 차이가 안 나면 그 시간이 통째로 날아가고,
팀원 앞에서 "어... 왜 안 되지"를 하게 된다. Host의 진짜 준비가 이것이다.

## 데이터 초기화

실험 중 인덱스를 지우고 실험용 칼럼(`movie_id_str`, `rating_count` 등)을
추가하다 보면 원래 상태를 잃는다. 언제든 되돌릴 수 있어야 마음 편히 부술 수 있다.

### 인덱스만 복구

```bash
psql "postgresql://lab:lab@localhost:5433/labdb" -f sql/04_indexes.sql
```

`04_indexes.sql`이 실험용으로 지운 인덱스를 원래 상태로 다시 만든다.

### 실험용 추가 칼럼 제거

B급 실험(`movie_id_str`)이나 A-2(`rating_count`, `rating_sum`)에서
스키마에 덧붙인 칼럼과 인덱스는 `sql/99_cleanup.sql`에 DROP 문으로 모아둔다.

```bash
psql "postgresql://lab:lab@localhost:5433/labdb" -f sql/99_cleanup.sql
```

### 전체 초기화

컨테이너 볼륨째 지우고 처음부터 다시 쌓는다. 인덱스 구조 자체를 바꿔서
`04_indexes.sql`로도 못 되돌릴 때 쓴다.

```bash
cd docker
docker compose down -v   # 볼륨(lab_pgdata) 삭제 — 데이터 전부 사라짐
docker compose up -d
cd ../sql
psql "postgresql://lab:lab@localhost:5433/labdb" -f 01_schema.sql
./02_load_movies.sh
psql "postgresql://lab:lab@localhost:5433/labdb" -f 03_seed_ratings.sql
psql "postgresql://lab:lab@localhost:5433/labdb" -c "ANALYZE user_rating;"
psql "postgresql://lab:lab@localhost:5433/labdb" -f 04_indexes.sql
```

소요 시간: **TODO — 최초 실행 시 실측해서 채운다** (500만 건 시딩이 대부분을 차지한다).

`docker compose down -v`는 되돌릴 수 없다. 실험 중 임시로 넣은 값이 있다면
먼저 `raw/`나 노트에 옮겨 적었는지 확인하고 실행한다.
