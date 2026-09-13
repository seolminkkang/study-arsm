import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import urllib.request
import urllib.error
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import session

class MetricsTest(unittest.TestCase):
    def test_missing_is_not_zero(self):
        self.assertTrue(all(v is None for v in session.metric_values({}).values()))
    def test_metric_uses_instance_and_ignores_stale(self):
        data={"status":"success","data":{"result":[
            {"metric":{"__name__":"lab_http_pool_leased","instance":"review:8081"},"value":[time.time(),"2"]},
            {"metric":{"__name__":"lab_http_pool_pending","instance":"review:8081"},"value":[time.time()-20,"8"]}]}}
        result=session.metric_values(data)
        self.assertEqual(result["httpUsed"],2)
        self.assertIsNone(result["httpWait"])

class SessionTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=patch.object(session,"ROOT",Path(self.temp.name))
        self.root.start()
        self.git=patch.object(session.Session,"git_info",return_value={"commit":"test"})
        self.git.start()
        self.s=session.Session()
    def tearDown(self):
        self.git.stop()
        self.root.stop()
        self.temp.cleanup()
    def test_predictions_are_required(self):
        self.s.state["results"]={s["id"]:{} for s in session.STEPS[:2]}
        self.s.select("connections")
        with self.assertRaisesRegex(ValueError,"예측"):
            self.s.execute("connections")
        self.assertFalse(self.s.state["busy"])
    def test_order_and_unknown_actions(self):
        self.s.select("retry")
        with self.assertRaisesRegex(ValueError,"앞 단계"):
            self.s.execute("retry")
        with self.assertRaisesRegex(ValueError,"허용"):
            self.s.execute("shell")
    def test_crash_requires_explicit_confirmation(self):
        self.s.state["results"]={s["id"]:{} for s in session.STEPS if s["id"]!="crash"}
        self.s.select("crash")
        self.s.notes("crash","예측 A","예측 B","")
        with self.assertRaisesRegex(ValueError,"강제 종료 확인"):
            self.s.execute("crash")
    def test_notes_are_append_only_and_new_preserves_old(self):
        self.s.notes("ready","a","b","c")
        before=(self.s.directory/"events.jsonl").read_text()
        old=self.s.directory
        self.s.notes("ready","changed","b","c")
        self.assertTrue((old/"events.jsonl").read_text().startswith(before))
        self.s.new()
        self.assertTrue(old.exists())
        self.assertNotEqual(old,self.s.directory)
    def test_new_rejects_paused_worker(self):
        self.s.snapshot["worker"]={"paused":True}
        with self.assertRaisesRegex(ValueError,"일시정지"):
            self.s.new()
    def test_readonly_port_rejects_commands_and_keys_differ(self):
        server=session.Server(("127.0.0.1",0),self.s,True)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        def req(path, key=None, data=None):
            r=urllib.request.Request("http://127.0.0.1:"+str(server.server_port)+path,
                data=None if data is None else json.dumps(data).encode(),
                headers={"Content-Type":"application/json","Authorization":"Bearer "+(key or "")})
            try:
                with urllib.request.urlopen(r) as res:
                    return res.status,res.read()
            except urllib.error.HTTPError as e:
                with e:
                    return e.code,e.read()
        try:
            self.assertEqual(req("/api/state")[0],401)
            self.assertEqual(req("/api/state",self.s.operator_key)[0],401)
            self.assertEqual(req("/api/state",self.s.viewer_key)[0],200)
            self.assertEqual(req("/api/run",self.s.viewer_key,{"step":"ready"})[0],403)
            self.assertEqual(req("/api/reset",self.s.viewer_key,{"confirmation":session.CONFIRMATION})[0],403)
            self.assertEqual(req("/api/share",self.s.viewer_key)[0],404)
            self.assertNotIn(self.s.operator_key.encode(),req("/")[1])
        finally:
            server.shutdown()
            server.server_close()
    def test_operator_requires_key_and_same_origin(self):
        server=session.Server(("127.0.0.1",0),self.s,False)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        def req(origin, key):
            r=urllib.request.Request("http://127.0.0.1:"+str(server.server_port)+"/api/select",
                data=b'{"step":"ready"}',headers={"Content-Type":"application/json",
                "Host":"127.0.0.1:8090","Origin":origin,"Authorization":"Bearer "+key})
            try:
                with urllib.request.urlopen(r) as res:
                    return res.status
            except urllib.error.HTTPError as e:
                with e:
                    return e.code
        try:
            self.assertEqual(req("http://evil.example",self.s.operator_key),403)
            self.assertEqual(req("http://127.0.0.1:8090","wrong"),403)
            self.assertEqual(req("http://127.0.0.1:8090",self.s.operator_key),200)
        finally:
            server.shutdown()
            server.server_close()

    def test_reset_requires_phrase_and_idle_action_lock(self):
        with patch.object(session, "LabReset") as reset:
            with self.assertRaisesRegex(ValueError,"확인 문구"):
                self.s.reset(True)
            self.s.action_lock.acquire()
            with self.assertRaisesRegex(ValueError,"실행 중"):
                self.s.reset(session.CONFIRMATION)
            self.s.action_lock.release()
            reset.assert_not_called()

    def test_reset_preserves_journal_and_starts_fresh_only_after_verification(self):
        self.s.notes("ready","검증용 예측","검증용 예측","해석")
        old=self.s.directory
        def collect():
            self.s.snapshot={"reviews":[],"grants":[],"fault":{"beforeMs":0,"afterMs":0,"fail":False},
                             "solutions":{"outbox":[]},
                             "worker":{"paused":False,"active":0,"queued":0}}
        with patch.object(session,"LabReset") as reset, patch.object(self.s,"collect",side_effect=collect), \
                patch.object(session,"call",return_value={"status":200,"body":{"paused":True,"ready":0,"active":0}}):
            reset.return_value.perform.return_value={"backup":str(old/"before-reset.dump")}
            self.s.action_lock.acquire()
            self.s.state["busy"]=True
            self.s._reset()
        self.assertEqual(self.s.state["step"],"ready")
        self.assertEqual(self.s.state["notes"],{})
        self.assertNotEqual(old,self.s.directory)
        self.assertIn("검증용 예측",(old/"events.jsonl").read_text())
        self.assertIn("reset_completed",(old/"events.jsonl").read_text())
        self.assertTrue(self.s.state["lastReset"]["backup"])

    def test_reset_failure_does_not_create_new_session(self):
        old=self.s.directory
        with patch.object(session,"LabReset") as reset, patch.object(session,"call",return_value={"status":200,"body":{"paused":True,"ready":0,"active":0}}):
            reset.return_value.perform.side_effect=RuntimeError("backup failed")
            self.s.action_lock.acquire()
            self.s.state["busy"]=True
            self.s._reset()
        self.assertEqual(old,self.s.directory)
        self.assertIn("backup failed",self.s.state["error"])
        self.assertFalse(self.s.state["busy"])
        self.assertFalse(self.s.action_lock.locked())

    def test_observation_waits_for_remote_then_one_second(self):
        order=[]
        self.s.action_lock.acquire()
        with patch.object(self.s,"action",side_effect=lambda *args:order.append("action")), \
             patch.object(self.s,"wait_idle",side_effect=lambda:order.append("remote-idle")), \
             patch.object(session.time,"sleep",side_effect=lambda seconds:order.append(seconds)), \
             patch.object(self.s,"collect",side_effect=lambda:order.append("collect")):
            self.s._execute("slow")
        self.assertEqual(order,["action","remote-idle",1,"collect"])
        self.assertIn("requestsEnded",self.s.state["results"]["slow"])

    def test_intentionally_paused_stage_still_observes_one_second(self):
        self.s.action_lock.acquire()
        with patch.object(self.s,"action"),patch.object(self.s,"wait_idle") as wait, \
             patch.object(session.time,"sleep") as sleep,patch.object(self.s,"collect"):
            self.s._execute("outbox_store")
        wait.assert_not_called()
        sleep.assert_called_once_with(1)

class LessonTest(unittest.TestCase):
    def test_solutions_have_code_and_comparisons(self):
        for id in ("protected","idempotent","outbox_recover","broker_drain","circuit_solution"):
            step=session.STEP_MAP[id]
            for key in ("codeBefore","codeAfter","codeNotes","compare"):
                self.assertTrue(step[key])
        for id in ("ready","restore","finish"):
            self.assertTrue(session.STEP_MAP[id]["prepare"])
            self.assertFalse(session.STEP_MAP[id]["question"])
    def test_every_stage_has_concepts_conditions_and_explanations(self):
        for step in session.STEPS:
            for key in ("goal","terms","example","flow","conditions","reading","reasoning","caution","transfer"):
                self.assertTrue(step.get(key),(step["id"],key))
            if step["question"]:
                self.assertGreaterEqual(len(step["prompts"]),3)

if __name__=="__main__":
    unittest.main()
