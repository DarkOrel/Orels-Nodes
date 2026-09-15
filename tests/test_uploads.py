import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest

root = Path(__file__).resolve().parents[1]
pkg = types.ModuleType('orel_upload_test')
pkg.__path__ = [str(root)]
sys.modules['orel_upload_test'] = pkg
spec = importlib.util.spec_from_file_location('orel_upload_test.uploads', root / 'uploads.py')
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)


def safetensors(payload=b'1234'):
    header = json.dumps({'lora_A.weight': {
        'dtype': 'U8', 'shape': [len(payload)], 'data_offsets': [0, len(payload)]
    }}).encode()
    return len(header).to_bytes(8, 'little') + header + payload


class Request:
    def __init__(self, upload_id, offset, data):
        self.headers = {
            'X-Orels-Upload-ID': upload_id,
            'X-Orels-Upload-Offset': str(offset),
        }
        self.content_length = len(data)
        self.data = data

    async def read(self):
        return self.data


class UploadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name).resolve()
        self.manager = u.UploadManager()

    async def asyncTearDown(self):
        for session in self.manager.sessions.values():
            session['temp'].unlink(missing_ok=True)
        self.tmp.cleanup()

    async def send(self, raw, name='test.safetensors', chunk_size=101):
        started = self.manager.start({'filename': name, 'size': len(raw)}, [self.folder])
        upload_id = started['upload_id']
        for offset in range(0, len(raw), chunk_size):
            result = await self.manager.append(Request(upload_id, offset, raw[offset:offset + chunk_size]))
            self.assertEqual(result['received'], min(offset + chunk_size, len(raw)))
        return self.manager.finish({'upload_id': upload_id})

    async def test_chunked_upload_and_identical_skip(self):
        raw = safetensors(b'x' * (u.CHUNK_BYTES * 2 + 99))
        result = await self.send(raw)
        self.assertEqual((self.folder / 'test.safetensors').read_bytes(), raw)
        result = await self.send(raw)
        self.assertIn('Identical', result['message'])
        self.assertEqual(list((self.folder / '.orels-uploads').glob('*.partial')), [])

    async def test_collision_never_overwrites(self):
        original = safetensors()
        await self.send(original)
        with self.assertRaises(ValueError):
            await self.send(safetensors(b'other'))
        self.assertEqual((self.folder / 'test.safetensors').read_bytes(), original)

    async def test_invalid_containers(self):
        for raw in [b'not a model', safetensors()[:-1], safetensors() + b'junk']:
            with self.assertRaises(ValueError):
                await self.send(raw)
            self.assertFalse((self.folder / 'test.safetensors').exists())

    async def test_names_and_size(self):
        for name in ['../evil.safetensors', '/evil.safetensors', 'a\\evil.safetensors', 'file.ckpt', '.hidden.safetensors']:
            with self.assertRaises(ValueError):
                u.upload_name(name)
        with self.assertRaises(ValueError):
            self.manager.start({'filename': 'x.safetensors', 'size': u.MAX_UPLOAD_BYTES + 1}, [self.folder])

    async def test_out_of_order_and_too_large_chunk(self):
        raw = safetensors()
        started = self.manager.start({'filename': 'x.safetensors', 'size': len(raw)}, [self.folder])
        with self.assertRaises(ValueError):
            await self.manager.append(Request(started['upload_id'], 1, raw))
        huge = Request(started['upload_id'], 0, b'x')
        huge.content_length = u.CHUNK_BYTES + 1
        with self.assertRaises(ValueError):
            await self.manager.append(huge)

    async def test_incomplete_finish_and_cancel_cleanup(self):
        raw = safetensors()
        started = self.manager.start({'filename': 'x.safetensors', 'size': len(raw)}, [self.folder])
        await self.manager.append(Request(started['upload_id'], 0, raw[:5]))
        with self.assertRaises(ValueError):
            self.manager.finish({'upload_id': started['upload_id']})
        self.assertEqual(list((self.folder / '.orels-uploads').glob('*.partial')), [])
        started = self.manager.start({'filename': 'x.safetensors', 'size': len(raw)}, [self.folder])
        self.manager.cancel({'upload_id': started['upload_id']})
        self.assertEqual(list((self.folder / '.orels-uploads').glob('*.partial')), [])

    async def test_extra_registered_root(self):
        extra = self.folder / 'extra'
        extra.mkdir()
        raw = safetensors()
        (extra / 'test.safetensors').write_bytes(raw)
        staged = self.folder / 'temp'
        staged.write_bytes(raw)
        result = u.publish(staged, [self.folder, extra], 'test.safetensors', hashlib.sha256(raw).hexdigest())
        self.assertEqual(result['path'], str(extra / 'test.safetensors'))

    async def test_symlink_and_shape_rejected(self):
        (self.folder / 'target').write_bytes(b'keep')
        (self.folder / 'test.safetensors').symlink_to(self.folder / 'target')
        with self.assertRaises(ValueError):
            await self.send(safetensors())
        self.assertEqual((self.folder / 'target').read_bytes(), b'keep')
        header = json.dumps({'x': {'dtype': 'F32', 'shape': [4], 'data_offsets': [0, 4]}}).encode()
        with self.assertRaises(ValueError):
            await self.send(len(header).to_bytes(8, 'little') + header + b'1234', 'shape.safetensors')

    async def test_expired_session_cleanup(self):
        raw = safetensors()
        started = self.manager.start({'filename': 'x.safetensors', 'size': len(raw)}, [self.folder])
        temp = self.manager.sessions[started['upload_id']]['temp']
        self.manager.sessions[started['upload_id']]['updated'] = 0
        self.manager.start({'filename': 'y.safetensors', 'size': len(raw)}, [self.folder])
        self.assertFalse(temp.exists())
        self.assertNotIn(started['upload_id'], self.manager.sessions)
