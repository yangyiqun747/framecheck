"""Offline runner tests. No serial import, enumeration or open."""
import copy
from pathlib import Path
import sys
import unittest
from framecheck import serial_runner as runner
FIXTURES = Path(__file__).parent/"fixtures"/"serial"

class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.profile, self.suite, self.fingerprints = runner.load_inputs(FIXTURES/"profile.json", FIXTURES/"normal-suite.json")
        self.profile.update(ready_timeout_s=0.01, response_timeout_s=0.01, quiet_s=0.001, inter_chunk_s=0)
    def test_normal_three_cases_and_second_request_after_reply(self):
        fake = runner.memory_for_suite(self.profile, self.suite)
        report, code = runner.run_suite(fake, self.profile, self.suite, self.fingerprints, "dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(report["counts"], {"pass": 3, "fail": 0, "error": 0, "skipped": 0})
        self.assertFalse(report["is_board_validation"])
        self.assertEqual(report["verdict"], "self_check_passed")
        events = report["events"]
        second_at = next(i for i, event in enumerate(events) if event["kind"] == "write" and event["bytes_hex"] == "58595a0d0a")
        self.assertEqual(events[second_at-1]["kind"], "quiet_observed")
        preceding_reads = [event for event in events[:second_at] if event["kind"] == "read"]
        self.assertEqual(preceding_reads[-1]["bytes_hex"], "4142430d0a")
        self.assertNotIn("serial", sys.modules)
    def one_exchange(self, response):
        suite = {"cases": [self.suite["cases"][0], self.suite["cases"][2]]}
        fake = runner.MemoryTransport([(bytes.fromhex("4142430d0a"), response)], bytes.fromhex(self.profile["ready_banner_hex"]))
        return runner.run_suite(fake, self.profile, suite, self.fingerprints, "dry-run")
    def test_absent_response_is_error_and_stops(self):
        report, code = self.one_exchange(b"")
        self.assertEqual(code, 1)
        self.assertEqual(report["counts"], {"pass": 0, "fail": 0, "error": 1, "skipped": 1})
        self.assertTrue(any(e["kind"] == "response_timeout" for e in report["events"]))
    def test_wrong_response_is_fail_not_error(self):
        report, code = self.one_exchange(b"BAD\r\n")
        self.assertEqual(code, 1)
        self.assertEqual(report["counts"]["fail"], 1)
        self.assertEqual(report["counts"]["error"], 0)
        self.assertTrue(any(e["kind"] == "mismatch" for e in report["events"]))
    def test_required_ready_absent_stops_before_any_write(self):
        fake = runner.MemoryTransport([])
        report, code = runner.run_suite(fake, self.profile, self.suite, self.fingerprints, "dry-run")
        self.assertEqual(code, 1)
        self.assertEqual(report["ready"]["status"], "error")
        self.assertEqual(report["counts"]["skipped"], 3)
        self.assertEqual(fake.writes, [])
    def test_skip_ready_dry_run_has_no_leftover_banner(self):
        self.profile["ready_policy"] = "skip"
        fake = runner.memory_for_suite(self.profile, self.suite)
        report, code = runner.run_suite(fake, self.profile, self.suite, self.fingerprints, "dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(report["ready"]["status"], "skipped")
    def test_ready_read_io_error_is_reported(self):
        class BrokenRead(runner.MemoryTransport):
            def read(self, size):
                raise IOError("fake unplugged")
        report, code = runner.run_suite(BrokenRead([]), self.profile, self.suite, self.fingerprints, "dry-run")
        self.assertEqual(code, 1)
        self.assertEqual(report["ready"]["status"], "error")
        self.assertEqual(report["events"][0]["kind"], "ready_io_error")
    def test_ready_trailing_old_reply_cannot_satisfy_new_request(self):
        old = bytes.fromhex("4142430d0a")
        fake = runner.MemoryTransport([(old, b"")], bytes.fromhex(self.profile["ready_banner_hex"])+old)
        report, code = runner.run_suite(fake, self.profile, {"cases": [self.suite["cases"][0]]}, self.fingerprints, "dry-run")
        self.assertEqual(code, 1)
        tx = report["cases"][0]["transactions"][0]
        self.assertEqual(tx["status"], "fail")
        self.assertEqual(tx["preexisting_rx_hex"], old.hex())
        self.assertEqual(tx["received_hex"], "")
        self.assertEqual(fake.writes, [])
        self.assertEqual(len(fake.steps), 1)
    def test_unread_transport_old_bytes_stop_before_request(self):
        old = bytes.fromhex("4142430d0a")
        banner = bytes.fromhex(self.profile["ready_banner_hex"])
        class BannerOnlyFirstRead(runner.MemoryTransport):
            def read(self, size):
                return super().read(min(size, len(banner)) if not self.writes and bytes(self.buffer).startswith(banner) else size)
        fake = BannerOnlyFirstRead([(old, b"")], banner+old)
        report, code = runner.run_suite(fake, self.profile, {"cases": [self.suite["cases"][0]]}, self.fingerprints, "dry-run")
        self.assertEqual(code, 1)
        self.assertEqual(fake.writes, [])
        tx = report["cases"][0]["transactions"][0]
        self.assertEqual(tx["preexisting_rx_hex"], old.hex())
        self.assertEqual(tx["events"][0]["transport_hex"], old.hex())
    def test_late_equal_response_without_quiet_is_error(self):
        self.profile["quiet_s"] = 0.005
        old = bytes.fromhex("4142430d0a")
        class LateResponse(runner.MemoryTransport):
            def read(self, size):
                if self.writes and self.buffer:
                    self.clock.sleep(0.009)
                return super().read(size)
        fake = LateResponse([(old, old)], bytes.fromhex(self.profile["ready_banner_hex"]))
        report, code = runner.run_suite(fake, self.profile, {"cases": [self.suite["cases"][0]]}, self.fingerprints, "dry-run")
        self.assertEqual(code, 1)
        tx = report["cases"][0]["transactions"][0]
        self.assertEqual(tx["status"], "error")
        self.assertEqual(tx["received_hex"], old.hex())
        self.assertTrue(any(event["kind"] == "quiet_timeout" for event in tx["events"]))
        self.assertLessEqual(fake.clock.monotonic(), self.profile["response_timeout_s"])
    def test_project_quiet_duration_completes_without_float_stall(self):
        self.profile.update(quiet_s=0.1, response_timeout_s=2, inter_chunk_s=0.02)
        fake = runner.memory_for_suite(self.profile, self.suite)
        report, code = runner.run_suite(fake, self.profile, self.suite, self.fingerprints, "dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(report["counts"]["pass"], 3)
        self.assertLess(fake.clock.monotonic(), 1.0)
    def test_invalid_profile_is_configuration_error(self):
        with self.assertRaises(runner.ConfigError):
            runner.positive(True, "response_timeout_s")
        with self.assertRaises(runner.ConfigError):
            runner.hex_bytes("0G", "chunk")


class SilenceTests(unittest.TestCase):
    def setUp(self):
        self.profile,self.suite,self.fingerprints=runner.load_inputs(FIXTURES/'profile.json',FIXTURES/'normal-suite.json')
        self.profile.update(ready_timeout_s=0.01,response_timeout_s=0.02,quiet_s=0.001,inter_chunk_s=0)
        self.silent={'chunks_hex':['41410d0a'],'expected_hex':'','expect_silence_s':0.01}
    def run_tx(self,response,extra=False):
        steps=[(bytes.fromhex('41410d0a'),response)]
        transactions=[self.silent]
        if extra:
            steps.append((bytes.fromhex('474f4f440d0a'),bytes.fromhex('474f4f440d0a')))
            transactions.append({'chunks_hex':['474f4f440d0a'],'expected_hex':'474f4f440d0a'})
        fake=runner.MemoryTransport(steps,bytes.fromhex(self.profile['ready_banner_hex']))
        return fake,*runner.run_suite(fake,self.profile,{'cases':[{'id':'silence','transactions':transactions}]},self.fingerprints,'dry-run')
    def test_silence_observes_entire_window(self):
        fake,report,code=self.run_tx(b'')
        self.assertEqual(code,0)
        self.assertGreaterEqual(fake.clock.monotonic(),0.01)
        self.assertTrue(any(e['kind']=='silence_observed' for e in report['events']))
    def test_unexpected_empty_line_is_failure(self):
        fake,report,code=self.run_tx(bytes.fromhex('0d0a'))
        self.assertEqual(code,1)
        self.assertEqual(report['cases'][0]['transactions'][0]['received_hex'],'0d0a')
        self.assertEqual(report['counts']['fail'],1)
    def test_next_message_required_after_silence(self):
        fake,report,code=self.run_tx(b'',extra=True)
        self.assertEqual(code,0)
        self.assertEqual(len(fake.writes),2)
        self.assertEqual(report['cases'][0]['transactions'][1]['status'],'pass')
    def test_empty_expectation_needs_explicit_window(self):
        import tempfile,json
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'profile.json';s=Path(d)/'suite.json'
            p.write_text(json.dumps(self.profile),encoding='utf-8')
            s.write_text(json.dumps({'schema_version':1,'cases':[{'id':'bad','transactions':[{'chunks_hex':['41'],'expected_hex':''}]}]}),encoding='utf-8')
            with self.assertRaises(runner.ConfigError):runner.load_inputs(p,s)
            s.write_text(json.dumps({'schema_version':1,'cases':[{'id':'bad','transactions':[{'chunks_hex':['41'],'expected_hex':'41','expect_silence_s':0.01}]}]}),encoding='utf-8')
            with self.assertRaises(runner.ConfigError):runner.load_inputs(p,s)

if __name__ == "__main__":
    unittest.main()
