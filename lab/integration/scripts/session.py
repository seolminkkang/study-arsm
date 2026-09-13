#!/usr/bin/env python3
"""두 화면 로컬 실습 진행 도구. 표준 라이브러리만 사용하며 임의 셸 입력을 실행하지 않는다."""
import argparse
import concurrent.futures
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from guide_steps import STEPS
from reset_lab import LabReset, CONFIRMATION

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "ui" / "session.html"
STEP_MAP = {s["id"]: s for s in STEPS}
METRICS = {
    "httpUsed": ("lab_http_pool_leased", "review:8081"),
    "httpWait": ("lab_http_pool_pending", "review:8081"),
    "httpMax": ("lab_http_pool_max", "review:8081"),
    "dbUsed": ("hikaricp_connections_active", "review:8081"),
    "dbWait": ("hikaricp_connections_pending", "review:8081"),
    "bActive": ("lab_points_active", "points:8082"),
    "asyncActive": ("lab_async_active", "review:8081"),
    "asyncQueued": ("lab_async_queued", "review:8081"),
}
NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def call(port, path, body=None, timeout=2, headers=None):
    start = time.monotonic()
    request = urllib.request.Request(
        "http://127.0.0.1:" + str(port) + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with NO_PROXY.open(request, timeout=timeout) as response:
            text = response.read(2_000_000).decode()
            try:
                value = json.loads(text)
            except ValueError:
                value = text
            return {"status": response.status, "body": value,
                    "ms": round((time.monotonic()-start)*1000, 1)}
    except urllib.error.HTTPError as error:
        with error:
            return {"status": error.code, "body": error.read(16000).decode(errors="replace"),
                    "ms": round((time.monotonic()-start)*1000, 1)}
    except (OSError, ValueError) as error:
        return {"status": None, "body": str(error), "ms": round((time.monotonic()-start)*1000, 1)}

def require(result):
    if result["status"] != 200:
        raise RuntimeError("요청 실패: " + json.dumps(result, ensure_ascii=False))
    return result["body"]

def command(args, timeout=45):
    # 호출자는 코드 안의 고정 인수만 사용한다. shell=True를 사용하지 않는다.
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    value = {"command": args, "exit": result.returncode,
             "stdout": result.stdout[-32000:], "stderr": result.stderr[-8000:]}
    if result.returncode:
        raise RuntimeError(json.dumps(value, ensure_ascii=False))
    return value

def metric_values(payload):
    values = {key: None for key in METRICS}
    if not isinstance(payload, dict) or payload.get("status") != "success":
        return values
    now = time.time()
    for row in payload.get("data", {}).get("result", []):
        labels = row.get("metric", {})
        stamp, raw = row.get("value", [0, "NaN"])
        for key, (name, instance) in METRICS.items():
            if labels.get("__name__") == name and labels.get("instance") == instance:
                try:
                    number = float(raw)
                    if now-float(stamp) <= 10 and number == number and abs(number) != float("inf"):
                        values[key] = number
                except (ValueError, TypeError):
                    pass
    return values

class Session:
    def __init__(self):
        self.lock = threading.RLock()
        self.action_lock = threading.Lock()
        self.stop = threading.Event()
        self.operator_key = secrets.token_urlsafe(32)
        self.viewer_key = secrets.token_urlsafe(32)
        self.samples = []
        self.snapshot = {"at": None, "metrics": {k: None for k in METRICS}, "errors": {}}
        self.new()

    def new(self):
        with self.lock:
            if hasattr(self, "state") and self.state["busy"]:
                raise ValueError("실행 중에는 새 세션을 만들 수 없다")
            if self.snapshot.get("worker", {}).get("paused"):
                raise ValueError("작업자가 일시정지 중이다. 마무리 단계로 조건을 복구한 뒤 새 세션을 만든다")
            done=getattr(self,"state",{}).get("results",{})
            if "cdc_lag" in done and "cdc_resume" not in done and "finish" not in done:
                raise ValueError("CDC 슬롯이 진행 중이다. CDC 재개 또는 마무리로 슬롯을 종료한 뒤 새 세션을 만든다")
            self.id = "pair-" + time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)
            self.directory = ROOT / "runs" / self.id
            self.directory.mkdir(parents=True, exist_ok=False)
            self.samples = []
            self.state = {"session": self.id, "step": "ready", "busy": False,
                          "notes": {}, "results": {}, "focus": [], "focusLabel": "준비",
                          "error": "", "revision": 0}
            self.record("session", {"id": self.id, "git": self.git_info()})

    def reset(self, confirmation):
        if confirmation != CONFIRMATION:
            raise ValueError("확인 문구 ‘" + CONFIRMATION + "’를 정확히 입력한다")
        if not self.action_lock.acquire(blocking=False):
            raise ValueError("실행 중에는 초기화할 수 없다. 현재 단계 종료 후 다시 시도한다")
        with self.lock:
            self.state["busy"] = True
            self.state["resetting"] = True
            self.state["error"] = ""
            self.record("reset_requested", {"session":self.id})
        threading.Thread(target=self._reset, daemon=True).start()

    def _reset(self):
        old_session = self.id
        try:
            queue=require(call(8082,"/control/consumer"))
            if not queue.get("paused") or queue.get("ready") != 0 or queue.get("active") != 0:
                raise RuntimeError("메시지 큐가 비어 있고 소비자가 정지한 경우에만 초기화할 수 있습니다. 소비 완료 후 마무리 단계를 실행하세요. 큐 메시지는 삭제하지 않습니다")
            result = LabReset(ROOT, self.directory, self.record).perform()
            end = time.monotonic() + 90
            while time.monotonic() < end:
                if all(call(p, "/actuator/health")["status"] == 200 for p in (8081,8082)):
                    break
                time.sleep(1)
            else:
                raise RuntimeError("DB 초기화 후 A·B 재시작 확인 실패. 백업과 reset_tables_cleared 기록을 확인한다")
            self.collect()
            with self.lock:
                snap = self.snapshot
                if (snap.get("reviews") != [] or snap.get("grants") != [] or
                        snap.get("solutions",{}).get("outbox") != [] or
                        snap.get("fault") != {"beforeMs":0,"afterMs":0,"fail":False} or
                        snap.get("worker") != {"paused":False,"active":0,"queued":0}):
                    raise RuntimeError("초기화 후 빈 DB/정상 조건 확인 실패. 직접 실행 중인 요청이 없는지 확인한다")
                result["previousSession"] = old_session
                self.record("reset_completed", result)
                self.state["busy"] = False
                self.new()
                self.state["lastReset"] = result
                self.record("reset_origin", result)
        except Exception as e:
            with self.lock:
                self.state["error"] = "초기화 중단: " + str(e) + " · runs의 백업/기록을 보존했다. 중지된 A·B는 원인을 확인한 뒤 다시 시작한다."
                self.record("reset_error", {"error":str(e)})
        finally:
            with self.lock:
                self.state["busy"] = False
                self.state["resetting"] = False
                self.state["revision"] += 1
            self.action_lock.release()

    def git_info(self):
        output = {}
        for label, args in [
                ("commit", ["git", "rev-parse", "HEAD"]),
                ("status", ["git", "status", "--short"]),
                ("diff", ["git", "diff", "HEAD", "--", "lab/integration"])]:
            try:
                output[label] = command(args)["stdout"]
            except Exception as e:
                output[label] = str(e)
        return output

    def record(self, kind, data):
        # 예측 수정/결과/샘플은 각각 새 JSONL 행으로 추가한다. 과거 행은 변경하지 않는다.
        with self.lock:
            with (self.directory / "events.jsonl").open("a", encoding="utf8") as f:
                f.write(json.dumps({"at": time.time(), "kind": kind, "data": data}, ensure_ascii=False)+"\n")

    def view(self):
        with self.lock:
            return json.loads(json.dumps({"state": self.state, "snapshot": self.snapshot,
                                          "history": self.samples[-120:], "steps": STEPS}))

    def notes(self, step, operator, observer, reflection):
        if step not in STEP_MAP or any(not isinstance(t, str) or len(t)>4000 for t in (operator, observer, reflection)):
            raise ValueError("유효한 단계와 4000자 이하 메모가 필요하다")
        with self.lock:
            self.state["notes"][step] = dict(operator=operator, observer=observer, reflection=reflection)
            self.state["revision"] += 1
            self.record("notes", {"step": step, **self.state["notes"][step]})

    def select(self, step):
        if step not in STEP_MAP:
            raise ValueError("없는 단계")
        with self.lock:
            if self.state["busy"]:
                raise ValueError("실행이 끝난 뒤 단계를 바꾼다")
            self.state["step"] = step
            self.state["revision"] += 1
            self.state["error"] = ""
            result = self.state["results"].get(step)
            if result:
                self.state["focus"] = result.get("focus", [])
                self.state["focusLabel"] = STEP_MAP[step]["title"]
            else:
                self.state["focus"] = ([self.id+"-late"] if step in ("late","retry") else
                                       [self.id+"-async"] if step in ("async","crash") else [])
                self.state["focusLabel"] = STEP_MAP[step]["title"]
            self.record("select", {"step": step})

    def collect(self):
        query = '{job="integration",__name__=~"' + "|".join(sorted({v[0] for v in METRICS.values()})) + '"}'
        paths = {
            "aHealth": (8081, "/actuator/health"), "bHealth": (8082, "/actuator/health"),
            "reviews": (8081, "/reviews"), "grants": (8082, "/grants"),
            "fault": (8082, "/control/fault"), "worker": (8081, "/control/worker"),
            "solutions": (8081, "/control/solutions"), "queue": (8082, "/control/consumer"),
            "prometheus": (9091, "/api/v1/query?query="+urllib.parse.quote(query))}
        with self.lock:
            generation = self.id
        with concurrent.futures.ThreadPoolExecutor(max_workers=9) as pool:
            jobs = {key: pool.submit(call, *value, timeout=1) for key, value in paths.items()}
            raw = {key: future.result() for key, future in jobs.items()}
        errors = {key: value["body"] for key,value in raw.items() if value["status"] != 200}
        metrics = metric_values(raw["prometheus"]["body"])
        if raw["aHealth"]["status"] != 200:
            for key in metrics:
                if key != "bActive":
                    metrics[key] = None
        if raw["bHealth"]["status"] != 200:
            metrics["bActive"] = None
        snapshot = {"at": time.time(), "metrics": metrics, "errors": errors}
        for key in ("aHealth", "bHealth", "fault", "worker", "solutions", "queue"):
            snapshot[key] = raw[key]["body"] if raw[key]["status"] == 200 else {}
        for key in ("reviews", "grants"):
            snapshot[key] = raw[key]["body"] if raw[key]["status"] == 200 else None
        with self.lock:
            if generation != self.id:
                return
            self.snapshot = snapshot
            sample = {"at": snapshot["at"], **metrics}
            self.samples.append(sample)
            self.samples = self.samples[-120:]
            self.record("sample", {"step": self.state["step"], **snapshot})

    def collector(self):
        while not self.stop.is_set():
            try:
                self.collect()
            except Exception as e:
                with self.lock:
                    self.snapshot["errors"]["collector"] = str(e)
            self.stop.wait(1)

    def execute(self, step, confirm=False):
        if step not in STEP_MAP:
            raise ValueError("허용되지 않은 동작")
        if not self.action_lock.acquire(blocking=False):
            raise ValueError("이미 실행 중이다")
        try:
            with self.lock:
                if step != self.state["step"]:
                    raise ValueError("먼저 해당 단계를 선택한다")
                if step in self.state["results"]:
                    raise ValueError("완료한 단계다. 반복 실험은 새 세션에서 한다")
                position = [s["id"] for s in STEPS].index(step)
                if step != "finish" and any(s["id"] not in self.state["results"] for s in STEPS[:position]):
                    raise ValueError("앞 단계를 먼저 실행한다")
                notes = self.state["notes"].get(step, {})
                if STEP_MAP[step]["question"] and not all(notes.get(k, "").strip() for k in ("operator","observer")):
                    raise ValueError("두 사람의 예측을 먼저 저장한다. 모르면 ‘모르겠다’와 궁금한 점을 적어도 된다")
                if STEP_MAP[step].get("danger") and not confirm:
                    raise ValueError("review 컨테이너 강제 종료 확인이 필요하다")
                self.state["busy"] = True
                self.state["phase"] = "설정과 요청 실행 중"
                self.state["error"] = ""
            threading.Thread(target=self._execute, args=(step,), daemon=True).start()
        except Exception:
            self.action_lock.release()
            raise

    def _execute(self, step):
        started = time.time()
        evidence = []
        self.record("action_start", {"step": step, "notes": self.state["notes"].get(step, {})})
        try:
            self.action(step, evidence)
            requests_ended = time.time()
            with self.lock:
                self.state["phase"] = "후속 작업 관찰 중 · 아직 결과를 고정하지 않습니다"
            # 의도적으로 멈춘 작업은 기다리지 않는다. 나머지는 B 완료 후 여유 1초 + 직접 재조회.
            if step not in ("async", "outbox_store", "broker_hold"):
                self.wait_idle()
            time.sleep(1)
            self.collect()
            evidence.append({"operation":"관찰 종료 기준", "requestsEnded":requests_ended,
                             "criterion":"의도적 정지 상태 + 1초" if step in ("async","outbox_store","broker_hold") else "B active=0 확인 + 1초"})
            with self.lock:
                result = {"started": started, "ended": time.time(), "evidence": evidence,
                          "requestsEnded": requests_ended,
                          "focus": self.state["focus"][:], "snapshot": self.snapshot,
                          "history": [s for s in self.samples if s["at"] >= started-1]}
                self.state["results"][step] = result
                self.record("action_result", {"step": step, **result})
        except Exception as error:
            with self.lock:
                self.state["error"] = str(error)
                self.record("action_error", {"step": step, "error": str(error), "evidence": evidence})
        finally:
            with self.lock:
                self.state["busy"] = False
                self.state["phase"] = ""
                self.state["revision"] += 1
            self.action_lock.release()

    def focus(self, ids, label):
        with self.lock:
            self.state["focus"] = ids
            self.state["focusLabel"] = label

    def normal(self, evidence):
        evidence.append({"operation": "B 장애 정상화", **call(8082, "/control/fault",
                        {"beforeMs":0,"afterMs":0,"fail":False})})
        require(evidence[-1])

    def request_review(self, id, attempt, mode="sync"):
        return {"operation": "리뷰 작성", "reviewId": id, "attemptId": attempt,
                **call(8081, "/reviews?mode="+mode, {"id":id,"content":"two-screen lab"},
                       timeout=8, headers={"X-Attempt-Id":attempt})}

    def wait_idle(self):
        end = time.monotonic()+35
        while time.monotonic()<end:
            text = call(8082,"/actuator/prometheus")["body"]
            if isinstance(text,str) and re.search(r"^lab_points_active(?:\{[^\n]*\})? 0(?:\.0)?$", text, re.M):
                return
            time.sleep(.25)
        raise RuntimeError("B active=0 확인 실패. 관찰 화면의 연결 상태를 확인한다")

    def action(self, step, evidence):
        from extension_actions import IDS, action as extended_action
        if step in IDS:
            return extended_action(self,step,evidence,call,command,require)
        if step == "ready":
            for port in (8081,8082,8083):
                evidence.append({"operation":str(port)+" health", **call(port,"/actuator/health")})
                require(evidence[-1])
            from extension_actions import sql
            wal=sql(command,"SHOW wal_level")
            evidence.append({"operation":"CDC 준비 설정","wal_level":wal})
            if wal!="logical": raise RuntimeError("확장 CDC 실습은 wal_level=logical이 필요합니다. README의 갱신 방법을 확인하세요")
            fault = require(call(8082,"/control/fault"))
            worker = require(call(8081,"/control/worker"))
            solutions=require(call(8081,"/control/solutions"))
            queue=require(call(8082,"/control/consumer"))
            if not solutions.get("relayPaused") or not queue.get("paused") or queue.get("ready") or queue.get("active"):
                raise RuntimeError("이전 전달자/메시지 작업이 남아 있습니다. 이전 소비 완료와 마무리를 확인하세요. 데이터는 자동 삭제하지 않습니다")
            if fault != {"beforeMs":0,"afterMs":0,"fail":False} or any(worker.get(k) for k in ("paused","active","queued")):
                raise RuntimeError("기존 장애/비동기 작업이 남아 있다. 마무리 단계로 복구하거나 기존 실험을 마친다")
            # 실제 실행 컨테이너의 설정을 기록한다. 복사된 compose 파일 값만 믿지 않는다.
            container = command(["docker","compose","ps","-q","review"])["stdout"].strip()
            if not re.fullmatch("[0-9a-f]{12,64}",container):
                raise RuntimeError("review 컨테이너 식별 실패")
            env = json.loads(command(["docker","inspect","--format","{{json .Config.Env}}",container])["stdout"])
            config = dict(line.split("=",1) for line in env if line.startswith(("HTTP_","DB_POOL_SIZE=")))
            evidence.append({"operation":"실행 중인 A 설정","config":config})
            if config.get("HTTP_READ_MS","1000") != "1000":
                raise RuntimeError("이 길라잡이의 시작 조건은 HTTP_READ_MS=1000이다. A 설정을 복구한 뒤 재시도한다")
        elif step in ("connections","connections_fresh"):
            ids=[self.id+"-"+step+"-"+str(i) for i in range(3)]
            self.focus(ids,"순차 호출 3건")
            for i,id in enumerate(ids):
                row=self.request_review(id,step+"-"+str(i),"fresh" if step=="connections_fresh" else "sync")
                evidence.append(row)
                require(row)
            evidence.append(command(["docker","compose","logs","--no-color","--tail","120","points"]))
        elif step in ("slow","outside","protected"):
            self.wait_idle()
            require(call(8082,"/control/fault",{"beforeMs":3000,"afterMs":0,"fail":False}))
            ids=[self.id+"-"+step+"-"+str(i) for i in range(24)]
            self.focus(ids,"작성 24건 · 별도 조회 12건")
            # 6초에 걸쳐 예약. 실제 시작 지연도 기록한다. 정밀 부하 측정 대신 짧은 현상 관찰용.
            t0=time.monotonic()
            def task(index, read=False):
                scheduled=(index*.5 if read else index*.25)
                time.sleep(max(0,t0+scheduled-time.monotonic()))
                lag=max(0,time.monotonic()-t0-scheduled)
                row=({"operation":"독립 리뷰 조회", **call(8081,"/reviews",timeout=8)}
                     if read else self.request_review(ids[index],step+"-"+str(index),{"slow":"sync","outside":"outside","protected":"guarded"}[step]))
                if read:
                    row["body"] = {"rows":len(row["body"])} if isinstance(row["body"],list) else row["body"]
                row["scheduleLagMs"]=round(lag*1000,1)
                return row
            with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
                jobs=[pool.submit(task,i) for i in range(24)]+[pool.submit(task,i,True) for i in range(12)]
                for job in concurrent.futures.as_completed(jobs):
                    evidence.append(job.result())
        elif step == "restore":
            self.normal(evidence)
            self.wait_idle()
            evidence.append({"operation":"준비 완료","fault":require(call(8082,"/control/fault")),
                             "bActive":0,"preserved":"기존 리뷰·지급 데이터와 결과 기록은 삭제하지 않았습니다"})
        elif step == "late":
            id=self.id+"-late"
            self.focus([id],"같은 업무의 첫 번째 시도")
            require(call(8082,"/control/fault",{"beforeMs":0,"afterMs":3000,"fail":False}))
            evidence.append(self.request_review(id,"late-first"))
            self.wait_idle()
        elif step == "retry":
            self.normal(evidence)
            id=self.id+"-late"
            self.focus([id],"같은 업무의 두 번째 시도")
            evidence.append(self.request_review(id,"late-retry"))
        elif step == "idempotent":
            id=self.id+"-idempotent"
            self.focus([id],"해결 버전: 첫 호출과 재시도에 같은 업무 키")
            require(call(8082,"/control/fault",{"beforeMs":0,"afterMs":3000,"fail":False}))
            evidence.append(self.request_review(id,"idem-first","idempotent"))
            self.wait_idle()
            self.normal(evidence)
            evidence.append(self.request_review(id,"idem-retry","idempotent"))
        elif step == "backoff":
            ids=[self.id+"-immediate",self.id+"-backoff"]
            self.focus(ids,"동일한 1.2초 일시 장애 · 즉시 3회와 간격 있는 3회 비교")
            for id,delays in zip(ids,((0,0,0),(0,.5,1))):
                require(call(8082,"/control/fault",{"beforeMs":0,"afterMs":0,"fail":True}))
                def recover():
                    time.sleep(1.2)
                    return require(call(8082,"/control/fault",{"beforeMs":0,"afterMs":0,"fail":False}))
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    recovery=pool.submit(recover)
                    for i,delay in enumerate(delays):
                        time.sleep(delay)
                        row=self.request_review(id,"retry-"+str(i),"idempotent")
                        row["retryWaitSeconds"]=delay
                        evidence.append(row)
                        if row["status"]==200: break
                    recovery.result()
        elif step in ("circuit_problem","circuit_solution"):
            self.wait_idle()
            require(call(8081,"/control/breaker-reset",{}))
            require(call(8082,"/control/fault",{"beforeMs":0,"afterMs":0,"fail":True}))
            ids=[self.id+"-"+step+"-"+str(i) for i in range(6)]
            self.focus(ids,"장애 중 6회 순차 호출 · 회로 상태 함께 기록")
            received_before=self.b_received()
            for i,id in enumerate(ids):
                row=self.request_review(id,str(i),"circuit" if step=="circuit_solution" else "guarded")
                row["solutionState"]=require(call(8081,"/control/solutions"))
                evidence.append(row)
            evidence.append({"operation":"실제 B 수신 횟수","count":self.b_received()-received_before})
        elif step == "circuit_recover":
            self.normal(evidence)
            time.sleep(3.1)
            require(call(8082,"/control/fault",{"beforeMs":500,"afterMs":0,"fail":False}))
            id=self.id+"-probe"
            self.focus([id],"차단 시간 뒤 시험 요청 한 건")
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                job=pool.submit(self.request_review,id,"probe","circuit")
                time.sleep(.2)
                evidence.append({"operation":"시험 요청 중 회로 상태",**require(call(8081,"/control/solutions"))})
                evidence.append(job.result())
            self.normal(evidence)
            evidence.append({"operation":"시험 요청 후 회로 상태",**require(call(8081,"/control/solutions"))})
        elif step == "async":
            self.normal(evidence)
            require(call(8081,"/control/worker?paused=true",{}))
            id=self.id+"-async"
            self.focus([id],"메모리에 대기 중인 지급 작업")
            row=self.request_review(id,"async-first","async")
            evidence.append(row)
            require(row)
        elif step == "crash":
            worker=require(call(8081,"/control/worker"))
            if not worker.get("paused") or not (worker.get("active") or worker.get("queued")):
                raise RuntimeError("강제 종료 전 일시정지된 미지급 작업을 확인할 수 없다")
            self.focus([self.id+"-async"],"재시작 이후의 같은 리뷰")
            evidence.append(command(["docker","compose","kill","-s","SIGKILL","review"]))
            evidence.append(command(["docker","compose","up","-d","review"],timeout=90))
            end=time.monotonic()+90
            while time.monotonic()<end:
                health=call(8081,"/actuator/health")
                if health["status"]==200:
                    evidence.append({"operation":"A 재시작 health",**health})
                    break
                time.sleep(1)
            else:
                raise RuntimeError("재시작 health 시간 초과. docker compose logs review를 확인한다")
        elif step in ("outbox_store","broker_hold"):
            self.normal(evidence)
            require(call(8081,"/control/relay?paused=true",{}))
            if step=="broker_hold":
                require(call(8082,"/control/consumer?paused=true",{}))
            ids=[self.id+"-"+step+"-"+str(i) for i in range(3 if step=="broker_hold" else 1)]
            self.focus(ids,"DB에 저장된 할 일" if step=="outbox_store" else "소비자를 멈춘 실제 RabbitMQ 큐")
            for id in ids:
                evidence.append(self.request_review(id,step,"broker" if step=="broker_hold" else "outbox"))
                require(evidence[-1])
            if step=="broker_hold":
                require(call(8081,"/control/relay?paused=false&scope="+self.id,{}))
                self.wait_outbox(ids)
        elif step == "outbox_recover":
            id=self.id+"-outbox_store-0"
            self.focus([id],"재시작해도 보존된 지급 작업")
            state=require(call(8081,"/control/solutions"))
            if not state.get("relayPaused") or not any(r["review_id"]==id and r["status"]=="WAITING" for r in state["outbox"]):
                raise RuntimeError("일시정지된 WAITING 아웃박스가 확인되지 않아 강제 종료하지 않습니다")
            evidence.append(command(["docker","compose","kill","-s","SIGKILL","review"]))
            evidence.append(command(["docker","compose","up","-d","review"],timeout=90))
            end=time.monotonic()+90
            while time.monotonic()<end:
                if call(8081,"/actuator/health")["status"]==200: break
                time.sleep(1)
            else: raise RuntimeError("A 재시작 확인 실패")
            evidence.append({"operation":"재시작 직후 남은 작업",**require(call(8081,"/control/solutions"))})
            require(call(8081,"/control/relay?paused=false&scope="+self.id,{}))
            self.wait_outbox([id])
        elif step == "broker_drain":
            ids=[self.id+"-broker_hold-"+str(i) for i in range(3)]
            self.focus(ids,"소비 재개 후 같은 메시지의 지급 결과")
            require(call(8082,"/control/consumer?paused=false",{}))
            end=time.monotonic()+35
            while time.monotonic()<end:
                grants=require(call(8082,"/grants"))
                queue=require(call(8082,"/control/consumer"))
                if all(any(r["review_id"]==id for r in grants) for id in ids) and queue["ready"]==0 and queue["active"]==0: break
                time.sleep(.25)
            else: raise RuntimeError("소비 완료 확인 실패. 지급 결과와 큐 상태를 확인하세요")
        elif step == "finish":
            from extension_actions import cleanup
            cleanup(self,command,evidence)
            require(call(8083,"/control/fault",{"beforeMs":0,"afterMs":0,"fail":False}))
            self.normal(evidence)
            evidence.append({"operation":"A 일시정지 해제",**call(8081,"/control/worker?paused=false",{})})
            require(evidence[-1])
            self.wait_idle()
            require(call(8081,"/control/relay?paused=true",{}))
            require(call(8082,"/control/consumer?paused=true",{}))
            require(call(8081,"/control/breaker-reset",{}))
            evidence.append({"operation":"준비 완료","preserved":"리뷰·지급·아웃박스·큐·실험 기록 유지. 삭제나 지급 보정은 하지 않았습니다"})

    def wait_outbox(self, ids):
        end=time.monotonic()+35
        while time.monotonic()<end:
            state=require(call(8081,"/control/solutions"))
            if all(any(r["review_id"]==id and r["status"]=="DONE" for r in state["outbox"]) for id in ids): return
            time.sleep(.25)
        raise RuntimeError("아웃박스 전송 완료 확인 실패. WAITING을 완료로 표시하지 않습니다")

    def b_received(self):
        body=require(call(8082,"/actuator/prometheus"))
        m=re.search(r"^lab_points_received_total(?:\{[^\n]*\})? ([0-9.eE+]+)$",body,re.M)
        if not m: raise RuntimeError("B 수신 카운터를 읽을 수 없습니다")
        return int(float(m.group(1)))

