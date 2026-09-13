"""4·5장 전용 DB만 백업 후 비우기. 기존 lab/docker와 볼륨 삭제는 사용하지 않는다."""
import json
import os
from pathlib import Path
import subprocess
import time

PROJECT = "arsm-integration"
VOLUME = "arsm-integration_integration-data"
CONFIRMATION = "4·5장 실험 초기화"
DEFAULTS = {"HTTP_POOL_SIZE":"2", "HTTP_ACQUIRE_MS":"500", "HTTP_CONNECT_MS":"1000",
            "HTTP_READ_MS":"1000", "DB_POOL_SIZE":"4"}
TABLES = ["review.reviews", "review.outbox", "review.batch_received", "review.cdc_source",
          "review.cdc_target", "review.cdc_seen", "points.point_grants", "points.backup_grants"]
SQL = "BEGIN; TRUNCATE " + ", ".join(TABLES) + " RESTART IDENTITY; COMMIT;"


class LabReset:
    def __init__(self, root, directory, record):
        self.root, self.directory, self.record = Path(root), Path(directory), record
        self.base = ["docker", "compose", "--project-name", PROJECT,
                     "--file", str(self.root / "compose.yml")]

    def run(self, args, **kwargs):
        result = subprocess.run(args, cwd=self.root, env={**os.environ, **DEFAULTS},
                                timeout=120, stderr=subprocess.PIPE, **kwargs)
        if result.returncode:
            error = result.stderr.decode(errors="replace")[-4000:]
            raise RuntimeError("초기화 명령 실패: " + error)
        return result

    def output(self, args):
        return self.run(args, stdout=subprocess.PIPE).stdout.decode()

    def verify_targets(self):
        """실제 컨테이너의 프로젝트/서비스/DB/마운트를 확인한 뒤에만 변경한다."""
        targets = {}
        for service in ("db", "review", "points", "points-backup", "broker"):
            ids = self.output(self.base + ["ps", "--all", "--quiet", service]).split()
            if len(ids) != 1:
                raise RuntimeError(service + " 컨테이너를 하나로 특정할 수 없어 중단했다")
            info = json.loads(self.output(["docker", "inspect", ids[0]]))[0]
            labels = info["Config"].get("Labels") or {}
            if (labels.get("com.docker.compose.project") != PROJECT or
                    labels.get("com.docker.compose.service") != service):
                raise RuntimeError("4·5장 전용 컨테이너가 아니므로 중단했다")
            targets[service] = ids[0]
            if service == "db":
                env = dict(v.split("=", 1) for v in info["Config"]["Env"])
                mounts = [m for m in info.get("Mounts", []) if m.get("Destination") == "/var/lib/postgresql/data"]
                if (env.get("POSTGRES_DB") != "integration" or env.get("POSTGRES_USER") != "integration" or
                        len(mounts) != 1 or mounts[0].get("Type") != "volume" or mounts[0].get("Name") != VOLUME):
                    raise RuntimeError("전용 DB/볼륨이 예상과 다르므로 초기화를 중단했다")
                if not info.get("State", {}).get("Running"):
                    raise RuntimeError("전용 DB가 실행 중이어야 백업할 수 있다")
        self.record("reset_targets", targets)

    def verify_empty_queue(self):
        # A·B를 멈춘 뒤 다시 확인: 사전 화면 조회와 실제 정지 사이의 발행도 놓치지 않는다.
        rows=self.output(self.base+["exec","-T","broker","rabbitmqctl","list_queues","--formatter=json",
                                   "name","messages_ready","messages_unacknowledged"])
        queues=json.loads(rows)
        target=[q for q in queues if q.get("name")=="review-points"]
        if len(target)!=1 or any(target[0].get(k)!=0 for k in ("messages_ready","messages_unacknowledged")):
            raise RuntimeError("A·B 정지 후에도 큐가 비어 있음을 확인하지 못했습니다. 메시지를 보존하고 DB 초기화를 중단합니다")
        self.record("reset_queue_empty",target[0])

    def backup(self):
        path = self.directory / ("before-reset-" + str(time.time_ns()) + ".dump")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            self.run(self.base + ["exec", "-T", "db", "pg_dump", "-U", "integration", "-d", "integration",
                                  "--format=custom", "--schema=review", "--schema=points",
                                  "--no-owner", "--no-privileges"], stdout=stream)
            stream.flush()
            os.fsync(stream.fileno())
        if path.stat().st_size == 0:
            raise RuntimeError("빈 백업이므로 DB 삭제를 중단했다")
        with path.open("rb") as stream:
            self.run(self.base + ["exec", "-T", "db", "pg_restore", "--list"],
                     stdin=stream, stdout=subprocess.PIPE)
        self.record("reset_backup", {"path":str(path), "bytes":path.stat().st_size})
        return path

    def verify_no_cdc_slot(self):
        count=self.output(self.base+["exec","-T","db","psql","-X","-At","-U","integration","-d","integration",
            "-c","SELECT count(*) FROM pg_replication_slots WHERE slot_name LIKE 'labcdc_%';"]).strip()
        if count!="0":
            raise RuntimeError("미완료 CDC 슬롯이 남아 있어 초기화를 중단합니다. 해당 세션 마무리로 슬롯을 종료하세요. 이전 세션 슬롯이면 기록을 확인한 뒤 별도로 정리해야 합니다")

    def perform(self):
        self.verify_targets()
        self.record("reset_phase", {"message":"A·B 중지 → DB 백업 → 실험 테이블 비우기 → A·B 재시작"})
        # 먼저 쓰기 주체를 멈춘다. paused 작업도 종료되며, DB에 반영된 결과는 백업한다.
        # 백업 실패 시 TRUNCATE는 실행하지 않고 A·B는 중지 상태로 둔다.
        self.verify_no_cdc_slot()
        self.output(self.base + ["stop", "--timeout", "5", "review", "points", "points-backup"])
        self.verify_empty_queue()
        backup = self.backup()
        self.output(self.base + ["exec", "-T", "db", "psql", "-U", "integration", "-d", "integration",
                                 "-v", "ON_ERROR_STOP=1", "-c", SQL])
        self.record("reset_tables_cleared", {"backup":str(backup), "tables":TABLES})
        self.output(self.base + ["up", "-d", "--no-deps", "--force-recreate", "review", "points", "points-backup"])
        return {"backup":str(backup), "defaults":DEFAULTS,
                "preserved":"기존 실습 DB, 코드·스키마, 예측·결과 파일, Grafana/Prometheus 과거 기록"}
