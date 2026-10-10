"""Offline metadata tests: no hardware or optional SDK required."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch, Mock
from framecheck import board_backend as back, board_info as front
from framecheck.cli import main

class Target:
    def __init__(self, cpuid=0x411fc231, identity=0x10036414, size=512, states=("RUNNING", "RUNNING")):
        self.values={0xe000ed00:cpuid,0xe0042000:identity,0x1ffff7e0:size};self.states=iter(states);self.reads=[]
    def get_state(self): return NS(name=next(self.states))
    def read32(self,a): self.reads.append((a,32));return self.values[a]
    def read16(self,a): self.reads.append((a,16));return self.values[a]
    # Reset, halt, resume, block reads and writes deliberately do not exist.

def probe(uid="exact-id"): return NS(unique_id=uid,vendor_name="vendor",product_name="CMSIS-DAP")
def envelope(connect=False):
    return {"schema_version":1,
      "probe_inventory":{"status":"ok","provider":"pyocd","items":[],"truncated":False},
      "serial_inventory":{"status":"ok","provider":"pyserial","items":[],"truncated":False},
      "chip":{"status":"ok" if connect else "not_requested","target_connected":connect},
      "actions":{"target_connection_requested":connect,"serial_opened":False,"reset_requested":False,
                 "halt_requested":False,"firmware_read":False,"firmware_written":False,"unlock_requested":False}}

class BackendTests(unittest.TestCase):
    def read(self,target=None,profile="stm32f1-high-density",probes=None,uid="exact-id"):
        target=target or Target();calls=[]
        class Session:
            def __init__(self,chosen,**options):
                calls.append((chosen,options));self.target=target
                assert list(Path(options['project_dir']).iterdir())==[]
                os.chdir(options['project_dir'])  # Reproduce actual SDK cwd behavior.
            def __enter__(self):return self
            def __exit__(self,*args):return False
        result=back.read_chip([probe()] if probes is None else probes,Session,uid,profile)
        return result,target,calls
    def test_sdk_cwd_is_restored_before_temp_cleanup(self):
        previous = Path.cwd()
        result, _, calls = self.read()
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(Path.cwd(), previous)
        self.assertFalse(Path(calls[0][1]['project_dir']).exists())
    def test_constructor_failure_restores_cwd(self):
        previous = Path.cwd()
        def broken(probe, **options):
            os.chdir(options['project_dir'])
            raise RuntimeError('constructor failed after chdir')
        result = back.read_chip([probe()], broken, 'exact-id', 'cortex-m')
        self.assertEqual(result['status'], 'error')
        self.assertEqual(Path.cwd(), previous)
    def test_inventory_never_constructs_target_session(self):
        helper=Mock();helper.get_all_connected_probes.return_value=[probe()]
        session=Mock(side_effect=AssertionError("target session prohibited"))
        with patch.object(back,'_load_pyocd',return_value=(helper,session,'test')),patch.object(back,'_load_serial_ports',return_value=(lambda:[],'test')),patch.object(back,'read_chip',side_effect=AssertionError('no chip read')):
            data=back.collect()
        session.assert_not_called();helper.get_all_connected_probes.assert_called_once_with(blocking=False)
        self.assertEqual(data['chip']['status'],'not_requested');self.assertTrue(all(v is False for v in data['actions'].values()))
    def test_missing_sdk_is_not_empty_inventory(self):
        with patch.object(back,'_load_pyocd',side_effect=ImportError('missing')):result,probes,session=back.probe_inventory()
        self.assertEqual(result['status'],'unavailable');self.assertEqual(probes,[]);self.assertIsNone(session)
    def test_port_listing_uses_only_metadata(self):
        ports=[NS(device='COM14',description='UART',hwid='USB'),NS(device='COM9',description='DAP',hwid='USB2')]
        with patch.object(back,'_load_serial_ports',return_value=(lambda:ports,'test')):result=back.serial_inventory()
        self.assertEqual([p['port'] for p in result['items']],['COM14','COM9'])
    def test_enumeration_error_not_no_devices(self):
        with patch.object(back,'_load_serial_ports',side_effect=OSError('driver')):self.assertEqual(back.serial_inventory()['status'],'error')
    def test_attach_options_and_allowlisted_reads(self):
        result,target,calls=self.read();self.assertEqual(result['status'],'ok');self.assertEqual(result['flash_kib'],512);self.assertIsNone(result['exact_part_number'])
        self.assertEqual(target.reads,[(0xe000ed00,32),(0xe0042000,32),(0x1ffff7e0,16)])
        options=calls[0][1];self.assertEqual(options['target_override'],'cortex_m');self.assertEqual(options['connect_mode'],'attach')
        for key in ('auto_unlock','resume_on_disconnect'):self.assertIs(options[key],False)
        self.assertIs(options['no_config'],True);self.assertNotIn('pack',options);self.assertFalse(Path(options['project_dir']).exists())
        self.assertEqual(result['core_state_before'],result['core_state_after'])
    def test_generic_profile_does_not_read_vendor_registers(self):
        result,target,_=self.read(profile='cortex-m');self.assertEqual(result['status'],'ok');self.assertEqual(target.reads,[(0xe000ed00,32)]);self.assertNotIn('flash_kib',result)
    def test_exact_unique_id_required(self):
        for probes,uid in [([probe()],'exact'),([probe(),probe()],'exact-id'),([],'exact-id')]:
            with self.subTest(uid=uid,count=len(probes)):
                result,target,calls=self.read(probes=probes,uid=uid);self.assertEqual(result['status'],'error');self.assertFalse(calls);self.assertFalse(target.reads)
    def test_wrong_core_stops_vendor_reads(self):
        result,target,_=self.read(Target(cpuid=0x410fc241));self.assertEqual(result['status'],'unsupported');self.assertEqual(len(target.reads),1)
    def test_wrong_family_stops_capacity_read(self):
        result,target,_=self.read(Target(identity=0x410));self.assertEqual(result['status'],'unsupported');self.assertEqual(len(target.reads),2);self.assertNotIn('flash_kib',result)
    def test_invalid_capacity_remains_unknown(self):
        result,_,_=self.read(Target(size=65535));self.assertEqual(result['status'],'unsupported');self.assertNotIn('flash_kib',result)
    def test_core_state_change_errors_without_restore(self):
        result,_,_=self.read(Target(states=('RUNNING','HALTED')));self.assertEqual(result['status'],'error');self.assertIn('no corrective',result['error'])
    def test_connection_failure_no_retry_or_unlock(self):
        session=Mock(side_effect=RuntimeError('protected target'));result=back.read_chip([probe()],session,'exact-id','cortex-m')
        self.assertEqual(result['status'],'error');self.assertFalse(result['target_connected']);self.assertEqual(session.call_count,1);self.assertIs(session.call_args.kwargs['auto_unlock'],False)
    def test_invalid_request_never_enumerates(self):
        with patch.object(back,'probe_inventory',side_effect=AssertionError('no enumeration')),self.assertRaises(ValueError):back.collect(connect=True,probe_id='exact-id')

class FrontendTests(unittest.TestCase):
    def collect(self,data=None,**kwargs):
        with tempfile.TemporaryDirectory() as tmp,patch.object(front,'run_backend',return_value=(envelope() if data is None else data,'')):
            result=front.collect_board_info(tmp,**kwargs);self.assertEqual(result,json.loads((Path(tmp)/'board-info.json').read_text(encoding='utf-8')))
            return result,(Path(tmp)/'board-info.md').read_text(encoding='utf-8')
    def test_default_rules_stay_unknown(self):
        result,_=self.collect();self.assertEqual(result['status'],'ok');self.assertIsNone(result['protocol_rules']);self.assertIs(result['is_parser_validation'],False);self.assertIn('未发现下载器',' '.join(result['suggestions']))
    def test_missing_dependency_partial(self):
        data=envelope();data['probe_inventory'].update(status='unavailable',error='missing');result,_=self.collect(data)
        self.assertEqual(result['status'],'partial');self.assertNotIn('未发现下载器',' '.join(result['suggestions']))
    def test_truncated_inventory_partial(self):
        data=envelope();data['serial_inventory']['truncated']=True;result,_=self.collect(data);self.assertEqual(result['status'],'partial')
    def test_multiple_ports_no_auto_mapping(self):
        data=envelope();data['serial_inventory']['items']=[{'port':'COM9'},{'port':'COM14'}];result,_=self.collect(data)
        self.assertIn('不能仅凭端口号自动选择',' '.join(result['suggestions']));self.assertNotIn('selected_port',result)
    def test_invalid_parameters_never_start_backend(self):
        invalid=[dict(connect=True),dict(probe_id='id'),dict(profile='cortex-m'),dict(connect=True,probe_id=' ',profile='cortex-m'),dict(timeout=float('nan')),dict(timeout=61),dict(timeout=0)]
        with patch.object(front,'run_backend',side_effect=AssertionError('no backend')):
            for kwargs in invalid:
                with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):front.collect_board_info('unused',**kwargs)
    def test_malformed_response_and_unexpected_actions_fail_closed(self):
        values=[[],{'schema_version':9}]
        for field in ('actions','chip','probe_inventory','serial_inventory'):
            data=envelope();del data[field];values.append(data)
        for field,value in [('reset_requested',True),('halt_requested',0)]:
            data=envelope();data['actions'][field]=value;values.append(data)
        data=envelope();data['chip']['target_connected']=True;values.append(data)
        for data in values:
            with self.subTest(data=data):
                result,_=self.collect(data);self.assertEqual(result['status'],'error');self.assertIn('error',result)
    def test_timeout_is_saved_error(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(front,'run_backend',side_effect=subprocess.TimeoutExpired('backend',1)):
            result=front.collect_board_info(tmp);self.assertTrue((Path(tmp)/'board-info.md').exists())
        self.assertEqual(result['status'],'error');self.assertIn('TimeoutExpired',result['error'])
    def test_usb_metadata_cannot_create_html_or_markdown_links(self):
        data=envelope();data['probe_inventory']['items']=[{'unique_id':'<img src=x onerror=alert(1)>','vendor':'[click](https://x)','product':'a|b\nline'}]
        _,md=self.collect(data);self.assertNotIn('<img',md);self.assertNotIn('[click]',md);self.assertIn('&lt;img',md);self.assertIn('a\\|b line',md)
    def test_backend_isolated_empty_working_directory(self):
        def run(command,**kwargs):
            self.assertEqual(command[1:5],['-I','-B','-X','utf8']);self.assertEqual(list(Path(kwargs['cwd']).iterdir()),[]);self.assertNotIn('shell',kwargs);self.assertEqual(kwargs['timeout'],5)
            return NS(returncode=0,stdout=json.dumps(envelope()).encode(),stderr=b'')
        with patch.object(front.subprocess,'run',side_effect=run):data,_=front.run_backend(sys.executable,False,None,None,5)
        self.assertEqual(data['schema_version'],1)
    def test_backend_rejects_nonobject_json(self):
        with patch.object(front.subprocess,'run',return_value=NS(returncode=0,stdout=b'[]',stderr=b'')),self.assertRaisesRegex(RuntimeError,'must be an object'):front.run_backend(sys.executable,False,None,None,5)
    def test_backend_rejects_oversize_output(self):
        with patch.object(front.subprocess,'run',return_value=NS(returncode=0,stdout=b'x'*(512*1024+1),stderr=b'')),self.assertRaisesRegex(RuntimeError,'exceeded'):front.run_backend(sys.executable,False,None,None,5)
    def test_cli_status_and_partial_connect(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(front,'run_backend',return_value=(envelope(),'')),patch('sys.stdout',new_callable=io.StringIO):self.assertEqual(main(['board-info','--out',tmp]),0)
        data=envelope();data['probe_inventory']['status']='unavailable'
        with tempfile.TemporaryDirectory() as tmp,patch.object(front,'run_backend',return_value=(data,'')),patch('sys.stdout',new_callable=io.StringIO):self.assertEqual(main(['board-info','--out',tmp]),1)
        with patch.object(front,'run_backend',side_effect=AssertionError('no backend')),patch('sys.stderr',new_callable=io.StringIO):self.assertEqual(main(['board-info','--out','unused','--connect']),2)

if __name__=='__main__':unittest.main()
