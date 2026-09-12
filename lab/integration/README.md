# 4–5장 외부 연동 실습 준비 환경

**문제가 있는 시작 코드**다. 운영용 예제가 아니며 인증 없는 장애 제어 API를 포함한다.
기존 `lab/app`, 영화 데이터, 1회차 컨테이너는 변경하지 않는다.
실습은 리뷰 서비스 A → HTTP/1.1 → 포인트 서비스 B로 진행한다.
같은 실행 파일을 역할 설정으로 두 프로세스에서 실행하며, PostgreSQL 스키마도 분리한다.
물리 DB를 공유하므로 CPU·디스크 장애까지 분리한 MSA 실험은 아니다.

## 시작

Docker Desktop을 실행한 뒤, 이 디렉터리에서:

```sh
docker compose up --build -d
docker compose logs -f review points
```

첫 빌드에는 네트워크가 필요하다. 컨테이너 안에서 Java 21로 자동 테스트와 빌드를 실행한다.
DB 준비 후 앱 초기화까지 기다리고 다음 응답을 확인한다.

```sh
curl -f http://localhost:8081/actuator/health
curl -f http://localhost:8082/actuator/health
```

| 주소 | 용도 |
|---|---|
| localhost:8081 | 리뷰 A |
| localhost:8082 | 포인트 B |
| localhost:5434 | 실습 전용 PostgreSQL |
| localhost:9091 | Prometheus |
| localhost:3001 | Grafana (lab / integration-local) |

Grafana → Dashboards → **4–5장 외부 연동 실험**.
모든 호스트 포트는 127.0.0.1에만 공개한다. 다른 컴퓨터/인터넷에 노출하지 않는다.
기존 포트 8080/5433/9090/3000과 분리했다. 새 포트를 이미 사용 중이면 시작 전에 확인한다.
비밀번호는 격리된 로컬 실습 전용 공개 값이다.

## 요구사항

리뷰 저장 후 포인트는 늦게 지급되어도 된다. 같은 리뷰에 중복 지급하면 안 된다.
포인트 장애가 리뷰 조회까지 마비시키면 안 된다.
**시작 코드는 이 요구사항을 모두 만족하지 않는다.**

## 기본 요청

```sh
curl -sS -H 'Content-Type: application/json' -H 'X-Attempt-Id: attempt-1' \
  -d '{"id":"review-1","content":"재미있어요"}' http://localhost:8081/reviews
curl -sS http://localhost:8081/reviews
curl -sS http://localhost:8082/grants
```

리뷰 ID는 영문/숫자/밑줄/하이픈 1~100자다. 새 실험에는 새 ID를 사용한다.
reviewId는 같은 업무를 식별한다. X-Attempt-Id는 각 네트워크 시도를 구분한다.
리뷰 ID 중복 삽입은 현재 오류다. A 전체 요청의 멱등성과 B 지급 멱등성은 별도 문제다.

## 장애 조절: 한 번에 한 조건

```sh
# 정상
curl -sS -H 'Content-Type: application/json' \
  -d '{"beforeMs":0,"afterMs":0,"fail":false}' http://localhost:8082/control/fault

# 지급 전에 3초 대기: 자원 점유 실험
curl -sS -H 'Content-Type: application/json' \
  -d '{"beforeMs":3000,"afterMs":0,"fail":false}' http://localhost:8082/control/fault

# 지급은 커밋하고 응답만 3초 지연: 타임아웃과 중복 지급
curl -sS -H 'Content-Type: application/json' \
  -d '{"beforeMs":0,"afterMs":3000,"fail":false}' http://localhost:8082/control/fault

# 저장 전 503 반환
curl -sS -H 'Content-Type: application/json' \
  -d '{"beforeMs":0,"afterMs":0,"fail":true}' http://localhost:8082/control/fault
```

