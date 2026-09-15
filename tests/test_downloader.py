import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

location = Path(__file__).resolve().parents[1] / 'downloader.py'
module_spec = importlib.util.spec_from_file_location('orels_downloader', location)
m = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(m)

class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.inst = m.Installer(lambda category: [self.root / category])
        self.s = m.spec(dict(repo_id='owner/model', filename='split/model.safetensors', category='diffusion_models', subfolder='nested'))
    def tearDown(self):
        self.inst.pool.shutdown(wait=True)
        self.tmp.cleanup()
    def fake(self, **kw):
        p = Path(kw['local_dir']) / kw['filename']
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b'model weights')
        return str(p)
    def run_download(self):
        with patch.object(m, 'hf_hub_download', side_effect=self.fake) as call:
            self.inst.status(self.s, True)
            self.inst.pool.shutdown(wait=True)
            self.assertEqual(self.inst.status(self.s)['status'], 'Installed')
            return call
    def test_atomic_install_and_repeat(self):
        call = self.run_download()
        self.assertEqual(call.call_count, 1)
        with patch.object(m, 'hf_hub_download') as again:
            self.assertEqual(self.inst.status(self.s, True)['status'], 'Installed')
            again.assert_not_called()
        p, _ = self.inst.paths(self.s)
        self.assertEqual(p, self.root / 'diffusion_models/nested/model.safetensors')
        self.assertEqual(p.read_bytes(), b'model weights')
    def test_existing_offline_and_extra_path(self):
        alt = self.root / 'extra'
        p = alt / 'nested/model.safetensors'
        p.parent.mkdir(parents=True)
        p.write_bytes(b'existing')
        self.inst.roots = lambda c: [self.root/c, alt]
        with patch.object(m, 'hf_hub_download') as call:
            self.assertEqual(self.inst.status(self.s, True)['path'], str(p))
            call.assert_not_called()
    def test_traversal_and_category(self):
        for field, value in [('filename','../x'),('subfolder','/tmp'),('subfolder','x/../../x'),('filename','C:\\x'),('category','../x'),('repo_id','https://evil.test/model'),('revision','../x')]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                m.spec(dict(self.s, **{field:value}))
    def test_symlink_escape(self):
        root = self.root / 'diffusion_models'
        root.mkdir()
        (root / 'nested').symlink_to(self.root)
        with self.assertRaises(ValueError):
            self.inst.status(self.s)
    def test_collision(self):
        self.run_download()
        with self.assertRaisesRegex(ValueError, 'another source'):
            self.inst.status(dict(self.s, repo_id='other/model'))
    def test_truncated_file(self):
        self.run_download()
        p, _ = self.inst.paths(self.s)
        p.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'size changed'):
            self.inst.status(self.s)
    def test_zero_file(self):
        p, _ = self.inst.paths(self.s)
        p.parent.mkdir(parents=True)
        p.touch()
        with self.assertRaisesRegex(ValueError, 'empty'):
            self.inst.status(self.s, True)
    def test_failure_and_resume(self):
        def fail(**kw):
            p = Path(kw['local_dir']) / 'partial.incomplete'
            p.write_bytes(b'partial')
            raise OSError(28, 'disk full secret hf_12345')
        with patch.object(m, 'hf_hub_download', side_effect=fail):
            self.inst.status(self.s, True)
            self.inst.pool.shutdown(wait=True)
        self.assertEqual(self.inst.status(self.s)['status'], 'Error')
        self.assertIn('Disk full', self.inst.status(self.s)['message'])
        self.assertFalse(self.inst.paths(self.s)[0].exists())
        self.assertTrue(list(self.root.rglob('partial.incomplete')))
        self.inst = m.Installer(lambda c: [self.root/c])
        self.run_download()
    def test_concurrent_duplicate(self):
        entered, release = threading.Event(), threading.Event()
        def delayed(**kw):
            entered.set()
            release.wait(5)
            return self.fake(**kw)
        with patch.object(m, 'hf_hub_download', side_effect=delayed) as call:
            self.inst.status(self.s, True)
            self.assertTrue(entered.wait(5))
            try:
                self.assertEqual(self.inst.status(self.s, True)['status'], 'Downloading')
                with self.assertRaisesRegex(ValueError, 'Another source'):
                    self.inst.status(dict(self.s, repo_id='other/model'), True)
                self.assertFalse(self.inst.paths(self.s)[0].exists())
            finally:
                release.set()
            self.inst.pool.shutdown(wait=True)
            self.assertEqual(call.call_count, 1)
    def test_env_token_and_endpoint(self):
        with patch.dict(m.os.environ, {'HF_TOKEN':'hf_test_secret'}):
            call = self.run_download()
        self.assertEqual(call.call_args.kwargs['token'], 'hf_test_secret')
        self.assertEqual(call.call_args.kwargs['endpoint'], 'https://huggingface.co')
        self.assertNotIn('hf_test_secret', json.dumps(self.inst.status(self.s)))
    def test_error_redaction(self):
        self.assertNotIn('hf_secret', m.friendly(RuntimeError('hf_secret')))
        exc = RuntimeError('hf_secret')
        exc.response = type('Response', (), {'status_code':403})()
        self.assertIn('Accept the repository agreement', m.friendly(exc))
    def test_external_race_no_overwrite(self):
        def race(**kw):
            result = self.fake(**kw)
            target, _ = self.inst.paths(self.s)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'other writer')
            return result
        with patch.object(m, 'hf_hub_download', side_effect=race):
            self.inst.status(self.s, True)
            self.inst.pool.shutdown(wait=True)
        self.assertEqual(self.inst.paths(self.s)[0].read_bytes(), b'other writer')

if __name__ == '__main__':
    unittest.main()
