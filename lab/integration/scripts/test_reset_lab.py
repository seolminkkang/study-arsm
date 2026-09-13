import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
from reset_lab import LabReset, SQL, PROJECT, VOLUME


class ResetTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)
        self.events=[]
        self.reset=LabReset(self.path,self.path,lambda *e:self.events.append(e))
        self.slots=patch.object(self.reset,"verify_no_cdc_slot")
        self.slots.start()
    def tearDown(self):
        self.slots.stop()
        self.temp.cleanup()
    def test_exact_targets_required(self):
        def output(args):
            if "--quiet" in args:
                return args[-1]+"-id"
            service=args[-1].removesuffix("-id")
            return json.dumps([{"Config":{"Labels":{"com.docker.compose.project":PROJECT,
                "com.docker.compose.service":service},"Env":["POSTGRES_DB=integration","POSTGRES_USER=integration"]},
                "State":{"Running":True},"Mounts":[{"Type":"volume","Name":VOLUME,"Destination":"/var/lib/postgresql/data"}]}])
        with patch.object(self.reset,"output",side_effect=output):
            self.reset.verify_targets()
        def wrong_volume(args):
            return output(args).replace(VOLUME,"existing-movie-db")
        with patch.object(self.reset,"output",side_effect=wrong_volume):
            with self.assertRaisesRegex(RuntimeError,"볼륨"):
                self.reset.verify_targets()
        def wrong_project(args):
            return output(args).replace(PROJECT,"movie-lab")
        with patch.object(self.reset,"output",side_effect=wrong_project):
            with self.assertRaisesRegex(RuntimeError,"전용 컨테이너"):
                self.reset.verify_targets()
    def test_backup_failure_never_truncates_or_restarts(self):
        with patch.object(self.reset,"verify_targets"), patch.object(self.reset,"output") as output, \
                patch.object(self.reset,"verify_empty_queue"), \
                patch.object(self.reset,"backup",side_effect=RuntimeError("backup failed")):
            with self.assertRaisesRegex(RuntimeError,"backup failed"):
                self.reset.perform()
        self.assertEqual(output.call_count,1)
        self.assertIn("stop",output.call_args.args[0])
    def test_target_check_failure_has_no_mutation(self):
        with patch.object(self.reset,"verify_targets",side_effect=RuntimeError("target")), \
                patch.object(self.reset,"output") as output, patch.object(self.reset,"backup") as backup:
            with self.assertRaises(RuntimeError):
                self.reset.perform()
        output.assert_not_called()
        backup.assert_not_called()
    def test_order_and_exact_sql_without_cascade_or_volume_deletion(self):
        actions=[]
        with patch.object(self.reset,"verify_targets",side_effect=lambda:actions.append("verify")), \
                patch.object(self.reset,"verify_empty_queue"), \
                patch.object(self.reset,"backup",side_effect=lambda:actions.append("backup") or self.path/"backup.dump"), \
                patch.object(self.reset,"output",side_effect=lambda args:actions.append(args)):
            self.reset.perform()
        self.assertEqual(actions[0],"verify")
        self.assertIn("stop",actions[1])
        self.assertEqual(actions[2],"backup")
        self.assertEqual(actions[3][-1],SQL)
        self.assertIn("--force-recreate",actions[4])
        self.assertNotIn("CASCADE",SQL)
        self.assertNotIn("down",str(actions))
    def test_nonempty_queue_blocks_before_backup(self):
        with patch.object(self.reset,"output",return_value='[{"name":"review-points","messages_ready":1,"messages_unacknowledged":0}]'):
            with self.assertRaisesRegex(RuntimeError,"큐"):
                self.reset.verify_empty_queue()
        with patch.object(self.reset,"verify_targets"),patch.object(self.reset,"output"), \
             patch.object(self.reset,"verify_empty_queue",side_effect=RuntimeError("queue pending")), \
             patch.object(self.reset,"backup") as backup:
            with self.assertRaisesRegex(RuntimeError,"queue pending"): self.reset.perform()
            backup.assert_not_called()
    def test_empty_backup_is_rejected(self):
        with patch.object(self.reset,"run"):
            with self.assertRaisesRegex(RuntimeError,"빈 백업"):
                self.reset.backup()