class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, session, readonly):
        self.session=session
        self.readonly=readonly
        super().__init__(address, Handler)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # URL, 접속 키, 예측 내용을 콘솔 접근 로그에 남기지 않는다.

    def valid_host(self):
        if self.server.readonly:
            return True
        return self.headers.get("Host") in ("127.0.0.1:8090","localhost:8090")

    def auth(self):
        key=self.server.session.viewer_key if self.server.readonly else self.server.session.operator_key
        return self.valid_host() and hmac.compare_digest(self.headers.get("Authorization",""),"Bearer "+key)

    def respond(self, status, body, content="application/json; charset=utf-8"):
        data=body.encode() if isinstance(body,str) else json.dumps(body,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type",content)
        self.send_header("Content-Length",str(len(data)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Referrer-Policy","no-referrer")
        self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError,ConnectionResetError):
            pass

    def do_GET(self):
        if not self.valid_host():
            return self.respond(403,{"error":"Host not allowed"})
        path=urllib.parse.urlsplit(self.path).path
        if path=="/":
            role="observer" if self.server.readonly else "operator"
            token="" if self.server.readonly else self.server.session.operator_key
            html=UI.read_text().replace("__ROLE__",role).replace("__OPERATOR_KEY__",token)
            return self.respond(200,html,"text/html; charset=utf-8")
        if path=="/favicon.ico":
            return self.respond(204,"","image/x-icon")
        if not self.auth():
            return self.respond(401,{"error":"접속 키가 없거나 만료됐다. 실행자의 새 관찰 주소를 사용한다."})
        if path=="/api/state":
            return self.respond(200,self.server.session.view())
        if path=="/api/export":
            return self.respond(200,(self.server.session.directory/"events.jsonl").read_text(),
                                "application/x-ndjson; charset=utf-8")
        if path=="/api/share" and not self.server.readonly:
            return self.respond(200,{"key":self.server.session.viewer_key,"addresses":lan_addresses()})
        return self.respond(404,{"error":"not found"})

    def do_POST(self):
        if self.server.readonly:
            return self.respond(403,{"error":"관찰 전용 포트에서는 실행/수정할 수 없다"})
        if not self.auth():
            return self.respond(403,{"error":"실행자 인증 실패"})
        origin=self.headers.get("Origin")
        if origin and origin not in ("http://127.0.0.1:8090","http://localhost:8090"):
            return self.respond(403,{"error":"Origin not allowed"})
        if self.headers.get("Content-Type","").split(";")[0]!="application/json":
            return self.respond(415,{"error":"JSON only"})
        try:
            size=int(self.headers.get("Content-Length","0"))
            if size<0 or size>16000:
                raise ValueError("요청 크기 초과")
            data=json.loads(self.rfile.read(size))
            if not isinstance(data,dict):
                raise ValueError("JSON object required")
            session=self.server.session
            if self.path=="/api/select":
                session.select(data.get("step"))
            elif self.path=="/api/notes":
                session.notes(data.get("step"),data.get("operator",""),data.get("observer",""),data.get("reflection",""))
            elif self.path=="/api/run":
                session.execute(data.get("step"),data.get("confirm") is True)
            elif self.path=="/api/new":
                session.new()
            elif self.path=="/api/reset":
                session.reset(data.get("confirmation"))
            else:
                return self.respond(404,{"error":"허용되지 않은 동작"})
            return self.respond(200,{"ok":True})
        except (ValueError,TypeError) as e:
            return self.respond(409,{"error":str(e)})

def lan_addresses():
    addresses=[]
    for interface in ("en0","en1"):
        try:
            ip=subprocess.run(["ipconfig","getifaddr",interface],capture_output=True,text=True,timeout=2).stdout.strip()
            if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}",ip) and ip not in addresses:
                addresses.append(ip)
        except (OSError,subprocess.TimeoutExpired):
            pass
    return addresses or ["노트북의-Wi-Fi-IP"]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("mode",choices=["serve","run"])
    parser.add_argument("step",nargs="?")
    parser.add_argument("--confirm-crash",action="store_true")
    args=parser.parse_args()
    if args.mode=="run":
        if args.step not in STEP_MAP:
            parser.error("허용된 단계: "+", ".join(STEP_MAP))
        access=json.loads((ROOT/"runs"/"presenter-access.json").read_text())
        result=call(8090,"/api/run",{"step":args.step,"confirm":args.confirm_crash},headers={"Authorization":"Bearer "+access["key"]})
        print(json.dumps(result,ensure_ascii=False,indent=2))
        sys.exit(0 if result["status"]==200 else 1)
    session=Session()
    # 실행 권한 포트는 항상 loopback, 관찰 전용 포트만 같은 Wi-Fi에 공개한다.
    operator=Server(("127.0.0.1",8090),session,False)
    observer=Server(("0.0.0.0",8091),session,True)
    access=ROOT/"runs"/"presenter-access.json"
    fd=os.open(access,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,"w") as f:
        json.dump({"key":session.operator_key},f)
    threading.Thread(target=session.collector,daemon=True).start()
    threading.Thread(target=observer.serve_forever,daemon=True).start()
    print("실행자: http://127.0.0.1:8090",flush=True)
    for ip in lan_addresses():
        print("관찰자: http://"+ip+":8091/#key="+session.viewer_key,flush=True)
    print("같은 신뢰하는 Wi-Fi에서만 사용. 배포/포트포워딩 없음. 종료: Ctrl+C",flush=True)
    try:
        operator.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        session.stop.set()
        observer.shutdown()
        operator.server_close()
        observer.server_close()
        print("화면 서버 종료. 실습 컨테이너는 유지됨. 미완료 작업은 마무리 단계나 README 명령으로 복구.",flush=True)

if __name__=="__main__":
    main()
