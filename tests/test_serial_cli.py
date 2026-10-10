"""Portable serial CLI regressions; hardware calls are replaced or prohibited."""
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from framecheck import serial_runner as runner
from framecheck.cli import main

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT/'examples'/'serial'


class SerialCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile = json.loads((EXAMPLE/'profile.json').read_text(encoding='utf-8'))
        self.suite = json.loads((EXAMPLE/'suite.json').read_text(encoding='utf-8'))
        self.profile_path = self.root/'profile.json'
        self.suite_path = self.root/'suite.json'
        self.out = self.root/'out'
        self.save_inputs()

    def save_inputs(self):
        self.profile_path.write_text(json.dumps(self.profile), encoding='utf-8')
        self.suite_path.write_text(json.dumps(self.suite), encoding='utf-8')

    def args(self, *flags):
        return ['serial-run', '--profile', str(self.profile_path), '--suite', str(self.suite_path), '--out', str(self.out), *flags]

    def call(self, *flags):
        with patch('sys.stdout', new_callable=io.StringIO), patch('sys.stderr', new_callable=io.StringIO):
            return main(self.args(*flags))

    def test_binary_non_echo_example_passes_offline(self):
        with patch.object(runner, 'open_live', side_effect=AssertionError('no hardware')):
            self.assertEqual(self.call('--dry-run'), 0)
        report = json.loads((self.out/'report.json').read_text(encoding='utf-8'))
        self.assertFalse(report['is_board_validation'])
        self.assertEqual(report['verdict'], 'self_check_passed')
        self.assertEqual(report['counts']['pass'], 2)
        self.assertNotEqual(report['cases'][0]['transactions'][0]['chunks_hex'][0], report['cases'][0]['transactions'][0]['received_hex'])
        self.assertIn('runner_sha256', report['fingerprints'])

    def test_dry_run_in_fresh_process_prohibits_serial_import(self):
        code = '''import sys,builtins
sys.path.insert(0, sys.argv.pop(1))
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == 'serial' or name.startswith('serial.') or name == 'pyocd' or name.startswith('pyocd.'):
        raise AssertionError('optional hardware import prohibited')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from framecheck.cli import main
raise SystemExit(main(sys.argv[1:]))
'''
        result = subprocess.run([sys.executable, '-I', '-X', 'utf8', '-c', code, str(ROOT), *self.args('--dry-run')], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))

    def test_modes_must_be_explicit_and_exclusive(self):
        for flags in [(), ('--live', '--dry-run')]:
            with self.subTest(flags=flags), patch('sys.stderr', new_callable=io.StringIO), self.assertRaises(SystemExit) as caught:
                main(self.args(*flags))
            self.assertEqual(caught.exception.code, 2)

    def test_live_requires_explicit_port_and_dry_run_rejects_port(self):
        with patch.object(runner, 'open_live', side_effect=AssertionError('do not open')):
            self.assertEqual(self.call('--live'), 2)
            self.assertEqual(self.call('--live', '--port', ' '), 2)
            self.assertEqual(self.call('--dry-run', '--port', 'COM_TEST'), 2)

    def test_invalid_config_fails_before_open(self):
        self.profile['serial']['stopbits'] = True
        self.save_inputs()
        with patch.object(runner, 'open_live', side_effect=AssertionError('do not open')):
            self.assertEqual(self.call('--live', '--port', 'COM_TEST'), 2)

    def test_ready_override_cannot_make_empty_banner_succeed(self):
        self.assertEqual(self.profile['ready_policy'], 'skip')
        self.assertEqual(self.profile['ready_banner_hex'], '')
        with patch.object(runner, 'open_live', side_effect=AssertionError('do not open')):
            self.assertEqual(self.call('--live', '--port', 'COM_TEST', '--ready-policy', 'required'), 2)

    def test_existing_output_not_overwritten_or_opened(self):
        self.out.mkdir()
        marker = self.out/'report.json'
        marker.write_text('preserve earlier evidence', encoding='utf-8')
        with patch.object(runner, 'open_live', side_effect=AssertionError('do not open')):
            self.assertEqual(self.call('--live', '--port', 'COM_TEST'), 2)
        self.assertEqual(marker.read_text(encoding='utf-8'), 'preserve earlier evidence')

    def test_open_failure_records_all_cases_skipped(self):
        with patch.object(runner, 'open_live', side_effect=OSError('port busy')):
            self.assertEqual(self.call('--live', '--port', 'COM_TEST'), 1)
        report = json.loads((self.out/'report.json').read_text(encoding='utf-8'))
        self.assertFalse(report['is_board_validation'])
        self.assertEqual(report['counts'], {'pass': 0, 'fail': 0, 'error': 0, 'skipped': 2})
        self.assertEqual(report['verdict'], 'board_cases_not_passed')

    def test_close_error_cannot_report_overall_success(self):
        class BrokenClose(runner.MemoryTransport):
            def close(self):
                raise OSError('close failed')
        original = runner.memory_for_suite(self.profile, self.suite)
        fake = BrokenClose(original.steps)
        with patch.object(runner, 'open_live', return_value=fake):
            self.assertEqual(self.call('--live', '--port', 'COM_TEST'), 1)
        report = json.loads((self.out/'report.json').read_text(encoding='utf-8'))
        self.assertEqual(report['verdict'], 'board_cases_not_passed')
        self.assertIn('close_error', report)

    def test_input_json_size_limit_applies_before_open(self):
        self.profile_path.write_bytes(b' ' * (runner.MAX_INPUT_BYTES + 1))
        with patch.object(runner, 'open_live', side_effect=AssertionError('do not open')):
            self.assertEqual(self.call('--live', '--port', 'COM_TEST'), 2)

    def test_runtime_capacity_and_timing_limits_are_configuration_errors(self):
        for mutate in [lambda p,s: p.update(quiet_s=p['response_timeout_s']),
                       lambda p,s: p.update(response_timeout_s=float('nan')),
                       lambda p,s: s.update(cases=[{'id': str(i), 'transactions': s['cases'][0]['transactions']} for i in range(257)]),
                       lambda p,s: s['cases'][0].update(transactions=s['cases'][0]['transactions']*2049),
                       lambda p,s: s['cases'][0]['transactions'][0].update(expected_hex='00'*(runner.MAX_RESPONSE_BYTES+1))]:
            p,s = copy.deepcopy(self.profile),copy.deepcopy(self.suite)
            mutate(p,s)
            with self.subTest(mutate=mutate), self.assertRaises(runner.ConfigError):
                runner.validate_inputs(p,s)

    def test_report_metadata_is_inert_markdown(self):
        self.suite['cases'][0]['id'] = '<img src=x onerror=x>|[click](https://x)\nline'
        self.save_inputs()
        self.assertEqual(self.call('--dry-run'), 0)
        md = (self.out/'report.md').read_text(encoding='utf-8')
        self.assertNotIn('<img', md)
        self.assertNotIn('[click]', md)
        self.assertIn('&lt;img', md)

    def test_live_open_sets_control_lines_before_open_without_reset_hook(self):
        events = []
        class Serial:
            def __init__(self, **settings):
                events.append(('construct',settings))
            def open(self):
                events.append(('open',self.port,self.dtr,self.rts))
            def close(self):
                events.append(('close',))
        with patch.dict(sys.modules, {'serial':SimpleNamespace(Serial=Serial)}):
            transport = runner.open_live(self.profile,'COM_TEST')
            transport.close()
        self.assertEqual(events[0][1]['port'],None)
        self.assertEqual(events[1],('open','COM_TEST',False,False))
        self.assertEqual(events[2],('close',))


