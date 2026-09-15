import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
spec = importlib.util.spec_from_file_location('credentials', Path(__file__).resolve().parents[1]/'credentials.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.c = m.Credentials(lambda: self.tmp.name)
    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()
    def test_session(self):
        result = self.c.save('hf_example_secret')
        self.assertEqual(result['source'], 'session')
        self.assertEqual(self.c.token(),'hf_example_secret')
        self.assertFalse(self.c.path().exists())
        self.assertNotIn('hf_example_secret',str(result))
    def test_remember_restart_permissions_clear(self):
        self.c.save('hf_example_secret',True)
        self.assertEqual(self.c.path().stat().st_mode & 0o777,0o600)
        other = m.Credentials(lambda:self.tmp.name)
        self.assertEqual(other.token(),'hf_example_secret')
        other.clear()
        self.assertFalse(other.token())
    def test_session_removes_saved(self):
        self.c.save('hf_old_secret',True)
        self.c.save('hf_new_secret',False)
        self.assertFalse(self.c.path().exists())
        self.assertEqual(self.c.token(),'hf_new_secret')
    def test_environment_precedence(self):
        with patch.dict(os.environ,{'HF_TOKEN':'hf_environment_secret'}):
            self.assertEqual(self.c.token(),'hf_environment_secret')
            with self.assertRaises(ValueError):
                self.c.save('hf_other_secret')
            self.assertEqual(self.c.clear()['source'],'environment')
    def test_invalid(self):
        for token in [None, {}, 'bad', 'hf_a b c secret']:
            with self.assertRaises(ValueError): self.c.save(token)
