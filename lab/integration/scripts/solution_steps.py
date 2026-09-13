"""문제→해결 비교 학습. 코드는 읽기용 발췌이며 버튼은 구현된 mode를 실행한다."""

def lesson(id, title, group, situation, definition, example, before, after, changes, expected, why,
           caution, compare=None, danger=False, prepare=False):
    return dict(id=id, title=title, group=group, situation=situation, definition=definition,
        goal=title, question="" if prepare else "기존 방식과 무엇이 달라질까? 저장 결과·호출 횟수·대기 시간을 구분해 예상해보자.",
        terms=[["이번 개념",definition],["비교 방법","서로 다른 실험 ID를 사용하지만 부하·지연 조건은 설명에 적힌 대로 맞춘다. 이전 결과나 DB는 지우지 않는다."]],
        example=example, flow=[["문제와 비교 조건",situation],["코드 변경의 의미",definition],["관찰할 결과",expected]],
        conditions=[["이번 변경",changes],["보존","기존 실험 결과와 데이터는 그대로 보존한다. 해결이 과거 오류 데이터를 자동 보정하지는 않는다."]],
        watch=["아래 이전 결과와 현재 결과에서 리뷰·지급 건수 및 응답 시간을 비교한다.","회로·아웃박스·메시지 큐 상태가 있는 단계는 해당 실제 상태도 확인한다."],
        prompts=[["데이터","리뷰·지급·미완료 작업은 각각 몇 개일까?"],["응답","성공/실패 응답과 업무 완료는 같을까?"],["남은 위험","이 변경으로도 해결되지 않는 상황은 무엇일까?"]],
        command="python3 scripts/session.py run "+id, does=changes, expected=expected, why=why,
        reading=[["응답과 데이터", "빠른 실패를 빠른 성공으로 읽지 않는다. 응답을 잃어도 실제 데이터가 저장됐을 수 있다."],
                 ["단계의 관찰 기준",expected],["비교의 한계",caution]],
        reasoning=[why,changes,caution], caution=caution, transfer="장애가 더 오래 지속되거나 동시에 요청하는 사람이 많아지면 어떤 제한이 더 필요할까?",
        next="두 사람의 실제 해석을 남기고 다음 단계로 이동한다.",compare=compare,danger=danger,prepare=prepare,
        codeBefore=before,codeAfter=after,codeNotes=changes,
        codeSource="src/main/java/study/integration/ReviewController.java · PointsController.java (핵심 발췌·일부 주석 생략)")

