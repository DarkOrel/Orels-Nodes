import asyncio
import threading
import time
from pathlib import Path
from aiohttp import web
import folder_paths
from server import PromptServer
from .downloader import Installer, CATEGORIES, DEFAULT_REPO, DEFAULT_FILE, friendly, spec

from .credentials import Credentials

credentials = Credentials(lambda: Path(folder_paths.get_user_directory()) / 'orels-nodes')
installer = Installer(folder_paths.get_folder_paths, credentials.token)

@PromptServer.instance.routes.get('/orels-nodes/credentials')
async def credential_status(request):
    try:
        return web.json_response(credentials.status(), headers={'Cache-Control': 'no-store'})
    except Exception:
        return web.json_response({'message': 'Cannot read server credential settings.'}, status=400)

@PromptServer.instance.routes.post('/orels-nodes/credentials')
async def credential_save(request):
    try:
        if request.content_type != 'application/json' or (request.content_length and request.content_length > 2048):
            raise ValueError('Expected a small JSON request.')
        data = await request.json()
        if not isinstance(data, dict):
            raise ValueError('Expected credential settings.')
        if data.get('action') == 'clear':
            result = credentials.clear()
        else:
            if not isinstance(data.get('remember', False), bool):
                raise ValueError('Remember must be true or false.')
            result = credentials.save(data.get('token'), data.get('remember', False))
        return web.json_response(result, headers={'Cache-Control': 'no-store'})
    except ValueError as exc:
        return web.json_response({'message': str(exc)}, status=400)
    except Exception:
        return web.json_response({'message': 'Could not update token. Check server user-folder permissions.'}, status=400)


class OrelsModelDownload:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {
            'repo_id': ('STRING', {'default': DEFAULT_REPO}),
            'filename': ('STRING', {'default': DEFAULT_FILE}),
            'category': (list(CATEGORIES),),
        }, 'optional': {'download_control': ('ORELS_DOWNLOAD_CONTROL',)}}
    RETURN_TYPES = ()
    FUNCTION = 'check'
    CATEGORY = "Orel's Nodes / Models"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float('nan')

    def check(self, download_control=None, **kwargs):
        installer.status(kwargs)
        return ()

async def handle(request, start=False):
    try:
        if request.content_length and request.content_length > 8192:
            raise ValueError('Request is too large.')
        data = await request.json()
        if not isinstance(data, dict):
            raise ValueError('Expected a model configuration object.')
        result = await asyncio.to_thread(installer.status, data, start)
        return web.json_response(result)
    except Exception as exc:
        return web.json_response({'status': 'Error', 'message': friendly(exc)}, status=400)

@PromptServer.instance.routes.post('/orels-nodes/models/status')
async def status(request):
    return await handle(request)

@PromptServer.instance.routes.post('/orels-nodes/models/download')
async def download(request):
    return await handle(request, True)

class OrelsDownloadAll:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {}}
    RETURN_TYPES = ('ORELS_DOWNLOAD_CONTROL',)
    RETURN_NAMES = ('download_models',)
    FUNCTION = 'control'
    CATEGORY = "Orel's Nodes / Models"
    def control(self):
        # Wires select targets for the button; queue execution has no side effects.
        return (False,)

batch_lock = threading.RLock()
batch_state = {'status': 'Idle', 'message': 'Connect model nodes, then click Download All.'}

def batch_worker(models):
    errors = []
    for index, model in enumerate(models):
        with batch_lock:
            batch_state.update(status='Downloading', message=f'Model {index + 1}/{len(models)}: {model["filename"]}')
        try:
            while True:
                with installer.guard:
                    if sum(j['status'] == 'Downloading' for j in installer.jobs.values()) < 2:
                        result = installer.status(model, True)
                        break
                time.sleep(1)
            while result['status'] == 'Downloading':
                time.sleep(1)
                result = installer.status(model)
            if result['status'] != 'Installed':
                errors.append(f'{model["filename"]}: {result["message"]}')
        except Exception as exc:
            errors.append(f'{model["filename"]}: {friendly(exc)}')
    with batch_lock:
        batch_state.update(status='Error' if errors else 'Installed', message='; '.join(errors) if errors else f'All {len(models)} models installed.')

