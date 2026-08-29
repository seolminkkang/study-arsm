# app — 실험용 스프링 앱

`lab/README.md` ⑤번 명세대로 만든다. **파일 5개, 의존성 5개.**

| 파일 | 역할 |
|---|---|
| `LabApplication.java` | `@SpringBootApplication` 하나뿐 |
| `LabController.java` | 조회 API 4개. 리포지토리를 직접 호출한다 |
| `LabRepository.java` | `JdbcTemplate` + raw SQL |
| `application.yml` | DB 연결, HikariCP, Actuator 노출 |
| `build.gradle` | 의존성 5개 |

빌드 파일(`settings.gradle`, `gradlew`, `gradle/wrapper/`)은 위 5개에 안 넣는다.
Gradle이 없으면 빌드 자체가 안 되므로 세는 대상이 아니다.
wrapper는 원본 Moha 프로젝트에서 그대로 복사했다(Gradle 8.14.3).

## 만들지 않는 것

Service 계층, DTO, Mapper, `@ControllerAdvice`, Security, JWT, OAuth,
MyBatis, WebFlux, 엔티티 클래스.

스프링은 관례가 무거워서 그냥 두면 3계층에 DTO에 예외 핸들러까지 생긴다.
그러면 응답 시간에 프레임워크 오버헤드가 섞여서 **"쿼리가 느린 건지
프레임워크가 느린 건지" 구분할 수 없게 된다.** 병목을 하나만 만들어야 하는
실험에서 치명적이다. (`CLAUDE.md`의 ponytail 섹션)

`userId`는 토큰이 아니라 쿼리 파라미터로 받는다. 인증이 개입할 여지를 없앤다.

## JPA를 넣고 JdbcTemplate을 쓰는 이유

의존성 목록에 `spring-boot-starter-data-jpa`가 있지만 엔티티는 만들지 않고
`JdbcTemplate`으로 raw SQL을 직접 쓴다.

Hibernate가 실제로 날리는 SQL은 코드에 적은 것과 다를 수 있다. 그러면
psql에서 `EXPLAIN`한 쿼리와 앱이 실행한 쿼리가 서로 다른 것이 되어
실험이 성립하지 않는다. **`LabRepository.java`에 적힌 문자열이 곧 DB가
받는 문자열이어야 한다.**

반환 타입도 DTO 없이 `Map` 그대로 둔다.

## 엔드포인트

`lab/README.md` ⑤번 표의 4개. 경로는 4개지만 `/lab/ratings`는
`001-plan.md` A-1 ①이 요구하는 오프셋 형태도 함께 받는다.

| 엔드포인트 | 실험 대상 |
|---|---|
| `GET /lab/movies?offset=&limit=` | 오프셋 페이징 |
| `GET /lab/movies?cursorId=&limit=` | 커서 페이징 (개선안) |
| `GET /lab/ratings?userId=&from=&to=` | 복합 인덱스, 선택도 |
| `GET /lab/movies/{id}/stats` | count 집계 vs 미리 집계 |

`/lab/ratings` 추가 형태 (A-1 ①, A-2 ⑥용)
```
GET /lab/ratings?userId=36&offset=4000&limit=10          특정 유저 안에서 오프셋
GET /lab/ratings?offset=4900000&limit=10                 전체 목록 기준 오프셋
GET /lab/ratings?cursorUpdatedAt=2024-10-01T00:00:00Z&limit=10    커서 페이징
GET /lab/ratings?userId=36&cursorUpdatedAt=...&limit=10  유저 안에서 커서
```

`/lab/ratings?userId=&from=&to=` 에는 `LIMIT`을 걸지 않는다.
헤비 유저와 라이트 유저의 반환 행 수 차이가 선택도 실험의 관측 대상이라
`LIMIT`으로 덮으면 안 된다.