def extend(steps):
    old={s["id"]:s for s in steps}
    fresh=lesson("connections_fresh","문제 · 요청마다 연결을 닫으면?","01 · 연결 — 문제",
        "정상 B에 리뷰 3개를 순차 호출한다. 비교를 위해 HTTP/1.1 Connection: close를 붙인다.",
        "연결 재사용은 이미 연결된 통로로 다음 HTTP 요청을 보내는 것이다. 응답 내용을 저장하는 캐시와 다르다.",
        "통화할 때 질문 하나마다 전화를 끊고 다시 거는 것과 비슷하다. 연결이 유지돼도 각 요청·응답은 별개다.",
        'if (close) request.header("Connection", "close");\nrequest.body(Map.of("reviewId", id))\n    .retrieve().toBodilessEntity();',
        '// 다음 해결 단계에서는 close 헤더를 붙이지 않는다.\n// 같은 Apache HTTP/1.1 풀의 연결을 재사용한다.',
        "버튼은 mode=fresh로 3회 호출한다. 다음 단계는 같은 요청 수로 mode=sync를 사용한다.",
        "리뷰·지급 각 3건. B 로그에서 요청별 remote 포트를 비교한다.",
        "close가 지정되면 응답 후 연결을 유지하지 않는다. 따라서 다음 요청은 새 연결을 필요로 한다.",
        "로컬 3회 요청으로 성능 향상 비율을 단정하지 않는다. 이것은 재사용 유무 실험이지 연결 비용 벤치마크가 아니다.")
    old["connections"].update(group="01 · 연결 — 해결",compare="connections_fresh",codeBefore=fresh["codeBefore"],
        codeAfter='// Connection: close 없이 같은 풀을 사용한다.\nrequest.body(Map.of("reviewId", id))\n    .retrieve().toBodilessEntity();',
        codeNotes="풀 크기 2는 미리 2개 요청을 만든다는 뜻이 아니다. 필요한 연결을 빌리고, 응답 본문 처리를 마친 연결을 반환한다. 버튼은 소스 파일을 수정하지 않고 sync 분기를 실행한다.",
        codeSource="HttpConfiguration.java / ReviewController.java")
    protected=lesson("protected","해결 · 외부 대기를 DB 밖으로, 입구는 2개로","02 · 장애 전파 — 해결",
        "앞 실험과 똑같이 B 저장 전 지연 3초, 작성 24건·조회 12건이다. A의 처리 경계만 바꾼다.",
        "벌크헤드는 장애가 난 기능이 공유 자원을 모두 차지하지 못하도록 동시 실행 자원을 격리하는 방식이다.",
        "포인트 창구가 밀려도 리뷰 조회 창구의 직원까지 모두 붙잡히지 않게 한다. 자원 보호와 업무 성공은 다른 목표다.",
        'tx.executeWithoutResult(s -> {\n    insert(review);\n    grant(review.id(), attempt);\n});',
        'if (!slots.tryAcquire()) throw new ResponseStatusException(503, "full", null);\ntry {\n    grant(review.id(), attempt, true); // DB 트랜잭션 밖\n    tx.executeWithoutResult(s -> insert(review));\n} finally { slots.release(); }',
        "mode=guarded는 세마포어 2개를 즉시 획득하지 못하면 503을 반환한다. 획득한 요청도 HTTP 대기 중 DB 연결을 잡지 않는다. 이 단계는 두 변경을 묶은 자원 보호 패키지이며 각 변경의 개별 효과를 분리한 측정은 아니다.",
        "작성 실패는 여전히 있을 수 있다. DB 점유·대기와 독립 조회 지연이 앞 실험보다 줄었는지 실제 측정으로 판단한다.",
        "DB를 빌린 채 HTTP를 기다리던 구간을 없앴다. 밀린 요청은 세마포어 앞에서 즉시 거절해 HTTP 풀 대기까지 들어오는 양도 제한한다.",
        "B 지급 후 A DB 저장이 실패하면 여전히 데이터가 어긋난다. 세마포어 2개도 타임아웃 이후 B에 남은 작업까지 취소하지는 않는다.","slow")
    outside=lesson("outside","해결 1 · DB를 빌린 채 기다리지 않기","02 · 장애 전파 — DB 경계",
        "같은 B 지연 3초·작성 24건·조회 12건을 반복하되 HTTP 대기를 DB 트랜잭션 밖으로 옮긴다.",
        "트랜잭션 경계는 어떤 작업을 하나의 DB 커밋/롤백으로 묶을지 정한다. 외부 HTTP 호출은 DB 트랜잭션에 자동으로 묶이지 않는다.",
        "전화 응답을 기다리는 동안 DB 창구의 자리를 차지하지 않는 것이다. 전화 업무 자체가 빨라진 것은 아니다.",
        protected["codeBefore"],
        'grant(review.id(), attempt, true); // DB 연결 점유 없이 대기\ntx.executeWithoutResult(s -> insert(review));',
        "mode=outside로 HTTP 호출을 DB 밖에서 실행한다. HTTP 풀 크기·타임아웃·예약 요청 수는 그대로다. 원격 지급에는 해결용 멱등 키를 사용하지만 각 작성은 새 ID이므로 이번 비교에서 중복 방지 효과를 측정하지는 않는다.",
        "HTTP 오류는 남아도 DB 점유·대기와 독립 조회 지연이 줄었는지 비교한다.",
        "A는 B가 성공한 뒤에만 DB 트랜잭션을 시작하므로 외부 대기가 DB 연결을 붙잡지 않는다.",
        "B 지급 후 A 저장 실패의 불일치는 여전히 남는다. 처리 순서 변경만으로 분산 원자성을 얻지는 못한다.","slow")
    protected.update(title="해결 2 · 외부 호출 입구를 2개로 제한",compare="outside",codeBefore=outside["codeAfter"])
    protected["codeNotes"]=protected["does"]="DB 밖 호출 구조를 유지하고 mode=guarded에서 세마포어 2개를 추가한다. 슬롯이 없으면 503으로 즉시 거절한다. 이전 outside 결과와 HTTP 풀 대기·거절 응답을 비교한다."
    protected["conditions"][0][1]=protected["does"]
    protected["reasoning"][1]=protected["does"]
    protected["goal"]="이미 분리한 DB 경계는 유지하고, HTTP 풀 앞 대기를 줄인다."
    protected["expected"]="앞 outside 실행과 비교해 HTTP 획득 대기가 줄고, 슬롯 초과 요청은 빠르게 503으로 거절되는지 확인한다. DB는 앞 단계에서도 외부 대기 중 점유하지 않았다."
    protected["why"]="앞 단계는 DB 자원을 보호했다. 이번에는 HTTP 풀에 들어가기 전에 동시 호출 수를 제한한다. 대기하는 대신 거절하므로 처리 성공률이 반드시 높아지는 것은 아니다."
    protected["reasoning"][0]=protected["why"]
    protected["flow"][2][1]=protected["expected"]
    protected["reading"][1][1]=protected["expected"]
    protected["codeAfter"]='private final Semaphore slots = new Semaphore(2);\n\n'+protected["codeAfter"]
    protected["codeSource"]="ReviewController.java · mode=guarded (핵심 발췌)"
    circuit_problem=lesson("circuit_problem","문제 · 이미 고장 난 B를 계속 부르면?","03 · 서킷 브레이커 — 문제",
        "B가 지연 없이 503을 반환하게 만든 뒤 A에 6번 순차 요청한다. HTTP 풀과 DB 보호만 켠 상태다.",
        "동시 요청 제한은 한 번에 들어오는 양을 제한할 뿐, 실패하는 곳에 다음 요청을 계속 보내는 것까지 막지는 않는다.",
        "닫힌 가게에 손님이 한 명씩 계속 방문하는 상황이다. 줄은 짧아도 헛걸음은 계속된다.",
        'grant(review.id(), attempt, true);',
        '// 다음 단계에서 과거 실패를 기록하는 회로를 추가한다.',
        "mode=guarded로 순차 6회 실행. B의 실패 설정은 다음 해결 단계에서도 동일하다.",
        "A 요청 6건 실패. B에 6번 실제 도달했는지는 아래 호출 증거를 확인한다.",
        "요청이 동시에 몰리지 않아 벌크헤드로 거절되지 않는다. 이전 실패를 기억하지 않으니 매번 다시 B를 호출한다.",
        "서킷 브레이커는 실패 이력을 이용한다. 타임아웃이나 멱등성의 대체물이 아니다.")
    circuit=lesson("circuit_solution","해결 · 실패 3회 뒤 B 호출 차단","03 · 서킷 브레이커 — 해결",
        "같은 B 503 장애, 같은 순차 6회 요청이다. 연속 실패 3회면 3초 차단하는 교육용 회로를 켠다.",
        "CLOSED는 호출 허용, OPEN은 호출 차단, HALF_OPEN은 회복 여부를 알아보는 제한된 시험 호출 상태다.",
        "휴점이 확인된 가게로 계속 보내지 않고, 잠시 뒤 대표 한 명만 가게가 열렸는지 확인한다.",
        'grant(review.id(), attempt, true);',
        'if (!breaker.allow()) throw new ResponseStatusException(503, "circuit open", null);\ntry {\n    grant(review.id(), attempt, true);\n    breaker.success();\n} catch (RestClientException e) {\n    breaker.failure();\n    throw e;\n}',
        "mode=circuit를 실행한다. 각 응답과 그 직후 회로 상태를 원본에 기록한다. 버튼을 누르는 것은 회로 상태를 수동 선택하는 일이 아니다.",
        "6건 모두 실패해도 B 호출은 처음 3건으로 제한되고 이후는 A가 거절하는지 확인한다. 회로 상태는 OPEN으로 바뀐다.",
        "차단의 목표는 오류 응답을 성공으로 만드는 것이 아니라, 실패할 외부 호출과 불필요한 대기를 줄이고 B에게 회복 시간을 주는 것이다.",
        "실습은 연속 실패 기준의 단일 프로세스 회로다. 운영에서는 슬라이딩 윈도·최소 표본·오류 분류·분산 인스턴스 차이를 고려한다.","circuit_problem")
    recovery=lesson("circuit_recover","회복 검증 · 시험 요청이 성공하면?","03 · 서킷 브레이커 — 회복",
        "B를 정상화하고 차단 시간 3초를 기다린 뒤 시험 요청 1건을 보낸다. HALF_OPEN을 관찰하도록 이번 요청은 500ms 지연한다.",
        "OPEN에서 시간이 지났다는 사실만으로 정상 복귀하지 않는다. 시험 요청의 성공·실패가 복귀 여부를 결정한다.",
        "‘3초 지났으니 영업 중일 것’이라 추측하는 대신, 실제로 한 번 확인한다.",
        '// OPEN: 요청을 즉시 거절한다.',
        '// 3초 경과 후 allow()가 시험 요청 하나만 허용\n// 실행 중 HALF_OPEN\n// 성공 → CLOSED, 실패 → OPEN',
        "B 정상화 → 3.1초 대기 → 500ms 시험 요청 중 상태 조회 → 응답 후 상태 조회. 원본에 두 시점의 상태를 남긴다.",
        "시험 중 HALF_OPEN, 성공 후 CLOSED를 확인한다. 1초 수집 간격으로 중간 상태를 놓쳐도 아래 직접 조회 증거에서 볼 수 있다.",
        "차단과 회복을 자동으로 연결해야 정상화된 뒤에도 계속 거절하는 일이 없다.",
        "운영에서는 시험 요청 수와 성공 비율을 정할 수 있다. 이 구현은 하나의 성공으로 닫는 단순화다.")
    circuit["codeSource"]="ReviewController.java / LabBreaker.java (교육용 단일 프로세스 회로)"
    circuit["codeAfter"]+='\n\n// LabBreaker.failure(): 연속 실패 카운터\nif (++failures >= 3 || probe)\n    openedAt = System.nanoTime();\n// allow(): 열린 지 3초가 안 지났거나\n// 시험 요청이 이미 실행 중이면 false를 반환한다.'
    idem=lesson("idempotent","해결 · 응답을 잃어도 지급은 한 번만","04 · 재시도 — 해결",
        "새 업무 ID로 앞의 ‘지급 후 응답 3초 지연 → 정상화 → 같은 ID 재시도’를 그대로 반복한다. 이번에는 B의 멱등 분기를 사용한다.",
        "멱등 처리는 같은 업무 키로 여러 번 요청해도 업무 효과가 중복되지 않도록 하는 것이다. 요청 시도 ID와 구분한다.",
        "같은 영수증 번호로 적립을 다시 요청해도 이미 적립했다면 결과만 알려준다. 서로 다른 영수증을 같은 번호로 처리하면 안 된다.",
        'INSERT INTO point_grants(review_id, amount)\nVALUES (?, 100);',
        'CREATE UNIQUE INDEX point_grants_dedupe\n  ON point_grants(dedupe_key);\n\nINSERT INTO point_grants(review_id, amount, dedupe_key)\nVALUES (?, 100, ?)\nON CONFLICT (dedupe_key) DO NOTHING;',
        "mode=idempotent는 첫 호출부터 X-Idempotent:true를 전달한다. B는 dedupe_key에 reviewId를 저장한다. 기존 문제 버전 행은 NULL 키로 그대로 두며, 과거 중복 지급을 자동 취소하지 않는다.",
        "첫 응답은 타임아웃이어도 지급 1건. 정상 재시도 후 리뷰 1건·지급 1건·100포인트가 되는지 확인한다.",
        "‘없는지 조회한 뒤 INSERT’가 아니라 DB의 고유 제약과 단일 INSERT로 원자적으로 경쟁을 해결한다. 중복이면 이미 처리된 100포인트 결과를 반환한다.",
        "이 실습의 지급액은 항상 100이다. 가변 금액 API라면 같은 키·다른 요청 본문 충돌 검증과 저장된 응답 재사용도 필요하다. A 전체 API의 완전한 멱등성을 구현한 것은 아니다.","retry")
    backoff=lesson("backoff","해결 · 즉시 반복하지 말고 간격 두기","04 · 재시도 — 간격",
        "각 비교 실행마다 B를 1.2초 후 복구시킨다. 즉시 3회와 0초·0.5초·추가 1초 후의 최대 3회를 비교한다.",
        "백오프는 재시도 사이의 대기 시간을 늘리는 것이다. 횟수 제한과 함께 써서 장애 서비스에 요청을 더 쌓지 않도록 한다.",
        "문을 세 번 연달아 두드리는 대신 조금 기다렸다 다시 확인한다. 기다린다고 반드시 문이 열리는 것은 아니다.",
        'for attempt in range(3):\n    request_review(id, attempt, "idempotent")',
        'for delay in (0, .5, 1):\n    time.sleep(delay)\n    row = request_review(id, attempt, "idempotent")\n    if row["status"] == 200:\n        break',
        "실습 실행기가 간격 있는 재호출을 수행한다. Java 클라이언트의 숨은 자동 재시도는 계속 꺼져 있다. 실제 대기 간격·응답을 원본에 남긴다.",
        "즉시 3회는 모두 장애 중에 끝날 수 있고, 간격 있는 3회는 복구 뒤 성공할 수 있다. 서로 다른 두 reviewId의 응답과 실제 지급을 비교한다.",
        "재시도 횟수가 같아도 시점이 다르면 회복된 서버를 만날 가능성이 달라진다. 멱등성을 먼저 넣었기 때문에 응답 유실에 따른 중복 효과도 방어할 수 있다.",
        "이 실험은 재시도 시점 비교이지 retry storm 부하 실험은 아니다. 운영에서는 재시도 가능한 오류만 선택하고 jitter·전체 시간 예산·여러 계층의 중복 재시도를 고려해야 한다.")
    backoff["codeSource"]="scripts/session.py · action(backoff) (핵심 구조 발췌)"
    outbox=lesson("outbox_store","해결 · 리뷰와 지급할 일을 같이 저장","05 · 비동기 내구성 — 해결",
        "메모리 작업이 사라진 앞 실험과 달리, 이번에는 리뷰와 지급할 일을 DB에 함께 저장한다. 전달자는 일부러 멈춰 두고 응답한다.",
        "트랜잭션 아웃박스는 업무 데이터와 전달할 메시지를 같은 DB 트랜잭션에 저장하는 패턴이다. 별도 전달자가 나중에 처리한다.",
        "직원에게 말로만 심부름을 맡기는 대신, 주문과 발송 목록을 함께 장부에 적는다. 직원이 바뀌어도 할 일을 찾을 수 있다.",
        'tx.executeWithoutResult(s -> insert(review));\nworker.execute(() -> grant(review.id(), attempt));',
        'tx.executeWithoutResult(s -> {\n    insert(review);\n    db.update("INSERT INTO outbox(review_id,channel) VALUES (?,?)",\n              review.id(), "HTTP");\n});',
        "mode=outbox로 실행한다. 리뷰·outbox 원자적 저장 후 응답하고 relay는 paused=true로 둔다. 완료된 업무가 아니라 ‘할 일을 안전하게 접수한 상태’다.",
        "리뷰 1건·지급 0건·아웃박스 WAITING 1건을 확인한다. 의도적인 대기 상태이므로 지급 완료까지 기다리지 않고 1초 더 관찰 후 고정한다.",
        "같은 DB 트랜잭션이므로 리뷰만 저장되고 지급할 일은 사라지는 저장 간극을 줄인다. 롤백되면 둘 다 저장되지 않는다.",
        "내구성은 외부 지급을 즉시 완료한다는 뜻이 아니다. 발송 지연·재전송·중복 처리는 별도로 다뤄야 한다.","async")
    recover=lesson("outbox_recover","검증 · A를 죽였다 켜도 할 일이 남을까?","05 · 비동기 내구성 — 복구",
        "WAITING 작업이 저장된 것을 확인한 뒤 A만 강제 종료·재시작한다. 재시작 직후 기록을 확인하고 전달자를 재개한다.",
        "전달자는 WAITING을 조회해 외부 호출하고 성공 후 DONE으로 바꾼다. 재시작해도 DB에 남은 작업을 다시 읽을 수 있다.",
        "새 직원이 장부의 미발송 목록을 보고 일을 이어간다. 전달 후 체크 표시 전에 자리를 떠나면 다시 전달할 수 있으므로 받는 쪽도 중복을 견뎌야 한다.",
        '// 메모리 큐만 사용하면 A 종료 시 할 일을 잃는다.',
        'for (var row : waitingRows) {\n    grant(id, "outbox", true); // 멱등한 B 호출\n    db.update("UPDATE outbox SET status=\'DONE\' WHERE review_id=?", id);\n}',
        "확인 체크 후 A만 재시작한다. relay는 안전을 위해 시작 시 정지 상태이며, 버튼이 이번 세션 범위만 재개한다. WAITING → DONE과 실제 지급 완료 후 1초를 더 관찰한다.",
        "재시작 직후 WAITING이 남고, 재개 후 리뷰 1건·지급 1건·DONE 1건이 되는지 확인한다.",
        "메모리가 아니라 DB에서 재시작 지점을 찾는다. 지급 성공 직후 A가 종료되어 DONE을 못 쓰더라도 다음 재전송은 B의 업무 키로 중복 지급을 막는다.",
        "현재 전달자는 단일 A 인스턴스다. 다중 인스턴스의 행 선점·리스, 실패 상한·경보·수동 복구, 업무별 순서는 추가 설계가 필요하다.","crash",danger=True)
    broker=lesson("broker_hold","메시징 · B를 멈추면 메시지는 어디에 남을까?","06 · 메시징 — 적체",
        "이번에는 아웃박스 전달 대상만 HTTP에서 실제 RabbitMQ 큐로 바꾼다. B 소비자를 멈춘 채 리뷰 3개를 만든다.",
        "브로커는 메시지를 보관하고 소비자가 처리하도록 전달하는 중간 시스템이다. 생산 성공과 소비 완료는 별개다.",
        "발송자가 우편물을 우체국에 맡겼다는 것과 수신자가 내용을 처리했다는 것은 다르다.",
        'grant(id, "outbox", true); // B에 직접 HTTP 호출',
        'channel.queueDeclare("review-points", true, false, false, null);\nchannel.basicPublish("", "review-points",\n    MessageProperties.PERSISTENT_TEXT_PLAIN, bytes);\nchannel.waitForConfirmsOrDie(2000); // 브로커 확인\n// 그 뒤 outbox DONE',
        "mode=broker로 리뷰 3개 저장 → 이번 세션 아웃박스 전달 → B 소비자는 paused=true 유지. RabbitMQ durable 큐·persistent 메시지·publisher confirm을 사용한다.",
        "리뷰 3건·아웃박스 DONE 3건이지만 지급은 0건, 큐 ready는 3개가 되는지 확인한다.",
        "이번 DONE은 브로커 전달 완료다. B 지급 완료가 아니다. B가 멈춰도 A는 업무와 할 일을 저장하고 브로커에 넘길 수 있다.",
        "큐는 무한하지 않다. 생산이 소비보다 계속 빠르면 적체와 완료 지연이 증가한다. 브로커 장애·용량 제한·운영 비용도 고려해야 한다.","outbox_store")
    broker["codeSource"]="ReviewController.java / LabQueue.java"
    drain=lesson("broker_drain","해결 확인 · 소비 재개와 ACK","06 · 메시징 — 소비",
        "방금 멈춰 둔 B 소비자를 재개한다. 새로운 리뷰는 만들지 않고 같은 3개 메시지의 처리를 따라간다.",
        "consumer ACK는 소비자가 처리 완료를 브로커에 알리는 확인이다. publisher confirm과 확인 주체·시점이 다르다.",
        "우체국 접수증과 수신자의 업무 완료 확인은 서로 다른 증거다.",
        '// 메시지를 받자마자 ACK하면 처리 중 종료 시 유실될 수 있다.',
        'var delivery = queue.get(); // autoAck=false\ntry {\n    apply(reviewId, true); // 지급 DB 커밋, 업무 키로 중복 방지\n    queue.ack(tag);\n} catch (Exception e) {\n    queue.retry(tag); // NACK + requeue\n}',
        "버튼은 소비자 paused=false로 바꾼다. 실제 지급 3건, 큐 ready=0, B active=0을 확인한 후 여유 1초를 두고 고정한다. 실습 소비자는 관찰을 위해 한 주기마다 한 건씩 읽는다.",
        "리뷰 3건·지급 3건·300포인트·큐 ready 0개가 되는지 확인한다. 아웃박스 DONE 수는 이미 3개였다는 점도 비교한다.",
        "지급 커밋 뒤 ACK한다. 그 사이 소비자가 종료되면 재전달될 수 있지만 B의 멱등 처리가 중복 효과를 막는다.",
        "at-least-once는 효과가 자동으로 한 번만 발생한다는 뜻이 아니다. 무한 재전달을 막는 재시도 상한·DLQ·모니터링은 별도 운영 설계다.","broker_hold")
    drain["codeSource"]="PointsController.java / LabQueue.java"
    for id in ("ready","restore","finish"):
        old[id]["prepare"]=True
        old[id]["question"]=""
        old[id]["transfer"]="이 단계는 설정 준비/정리다. 예측이나 해석 제출 대신 완료 기준을 확인한다."
    old["ready"]["caution"]="연결·자원 보호·재시도·비동기·메시징·배치·CDC·이중화를 실제 버튼 실험으로 비교한다. 교육용 단일 노트북 환경이며 운영용 구현 전체를 대체하지 않는다."
    old["slow"]["next"]="다음 해결 단계에서 같은 지연·부하로 DB 자원 보호 전후를 비교한다."
    old["crash"]["next"]="바로 다음 단계에서 아웃박스에 할 일을 남겨 같은 종료 상황을 다시 검증한다."
    old["crash"]["caution"]="현재 문제 버전에는 아웃박스가 없다. 다음 해결 단계는 새 리뷰로 비교하며 과거 누락 지급을 자동 보정하지 않는다."
    old["finish"]["does"]="B 정상화·작업자 정지 해제 후 B 종료 확인. 아웃박스 전달자와 메시지 소비자는 정지하고 회로를 초기 상태로 되돌린다. 데이터·큐는 삭제하지 않는다."
    old["finish"]["expected"]="B 지연 0, 메모리 작업자 정지 해제, 전달자·소비자 paused=true. 이전 결과와 데이터는 보존된다."
    result=[old["ready"],fresh,old["connections"],old["slow"],outside,protected,circuit_problem,circuit,recovery,
        old["restore"],old["late"],old["retry"],idem,backoff,old["async"],old["crash"],outbox,recover,broker,drain,old["finish"]]
    for s in result:
        s.setdefault("prepare",False)
        s.setdefault("codeSource","ReviewController.java / PointsController.java")
    from extension_steps import extend_more
    return extend_more(result,lesson)
