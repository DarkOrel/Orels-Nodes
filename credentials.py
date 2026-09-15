"""Server-only credentials. Never return a token to the browser."""
import os
from pathlib import Path
import tempfile
import threading

class Credentials:
    def __init__(self, directory):
        self.directory = directory
        self.session = None
        self.lock = threading.RLock()

    def path(self):
        return Path(self.directory()) / 'hf_token'

    def token(self):
        with self.lock:
            if os.environ.get('HF_TOKEN'):
                return os.environ['HF_TOKEN']
            if self.session:
                return self.session
            try:
                return self.path().read_text().strip() or False
            except FileNotFoundError:
                return False

    def status(self):
        with self.lock:
            source = 'environment' if os.environ.get('HF_TOKEN') else 'session' if self.session else 'saved on server' if self.path().is_file() else 'not configured'
            return {'configured': source != 'not configured', 'source': source}

    def save(self, token, remember=False):
        if not isinstance(token, str) or not token.startswith('hf_') or not 10 <= len(token) <= 512 or any(c.isspace() for c in token):
            raise ValueError('Enter a valid Hugging Face access token beginning with hf_.')
        with self.lock:
            if os.environ.get('HF_TOKEN'):
                raise ValueError('HF_TOKEN is already configured in the server environment. Change it there and restart, or remove it before using this dialog.')
            path = self.path()
            if remember:
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.token-')
                try:
                    with os.fdopen(fd, 'w') as stream:
                        stream.write(token)
                    os.replace(tmp, path)
                finally:
                    if os.path.exists(tmp):
                        os.unlink(tmp)
                self.session = None
            else:
                # Session-only must not leave a previously saved credential behind.
                path.unlink(missing_ok=True)
                self.session = token
            return self.status()

    def clear(self):
        with self.lock:
            self.path().unlink(missing_ok=True)
            self.session = None
            return self.status()