**커서 파라미터 이름이 `cursorId`가 아니라 `cursorUpdatedAt`인 이유:**
`user_rating`에는 대리키가 없다. 정렬 기준이 `updated_at`이므로 커서 값도
타임스탬프다. `001-plan.md`가 `cursorId`라고 적었지만 이 테이블에는
그런 칼럼이 없다.

`updated_at`이 같은 행이 여럿이면 경계에서 몇 건 건너뛸 수 있다.
시딩이 마이크로초까지 랜덤이라 실제로는 거의 안 생기고, 여기서 재려는 건
정확한 페이징이 아니라 오프셋과의 비용 차이다.

## 실행

```bash
cd lab/app
./gradlew bootRun
```

`Started LabApplication` 로그가 뜨면 성공. 실측 기동 시간 **4.7~5.3초**
(2026-08-29, 앱만 재시작. `001-plan.md` A-1 ④가 재시작 3회를 요구하므로
당일 시간 계산에 넣는다).

```bash
curl "http://localhost:8080/lab/movies?limit=1"
```

## application.yml에서 실측으로 고친 것 두 가지

둘 다 2026-08-29에 확인했다.

### 1. `metrics-tracker-factory`는 넣으면 앱이 안 뜬다

`lab/README.md` ⑤에 이렇게 적혀 있다.

```yaml
spring:
  datasource:
    hikari:
      metrics-tracker-factory: MicrometerMetricsTrackerFactory
```

**이대로 쓰면 기동 자체가 실패한다.**

```
Failed to bind properties under 'spring.datasource.hikari.metrics-tracker-factory'
  to com.zaxxer.hikari.metrics.MetricsTrackerFactory:
  Reason: No converter found capable of converting
          from type [java.lang.String] to type [...MetricsTrackerFactory]
```

`HikariConfig.metricsTrackerFactory`는 문자열이 아니라 객체를 받는 자리라
YAML 문자열을 꽂을 수 없다.

**이 줄은 애초에 필요 없다.** `spring-boot-starter-actuator`와
`micrometer-registry-prometheus`가 클래스패스에 있으면 스프링 부트의
`DataSourcePoolMetricsAutoConfiguration`이 `MicrometerMetricsTrackerFactory`를
알아서 꽂아준다. 지우고 나면 커넥션 획득 시간 히스토그램이 그대로 나온다.

```
hikaricp_connections_acquire_seconds_count{pool="HikariPool-1"} 8
hikaricp_connections_acquire_seconds_max{pool="HikariPool-1"} 0.0017434
hikaricp_connections_pending{pool="HikariPool-1"} 0.0
```

### 2. `tomcat_threads_busy`는 MBean 레지스트리를 켜야 나온다

`lab/README.md` ⑥의 "봐야 할 메트릭"에 `tomcat_threads_busy`가 있는데,
기본 설정에서는 `tomcat_sessions_*` 여섯 개만 나오고 스레드 메트릭이 아예 없다.

```yaml
server:
  tomcat:
    mbeanregistry:
      enabled: true
```

켜면 나온다.

```
tomcat_threads_busy_threads{name="http-nio-0.0.0.0-8080"} 1.0
tomcat_threads_config_max_threads{name="http-nio-0.0.0.0-8080"} 200.0
tomcat_threads_current_threads{name="http-nio-0.0.0.0-8080"} 10.0
```

라벨의 `http-nio-0.0.0.0-8080`이 `server.address: 0.0.0.0` 바인딩이
실제로 걸렸다는 증거이기도 하다. `localhost`로 바인딩되면 당일에
다른 노트북에서 k6를 못 쏜다.

## 실험할 때 바꾸는 값

`application.yml`의 이 두 줄이 A-1의 노브다. **바꾸면 반드시 `exp` 커밋**을
남긴다 — 설정만 바꾼 경우에도 그렇다(`CLAUDE.md` git 섹션).

```yaml
spring.datasource.hikari.maximum-pool-size: 10    # A-1 ④: 2 -> 10 -> 50
spring.datasource.hikari.connection-timeout: 30000 # A-1 ⑤: 30000 -> 1000
```
