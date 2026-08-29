# docker

| 파일 | 역할 |
|---|---|
| `docker-compose.yml` | postgres + prometheus + grafana + docker-stats-exporter |
| `prometheus/prometheus.yml` | 앱의 `/actuator/prometheus` 스크레이프, k6 remote write 수신 |
| `grafana/provisioning/` | 데이터소스·대시보드 자동 등록 |
| `grafana/dashboards/` | 대시보드 JSON 2개 |

앱은 컨테이너가 아니라 호스트에서 돈다(`cd lab/app && ./gradlew bootRun`).
Prometheus는 `host.docker.internal:8080`으로 호스트를 긁는다.

## 띄우기

```bash
cd lab/docker
docker compose up -d
```

| | 주소 | 계정 |
|---|---|---|
| Grafana | http://localhost:3000 | 익명 열람 가능 / 편집은 `admin` / `lab` |
| Prometheus | http://localhost:9090 | — |
| PostgreSQL | `localhost:5433` | `lab` / `lab` |

Grafana의 `lab` 폴더에 대시보드 두 개가 자동으로 올라온다.
`docker compose up` 만으로 리허설 때 정한 화면이 그대로 뜬다.

| 대시보드 | 용도 |
|---|---|
| **A-1 한 화면** | 회차 당일 띄워놓는 화면. 아래 4패널 |
| **Spring Boot JDBC & HikariCP (20729)** | 커넥션 풀 세부 지표 |

## A-1 한 화면 — 패널 4개

2×2로 배치했다. `001-plan.md` A-1 ④의 하이라이트는
**1번이 안 오르는데 2번과 3번이 치솟는 순간**이고, 그때 4번을 보면 이유가 나온다.

| 패널 | 쿼리 | 나오는 시점 |
|---|---|---|
| 1. TPS | `k6_http_reqs_total` / `http_server_requests_seconds_count` | k6 계열은 k6 실행 시 |
| 2. p95 응답시간 | `k6_http_req_duration_p95` / `http_server_requests_seconds_bucket` | 〃 |
| 3. `hikaricp_connections_pending` | + active / idle / max | 앱만 떠 있으면 |
| 4. DB 컨테이너 CPU | `dockerstats_cpu_usage_ratio{name="lab-postgres"}` | 항상 |

2번 패널에 k6 선과 서버 선을 같이 그리는 게 핵심이다.
**두 선의 차이가 곧 요청이 큐에서 기다린 시간이다**(`lab/README.md` ⑥).

4번은 `cpus: "2"` 제한 때문에 **200%가 상한**이다(100%가 코어 1개).
190% 위로 붙으면 빨갛게 칠해진다.

### 실제로 움직이는 걸 확인해둔 값 (2026-08-29 리허설)

`/lab/ratings?offset=4900000&limit=10`(건당 약 1.6초)을 24개 동시에 던졌을 때:

```
DB CPU                  197.29 %   <- 상한 200%에 붙음
hikaricp pending             14
hikaricp active              10    <- maximum-pool-size와 같음. 풀이 꽉 찬 상태
서버 p95                 30,000 ms
```

풀이 꽉 차고(active=10=max) 14개가 줄을 서 있는데 DB CPU는 이미 197%다.
A-1 ④에서 "풀을 키우면 빨라질까?"의 답이 이 화면에 그대로 있다.

## k6 remote write

Prometheus를 `--web.enable-remote-write-receiver` 로 띄워놨다.
k6 쪽 설정은 `lab/k6/README.md` 참고.

```bash
export K6_PROMETHEUS_RW_SERVER_URL=http://localhost:9090/api/v1/write
export K6_PROMETHEUS_RW_TREND_STATS="p(95),p(99),avg,max"
k6 run -o experimental-prometheus-rw script.js
```

## 당일 두 대로 나눌 때

```
[노트북 A — 서버]        [노트북 B — 부하·모니터링]
postgres                  k6
spring app                prometheus + grafana + docker-stats-exporter
```

고칠 곳은 **한 군데뿐이다.** `prometheus/prometheus.yml`의

```yaml
- targets: ["host.docker.internal:8080"]
```

를 노트북 A의 IP로 바꾼다. 예: `["192.168.0.12:8080"]`

Prometheus 설정 파일은 환경변수 치환을 지원하지 않는다.
`${APP_TARGET}` 같은 걸 써도 문자 그대로 들어가서 스크레이프가 실패한다.
그래서 변수가 아니라 직접 편집이다.

고친 뒤 반영:
```bash
docker compose restart prometheus
```

**설정 파일만 고치고 `docker compose up -d` 를 하면 반영이 안 된다.**
컨테이너가 이미 떠 있으면 재생성되지 않아서 옛 설정으로 계속 돈다.
`restart`를 써야 한다(2026-08-29에 이걸로 한 번 헤맸다).

## 자원 제한

**반드시 명시한다.** 안 하면 노트북 발열로 CPU 클럭이 내려가는 순간
숫자가 다 바뀌어 재현이 안 된다.

```yaml
deploy:
  resources:
    limits:
      cpus: "2"
      memory: 2g
```

