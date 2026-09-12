#!/usr/bin/env python3
"""시작 코드의 알려진 문제를 확인한다. 고친 뒤에는 기대값도 바꿔야 한다."""
import argparse
import json
import subprocess
import time
import urllib.request
import urllib.error
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def request(port, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(f"http://localhost:{port}{path}", data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as res:
            return res.status, json.load(res)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()

def healthy(port):
    end = time.monotonic()+90
    while time.monotonic()<end:
        try:
            status, body = request(port, "/actuator/health")
            if status == 200 and body["status"] == "UP":
                return
        except (OSError, ValueError):
            pass
        time.sleep(1)
    raise AssertionError(f"{port} health timeout")

def compose(*args):
    subprocess.run(["docker", "compose", *args], cwd=ROOT, check=True)

def grants(id):
    return [r for r in request(8082, "/grants")[1] if r["review_id"] == id]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--crash", action="store_true", help="이 실습 review 컨테이너만 강제 종료/재시작")
    args=parser.parse_args()
    healthy(8081)
    healthy(8082)
    run="smoke-"+uuid.uuid4().hex[:12]
    old_fault=request(8082, "/control/fault")[1]
    old_worker=request(8081, "/control/worker")[1]
    if old_worker["active"] or old_worker["queued"] or old_worker["paused"]:
        raise AssertionError("다른 비동기 작업이 없는 유휴 환경에서 실행하세요")
    results=[]
    try:
        request(8082, "/control/fault", {"beforeMs":0,"afterMs":0,"fail":False})
        status, _=request(8081, "/reviews", {"id":run,"content":"normal"})
        assert status==200 and len(grants(run))==1
        results.append("normal_review_and_grant")
        late=run+"-late"
        request(8082, "/control/fault", {"beforeMs":0,"afterMs":2000,"fail":False})
        status, _=request(8081, "/reviews", {"id":late,"content":"late"})
        assert status>=400 and len(grants(late))==1
        assert not any(r["id"]==late for r in request(8081,"/reviews")[1])
        request(8082, "/control/fault", {"beforeMs":0,"afterMs":0,"fail":False})
        status, _=request(8081, "/reviews", {"id":late,"content":"retry"})
        assert status==200 and len(grants(late))==2
        results.append("timeout_remote_commit_and_duplicate_retry")
        pending=run+"-async"
        request(8081, "/control/worker?paused=true", {})
        status, _=request(8081, "/reviews?mode=async", {"id":pending,"content":"queued"})
        assert status==200 and len(grants(pending))==0
        assert any(r["id"]==pending for r in request(8081,"/reviews")[1])
        results.append("async_response_before_grant")
        if args.crash:
            compose("kill", "-s", "SIGKILL", "review")
            compose("up", "-d", "review")
            healthy(8081)
            worker=request(8081, "/control/worker")[1]
            assert worker["active"]==0 and worker["queued"]==0
            assert any(r["id"]==pending for r in request(8081,"/reviews")[1])
            assert len(grants(pending))==0
            results.append("restart_keeps_review_but_loses_memory_job")
        print(json.dumps({"run":run,"passed":results}, ensure_ascii=False, indent=2))
    finally:
        request(8082, "/control/fault", old_fault)
        request(8081, "/control/worker?paused=false", {})
    # 생성한 데이터는 삭제하지 않는다. run ID로 검토한 다음 명시적으로 정리한다.

if __name__=="__main__":
    main()
