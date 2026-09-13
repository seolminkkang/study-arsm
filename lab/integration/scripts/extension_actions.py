"""배치 파일, PostgreSQL WAL 디코딩, 실제 두 HTTP 제공자 실험. 모든 SQL 값은 검증한다."""
import hashlib
import json
import re
import time

IDS = {"batch_wait", "batch_partial", "batch_recover", "cdc_lag", "cdc_apply", "cdc_resume",
       "failover_single", "failover_switch", "failover_unknown", "failover_reconcile"}

def literal(value):
    if not isinstance(value,str) or not re.fullmatch(r"[A-Za-z0-9_:/ %. -]{1,150}",value):
        raise ValueError("실습 SQL 값 형식 오류")
    return "'"+value+"'"

def sql(command, query):
    return command(["docker","compose","exec","-T","db","psql","-X","-qAt","-U","integration",
                    "-d","integration","-v","ON_ERROR_STOP=1","-c",query])["stdout"].strip()

def rows(command, query):
    return json.loads(sql(command,"SELECT COALESCE(json_agg(t),'[]'::json) FROM ("+query+") t"))

def slot_name(id):
    return "labcdc_"+hashlib.sha256(id.encode()).hexdigest()[:24]

def decode(changes, scope):
    result=[]
    for i,row in enumerate(changes):
        text=row["data"]
        if not text.startswith("table review.cdc_source: "): continue
        match=re.search(r"\b(INSERT|UPDATE|DELETE):.*?id\[character varying\]:'([A-Za-z0-9_-]+)'",text)
        if not match: raise ValueError("지원하지 않는 CDC 레코드: "+text)
        op,id=match.groups()
        if not id.startswith(scope+"-"): continue
        status=re.search(r"status\[text\]:'(CREATED|SHIPPED)'",text)
        if op!="DELETE" and not status: raise ValueError("지원하지 않는 상태")
        # LSN은 WAL 레코드 위치. 동일 LSN에서 발생하는 출력 구분을 위해 배치 내 ordinal도 기록.
        key=scope+":"+row["lsn"]+":"+str(i)
        result.append(dict(key=key,lsn=row["lsn"],op=op,id=id,status=status[1] if status else None))
    return result

def validated_file(path, manifest, scope):
    content=path.read_bytes()
    if hashlib.sha256(content).hexdigest()!=manifest["sha256"]:
        raise ValueError("파일 SHA-256 불일치: 반영 전 중단")
    records=[json.loads(line) for line in content.decode().splitlines()]
    if len(records)!=manifest["count"]: raise ValueError("파일 건수 불일치")
    for row in records:
        literal(row["id"]); literal(row["content"])
        if not row["id"].startswith(scope+"-batch-"): raise ValueError("다른 세션 파일")
    return records