지연은 0~30000ms만 허용한다. 요청이 시작될 때 조건을 복사하므로,
조건을 정상으로 바꿔도 이미 진행 중인 지연은 끝날 때까지 남는다.
조건 변경 후 이전 요청 종료를 로그/active 지표로 확인한다.
서버 sleep은 응답·처리 지연 모형이다. TCP 연결 실패나 패킷 손실을 재현하는 기능은 아니다.

## HTTP 연결 관찰

A는 Apache HttpClient 5 classic을 명시해서 사용한다. 자동 재시도는 꺼져 있다.
풀 전체/대상별 최대 연결 수는 같게 설정한다.
각각 다른 리뷰 ID로 순차 호출하고 B 로그의 remote 포트 재사용을 확인한다.
이 값은 이 로컬 직접 연결 환경에서의 관찰 보조 수단이며 영구 연결 ID가 아니다.
그다음 동시 호출하면서 Grafana의 leased(사용), pending(획득 대기)을 함께 본다.

| 설정 | 기본 | 의미 |
|---|---:|---|
| HTTP_POOL_SIZE | 2 | 전체·대상별 최대 연결 수 |
| HTTP_ACQUIRE_MS | 500 | 풀에서 연결을 빌릴 때 기다리는 한도 |
| HTTP_CONNECT_MS | 1000 | 새 연결 수립 한도 |
| HTTP_READ_MS | 1000 | 응답 대기 설정. 모든 단계를 합친 전체 요청 deadline이 아님 |
| DB_POOL_SIZE | 4 | A DB 풀 최대 연결 수 |

예: **다른 조건은 그대로 두고** 응답 대기만 늘린다.

```sh
HTTP_READ_MS=5000 docker compose up -d --no-deps --force-recreate review
```

다음 compose 명령에도 같은 환경 값을 전달해야 해당 조건을 유지/기록할 수 있다.
A의 `ReviewController.create`는 DB 트랜잭션 안에서 HTTP를 호출한다.
개선할 때 자원 점유뿐 아니라 데이터 정합성도 검증한다.

## 비동기 작업 유실: 정확한 중단 지점

먼저 B를 정상으로 돌린다. 이후:

```sh
curl -sS -X POST 'http://localhost:8081/control/worker?paused=true'
curl -sS -H 'Content-Type: application/json' \
  -d '{"id":"async-1","content":"비동기 실험"}' 'http://localhost:8081/reviews?mode=async'
curl -sS http://localhost:8081/control/worker
curl -sS http://localhost:8081/reviews
curl -sS http://localhost:8082/grants
# 리뷰가 저장됐고 작업 active/queued가 존재하며 지급이 없는 것을 확인한 후,
# 이 실습 프로젝트의 review 컨테이너만 강제 종료한다.
docker compose kill -s SIGKILL review
docker compose up -d review
# health UP을 확인하고 리뷰/지급 내역을 다시 조회한다.
```

paused는 A 내부 작업자가 B를 부르기 전에 멈추는 장치다.
B 안에서 멈추면 A 종료 후에도 B가 지급할 수 있으므로 서로 다른 실험이다.
정상 해제: `curl -X POST 'http://localhost:8081/control/worker?paused=false'`.
비동기 모드는 worker 1개 + 대기열 20개로 한정했다. 재시작하면 메모리 작업은 복구하지 않는다.
큐 포화 시 리뷰는 이미 저장됐는데 503을 반환하는 틈도 있다.
이 executor 기반 비교 버전은 @Async 프록시 동작 자체를 가르치는 예제가 아니다.

## 측정과 원본 기록

k6 설치 후, 매번 새 RUN_ID를 지정한다.

```sh
bash scripts/capture.sh k6 run -e RUN_ID=trial-001 -e RATE=5 load.js
```

