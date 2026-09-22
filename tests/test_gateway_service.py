import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('gateway_trace_service',Path(__file__).resolve().parents[1]/'scripts/gateway_trace_service.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class GatewayServiceTests(unittest.TestCase):
    def setUp(self):
        m.UNIT='example-memory.service';m.STATE='/example/state';m.PACKAGE=Path('/example/package')

    def test_preserves_options_and_exact_ember_scope(self):
        env={'OPENCLAW_STATE_DIR':m.STATE,'OPENCLAW_SYSTEMD_UNIT':m.UNIT,'NODE_OPTIONS':'--max-old-space-size=2048'}
        rendered=m.render(env,Path('/example/diagnostic/gateway-trace-preload.cjs'))
        self.assertIn('--max-old-space-size=2048',rendered)
        self.assertIn('EMBER_GATEWAY_TRACE=1',rendered)
        self.assertNotIn('ExecStart',rendered)
        self.assertNotIn('Restart=',rendered)
        env['OPENCLAW_SYSTEMD_UNIT']='other-gateway.service'
        with self.assertRaises(ValueError):m.render(env,Path('/tmp/probe'))

    def test_escaping_no_secret_copy_and_repeat_guard(self):
        env={'OPENCLAW_STATE_DIR':m.STATE,'OPENCLAW_SYSTEMD_UNIT':m.UNIT,'PRIVATE_TOKEN':'never-output'}
        self.assertNotIn('never-output',m.render(env,Path('/tmp/probe')))
        self.assertEqual(m.quote('a%"\\b'),'"a%%\\"\\\\b"')
        with self.assertRaises(ValueError):m.quote('a\nb')
        env['NODE_OPTIONS']='--require="/tmp/gateway-trace-preload.cjs"'
        with self.assertRaises(ValueError):m.render(env,Path('/tmp/probe'))

    def test_collector_excludes_arbitrary_payload_and_paths(self):
        spec=importlib.util.spec_from_file_location('collector',Path(__file__).resolve().parents[1]/'scripts/collect_gateway_trace.py')
        collector=importlib.util.module_from_spec(spec);spec.loader.exec_module(collector)
        import json
        projected=collector.project({'pid':5,'at_ms':1,'event':'end','phase':'query_embedding',
            'error_class':'http_429','message':'PRIVATE','query':'PRIVATE',
            'reason':'PRIVATE','frames':[{'file':'/home/PRIVATE/a.js','line':2,'samples':5,'text':'PRIVATE'}]})
        self.assertNotIn('PRIVATE',json.dumps(projected))
        self.assertEqual(projected['error_class'],'http_429')

    def test_stage_remove_hash_guard_and_never_restart(self):
        from unittest.mock import patch
        from contextlib import redirect_stdout
        import tempfile, hashlib, io, sys
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);package=root/'package';code=package/'dist/extensions/memory-core/manager-runtime.js'
            code.parent.mkdir(parents=True);code.write_text('V5 fixture')
            (package/'package.json').write_text('{"version":"2026.8.1"}')
            target=root/'unit.d'/m.NAME
            calls=[]
            def fake_run(*args):
                calls.append(args)
                return ('ActiveState=active\nEnvironmentFiles=\nEnvironment=OPENCLAW_STATE_DIR='+m.STATE+
                        ' OPENCLAW_SYSTEMD_UNIT='+m.UNIT+' NODE_OPTIONS=--max-old-space-size=2048\n') if args[0]=='show' else ''
            with patch.object(m,'PACKAGE',package),patch.object(m,'EXPECTED',hashlib.sha256(code.read_bytes()).hexdigest()),patch.object(m,'dropin_path',lambda:target),patch.object(m,'run',fake_run),redirect_stdout(io.StringIO()):
                with patch.object(sys,'argv',['helper','--check','--unit','example-memory.service','--state-dir','/example/state','--package-dir',str(package)]):m.main()
                self.assertFalse(target.exists())
                with patch.object(sys,'argv',['helper','--stage','--unit','example-memory.service','--state-dir','/example/state','--package-dir',str(package)]):m.main()
                data=target.read_bytes();self.assertIn(b'--max-old-space-size=2048',data)
                target.write_bytes(data+b'# later edit\n')
                with patch.object(sys,'argv',['helper','--remove','--unit','example-memory.service']):
                    with self.assertRaises(RuntimeError):m.main()
                self.assertTrue(target.exists());target.write_bytes(data)
                with patch.object(sys,'argv',['helper','--remove','--unit','example-memory.service']):m.main()
                self.assertFalse(target.exists())
                self.assertEqual(code.read_text(),'V5 fixture')
            self.assertTrue(all(c[0] in {'show','daemon-reload'} for c in calls))


if __name__=='__main__':unittest.main()
