"""Managed build reuses the launch receipt and shared dependency preparation."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('frontend', ROOT / 'files/app/hermes/hermes-frontend-build.py')
frontend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(frontend)


class FrontendBuildTest(unittest.TestCase):
    def setUp(self):
        self.module = types.ModuleType('hermes_cli.source_build')
        for name in ('source_product_current', 'source_build_env', 'prepare_launch_dependencies',
                     'build_source_tui', 'build_source_web'):
            setattr(self.module, name, Mock())
        self.modules = patch.dict(sys.modules, {'hermes_cli.source_build': self.module})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.addCleanup(setattr, sys, 'path', sys.path.copy())

    def test_current_product_never_prepares_or_builds(self):
        self.module.source_product_current.return_value = True
        self.assertEqual(frontend.run(Path('/source'), 'tui'), 0)
        self.module.source_build_env.assert_not_called()
        self.module.prepare_launch_dependencies.assert_not_called()

    def test_stale_guard_does_not_mutate_dependencies(self):
        self.module.source_product_current.return_value = False
        self.assertEqual(frontend.run(Path('/source'), 'web', check=True), 1)
        self.module.source_build_env.assert_not_called()

    def test_build_uses_pm_environment_and_launch_dependency_union(self):
        self.module.source_product_current.side_effect = [False, True]
        env = self.module.source_build_env.return_value
        self.assertEqual(frontend.run(Path('/source'), 'tui'), 0)
        self.module.source_build_env.assert_called_once_with(explicit=True, verify=False)
        self.module.prepare_launch_dependencies.assert_called_once_with(Path('/source'), env=env)
        self.module.build_source_tui.assert_called_once_with(Path('/source'), env=env)
        self.module.build_source_web.assert_not_called()

    def test_missing_post_build_receipt_fails(self):
        self.module.source_product_current.return_value = False
        with self.assertRaises(RuntimeError):
            frontend.run(Path('/source'), 'web')


if __name__ == '__main__':
    unittest.main()
