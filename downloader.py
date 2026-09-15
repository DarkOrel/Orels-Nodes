"""Single-file HF installer. No ComfyUI dependency in this module."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from filelock import FileLock
from huggingface_hub import hf_hub_download

CATEGORIES = ('diffusion_models', 'text_encoders', 'vae', 'loras', 'checkpoints', 'controlnet', 'clip_vision', 'upscale_models', 'embeddings')
DEFAULT_REPO = 'black-forest-labs/FLUX.2-klein-base-9b-fp8'
DEFAULT_FILE = 'flux-2-klein-base-9b-fp8.safetensors'

def relative(value, empty=False):
    if not isinstance(value, str) or len(value) > 512:
        raise ValueError('Paths must be text shorter than 513 characters.')
    if empty and not value:
        return ''
    p = PurePosixPath(value)
    if not value or p.is_absolute() or any(not x or x.startswith('.') for x in value.split('/')) or '\\' in value or ':' in value or any(ord(c) < 32 for c in value):
        raise ValueError('Use a relative path with / separators; absolute paths and .. are forbidden.')
    return value

def spec(data):
    repo = data.get('repo_id', '')
    if not isinstance(repo, str) or not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]*/[A-Za-z0-9_-][A-Za-z0-9_.-]*', repo) or '..' in repo:
        raise ValueError('repo_id must be owner/repository, not a URL.')
    category = data.get('category')
    if category not in CATEGORIES:
        raise ValueError('Choose a supported ComfyUI model category.')
    revision = data.get('revision', 'main')
    relative(revision)
    return dict(repo_id=repo, filename=relative(data.get('filename')), category=category,
                subfolder=relative(data.get('subfolder', ''), True), revision=revision)

def contained(root, rel):
    root = Path(root).resolve()
    p = root / rel
    if not p.resolve().is_relative_to(root):
        raise ValueError('Destination escapes the configured model folder (possibly through a symlink).')
    if p.is_symlink():
        raise ValueError('Destination must not be a symlink.')
    return p

def friendly(exc):
    code = getattr(getattr(exc, 'response', None), 'status_code', None)
    name = type(exc).__name__
    if code in (401, 403) or name == 'GatedRepoError':
        return 'Access denied. Accept the repository agreement on Hugging Face, use the Hugging Face token button, or set HF_TOKEN in the server environment and restart ComfyUI. The token needs read access to this repo.'
    if code == 404 or name in ('RepositoryNotFoundError', 'EntryNotFoundError', 'RemoteEntryNotFoundError', 'RevisionNotFoundError'):
        return 'Repository or filename not found, or private repo access is missing. Check exact spelling and HF_TOKEN permissions.'
    if name == 'Timeout':
        return 'Timed out waiting for another process to finish this model. Check the other ComfyUI process and retry.'
    if isinstance(exc, OSError):
        if exc.errno in (18, 38, 95):
            return 'This model volume does not support atomic hard-link installation. Use a Linux filesystem with hard-link support.'
        if exc.errno == 28:
            return 'Disk full. Free space on the model volume and retry; partial data is retained.'
        if exc.errno in (13, 30):
            return 'Model folder is not writable. Fix volume permissions or its read-only mount.'
    if isinstance(exc, ValueError):
        return str(exc)
    return f'Download failed ({name}). Check network access, free disk space and HF_TOKEN; retry to resume. Server error details are intentionally hidden to protect credentials.'

class Installer:
    def __init__(self, roots, token_provider=None):
        self.roots = roots
        self.token_provider = token_provider or (lambda: os.environ.get("HF_TOKEN") or False)
        self.jobs = {}
        self.guard = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='orels-download')

    def paths(self, s):
        roots = [Path(x).resolve() for x in self.roots(s['category'])]
        if not roots:
            raise ValueError('No model folders are registered for this category.')
        rel = '/'.join(filter(None, (s['subfolder'], PurePosixPath(s['filename']).name)))
        candidates = [contained(root, rel) for root in roots]
        # Reuse models on any configured path. New files use the first path.
        target = next((p for p in candidates if p.exists()), candidates[0])
        return target, roots[candidates.index(target)]

    def inspect(self, s):
        target, _ = self.paths(s)
        if target.exists():
            if not target.is_file() or target.stat().st_size == 0:
                raise ValueError('Destination exists but is empty or not a file. Move it aside manually and retry.')
            receipt = target.with_name(target.name + '.orels.json')
            if receipt.exists():
                try:
                    saved = json.loads(receipt.read_text())
                except (ValueError, OSError):
                    raise ValueError('Invalid installation receipt. Inspect the model and its .orels.json file.')
                if not isinstance(saved, dict) or saved.get('source') != s or saved.get('size') != target.stat().st_size:
                    raise ValueError('Existing file belongs to another source or its size changed. Rename the requested file; existing files are never overwritten.')
            return dict(status='Installed', message='Existing file retained.' if not receipt.exists() else 'Download complete.', path=str(target))
        return dict(status='Missing', message='Ready to download.', path=str(target))

    def status(self, data, start=False):
        s = spec(data)
        target, _ = self.paths(s)
        key = str(target)
        with self.guard:
            job = self.jobs.get(key)
            if job and job['status'] == 'Downloading':
                if job['source'] != s:
                    raise ValueError('Another source is downloading to this filename. Use a different local filename.')
                return {k:v for k,v in job.items() if k != 'source'}
            current = self.inspect(s)
            if current['status'] == 'Installed':
                return current
            if not start:
                return {k:v for k,v in job.items() if k != 'source'} if job and job['source'] == s else current
            if sum(j['status'] == 'Downloading' for j in self.jobs.values()) >= 2:
                raise ValueError('Two downloads are already running. Wait for one to finish and retry.')
            self.jobs[key] = dict(status='Downloading', message='Downloading / waiting for file lock…', path=key, source=s)
            self.pool.submit(self.worker, s, key)
            return {k:v for k,v in self.jobs[key].items() if k != 'source'}

    def worker(self, s, key):
        try:
            target, root = self.paths(s)
            ident = hashlib.sha256(str(target).encode()).hexdigest()
            work = contained(root, '.orels-downloads/' + ident)
            work.mkdir(parents=True, exist_ok=True)
            with FileLock(str(work / 'install.lock'), timeout=3600):
                result = self.inspect(s)
                if result['status'] != 'Installed':
                    source_id = hashlib.sha256(json.dumps(s, sort_keys=True).encode()).hexdigest()
                    stage = contained(work, source_id)
                    stage.mkdir(exist_ok=True)
                    downloaded = Path(hf_hub_download(repo_id=s['repo_id'], filename=s['filename'], revision=s['revision'],
                        token=self.token_provider(), endpoint='https://huggingface.co', local_dir=str(stage)))
                    if not downloaded.resolve().is_relative_to(stage.resolve()) or downloaded.stat().st_size <= 0:
                        raise ValueError('Download returned an invalid or empty file.')
                    target, _ = self.paths(s)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    # Hard-link publication is atomic, same-volume, and cannot overwrite.
                    os.link(downloaded, target)
                    receipt = target.with_name(target.name + '.orels.json')
                    tmp = work / 'receipt.tmp'
                    tmp.write_text(json.dumps(dict(source=s, size=target.stat().st_size), indent=2))
                    os.replace(tmp, receipt)
                    downloaded.unlink()
                    result = self.inspect(s)
        except Exception as exc:
            result = dict(status='Error', message=friendly(exc), path=key)
        with self.guard:
            self.jobs[key] = dict(**result, source=s)
