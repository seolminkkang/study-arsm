# 4–5장 외부 연동 실습 준비 환경

**버튼으로 두 사람이 실습하려면 [간단 실행 안내](START-HERE.md)부터 읽으세요.**

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
- 버튼으로 비교할 해결 분기: `outside`, `guarded`, `circuit`, `idempotent`, `outbox`, `broker`.
- 문제 분기는 지우지 않는다. 중복 허용 characterization test도 기존 모드의 증거로 유지한다.

## 두 화면으로 진행하기 · 같은 Wi-Fi

실행자 노트북만 이 레포와 Docker가 필요하다. 이 디렉터리(`lab/integration`)에서
`docker compose up --build -d`로 환경을 켠 뒤 별도 터미널에서 실행한다.

```sh
python3 scripts/session.py serve
```

- 실행자: `http://127.0.0.1:8090` → 설명 읽기 → 두 사람의 예측 기록 → 단계 실행 → 실제 결과 → 해설.
- 관찰자: 실행자 화면의 **친구 접속 주소**를 받아 브라우저로 연다. 같은 Wi-Fi에서 현재 단계와 관측값을 공유한다. 레포나 Docker 설치는 필요 없다.
- 실험 중에는 **화면 버튼만 사용**한다. 변경 전후 코드는 읽기용이며, 버튼이 미리 구현된 분기를 실행한다. 내부 명령은 접힌 참고 영역에만 둔다.
- 관찰 화면은 8091 읽기 전용이다. 실행 포트 8090과 DB/API/Grafana는 localhost에 유지한다. 신뢰하는 사설 Wi-Fi에서만 사용하며 인터넷 배포·공유기 포트포워딩을 하지 않는다. 접속 키가 있어도 HTTP 통신은 암호화되지 않는다.
- 같은 Wi-Fi여도 게스트 네트워크의 기기 간 차단, 방화벽, 호스트 절전으로 접속이 안 될 수 있다. 호스트 IP가 바뀌면 새 주소를 공유한다.
- Grafana는 필수가 아니다. 관찰 화면은 Prometheus 지표와 리뷰·지급 API 데이터를 함께 보여준다. 타임아웃·중복 지급은 그래프뿐 아니라 실제 행을 확인한다.

화면은 단일 파일을 열어 사용하는 시뮬레이션이 아니라 로컬 웹앱이다. 설명의 흐름 도식과 실제 측정값을 구분한다.
브라우저가 연결되지 않거나 값 수집에 실패하면 `확인 불가`로 표시한다. 과거 단계는 **종료 시점 기록**, 전환 버튼을 누르면 **실시간 상태**다.
약 6초의 예약 요청 실험은 정밀 처리량 벤치마크가 아니며 순간적인 풀 사용은 수집 사이에 지나갈 수 있다.

### 반복 실행 · 세 가지 정리의 차이

| 동작 | 변경하는 것 | 보존하는 것 |
| --- | --- | --- |
| 마지막 마무리 단계 | B 지연 해제, A 작업자 일시정지 해제 | DB와 이전 기록. 미완료 작업이 남아 있으면 해제 후 처리될 수 있음 |
| 새 세션 시작 | 새 ID, 빈 예측 칸과 진행 기록 | DB와 이전 세션 파일 |
| **이번 실험 초기화** | 큐 비움·소비자 정지·CDC 슬롯 종료 확인 → A·B·B2 중지 → DB 백업 → 실험 8테이블 비우기 → 기본 설정 재시작 → 새 세션 | 기존 영화 실습 DB, 수정한 코드·스키마, 배치 파일·이전 기록/백업, Prometheus 과거 시계열 |

화면 맨 아래 **이번 실험 초기화**에서 범위를 확인하고 `4·5장 실험 초기화`를 입력한다.
마지막 단계까지 갈 필요 없이 현재 단계 실행이 끝나면 사용할 수 있다. 먼저 다른 터미널의 부하 테스트·수동 요청을 중단한다.

대상은 `arsm-integration` 프로젝트의 `integration` DB,
`arsm-integration_integration-data` 볼륨 안에 있는 **`review.reviews`, `review.outbox`, `review.batch_received`, `review.cdc_source`, `review.cdc_target`, `review.cdc_seen`, `points.point_grants`, `points.backup_grants`의 모든 행**이다.
직접 입력한 실험 데이터도 포함한다. 실제 컨테이너 라벨·DB 설정·볼륨이 다르면 초기화를 거부한다.
`lab/docker`의 기존 DB나 볼륨 삭제(`down -v`)는 사용하지 않는다. 위 8테이블 외의 추가 테이블이나 스키마 변경은 원복하지 않는다.
미완료 `labcdc_` 슬롯이 있으면 DB 초기화를 거절한다. CDC 재개 또는 해당 세션 마무리를 먼저 실행한다.
화면 서버 종료로 이전 세션 슬롯이 남았다면 이름·세션 기록을 확인한 후 별도 정리가 필요하다. 다른 슬롯을 자동 삭제하지 않는다.
RabbitMQ 메시지는 삭제하지 않는다. 메시지 소비를 완료하고 마지막 마무리 단계에서 소비자를 정지한 뒤 초기화한다.

