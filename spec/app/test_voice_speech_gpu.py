"""Fail-closed GPU policy tests; real kernels are checked by the live roundtrip."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import yaml

SOURCE = yaml.safe_load((Path(__file__).parents[2] / 'data/kubernetes/app/voice-speech.yaml').read_text())
SERVER = SOURCE['resources']['app']['data']['server.py']


def functions(*names, **namespace):
    tree = ast.parse(SERVER)
    nodes: list[ast.stmt] = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    for node in nodes:
        if isinstance(node, ast.FunctionDef):
            node.decorator_list = []
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'server.py', 'exec'), namespace)
    return namespace


class GpuPolicyTest(unittest.TestCase):
    def test_cpu_tensor_is_refused_at_inference_boundary(self):
        class Tensor:
            def __init__(self, device):
                self.device = device
        ns = functions('tensor_devices', 'check_tensors', torch=SimpleNamespace(Tensor=Tensor))
        self.assertIn('check_tensors', ns, 'Missing runtime tensor placement guard')
        with self.assertRaisesRegex(RuntimeError, 'GPU'):
            ns['check_tensors']('encoder', (Tensor('cpu'),))
        self.assertEqual(ns['check_tensors']('encoder', (Tensor('cuda:0'),)), ['cuda:0'])

    def test_kokoro_explicitly_requires_gpu(self):
        factory = Mock(return_value=object())
        ns = functions('get_tts_pipeline', voice_lang_code=lambda _: 'a', tts_pipelines={},
                       require_gpu=Mock(), KPipeline=factory, device='cuda')
        ns['get_tts_pipeline']('af_alloy')
        factory.assert_called_once_with(lang_code='a', device='cuda')

    def test_loaded_cpu_model_makes_health_unhealthy(self):
        model = SimpleNamespace(parameters=lambda: [SimpleNamespace(device='cpu')])
        ns = functions('gpu_errors', 'model_devices',
                       torch=SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True)),
                       tts_pipelines={'a': SimpleNamespace(model=model)}, stt_models={}, inference_errors={})
        self.assertIn('non-GPU parameters', ns['gpu_errors']()[0])

    def test_inference_failure_is_retained_and_hooks_are_removed(self):
        import contextlib
        model = SimpleNamespace(parameters=lambda: [SimpleNamespace(device='cuda:0')])
        handle = Mock()
        stage = SimpleNamespace(register_forward_hook=Mock(return_value=handle))
        ns = functions('gpu_inference', 'model_devices', require_gpu=lambda: None,
                       inference_evidence={}, inference_errors={})
        guard = contextlib.contextmanager(ns['gpu_inference'])
        with self.assertRaisesRegex(RuntimeError, 'unsupported kernel'):
            with guard('tts', model, {'decoder': stage}):
                raise RuntimeError('unsupported kernel')
        handle.remove.assert_called_once()
        self.assertIn('unsupported kernel', ns['inference_errors']['tts'])
        self.assertEqual(ns['inference_evidence'], {})

    def test_health_cannot_report_ok_without_required_gpu(self):
        ns = functions(
            'health', 'model_devices', 'gpu_errors',
            torch=SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False), __version__='test'),
            app=SimpleNamespace(version='test'),
            importlib=SimpleNamespace(metadata=SimpleNamespace(version=lambda _: 'test')),
            os=SimpleNamespace(environ={}), tts_pipelines={}, stt_models={},
            cached_voices=lambda: [], cached_stt_models=lambda: [],
            inference_evidence={}, inference_errors={},
            Response=lambda **kw: kw, JSONResponse=lambda **kw: kw,
        )
        result = ns['health']()
        self.assertEqual(result.get('status_code'), 503, result)
        self.assertFalse(result['content']['ok'])


if __name__ == '__main__':
    unittest.main()