메모리는 `001-plan.md` 공통 조건대로 2g다. 1g로 두면 500만 건 테이블에
`VACUUM`을 돌릴 때 실패한다.

`deploy.resources.limits`가 swarm 전용이라 무시된다는 얘기가 있는데,
Docker Compose v2에서는 적용된다. 실제로 확인했다(2026-08-29).

```
$ docker inspect lab-postgres --format 'NanoCpus={{.HostConfig.NanoCpus}} Memory={{.HostConfig.Memory}}'
NanoCpus=2000000000 Memory=2147483648
```

`shm_size: "256mb"` 도 필요하다. 기본값(64MB)에서는 500만 건 테이블에
`VACUUM`을 돌릴 때 `could not resize shared memory segment` 로 실패한다.

## 대시보드를 손봤을 때

당일에 패널을 고쳤으면 파일로 되돌려놔야 다음에도 그 화면이 뜬다.

1. Grafana에서 대시보드 설정 → **Export** → **Export as JSON**
2. 받은 JSON을 `grafana/dashboards/` 의 해당 파일에 덮어쓴다
   (**BOM 없이 저장해야 한다.** 아래 삽질 기록 2번 참고)
3. 커밋

프로비저닝 설정에 `allowUiUpdates: true` 를 줘서 화면에서 바로 편집할 수 있다.
다만 그 편집은 컨테이너를 지우면 사라지므로 위 절차로 파일에 반영해야 한다.

## 삽질 기록 — 세 가지

전부 2026-08-29 리허설에서 실제로 막혔던 것들이다.
당일에 같은 데서 시간을 버리지 않으려고 남긴다.

### 1. 대시보드 20729는 그냥 넣으면 전부 "No data"

20729는 변수를 이렇게 만든다.

```
label_values(jdbc_connections_max, namespace)
label_values(jdbc_connections_max{namespace="$namespace"}, application)
```

쿠버네티스 환경을 가정한 대시보드라 `namespace` / `application` 라벨을 요구하는데,
스프링 부트는 이 라벨을 안 붙인다. 변수가 비면 모든 패널이 No data가 된다.

`prometheus.yml`의 스크레이프에서 라벨을 붙여 해결했다.

```yaml
labels:
  namespace: lab
  application: lab-app
```

확인:
```
namespace    "lab"
application  "lab-app"
instance     "host.docker.internal:8080"
pool         "HikariPool-1"
```

### 2. 대시보드 JSON에 BOM이 붙으면 Grafana가 못 읽는다

```
failed to load dashboard ... error="invalid character 'ï' looking for beginning of value"
```

`ï` 는 UTF-8 BOM(`EF BB BF`)의 첫 바이트다. Windows PowerShell 5.1의
`Set-Content -Encoding utf8` 은 **BOM을 붙인다.** Grafana의 JSON 파서는 이걸 못 넘긴다.

대시보드 JSON을 손볼 일이 있으면 BOM 없이 저장한다.

```powershell
[System.IO.File]::WriteAllText($path, $json, (New-Object System.Text.UTF8Encoding($false)))
```

### 3. cAdvisor는 Docker Desktop에서 컨테이너별 CPU를 못 준다

원래 계획은 cAdvisor였는데 `container_cpu_usage_seconds_total` 이
cgroup 루트(`/`, `/docker`)만 나오고 컨테이너별로는 안 나온다. 이유 두 가지.

**cgroup 네임스페이스 격리.** Docker Desktop은 컨테이너마다 cgroup 네임스페이스를
따로 준다(`docker info` 의 `cgroupns`). 그래서 컨테이너 안의 cAdvisor가
형제 컨테이너의 cgroup을 볼 수 없다. postgres 컨테이너 안에서 보면 이렇다.

```
$ docker exec lab-postgres cat /proc/self/cgroup
0::/
```

자기 자신이 루트로 보인다. `--cgroupns=host` 로 띄워도,
`--raw_cgroup_prefix_whitelist=/docker` 를 줘도 `/docker/<id>` 가 안 나왔다.

**스토리지 드라이버.** Docker Desktop 29의 드라이버는 `overlay2`가 아니라 `overlayfs`다.
cAdvisor가 레이어 경로를 못 찾아서 컨테이너 등록 자체가 실패한다.

```
Failed to create existing container: /docker/853c78...:
  failed to identify the read-write layer ID
  - open /rootfs/var/lib/docker/image/overlayfs/layerdb/mounts/.../mount-id: no such file or directory
```

**해결:** cgroup을 직접 읽는 대신 **Docker API로 stats를 받는** 방식으로 바꿨다.
`docker stats` 명령이 동작하는 것과 같은 경로라 확실히 나온다.
`wywywywy/docker_stats_exporter` 를 쓰고, 태그가 `latest` 뿐이라 다이제스트로 고정했다.

메트릭 이름이 다르다. `container_cpu_usage_seconds_total` (cAdvisor) 대신
**`dockerstats_cpu_usage_ratio{name="lab-postgres"}`** 를 쓴다.
이미 퍼센트(0~200) 단위라 `rate()` 로 감쌀 필요가 없다.

리눅스에서 돌린다면 cAdvisor가 정상 동작할 가능성이 높다.
그때는 패널 4번의 쿼리만 바꾸면 된다.