초기화 시 HTTP 풀 2, DB 풀 4, HTTP 연결 획득 대기 500ms, 연결/응답 대기 1000ms로 재시작한다.
소스 수정은 유지되며 새로 빌드하지 않는다. 코드를 바꾼 실험이라면 필요한 빌드는 별도로 한다.

백업은 `runs/<이전 세션>/before-reset-<고유값>.dump`, 예측·해석·응답과 초기화 이력은 `events.jsonl`에 남는다.
백업 실패 시 테이블을 비우지 않고 A·B가 중지된 상태에서 중단한다. 이후 재시작 실패라면 이미 테이블을 비웠을 수 있으므로
`reset_tables_cleared` 기록과 백업을 먼저 확인한다. 재시도만 반복하지 않는다.
백업은 PostgreSQL `pg_restore`용이며 복원은 덮어쓰기가 될 수 있어 자동 실행하지 않는다. 필요한 경우 빈 별도 DB에서 먼저 확인한다.

화면 서버를 끄는 것만으로 조건이 복구되지는 않는다. 마무리 또는 초기화를 선택한 뒤 종료한다.
**화면 서버 코드 업데이트:** 메모를 저장하고 기록을 내려받은 뒤, 해당 터미널에서 Ctrl+C → `python3 scripts/session.py serve` → 두 브라우저 새로고침.
서비스와 DB는 유지되지만 화면의 진행 상태는 새 세션으로 시작하고 접속 키가 바뀐다. 친구 접속 주소도 다시 공유한다. 지난 세션 기록은 `runs`에 남는다.

## 문제 → 해결 버튼 실습 (31단계, 준비/회복 포함)

각 단계의 목적·예상 관찰·토론 질문은 [전체 커리큘럼](CURRICULUM.md)과 페이지 상단 길잡이에 있다.

1. HTTP/1.1 연결 닫기 → 재사용 (동일 3회 순차 호출)
2. 외부 호출 중 DB 점유 → HTTP를 트랜잭션 밖으로 이동 → 세마포어 2개 추가 (동일 지연·예약 부하)
3. 계속 실패하는 B 호출 → 회로 차단 → HALF_OPEN 시험과 정상 복귀
4. 응답 유실과 중복 지급 → B 업무 키 기반 멱등 처리 → 제한된 백오프 비교
5. 메모리 비동기 작업 유실 → 트랜잭션 아웃박스 → A 재시작 후 DB 작업 복구
6. 실제 RabbitMQ 큐에 적체 → 소비 재개와 커밋 뒤 ACK
7. 배치 전 미반영 → 실제 JSONL 파일 첫 행 처리 후 중단 → 같은 파일 멱등 재처리
8. PostgreSQL WAL의 INSERT/UPDATE/DELETE·롤백 구분 → 대상 반영 후 위치 확인 전 중단 → 재전달 건너뛰기·위치 확인
9. 단일 지급 제공자 거절 → B2 전환 → 응답 유실 시 위험한 전환과 UNKNOWN 보류 → 지급 결과 조회

준비 단계는 예측/해석을 요구하지 않고 변경값·보존 데이터·완료 기준을 보여준다.
일반 단계는 B active=0 확인 후 1초 더 수집하고 고정한다. 의도적으로 작업자를 멈춘 단계는
그 정지 상태에서 1초 더 관찰한다. 아웃박스·소비 완료 단계는 해당 업무의 완료도 별도로 확인한다.
그래프는 실행 구간만 저장하며 마지막 값과 관측 최대를 구분한다. 수집 사이의 순간 최대를 보장하지 않는다.

### 구현 경계