def action(s, step, evidence, call, command, require):
    prefix=literal(s.id+"-%")
    def report(title, values, detail=""):
        evidence.append({"operation":title,"extension":values,"detail":detail})
    def query(table): return rows(command,"SELECT * FROM review."+table+" WHERE id LIKE "+prefix+" ORDER BY id")
    def batch_state(title):
        source=rows(command,"SELECT id,content FROM review.reviews WHERE id LIKE "+literal(s.id+"-batch-%")+" ORDER BY id")
        target=query("batch_received")
        report(title,{"원본 리뷰":len(source),"수신 반영":len(target),"미반영":len(source)-len(target)},
               "배치의 대상은 포인트 지급이 아닌 별도 리뷰 복제 장부입니다.")
        evidence.append({"operation":"실제 원본·수신 행","source":source,"target":target})
    def slot_state():
        return rows(command,"SELECT slot_name,confirmed_flush_lsn::text,wal_status FROM pg_replication_slots WHERE slot_name="+literal(slot_name(s.id)))
    def peek():
        return rows(command,"SELECT lsn::text,data FROM pg_logical_slot_peek_changes("+literal(slot_name(s.id))+",NULL,NULL,'include-xids','0','skip-empty-xacts','1')")
    if step=="batch_wait":
        s.normal(evidence); s.wait_idle()
        ids=[s.id+"-batch-"+str(i) for i in range(3)]
        s.focus(ids,"배치 원본 리뷰 3건 · 포인트 실험 아님")
        sql(command,"INSERT INTO review.reviews(id,content) VALUES "+",".join("("+literal(id)+",'batch review')" for id in ids))
        time.sleep(1)
        batch_state("전송 전 · 원본만 커밋")
    elif step in ("batch_partial","batch_recover"):
        path=s.directory/"reviews-batch.jsonl"
        manifest_path=s.directory/"reviews-batch.manifest.json"
        if step=="batch_partial":
            source=rows(command,"SELECT id,content FROM review.reviews WHERE id LIKE "+literal(s.id+"-batch-%")+" ORDER BY id")
            data="".join(json.dumps(row,ensure_ascii=False)+"\n" for row in source).encode()
            temporary=path.with_suffix(".part")
            temporary.write_bytes(data); temporary.replace(path)
            manifest={"count":len(source),"sha256":hashlib.sha256(data).hexdigest()}
            manifest_path.write_text(json.dumps(manifest),encoding="utf-8")
        manifest=json.loads(manifest_path.read_text())
        records=validated_file(path,manifest,s.id)
        s.focus([r["id"] for r in records],"같은 배치 파일 재처리")
        added=0
        for i,row in enumerate(records):
            # SELECT wrapper와 구분: DML RETURNING은 CTE를 통해 실제 변경 건수를 확인한다.
            changed=sql(command,"WITH inserted AS (INSERT INTO review.batch_received(id,content) VALUES ("+literal(row["id"])+","+literal(row["content"])+") ON CONFLICT(id) DO NOTHING RETURNING id) SELECT count(*) FROM inserted")
            added+=int(changed)
            if step=="batch_partial": break  # 첫 행 커밋 직후 의도적으로 중단; 프로세스를 죽인 척하지 않는다.
        report("파일 처리 증거",{"파일 건수":len(records),"이번 신규 반영":added,"의도적 중단":step=="batch_partial"},
               "파일 경로: "+str(path)+" · SHA-256 "+manifest["sha256"])
        batch_state("일부 반영 후 중단" if step=="batch_partial" else "동일 파일 재처리 완료")
    elif step=="cdc_lag":
        if sql(command,"SHOW wal_level")!="logical": raise RuntimeError("CDC는 wal_level=logical 필요. 새 compose로 전용 DB를 재시작하세요")
        slot=literal(slot_name(s.id))
        if slot_state(): raise RuntimeError("이 세션 CDC 슬롯이 이미 있습니다. 마무리로 정리한 뒤 새 세션에서 실행하세요")
        sql(command,"SELECT * FROM pg_create_logical_replication_slot("+slot+",'test_decoding')")
        a,b,c=[s.id+"-cdc-"+x for x in ("kept","deleted","rolledback")]
        s.focus([a,b,c],"CDC 원본 상태 · 포인트 실험 아님")
        sql(command,"BEGIN; INSERT INTO review.cdc_source VALUES ("+literal(a)+",'CREATED'); COMMIT; "+
            "BEGIN; UPDATE review.cdc_source SET status='SHIPPED' WHERE id="+literal(a)+"; "+
            "INSERT INTO review.cdc_source VALUES ("+literal(b)+",'CREATED'); DELETE FROM review.cdc_source WHERE id="+literal(b)+"; COMMIT; "+
            "BEGIN; INSERT INTO review.cdc_source VALUES ("+literal(c)+",'CREATED'); ROLLBACK;")
        changes=peek(); decoded=decode(changes,s.id)
        report("원본 변경 · 아직 전달하지 않음",{"원본 현재 행":len(query("cdc_source")),"대상 현재 행":len(query("cdc_target")),
               "커밋된 변경 이벤트":len(decoded),"롤백 ID 포함":any(d["id"]==c for d in decoded)},
               "WAL 변경 4개와 최종 원본 1행은 다릅니다. 디코더는 현재 테이블을 통째로 읽은 것이 아닙니다.")
        evidence.append({"operation":"PostgreSQL 실제 WAL 출력","slot":slot_state(),"changes":changes})
    elif step in ("cdc_apply","cdc_resume"):
        before=slot_state()
        if not before: raise RuntimeError("이 세션 CDC 슬롯이 없습니다. 새 세션에서 CDC 준비부터 실행하세요")
        changes=peek(); decoded=decode(changes,s.id)
        added=0
        for d in decoded:
            # 반영과 중복 처리 기록을 한 트랜잭션으로 묶는다. LSN 진행 전 재전달도 안전하다.
            effect=("DELETE FROM review.cdc_target WHERE id="+literal(d["id"])+" AND EXISTS(SELECT 1 FROM seen)"
                if d["op"]=="DELETE" else "INSERT INTO review.cdc_target(id,status) SELECT "+literal(d["id"])+","+literal(d["status"])+
                " FROM seen ON CONFLICT(id) DO UPDATE SET status=EXCLUDED.status")
            added+=int(sql(command,"WITH seen AS (INSERT INTO review.cdc_seen VALUES ("+literal(d["key"])+
                ") ON CONFLICT DO NOTHING RETURNING event_key), applied AS ("+effect+" RETURNING id) SELECT count(*) FROM seen"))
        if step=="cdc_resume" and changes:
            # 읽은 마지막 COMMIT까지만 확인한다. 그 이후 새 WAL을 건너뛰지 않는다.
            last=changes[-1]
            if not last["data"].startswith("COMMIT"): raise RuntimeError("WAL 트랜잭션 끝을 확인할 수 없습니다")
            sql(command,"SELECT * FROM pg_replication_slot_advance("+literal(slot_name(s.id))+","+literal(last["lsn"])+"::pg_lsn)")
        after=slot_state()
        report("반영 후 위치 저장 전 중단" if step=="cdc_apply" else "새 디코딩 호출로 재개 · 중복 건너뛰기",
            {"받은 원본 변경":len(decoded),"이번 신규 적용 이벤트":added,"중복 건너뛰기":len(decoded)-added,
             "원본 현재 행":len(query("cdc_source")),"대상 현재 행":len(query("cdc_target")),
             "위치 전":before[0]["confirmed_flush_lsn"],"위치 후":after[0]["confirmed_flush_lsn"]},
             "중단은 DB 반영 뒤 슬롯 확인 위치를 갱신하지 않고 반환하는 장애 지점 주입입니다. 프로세스 강제 종료 실험은 아닙니다.")
        evidence.append({"operation":"CDC 행·변경 원본","source":query("cdc_source"),"target":query("cdc_target"),"events":decoded})
        if step=="cdc_resume":
            sql(command,"SELECT pg_drop_replication_slot("+literal(slot_name(s.id))+")")
            report("실습 슬롯 정리",{"슬롯 남음":len(slot_state())},"실험 DB 행·결과는 남기고 이번 세션 슬롯만 닫아 WAL 보관을 끝냅니다.")
    elif step.startswith("failover_"):
        require(call(8083,"/actuator/health")); require(call(8083,"/control/fault",{"beforeMs":0,"afterMs":0,"fail":False}))
        if step in ("failover_single","failover_switch"):
            id=s.id+"-"+step; s.focus([id],"서로 다른 제공자의 지급 장부")
            require(call(8082,"/control/fault",{"beforeMs":0,"afterMs":0,"fail":True}))
            response=call(8081,"/extension/failover?mode="+("single" if step=="failover_single" else "safe"),{"id":id},timeout=8)
            report("주 서비스 실패 후 경로",require(response),"503 일반 규칙이 아니라 이 실습 API의 X-Lab-Not-Applied 계약을 확인합니다.")
        elif step=="failover_unknown":
            ids=[s.id+"-unknown-"+mode for mode in ("unsafe","safe")]; s.focus(ids,"응답 유실 · 위험한 전환과 보류 비교")
            for id,mode in zip(ids,("unsafe","safe")):
                require(call(8082,"/control/fault",{"beforeMs":0,"afterMs":3000,"fail":False}))
                response=call(8081,"/extension/failover?mode="+mode,{"id":id},timeout=8)
                report("타임아웃 정책 · "+mode,require(response),"같은 키라도 두 제공자의 중복 방지 장부는 공유되지 않습니다.")
                s.wait_idle()
        else:
            s.focus([s.id+"-unknown-safe"],"새 지급 요청 없이 주 서비스 실제 결과 조회")
            s.normal(evidence)
        s.wait_idle()
        ids=s.state["focus"]
        primary=[r for r in require(call(8082,"/grants")) if r["review_id"] in ids]
        backup=[r for r in require(call(8083,"/grants")) if r["review_id"] in ids]
        for id in ids:
            a=[r for r in primary if r["review_id"]==id]; b=[r for r in backup if r["review_id"]==id]
            report("실제 장부 · "+id,{"주 서비스 지급":len(a),"대체 서비스 지급":len(b),"합계 포인트":sum(r["amount"] for r in a+b)},
                   "상태 조회로 확인한 사실입니다. UNKNOWN은 미지급 확정이 아닙니다.")
        s.normal(evidence)

def cleanup(s, command, evidence):
    slot=literal(slot_name(s.id))
    existing=rows(command,"SELECT slot_name FROM pg_replication_slots WHERE slot_name="+slot)
    if existing:
        sql(command,"SELECT pg_drop_replication_slot("+slot+")")
        evidence.append({"operation":"이번 세션 CDC 슬롯 종료","extension":{"정리한 슬롯":slot_name(s.id)},
                         "detail":"원본·대상 DB 데이터는 남습니다. 중간 종료이므로 같은 슬롯에서 이어 읽을 수는 없습니다."})
