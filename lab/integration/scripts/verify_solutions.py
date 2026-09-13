"""전체 버튼 흐름을 별도 compose.verify.yml의 DB/큐/포트에서 실행한다. 사용자 환경 변경 금지."""
import json
import threading
import time
from pathlib import Path
import session

original_call=session.call
original_command=session.command
def call(port,*args,**kwargs):
    return original_call({8081:18081,8082:18082,8083:18083,9091:19091}[port],*args,**kwargs)
def command(args,**kwargs):
    if args[:2]==["docker","compose"]:
        args=["docker","compose","-f","compose.verify.yml",*args[2:]]
    return original_command(args,**kwargs)
session.call=call
session.command=command
s=session.Session()
threading.Thread(target=s.collector,daemon=True).start()

def counts(step):
    r=s.state["results"][step]
    ids=r["focus"]
    return (sum(x["id"] in ids for x in r["snapshot"]["reviews"]),
            sum(x["review_id"] in ids for x in r["snapshot"]["grants"]))

try:
    deadline=time.monotonic()+60
    while not all(call(p,"/actuator/health")["status"]==200 for p in (8081,8082,8083)):
        if time.monotonic()>deadline: raise RuntimeError("검증 서버 시작 실패: compose.verify.yml 로그 확인")
        time.sleep(1)
    for step in session.STEPS:
        id=step["id"]
        s.select(id)
        s.notes(id,"검증 스크립트 예측: 조건별 기대값 assertion 확인","자동 검증용 관찰 기록","")
        s.execute(id,confirm=True)
        while s.state["busy"]: time.sleep(.2)
        if s.state["error"]: raise AssertionError((id,s.state["error"]))
        print(id,counts(id),flush=True)
        if id in ("connections_fresh","connections"): assert counts(id)==(3,3)
        if id=="retry": assert counts(id)==(1,2)
        if id=="idempotent": assert counts(id)==(1,1)
        if id in ("circuit_problem","circuit_solution"):
            count=next(e["count"] for e in s.state["results"][id]["evidence"] if e["operation"]=="실제 B 수신 횟수")
            assert count==(6 if id=="circuit_problem" else 3)
        if id=="circuit_recover":
            states=[e["breaker"] for e in s.state["results"][id]["evidence"] if "breaker" in e]
            assert states==["HALF_OPEN","CLOSED"]
        if id in ("async","crash","outbox_store"): assert counts(id)==(1,0)
        if id=="outbox_recover": assert counts(id)==(1,1)
        if id=="broker_hold":
            assert counts(id)==(3,0)
            assert s.state["results"][id]["snapshot"]["queue"]["ready"]==3
        if id=="broker_drain":
            assert counts(id)==(3,3)
            assert s.state["results"][id]["snapshot"]["queue"]["ready"]==0
        ext=[e["extension"] for e in s.state["results"][id]["evidence"] if "extension" in e]
        if id=="batch_wait": assert ext[-1]["수신 반영"]==0
        if id=="batch_partial": assert ext[-1]["수신 반영"]==1
        if id=="batch_recover": assert ext[-1]["수신 반영"]==3 and ext[0]["이번 신규 반영"]==2
        if id=="cdc_lag": assert ext[0]["커밋된 변경 이벤트"]==4 and not ext[0]["롤백 ID 포함"]
        if id=="cdc_apply": assert ext[0]["이번 신규 적용 이벤트"]==4 and ext[0]["위치 전"]==ext[0]["위치 후"]
        if id=="cdc_resume": assert ext[0]["이번 신규 적용 이벤트"]==0 and ext[0]["중복 건너뛰기"]==4 and ext[-1]["슬롯 남음"]==0
        if id=="failover_single": assert ext[0]["outcome"]=="REJECTED" and ext[-1]["합계 포인트"]==0
        if id=="failover_switch": assert ext[0]["provider"]=="backup" and ext[-1]["합계 포인트"]==100
        if id=="failover_unknown": assert ext[-2]["합계 포인트"]==200 and ext[-1]["합계 포인트"]==100
        if id=="failover_reconcile": assert ext[-1]["합계 포인트"]==100
    print("VERIFIED",str(s.directory),flush=True)
finally:
    s.stop.set()
