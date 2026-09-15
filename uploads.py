"""Small-request, atomic, no-overwrite safetensors uploads."""
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time

from .downloader import contained, relative

MAX_UPLOAD_BYTES = 8 * 1024**3
CHUNK_BYTES = 512 * 1024
MAX_HEADER_BYTES = 16 * 1024**2
SESSION_SECONDS = 24 * 60 * 60
DTYPE_BYTES = {
    'BOOL': 1, 'U8': 1, 'I8': 1, 'I16': 2, 'U16': 2, 'F16': 2,
    'BF16': 2, 'I32': 4, 'U32': 4, 'F32': 4, 'F64': 8, 'I64': 8,
    'U64': 8, 'F8_E4M3': 1, 'F8_E5M2': 1, 'F8_E8M0': 1,
    'F8_E4M3FN': 1,
}


def upload_name(name):
    relative(name)
    if ('/' in name or len(name.encode('utf-8')) > 200
            or not name.lower().endswith('.safetensors')):
        raise ValueError('Choose a .safetensors file with a simple filename (no folders; maximum 200 UTF-8 bytes).')
    return name


def validate_safetensors(path):
    size = path.stat().st_size
    with path.open('rb') as stream:
        header_size = int.from_bytes(stream.read(8), 'little')
        if not 2 <= header_size <= MAX_HEADER_BYTES or 8 + header_size >= size:
            raise ValueError('Invalid or empty safetensors file: header/size mismatch.')
        try:
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError('Duplicate safetensors header key.')
                    result[key] = value
                return result
            header = json.loads(stream.read(header_size), object_pairs_hook=unique)
        except (ValueError, UnicodeError):
            raise ValueError('Invalid safetensors JSON header.')
    if not isinstance(header, dict):
        raise ValueError('Invalid safetensors header.')
    ranges = []
    for name, tensor in header.items():
        if name == '__metadata__':
            if not isinstance(tensor, dict) or any(not isinstance(v, str) for v in tensor.values()):
                raise ValueError('Invalid safetensors metadata.')
            continue
        if not isinstance(tensor, dict):
            raise ValueError('Invalid tensor descriptor.')
        shape, offsets, dtype = tensor.get('shape'), tensor.get('data_offsets'), tensor.get('dtype')
        if not isinstance(dtype, str) or dtype not in DTYPE_BYTES:
            raise ValueError('Unsupported safetensors tensor dtype.')
        if not isinstance(shape, list) or any(type(x) is not int or x < 0 for x in shape):
            raise ValueError('Invalid tensor shape.')
        if not isinstance(offsets, list) or len(offsets) != 2 or any(type(x) is not int for x in offsets):
            raise ValueError('Invalid tensor offsets.')
        start, end = offsets
        if start < 0 or end < start or end - start != math.prod(shape) * DTYPE_BYTES[dtype]:
            raise ValueError('Tensor byte count does not match its shape.')
        ranges.append((start, end))
    end = 0
    for start, stop in sorted(ranges):
        if start != end:
            raise ValueError('Safetensors data contains a gap or overlapping tensors.')
        end = stop
    if not ranges or end != size - header_size - 8:
        raise ValueError('Safetensors data is incomplete or has unexpected trailing bytes.')


def digest_file(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def publish(temp, roots, name, digest):
    validate_safetensors(temp)
    paths = [contained(root, name) for root in roots]
    for target in paths:
        if target.exists():
            if (target.is_file() and target.stat().st_size == temp.stat().st_size
                    and digest_file(target) == digest):
                return {'status': 'Installed', 'message': 'Identical LoRA already exists; kept existing file.',
                        'path': str(target), 'filename': name}
            raise ValueError('A different file with this name already exists. Rename it and upload again.')
    try:
        os.link(temp, paths[0])
    except FileExistsError:
        raise ValueError('Another upload created this filename. Rename it and try again.')
    return {'status': 'Installed',
            'message': 'LoRA uploaded. Refresh model lists and select it in your LoRA loader.',
            'path': str(paths[0]), 'filename': name}


class UploadManager:
    def __init__(self):
        self.sessions = {}
        self.lock = threading.RLock()

    def _cleanup(self):
        cutoff = time.time() - SESSION_SECONDS
        for upload_id, session in list(self.sessions.items()):
            if session['updated'] < cutoff:
                session['temp'].unlink(missing_ok=True)
                del self.sessions[upload_id]

    def start(self, data, roots):
        if not isinstance(data, dict):
            raise ValueError('Invalid upload request.')
        name = upload_name(data.get('filename'))
        size = data.get('size')
        if type(size) is not int or not 1 <= size <= MAX_UPLOAD_BYTES:
            raise ValueError('LoRA must be between 1 byte and 8 GiB.')
        roots = [Path(root).resolve() for root in roots]
        if not roots:
            raise ValueError('No LoRA model folder is registered in ComfyUI.')
        for root in roots:
            contained(root, name)
        work = contained(roots[0], '.orels-uploads')
        work.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix='upload-', suffix='.partial', dir=work)
        os.close(fd)
        upload_id = secrets.token_urlsafe(32)
        with self.lock:
            self._cleanup()
            self.sessions[upload_id] = {
                'temp': Path(temp_name), 'name': name, 'size': size, 'received': 0,
                'roots': roots, 'digest': hashlib.sha256(), 'updated': time.time(),
            }
        return {'status': 'Ready', 'upload_id': upload_id, 'chunk_size': CHUNK_BYTES}

    async def append(self, request):
        upload_id = request.headers.get('X-Orels-Upload-ID', '')
        try:
            offset = int(request.headers.get('X-Orels-Upload-Offset', '-1'))
        except ValueError:
            raise ValueError('Invalid upload offset.')
        if request.content_length and request.content_length > CHUNK_BYTES:
            raise ValueError('Invalid upload chunk size.')
        data = await request.read()
        if not data or len(data) > CHUNK_BYTES:
            raise ValueError('Invalid upload chunk.')
        with self.lock:
            session = self.sessions.get(upload_id)
            if not session:
                raise ValueError('Upload session expired. Drop the file again.')
            if offset != session['received']:
                raise ValueError('Upload chunk arrived out of order. Drop the file again.')
            if session['received'] + len(data) > session['size']:
                raise ValueError('Upload contains more data than declared.')
            try:
                with session['temp'].open('ab') as stream:
                    stream.write(data)
                    stream.flush()
                session['digest'].update(data)
                session['received'] += len(data)
                session['updated'] = time.time()
                return {'status': 'Uploading', 'received': session['received'], 'size': session['size']}
            except Exception:
                session['temp'].unlink(missing_ok=True)
                del self.sessions[upload_id]
                raise

    def finish(self, data):
        upload_id = data.get('upload_id') if isinstance(data, dict) else None
        with self.lock:
            session = self.sessions.pop(upload_id, None)
        if not session:
            raise ValueError('Upload session expired. Drop the file again.')
        try:
            if session['received'] != session['size']:
                raise ValueError('Upload is incomplete. Drop the file again.')
            return publish(session['temp'], session['roots'], session['name'], session['digest'].hexdigest())
        finally:
            session['temp'].unlink(missing_ok=True)

    def cancel(self, data):
        upload_id = data.get('upload_id') if isinstance(data, dict) else None
        with self.lock:
            session = self.sessions.pop(upload_id, None)
        if session:
            session['temp'].unlink(missing_ok=True)
        return {'status': 'Cancelled'}


upload_manager = UploadManager()