class OutputQueueTests(unittest.TestCase):
    def setUp(self):
        self.profile,self.suite,_=runner.load_inputs(EXAMPLE/'profile.json',EXAMPLE/'suite.json')
        self.profile.update(write_timeout_s=0.02,quiet_s=0.001,response_timeout_s=0.02,inter_chunk_s=0)
        self.silent={'chunks_hex':['ff'],'expected_hex':'','expect_silence_s':0.01}
        self.cases={'cases':[{'id':'silence','transactions':[self.silent]},{'id':'later','transactions':[self.silent]}]}

    def test_silence_starts_after_driver_queue_empty(self):
        class DelayedQueue(runner.MemoryTransport):
            @property
            def out_waiting(self):
                return 1 if self.clock.monotonic()<0.01 else 0
        fake=DelayedQueue([(b'\xff',b''),(b'\xff',b'')])
        report,code=runner.run_suite(fake,self.profile,self.cases,{},'dry-run')
        self.assertEqual(code,0)
        first=report['cases'][0]['transactions'][0]
        queue=next(e for e in first['events'] if e['kind']=='write_queue_empty')
        observed=next(e for e in first['events'] if e['kind']=='silence_observed')
        self.assertGreaterEqual(queue['elapsed_s'],0.01)
        self.assertGreaterEqual(observed['elapsed_s']-queue['elapsed_s'],0.01-1e-6)

    def test_stalled_queue_errors_and_skips_later_cases(self):
        class StalledQueue(runner.MemoryTransport):
            @property
            def out_waiting(self):return 1
        fake=StalledQueue([(b'\xff',b'')])
        report,code=runner.run_suite(fake,self.profile,self.cases,{},'dry-run')
        self.assertEqual(code,1)
        self.assertEqual(report['counts'],{'pass':0,'fail':0,'error':1,'skipped':1})
        self.assertIn('did not drain',report['cases'][0]['transactions'][0]['error'])
        self.assertEqual(len(fake.writes),1)
        self.assertLessEqual(fake.clock.monotonic(),0.021)

    def test_response_buffered_while_draining_is_not_discarded(self):
        class DelayedQueue(runner.MemoryTransport):
            @property
            def out_waiting(self):return 1 if self.clock.monotonic()<0.01 else 0
        tx={'chunks_hex':['ff'],'expected_hex':'12'}
        fake=DelayedQueue([(b'\xff',b'\x12')])
        report,code=runner.run_suite(fake,self.profile,{'cases':[{'id':'response','transactions':[tx]}]}, {},'dry-run')
        self.assertEqual(code,0)
        self.assertEqual(report['cases'][0]['transactions'][0]['received_hex'],'12')

    def test_partial_write_never_counts_as_silence(self):
        class ShortWrite(runner.MemoryTransport):
            def write(self,data):return 0
        report,code=runner.run_suite(ShortWrite([]),self.profile,self.cases,{},'dry-run')
        self.assertEqual(code,1)
        self.assertIn('incomplete write',report['cases'][0]['transactions'][0]['error'])
        self.assertEqual(report['counts']['skipped'],1)


if __name__=='__main__':unittest.main()
