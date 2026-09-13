import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from extension_actions import literal,decode,validated_file,slot_name
from guide_steps import STEPS

class ExtensionTest(unittest.TestCase):
    def test_scope_and_sql_values_are_guarded(self):
        for text in ("x'; DROP TABLE reviews;--","", "bad\\value"):
            with self.assertRaises(ValueError): literal(text)
        self.assertEqual(literal("pair-123-%"),"'pair-123-%'")
        self.assertEqual(slot_name("one"),slot_name("one"))
        self.assertNotEqual(slot_name("one"),slot_name("two"))
    def test_cdc_reads_only_own_source_and_keeps_delete(self):
        changes=[{"lsn":"0/100","data":"table review.cdc_source: INSERT: id[character varying]:'pair-own-a' status[text]:'CREATED'"},
                 {"lsn":"0/101","data":"table review.cdc_source: DELETE: id[character varying]:'pair-own-a'"},
                 {"lsn":"0/102","data":"table review.cdc_source: INSERT: id[character varying]:'other-a' status[text]:'CREATED'"},
                 {"lsn":"0/103","data":"table review.cdc_target: UPDATE: id[character varying]:'pair-own-a' status[text]:'SHIPPED'"}]
        decoded=decode(changes,"pair-own")
        self.assertEqual([d["op"] for d in decoded],["INSERT","DELETE"])
        self.assertIsNone(decoded[-1]["status"])
        self.assertNotEqual(decoded[0]["key"],decoded[1]["key"])
    def test_file_corruption_or_cross_session_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/"batch.jsonl"
            data=(json.dumps({"id":"pair-1-batch-0","content":"batch review"})+"\n").encode()
            p.write_bytes(data)
            manifest={"count":1,"sha256":hashlib.sha256(data).hexdigest()}
            self.assertEqual(len(validated_file(p,manifest,"pair-1")),1)
            with self.assertRaisesRegex(ValueError,"다른 세션"): validated_file(p,manifest,"pair-2")
            p.write_bytes(data+b" ")
            with self.assertRaisesRegex(ValueError,"SHA-256"): validated_file(p,manifest,"pair-1")
    def test_all_added_steps_have_teaching_and_codes(self):
        self.assertEqual(len(STEPS),31)
        for s in STEPS:
            if not s.get("extensionView"): continue
            for key in ("definition","example","expected","why","caution","codeBefore","codeAfter"):
                self.assertTrue(s[key],(s["id"],key))
