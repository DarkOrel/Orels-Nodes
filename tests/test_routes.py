import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch
from aiohttp import web

class RouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        root = Path(__file__).resolve().parents[1]
        routes = web.RouteTableDef()
        server = types.SimpleNamespace(PromptServer=types.SimpleNamespace(instance=types.SimpleNamespace(routes=routes)))
        folders = types.SimpleNamespace(get_folder_paths=lambda category: ['/tmp/orels-route-models/'+category], get_user_directory=lambda:'/tmp/orels-user')
        spec = importlib.util.spec_from_file_location('orels_test_package',root/'__init__.py',submodule_search_locations=[str(root)])
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'server':server, 'folder_paths':folders, 'orels_test_package':self.module}):
            spec.loader.exec_module(self.module)
        self.routes = routes
    async def asyncTearDown(self):
        self.module.installer.pool.shutdown(wait=True)
    def request(self, value):
        async def read(): return value
        return types.SimpleNamespace(content_length=100, json=read)
    async def test_registered_routes(self):
        self.assertEqual({r.path for r in self.routes}, {
            '/orels-nodes/models/status','/orels-nodes/models/download','/orels-nodes/credentials',
            '/orels-nodes/models/batch','/orels-nodes/upload/init','/orels-nodes/upload/chunk',
            '/orels-nodes/upload/finish','/orels-nodes/upload/cancel','/orels-nodes/info'})
    async def test_status_and_download(self):
        data = dict(repo_id='owner/repo')
        with patch.object(self.module.installer, 'status', return_value={'status':'Missing'}) as call:
            result = await self.module.status(self.request(data))
            self.assertEqual(result.status,200)
            call.assert_called_with(data,False)
            await self.module.download(self.request(data))
            call.assert_called_with(data,True)
    async def test_validation(self):
        result = await self.module.status(self.request([]))
        self.assertEqual(result.status,400)
        self.assertEqual(json.loads(result.body)['status'],'Error')
    async def test_queue_never_downloads(self):
        with patch.object(self.module.installer, 'status', return_value={'path':'/tmp/a','status':'Missing','message':'Ready'}) as call:
            self.module.OrelsModelDownload().check(repo_id='owner/repo',filename='a.safetensors',category='vae')
            call.assert_called_once_with({'repo_id':'owner/repo','filename':'a.safetensors','category':'vae'})

    async def test_control_queue_has_no_effect(self):
        self.assertEqual(self.module.OrelsDownloadAll().control(), (False,))
        self.assertIn('download_control', self.module.OrelsModelDownload.INPUT_TYPES()['optional'])
        self.assertEqual(self.module.OrelsModelDownload.RETURN_TYPES, ())
        self.assertEqual(self.module.OrelsHFToken.RETURN_TYPES, ())

    async def test_batch_continues_after_error(self):
        models = [{'filename':'one'}, {'filename':'two'}]
        with patch.object(self.module.installer, 'status', side_effect=[{'status':'Error','message':'denied'}, {'status':'Installed'}]):
            self.module.batch_worker(models)
        self.assertEqual(self.module.batch_state['status'],'Error')
        self.assertIn('one: denied', self.module.batch_state['message'])

    async def test_batch_waits_then_completes(self):
        with patch.object(self.module.installer, 'status', side_effect=[{'status':'Downloading'}, {'status':'Installed'}]), patch.object(self.module.time, 'sleep'):
            self.module.batch_worker([{'filename':'one'}])
        self.assertEqual(self.module.batch_state['status'],'Installed')

    async def test_empty_batch_rejected(self):
        result = await self.module.batch_start(self.request({'models':[]}))
        self.assertEqual(result.status,400)

    async def test_brand_and_token_marker(self):
        self.assertEqual(set(self.module.NODE_CLASS_MAPPINGS), {
            'OrelsModelDownload', 'OrelsDownloadAll', 'OrelsHFToken', 'OrelsLoraUpload'})
        self.assertEqual(self.module.NODE_DISPLAY_NAME_MAPPINGS['OrelsModelDownload'], "Model's Download")
        self.assertEqual(self.module.OrelsHFToken().control(), ())
        fields = self.module.OrelsModelDownload.INPUT_TYPES()
        self.assertNotIn('hf_token_control', fields['optional'])
        self.assertNotIn('subfolder', fields['required'])
        self.assertNotIn('revision', fields['required'])
        for cls in self.module.NODE_CLASS_MAPPINGS.values():
            self.assertTrue(cls.CATEGORY.startswith("Orel's Nodes"))
