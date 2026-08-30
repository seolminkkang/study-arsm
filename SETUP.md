# SETUP — 환경 띄우기

clone 후 여기부터 따라간다. 회차 사전 과제("실행 환경을 자기 노트북에
미리 띄워보고 오기")가 이 문서다.

> 현재 구축 상태는 [CLAUDE.md](CLAUDE.md)의 "지금 단계"와
> [vault/progress.md](vault/progress.md)를 따른다. 아직 만들어지지 않은
> 단계는 [lab/README.md](lab/README.md)의 구축 순서 ①~⑦ 진행 상황에 맞춰
> 이 문서도 갱신한다.

## 먼저 확인할 것 — 원본 영화 덤프

**3단계에서 원본 Moha Cinema 프로젝트의 `exec/sql_dump/`가 필요하다.**
이 저장소에는 없다(용량 때문에 gitignore). 없으면 영화 데이터를 채울 수 없다.

```
exec/sql_dump/movies/moha_movies_2025-09-27_125634.sql
exec/sql_dump/movies/moha_genres_2025-09-27_121107.sql
exec/sql_dump/movies/moha_movie_genres_2025-09-27_121124.sql
```

이 경로를 확보하지 못했으면 **여기서 멈추고 Host에게 요청한다.**
1·2단계를 다 해놓고 3단계에서 막히면 시간만 버린다.

## 필요한 것

| 도구 | 버전 | 확인 명령 |
|---|---|---|
| Docker Desktop | 최신 | `docker --version` |
| JDK | 21 | `java --version` |
| k6 | 최신 | `k6 version` |
| bash | — | `bash --version` (Windows는 Git Bash. `02_load_movies.sh`가 bash 스크립트다) |

넷 중 하나라도 안 되면 이후 단계가 다 막힌다. 먼저 확인한다.

## 1) clone 후 .env 만들기

```bash
git clone <이 저장소 URL>
cd backend-study
cp .env.example lab/docker/.env
```

`docker compose`는 실행 디렉터리 기준으로 `.env`를 찾으므로
`lab/docker/` 안에 복사해둔다. 값은 기본값 그대로 써도 된다
(로컬 실습 전용이라 비밀번호를 따로 관리할 필요가 없다).

**이게 되면 성공:** `lab/docker/.env` 파일이 존재하고 `POSTGRES_DB=labdb` 등이 보인다.

## 2) 컨테이너 띄우기

```bash
cd lab/docker
docker compose up -d
```

컨테이너 4개가 뜬다 — PostgreSQL, Prometheus, Grafana,
그리고 컨테이너별 CPU를 뽑는 docker-stats-exporter다.

**이게 되면 성공:**
```bash
docker compose ps
```
에서 네 개(`lab-postgres`, `lab-prometheus`, `lab-grafana`,
`lab-docker-stats-exporter`)가 전부 `Up`이다.

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000    # Grafana  -> 302
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:9090/-/ready  # Prometheus -> 200
```

Grafana는 익명 접근을 켜뒀으므로 브라우저에서 http://localhost:3000 을 열면
로그인 없이 대시보드가 보인다.

## 3) 스키마 + 데이터 로드

`MOHA_DUMP_DIR`에 **맨 위에서 확인한 원본 덤프 경로**를 넣는다.
안 넣으면 스크립트가 `MOHA_DUMP_DIR (원본 exec/sql_dump 경로)를 지정하세요`로
멈춘다.

```bash
cd ../sql
psql "postgresql://lab:lab@localhost:5433/labdb" -f 01_schema.sql
MOHA_DUMP_DIR="<원본 프로젝트>/exec/sql_dump" ./02_load_movies.sh
psql "postgresql://lab:lab@localhost:5433/labdb" -f 03_seed_ratings.sql
psql "postgresql://lab:lab@localhost:5433/labdb" -c "ANALYZE user_rating;"
psql "postgresql://lab:lab@localhost:5433/labdb" -f 04_indexes.sql
```

`psql`이 로컬에 없으면 컨테이너 안의 psql로 대신할 수 있다. 파일은 표준입력으로 넣는다.

```bash
docker exec -i lab-postgres psql -U lab -d labdb < 01_schema.sql
docker exec -i lab-postgres psql -U lab -d labdb < 03_seed_ratings.sql
docker exec    lab-postgres psql -U lab -d labdb -c "ANALYZE user_rating;"
docker exec -i lab-postgres psql -U lab -d labdb < 04_indexes.sql
```

(`02_load_movies.sh`는 이미 `docker exec`로 적재하므로 psql 설치와 무관하다.)

`03_seed_ratings.sql`이 user_rating 500만 건을 채운다.
소요 시간: **TODO — 최초 실행 시 실측해서 이 줄에 채워 넣는다.**
(추측치를 적지 않는다. [CLAUDE.md](CLAUDE.md)의 "실측 없이 결론을 쓰지 않는다"
원칙을 설정 문서에도 적용한다.)

**이게 되면 성공:**
```sql
SELECT count(*) FROM movies;        -- 19,701
SELECT count(*) FROM genres;        -- 19
SELECT count(*) FROM movie_genres;  -- 47,104
SELECT count(*) FROM user_rating;   -- 약 5,030,000
```

`ANALYZE`를 빠뜨리면 옵티마이저가 옛날 통계로 판단해서 실행계획이 이상하게
나온다. "인덱스가 안 타네?"의 흔한 원인이다. 건수가 맞는데 뭔가 이상하면
`ANALYZE user_rating;`부터 다시 돌린다.

## 4) 앱 실행

```bash
cd ../../lab/app   # LabApplication.java가 있는 위치
./gradlew bootRun
```

**이게 되면 성공:** 콘솔에 `Started LabApplication` 로그가 뜬다.
기동은 5초 안쪽이다(2026-08-29 실측 4.7~5.3초).

## 5) 앱 확인

```bash
curl "http://localhost:8080/lab/movies?limit=1"
```

**이게 되면 성공:** 영화 한 편이 JSON으로 온다.

메트릭도 같이 확인한다. Grafana 패널이 여기서 나오는 값을 그린다.

```bash
curl -s http://localhost:8080/actuator/prometheus | grep hikaricp_connections_pending
```

**이게 되면 성공:** `hikaricp_connections_pending{pool="HikariPool-1"} 0.0` 이 보인다.

Prometheus가 앱을 실제로 긁고 있는지도 본다.
http://localhost:9090/targets 를 열어서 `lab-app`과 `docker-stats`가
둘 다 **UP**이면 된다. `lab-app`이 DOWN이면 앱은 떠 있어도 Grafana는
계속 No data다.

## 6) k6 한 번 돌려보기

먼저 스크립트가 파싱되는지 본다. 부하를 걸지 않고 설정만 읽어서 출력한다.

```bash
cd ../k6
k6 inspect offset-vs-cursor.js
```

**이게 되면 성공:** `scenarios`에 `warmup`과 `ramp`가 들어 있는 JSON이 나온다.

실제로 서버를 때려본다. 5초, VU 1개짜리 스모크다.

```bash
k6 run --duration 5s --vus 1 -e MODE=cursor -e PROFILE=rehearsal offset-vs-cursor.js
```

**이게 되면 성공:** 요약에 `http_req_failed ... 0.00%`가 찍힌다.
여기까지 되면 회차 당일 바로 실습에 들어갈 수 있다.

> `"cli" level configuration overrode scenarios configuration entirely` 경고가
> 뜨는 게 정상이다. `--duration`·`--vus`를 주면 스크립트의 워밍업 60초와
> 도착률 시나리오가 통째로 무시된다. **그래서 이건 측정이 아니라 연결 확인이다.**
> 결과를 `vault/raw/`에 넣지 않는다. 실험할 때는 이 두 플래그 없이
> `k6 run -e MODE=... -e PROFILE=... offset-vs-cursor.js` 로 돌린다.

## 안 될 때

| 증상 | 원인 | 조치 |
|---|---|---|
| `MOHA_DUMP_DIR ...를 지정하세요` | 3단계에서 원본 덤프 경로를 안 줌 | 맨 위 "먼저 확인할 것" 참고. 덤프가 없으면 Host에게 요청 |
| `./02_load_movies.sh: command not found` / 실행 안 됨 | Windows에서 cmd·PowerShell로 실행 | Git Bash에서 실행한다 |
| `port is already allocated` | 5433·8080·3000·9090 중 하나를 다른 프로세스가 씀 | `lab/docker/.env`에 `POSTGRES_PORT` / `GRAFANA_PORT` / `PROMETHEUS_PORT`를 바꿔 넣거나 기존 프로세스 종료. 3000은 프런트 dev 서버와 자주 겹친다 |
| 시딩 중 컨테이너가 멈추거나 매우 느림 | Docker Desktop에 할당된 메모리 부족 | Docker Desktop 설정 → Resources → Memory를 4GB 이상으로 |
| `./gradlew bootRun` 실행 시 버전 오류 | JDK가 21이 아님 | `java --version` 확인 후 21로 전환 (sdkman, jenv 등) |
| `psql: command not found` | PostgreSQL 클라이언트 미설치 | 3단계의 `docker exec -i` 형태를 쓴다 |
| Grafana 패널이 전부 No data | Prometheus가 앱을 못 긁고 있음 | http://localhost:9090/targets 에서 `lab-app`이 UP인지 확인. 앱이 떠 있는데 DOWN이면 방화벽이 `host.docker.internal:8080`을 막는지 본다 |
| k6가 `request timeout` | 서버가 이미 포화 | 정상일 수 있다. 스모크는 `--vus 1`로 돌린다. 부하 수준의 근거는 [lab/k6/README.md](lab/k6/README.md) |

## 다시 처음부터 하고 싶을 때

인덱스만 원복하면 되는 경우, 실험용 칼럼까지 지우는 경우, 볼륨째 지우는 경우가
각각 다르다. [lab/README.md](lab/README.md)의 "데이터 초기화" 절을 따른다.

## 옵시디언으로 vault 열기

1. Obsidian에서 "Open folder as vault" → 이 저장소의 `vault/` 폴더 선택
2. 커뮤니티 플러그인에서 **Dataview** 설치 후 활성화
   (`vault/dashboard.md`, `vault/progress.md`의 표가 Dataview 쿼리로 되어 있어
   플러그인 없이는 빈 화면으로 보인다)