기준 부하는 1분 워밍업 + 5초 간격 + 1분 측정이다. 환경별 안정화는 별도로 확인한다.
k6 JSON 원본까지 보관하려면 `--out json=<겹치지 않는 파일 경로>`를 추가한다.
기본 k6 전체 요약은 워밍업을 포함한다. 별도로 표시되는 phase=measure 하위 지표로 비교한다.
스크립트의 RATE는 리뷰 작성 시나리오 도착률이다. 독립 조회 시나리오는 초당 2회다.
작성 지연 때문에 조회 요청 생성까지 늦어지지 않도록 두 시나리오를 분리했다.
p95만 보지 말고 응답 실패율, 실제 지급 건수, 대기 수를 함께 확인한다.
비동기 200은 포인트 완료가 아니라 리뷰 저장/작업 제출 결과다.
dropped_iterations는 목표 부하를 만들지 못한 횟수다. 0이 아니면 조건 미달을 기록하고
부하 발생기 한계인지 시스템 지연인지 확인한다. 모든 측정치가 자동으로 무의미해지는 것은 아니다.

capture는 새 runs 디렉터리에 커밋, 변경 diff, compose 설정, 장애 설정, 명령,
stdout/stderr, 서비스 로그, 최종 데이터와 종료 코드를 저장한다.
측정 중 프로세스를 죽이는 실험은 명령들을 실행하는 별도 스크립트를 capture로 감싼다.
서비스 로그는 누적본이므로 start/end와 reviewId로 해당 실행을 구분한다.
미추적 파일 내용은 diff에 포함되지 않는다. 측정 전 코드를 커밋해 조건을 고정한다.
runs는 Git에서 제외한다. 검토한 원본만 vault/raw에 **새 이름으로 추가**한다.
예측/결론은 자동 작성하지 않는다.

## 테스트

호스트에 Java 21이 있으면 기존 Gradle wrapper를 재사용한다.

```sh
bash ../app/gradlew -p . test bootJar
```

자동 테스트는 H2 메모리 DB를 사용한다. PostgreSQL과 Docker 실행 검증을 대체하지 않는다.
컨테이너가 실행 중이고 다른 실험이 없을 때 실제 두 서비스의 시작 동작을 확인할 수 있다.
아래 검증은 기본 HTTP_READ_MS=1000 조건을 전제로 한다.

```sh
python3 scripts/smoke.py
# 추가로 review 컨테이너만 강제 종료/재시작해서 메모리 작업 유실을 확인한다.
bash scripts/capture.sh python3 scripts/smoke.py --crash
```

검증 데이터는 고유한 smoke ID로 남기며 자동 삭제하지 않는다.
현재 테스트에는 **중복 지급/타임아웃 뒤 원격 반영이 재현되는 것**을 확인하는
characterization test가 있다. 해결 코드를 작성하면 그 테스트의 기대값도 요구사항에 맞게 바꾼다.

직접 고칠 곳:
- ReviewController: 트랜잭션 경계, 외부 호출 동시 요청 제한, 비동기 내구성
- PointsController + schema.sql: 업무 식별자 기반 원자적 중복 방지
- HttpConfiguration: 타임아웃/풀 조건
- 후속 단계: 저장된 작업 처리, 아웃박스, 메시징 (현재 미구현)

## 정리

`docker compose down`은 이 프로젝트 컨테이너만 중지/제거하고 DB 볼륨은 보존한다.
기존 lab/docker에서 down을 실행하거나 기존 볼륨을 제거하지 않는다.
실습 데이터 초기화가 필요하면 실행 중인 요청이 없는 상태에서 아래를 사용한다.
**이 환경의 리뷰·지급 데이터가 지워지며 복구되지 않는다. 원본을 먼저 저장한다.**

```sh
docker compose stop review points
docker compose exec -T db psql -U integration -d integration -c \
  'TRUNCATE review.reviews, points.point_grants RESTART IDENTITY;'
docker compose start review points
```

학습 코드이므로 전역 타임아웃 정책, 보안, 배포, 복구 보장은 갖추지 않았다.
설정 수치는 실험 시작값이지 운영 권장값이나 성능 실측 결과가 아니다.
