# SETUP — 환경 띄우기

clone 후 여기부터 따라간다. 회차 사전 과제("실행 환경을 자기 노트북에
미리 띄워보고 오기")가 이 문서다.

> 현재 구축 상태는 [CLAUDE.md](CLAUDE.md)의 "지금 단계"와
> [vault/progress.md](vault/progress.md)를 따른다. 아직 만들어지지 않은
> 단계(앱, Prometheus/Grafana 등)는 [lab/README.md](lab/README.md)의
> 구축 순서 ①~⑦ 진행 상황에 맞춰 이 문서도 갱신한다.

## 필요한 것

| 도구 | 버전 | 확인 명령 |
|---|---|---|
| Docker Desktop | 최신 | `docker --version` |
| JDK | 21 | `java --version` |
| k6 | 최신 | `k6 version` |

셋 중 하나라도 안 되면 이후 단계가 다 막힌다. 먼저 확인한다.

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

**이게 되면 성공:**
```bash
docker compose ps
```
에서 `lab-postgres`가 `Up` 상태로 보인다.

## 3) 스키마 + 데이터 로드

```bash
cd ../sql
psql "postgresql://lab:lab@localhost:5433/labdb" -f 01_schema.sql
./02_load_movies.sh
psql "postgresql://lab:lab@localhost:5433/labdb" -f 03_seed_ratings.sql
psql "postgresql://lab:lab@localhost:5433/labdb" -c "ANALYZE user_rating;"
psql "postgresql://lab:lab@localhost:5433/labdb" -f 04_indexes.sql
```

`03_seed_ratings.sql`이 user_rating 500만 건을 채운다.
소요 시간: **TODO — 최초 실행 시 실측해서 이 줄에 채워 넣는다.**
(추측치를 적지 않는다. [[CLAUDE.md]]의 "실측 없이 결론을 쓰지 않는다" 원칙을
설정 문서에도 적용한다.)

**이게 되면 성공:**
```sql
SELECT count(*) FROM movies;       -- 19,701
SELECT count(*) FROM user_rating;  -- 5,000,000
```

## 4) 앱 실행

```bash
cd ../../lab/app   # LabApplication.java가 있는 위치
./gradlew bootRun
```

**이게 되면 성공:** 콘솔에 `Started LabApplication` 로그가 뜬다.

## 5) 최종 확인

```bash
curl "http://localhost:8080/lab/movies?limit=1"
```

응답이 JSON으로 오면 성공. 여기까지 되면 회차 당일 바로 실습에 들어갈 수 있다.

## 안 될 때

| 증상 | 원인 | 조치 |
|---|---|---|
| `port is already allocated` | 5433 또는 8080을 다른 프로세스가 쓰고 있음 | `lab/docker/.env`의 `POSTGRES_PORT` 변경 또는 기존 프로세스 종료 |
| 시딩 중 컨테이너가 멈추거나 매우 느림 | Docker Desktop에 할당된 메모리 부족 | Docker Desktop 설정 → Resources → Memory를 4GB 이상으로 |
| `./gradlew bootRun` 실행 시 버전 오류 | JDK가 21이 아님 | `java --version` 확인 후 21로 전환 (sdkman, jenv 등) |
| `psql: command not found` | PostgreSQL 클라이언트 미설치 | `docker exec -it lab-postgres psql -U lab -d labdb` 로 컨테이너 내부 psql 사용 |

## 옵시디언으로 vault 열기

1. Obsidian에서 "Open folder as vault" → 이 저장소의 `vault/` 폴더 선택
2. 커뮤니티 플러그인에서 **Dataview** 설치 후 활성화
   (`vault/dashboard.md`, `vault/progress.md`의 표가 Dataview 쿼리로 되어 있어
   플러그인 없이는 빈 화면으로 보인다)