@unittest.skipUnless(os.environ.get("RUN_DOCKER_RESET_TESTS")=="1","명시적 선택 시 독립된 일회용 PostgreSQL로 검증")
class RealDatabaseTest(unittest.TestCase):
    def test_backup_truncate_restore_in_owned_disposable_database(self):
        # 사용자 컨테이너·포트·볼륨을 쓰지 않는다. 방금 만든 컨테이너 ID만 finally에서 제거한다.
        name="arsm-reset-test-"+secrets.token_hex(5)
        cid=subprocess.check_output(["docker","run","-d","--rm","--name",name,
            "-e","POSTGRES_PASSWORD=test-only","-e","POSTGRES_USER=integration",
            "-e","POSTGRES_DB=integration","postgres:16"],text=True).strip()
        self.assertRegex(cid,r"^[0-9a-f]{64}$")
        def docker(*args,**kwargs):
            return subprocess.run(["docker","exec","-i",cid,*args],capture_output=True,check=True,**kwargs)
        try:
            for _ in range(60):
                # 초기화용 임시 서버의 Unix 소켓이 아니라 최종 TCP 서버가 뜰 때까지 기다린다.
                ready=subprocess.run(["docker","exec",cid,"pg_isready","-h","127.0.0.1","-U","integration"],capture_output=True)
                if ready.returncode==0: break
                time.sleep(.5)
            ddl="""CREATE SCHEMA review; CREATE SCHEMA points; CREATE SCHEMA untouched;
              CREATE TABLE review.reviews(id text primary key);
              CREATE TABLE review.outbox(review_id text primary key);
              CREATE TABLE review.batch_received(id text);
              CREATE TABLE review.cdc_source(id text);
              CREATE TABLE review.cdc_target(id text);
              CREATE TABLE review.cdc_seen(event_key text);
              CREATE TABLE points.backup_grants(id text);
              CREATE TABLE points.point_grants(id bigint generated by default as identity, review_id text, amount int);
              CREATE TABLE untouched.marker(value text);
              INSERT INTO review.reviews VALUES ('proof');
              INSERT INTO points.point_grants(review_id,amount) VALUES ('proof',100),('proof',100);
              INSERT INTO untouched.marker VALUES ('keep');"""
            docker("psql","-U","integration","-d","integration","-v","ON_ERROR_STOP=1","-c",ddl)
            with tempfile.TemporaryDirectory() as directory:
                reset=LabReset(directory,directory,lambda *e:None)
                original=reset.run
                def run_on_owned_db(args,**kwargs):
                    prefix=reset.base+["exec","-T","db"]
                    self.assertEqual(args[:len(prefix)],prefix)
                    return original(["docker","exec","-i",cid,*args[len(prefix):]],**kwargs)
                with patch.object(reset,"run",side_effect=run_on_owned_db):
                    backup=reset.backup()
                docker("psql","-U","integration","-d","integration","-v","ON_ERROR_STOP=1","-c",SQL)
                count="SELECT (SELECT count(*) FROM review.reviews),(SELECT count(*) FROM points.point_grants),(SELECT value FROM untouched.marker);"
                self.assertEqual(docker("psql","-U","integration","-d","integration","-Atc",count).stdout.strip(),b"0|0|keep")
                docker("pg_restore","-U","integration","-d","integration","--clean","--if-exists","--exit-on-error",input=backup.read_bytes())
                self.assertEqual(docker("psql","-U","integration","-d","integration","-Atc",count).stdout.strip(),b"1|2|keep")
        finally:
            subprocess.run(["docker","rm","-f",cid],check=True,capture_output=True)


if __name__=="__main__":
    unittest.main()