- 단일 A의 교육용 연속 실패 회로, 단일 아웃박스 전달자, 단일 큐 소비자다. 운영용 프레임워크 완제품이 아니다.
- 아웃박스 전달자는 현재 세션 ID 범위만 처리한다. 과거 누락 데이터는 자동 보정하지 않는다.
- B 지급액은 100으로 고정. 해결 모드의 `dedupe_key` UNIQUE로 동시 중복을 막는다. 기존 문제 모드의 NULL 키 행은 변경하지 않는다.
- RabbitMQ는 호스트 포트를 열지 않는다. durable 큐/persistent 메시지/publisher confirm/manual ACK를 사용한다.
- BROKER 아웃박스 DONE은 브로커 전달 완료이고 지급 완료는 아니다.
- 배치는 실제 파일과 수신 DB를 사용하지만 정시 스케줄러·SFTP는 구성하지 않는다. 파일은 `runs/<session>/reviews-batch.jsonl`과 manifest로 남는다.
- CDC는 실제 `wal_level=logical`·논리 슬롯·WAL 출력이다. `test_decoding`의 고정 예제 형식만 지원하는 교육용 파서다. Debezium·초기 스냅샷·DDL·다중 소비자·트랜잭션 단위 복제는 구현하지 않는다. 슬롯은 실습 완료/마무리에 해당 세션 것만 제거한다.
- CDC 소비자의 중단은 대상 반영 후 진행 위치 확인을 생략하는 코드 경계 주입이다. 프로세스 종료라고 표시하지 않는다. 새 SQL 호출로 같은 스트림을 재조회한다.
- 슬롯 보관 설정 `max_slot_wal_keep_size=128MB`는 체크포인트 시 슬롯의 WAL 보관/무효화 기준이지 디스크 사용의 정확한 상한은 아니다. 미완료 슬롯을 방치하지 않는다.
- B2는 `points-backup:8083`의 별도 프로세스와 `points.backup_grants` 장부다. 같은 DB·노트북을 공유하므로 인프라 이중화는 아니다. 백업 서버는 스키마 초기화를 하지 않으며 주 points 서버가 테이블을 준비한다.
- 일반 503은 미처리 증거가 아니다. 이 실습의 전용 `X-Lab-Not-Applied` 계약만 전환 조건으로 사용한다. UNKNOWN은 보류하며 실제 장부를 조회한다. `unsafe` 모드는 잘못된 전환의 중복 지급을 보여주기 위한 실험 분기다.
- 지터·재시도 폭풍 대규모 부하, 자동 보상·대사 스케줄러, 운영용 전체 장애 복구 체계는 구현하지 않는다.

CDC 처음 적용 시 `docker compose up --build -d`가 **전용 DB를 논리 WAL 설정으로 재시작**한다. 기존 볼륨/행은 유지된다. 기존 서버가 켜져 있었다면 실험 중이 아닌지 확인하고 기록을 저장한 뒤 적용한다.
참고: [PostgreSQL 16 논리 디코딩 개념](https://www.postgresql.org/docs/16/logicaldecoding-explanation.html), [test_decoding](https://www.postgresql.org/docs/16/test-decoding.html).

### 분리된 전체 검증

`compose.verify.yml`은 사용자 환경과 다른 DB·큐·포트(18081/18082/18083/19091)를 사용한다.
`docker compose build review points` 후 `docker compose -f compose.verify.yml up -d`로 검증 환경을 띄우고
`python3 scripts/verify_solutions.py`로 전체 흐름의 실제 저장 결과를 검증한다.
이 스크립트는 검증 프로젝트의 A만 종료/재시작하며 검증 데이터는 runs와 검증 DB에 남긴다.

### 진행 도구 검증

```sh
python3 -m unittest discover -s scripts -p 'test_*.py' -v
# 선택: 사용자 실습 DB와 분리된 일회용 PostgreSQL에서 백업→비우기→복원 검증
RUN_DOCKER_RESET_TESTS=1 python3 -m unittest discover -s scripts -p 'test_*.py' -v
```

## 정리

`docker compose down`은 이 프로젝트 컨테이너만 중지/제거하고 DB 볼륨은 보존한다.
기존 lab/docker에서 down을 실행하거나 기존 볼륨을 제거하지 않는다.
실습 데이터 초기화는 위 화면 버튼을 우선 사용한다(대상 검사와 자동 백업 포함).
아래는 화면 도구를 쓰지 않을 때의 **수동 방법이며 자동 백업은 없다**. 실행 중인 요청이 없는 상태에서만 사용한다.
**이 환경의 리뷰·지급 데이터가 지워지며 복구되지 않는다. 원본을 먼저 저장한다.**

```sh
docker compose stop review points
docker compose exec -T db psql -U integration -d integration -c \
  'TRUNCATE review.reviews, points.point_grants RESTART IDENTITY;'
docker compose start review points
```

학습 코드이므로 전역 타임아웃 정책, 보안, 배포, 복구 보장은 갖추지 않았다.
설정 수치는 실험 시작값이지 운영 권장값이나 성능 실측 결과가 아니다.