@PromptServer.instance.routes.post('/orels-nodes/models/batch')
async def batch_start(request):
    try:
        if request.content_length and request.content_length > 131072:
            raise ValueError('Batch request too large.')
        data = await request.json()
        if not isinstance(data, dict) or not isinstance(data.get('models'), list) or not 1 <= len(data['models']) <= 64:
            raise ValueError('Connect between 1 and 64 model download nodes.')
        models = [spec(m) for m in data['models']]
        # Validate every destination before starting any download.
        for model in models:
            installer.paths(model)
        with batch_lock:
            if batch_state['status'] == 'Downloading':
                raise ValueError('A Download All batch is already running on this server.')
            batch_state.update(status='Downloading', message=f'Starting {len(models)} models…')
            threading.Thread(target=batch_worker, args=(models,), daemon=True).start()
            return web.json_response(dict(batch_state))
    except Exception as exc:
        return web.json_response({'status':'Error', 'message':friendly(exc)}, status=400)

@PromptServer.instance.routes.get('/orels-nodes/models/batch')
async def batch_status(request):
    with batch_lock:
        return web.json_response(dict(batch_state))

class OrelsHFToken:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {}}
    RETURN_TYPES = ()
    FUNCTION = 'control'
    CATEGORY = "Orel's Nodes / Models"
    def control(self):
        return ()

class OrelsLoraUpload:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {}}
    RETURN_TYPES = ()
    FUNCTION = 'check'
    CATEGORY = "Orel's Nodes / Models"
    OUTPUT_NODE = True
    def check(self):
        return ()

@PromptServer.instance.routes.post('/orels-nodes/upload/init')
async def upload_init(request):
    from .uploads import upload_manager
    try:
        data = await request.json()
        result = upload_manager.start(data, folder_paths.get_folder_paths('loras'))
        return web.json_response(result)
    except Exception as exc:
        message = friendly(exc)
        if not isinstance(exc, ValueError):
            message = message.replace('Download failed', 'Upload failed').replace('partial data is retained', 'retry the upload')
        return web.json_response({'status':'Error','message':message},status=400)

@PromptServer.instance.routes.post('/orels-nodes/upload/chunk')
async def upload_chunk(request):
    from .uploads import upload_manager
    try:
        result = await upload_manager.append(request)
        return web.json_response(result)
    except Exception as exc:
        return web.json_response({'status':'Error','message':friendly(exc)},status=400)

@PromptServer.instance.routes.post('/orels-nodes/upload/finish')
async def upload_finish(request):
    from .uploads import upload_manager
    try:
        result = await asyncio.to_thread(upload_manager.finish, await request.json())
        return web.json_response(result)
    except Exception as exc:
        return web.json_response({'status':'Error','message':friendly(exc)},status=400)

@PromptServer.instance.routes.post('/orels-nodes/upload/cancel')
async def upload_cancel(request):
    from .uploads import upload_manager
    try:
        return web.json_response(upload_manager.cancel(await request.json()))
    except Exception as exc:
        return web.json_response({'status':'Error','message':friendly(exc)},status=400)

@PromptServer.instance.routes.get('/orels-nodes/info')
async def package_info(request):
    return web.json_response({'version':'0.5.0', 'lora_paths':folder_paths.get_folder_paths('loras')})

NODE_CLASS_MAPPINGS = {
    'OrelsModelDownload': OrelsModelDownload,
    'OrelsDownloadAll': OrelsDownloadAll,
    'OrelsHFToken': OrelsHFToken,
    'OrelsLoraUpload': OrelsLoraUpload,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    'OrelsModelDownload': "Model's Download",
    'OrelsDownloadAll': 'Download All',
    'OrelsHFToken': 'Hugging Face Token',
    'OrelsLoraUpload': 'LoRA Upload',
}
WEB_DIRECTORY = './web'
