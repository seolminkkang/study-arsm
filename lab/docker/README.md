# docker

| 파일 | 역할 |
|---|---|
| `docker-compose.yml` | postgres + app + prometheus + grafana |
| `prometheus/prometheus.yml` | `/actuator/prometheus` 스크레이프 |
| `grafana/` | 대시보드 프로비저닝 |

## 주의

**자원 제한을 반드시 명시한다.** 안 하면 노트북 발열로 CPU 클럭이 내려가는 순간
숫자가 다 바뀌어 재현이 안 된다.

```yaml
deploy:
  resources:
    limits:
      cpus: "2"
      memory: 1g
```

Grafana 대시보드는 **20729 (Spring Boot JDBC & HikariCP)** 임포트.

## 대시보드 저장하고 공유하기

리허설에서 패널 구성(순서, 크기, 어떤 메트릭을 같은 화면에 둘지)을 정한다
(`vault/sessions/001-plan.md` "화면 구성 정하기"). 당일에 그 구성을 다시
만들면 그만큼 시간이 날아가므로, 리허설이 끝나면 반드시 저장해서 커밋해둔다.

1. Grafana에서 대시보드 설정 → **Export** → **Export as JSON** (`Export for sharing externally` 체크)
2. 받은 JSON을 `lab/docker/grafana/dashboards/`에 저장
3. `lab/docker/grafana/provisioning/dashboards/`에 프로비저닝 설정 추가
   (JSON 경로를 가리키는 짧은 yaml 파일 하나면 된다)
4. `docker-compose.yml`의 grafana 서비스에 두 디렉터리를 볼륨으로 마운트

이렇게 해두면 팀원은 `docker compose up`만 실행해도 리허설 때 정한 화면이
그대로 뜬다. 대시보드를 수동으로 다시 구성할 필요가 없다.
