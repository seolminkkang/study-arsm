"""분리 검증 기록으로 화면 QA. 서비스 실행·새 세션·초기화는 차단한다."""
import json
import sys
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer
import session

record=Path(sys.argv[1])
s=session.Session()
for line in record.read_text().splitlines():
    event=json.loads(line)
    if event["kind"]=="action_result":
        data=event["data"]
        s.state["results"][data["step"]]=data
        s.snapshot=data["snapshot"]
s.select("protected")

class Handler(session.Handler):
    def valid_host(self): return self.headers.get("Host") in ("127.0.0.1:8093","127.0.0.1:8094")
    def do_GET(self):
        if self.path=="/":
            role="observer" if self.server.readonly else "operator"
            html=session.UI.read_text().replace("__ROLE__",role).replace("__OPERATOR_KEY__",s.operator_key)
            html=html.replace('<body>','<body><div class="notice">화면 검증용 · 분리된 검증 환경의 저장 결과입니다. 현재 사용자 실험의 실시간 값이 아닙니다.</div>')
            return self.respond(200,html,"text/html; charset=utf-8")
        return super().do_GET()
    def do_POST(self):
        if self.path not in ("/api/select","/api/notes"):
            return self.respond(403,{"error":"기록 미리보기에서는 실행하지 않습니다"})
        origin=self.headers.get("Origin")
        if origin=="http://127.0.0.1:8093": del self.headers["Origin"]
        return super().do_POST()

for port,readonly in ((8093,False),(8094,True)):
    server=ThreadingHTTPServer(("127.0.0.1",port),Handler)
    server.session=s; server.readonly=readonly
    threading.Thread(target=server.serve_forever,daemon=True).start()
print("preview http://127.0.0.1:8093",flush=True)
print("observer http://127.0.0.1:8094/#key="+s.viewer_key,flush=True)
threading.Event().wait()
