#!/usr/bin/env python3
"""Real local Git/input hashing and fake Bolt/Podman; never build an OS image."""

import copy
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = runpy.run_path(str(ROOT / "scripts/nest-release-manifest.py"))
INPUTS = runpy.run_path(str(ROOT / "scripts/nest-executor-inputs.py"))
FAKE_BOLT = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
p = json.load(sys.stdin)
with open(os.environ['CALLS'], 'a') as stream:
    stream.write(json.dumps({'args': sys.argv[1:], 'params': p}) + '\n')
if sys.argv[3] == 'nest::build::check_stage3_root':
    if os.environ.get('FAIL_ROOT_CHECK'):
        sys.exit(27)
    a = p['arguments']
    print(json.dumps({'path': a[0], 'dataset_guid': a[3],
                      'content_digest': 'sha256:' + 'd' * 64 if os.environ.get('CHANGE_ROOT_CHECK') else a[6]}))
    sys.exit(0)
if os.environ.get('FAIL_BUILD'):
    print('private-secret-error', file=sys.stderr)
    sys.exit(37)
if os.environ.get('CHANGE_MODULE'):
    (pathlib.Path(os.environ['EXECUTOR']) / '.modules/stdlib/data').write_text('changed')
stage = sys.argv[3].split('::')[-1]
repo = os.environ['CI_REGISTRY_IMAGE'] + ('/' + p['variant'] if stage not in ('stage0', 'tool', 'bolt', 'agent', 'firefox', 'camofox', 'pdk') else '')
row = ({'normal': repo + '@sha256:' + 'c' * 64, 'debug': repo + '/debug@sha256:' + 'd' * 64}
       if stage not in ('stage2', 'tool', 'bolt', 'agent', 'firefox', 'camofox', 'pdk') else {'image': repo + '@sha256:' + 'c' * 64})
if stage == 'stage3':
    row = {'root': {'path': p['hostroot'], 'dataset_guid': '456', 'content_digest': 'sha256:' + 'c' * 64}}
    bad = os.environ.get('BAD_ROOT')
    if bad == 'path':
        row['root']['path'] = '/nest/hosts/fixture'
    elif bad == 'guid':
        row['root']['dataset_guid'] = True
    elif bad == 'digest':
        row['root']['content_digest'] = 'mutable'
    elif bad == 'extra':
        row['root']['private'] = 'must not emit'
if os.environ.get('BAD_OUTPUT') == 'partial':
    row.pop(next(iter(row)))
if os.environ.get('BAD_OUTPUT') == 'mutable':
    row[next(iter(row))] = repo + ':latest'
if os.environ.get('BAD_OUTPUT') == 'same':
    row['debug'] = repo + '/debug@sha256:' + 'c' * 64
if os.environ.get('BAD_OUTPUT') == 'wrong_repo':
    row[next(iter(row))] = 'other.example/nest/stage0@sha256:' + 'c' * 64
print(json.dumps(row))
'''
FAKE_ROOT = r'''import json, os, sys
with open(os.environ['CALLS'], 'a') as stream:
    stream.write(json.dumps({'root_check': sys.argv[1:]}) + '\n')
if os.environ.get('FAIL_ROOT_CHECK'):
    print('private-secret-error', file=sys.stderr)
    sys.exit(27)
root = {'path': sys.argv[1], 'dataset_guid': sys.argv[4], 'content_digest': sys.argv[7]}
if os.environ.get('CHANGE_ROOT_CHECK'):
    root['content_digest'] = 'sha256:' + 'd' * 64
print(json.dumps(root))
'''


class CandidateBuildTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "executor"
        self.project.mkdir()
        self.env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", PYTHONDONTWRITEBYTECODE="1")
        self.env.update(CI_PIPELINE_ID="901", CI_JOB_ID="902", CI_REGISTRY="registry.example",
                        CI_PROJECT_DIR=str(self.root / "producer"), CALLS=str(self.root / "calls"), EXECUTOR=str(self.project))
        for name in ("bin/ci-release-build", "bin/ci-executor-receipt", "bin/bolt-wrapper",
                     "scripts/nest-release-manifest.py", "scripts/nest-executor-inputs.py"):
            path = self.project / name
            path.parent.mkdir(exist_ok=True)
            shutil.copy2(ROOT / name, path)
        checker = self.project / "files/build/check-stage3-root.py"
        checker.parent.mkdir(parents=True)
        checker.write_text(FAKE_ROOT)
        (self.project / "Puppetfile").write_text("fixture only\n")
        self.sha = self.init_git(self.project)
        modules = self.project / ".modules"
        modules.mkdir()
        subprocess.run(["git", "clone", "--quiet", str(self.project), str(modules / "nest")], env=self.env, check=True)
        for name in ("stdlib", "private", "reboot", "ruby_task_helper", "kubecm"):
            (modules / name).mkdir()
            (modules / name / "data").write_text("fixture only")
        base = "registry.example/nest/tools/bolt@sha256:" + "f" * 64
        observed = INPUTS["observe"](self.project, self.sha, base)
        (self.project / ".executor-inputs.json").write_bytes(INPUTS["canonical"](observed))
        self.receipt = {"schema": 2, "kind": "nest_config_executor_member", "project": "nest/config", "sha": self.sha,
                        "pipeline": 801, "job": 802, "cpu": "haswell", "image": "registry.example/nest/config/main@sha256:" + "e" * 64,
                        "source_verification": "git_head_and_oci_revision", "inputs": observed}
        producer = self.root / "producer"
        producer.mkdir()
        (producer / "gitlab-ci.yml").write_text("fixture only")
        self.producer_sha = self.init_git(producer)
        tools = MANIFEST["TOOL_CONSUMERS"]
        self.expected = {"schema": 1, "kind": "nest_release_expectations", "release": "fixture-only",
                         "sources": {"nest/config": self.sha, "nest/overlay": "a" * 40,
                                     "nest/gentoo/portage": "b" * 40, "nest/gentoo/haskell": "c" * 40},
                         "executor": {"source": self.sha, "image": self.receipt["image"]}, "members": [],
                         "consumers": [{"project": p, "decision": "defer", "reason": "Fixture only", "members": []} for p in sorted(tools)]}
        fake = self.root / "fake"
        fake.mkdir()
        for name, source in (("bolt", FAKE_BOLT), ("podman", "#!/bin/sh\nexit 0\n")):
            path = fake / name
            path.write_text(source)
            path.chmod(0o755)
        self.env["PATH"] = str(fake) + os.pathsep + self.env["PATH"]
        self.env["ZDOTDIR"] = str(fake)
        self.output = self.root / "output"
        self.output.mkdir()
        self.select("stage1")

    def init_git(self, path):
        def git(*args):
            return subprocess.check_output(["git", "-C", str(path), *args], env=self.env, stderr=subprocess.DEVNULL, text=True).strip()
        git("init", "-b", "main")
        git("config", "user.email", "fixture@example.invalid")
        git("config", "user.name", "Fixture")
        git("add", ".")
        git("commit", "-m", "Fixture only")
        return git("rev-parse", "HEAD")

    def select(self, stage, mode="fresh", tool="llama.cpp"):
        project = "nest/tools/" + tool if stage == "tool" else "nest/" + stage
        member = {"id": "fixture-member", "stage": stage, "project": project, "cpu": "haswell", "variant": "server",
                  "platform": "vanilla" if stage in ("stage2", "stage3") else None,
                  "host": "fixture" if stage == "stage3" else None, "mode": mode,
                  "bases": {key: "registry.example/nest/base@sha256:" + digit * 64
                            for key, digit in (("normal", "1"), ("debug", "2"))} if stage == "stage1"
                  else {"image": "registry.example/nest/base@sha256:" + "1" * 64},
                  "compatibility": {key: "fixture only" for key in ("kernel", "modules_abi", "firmware", "bootloader")}
                  if stage in ("stage2", "stage3") else {}, "identity_root": None}
        if stage == "stage3":
            reference = "12345678-1234-4123-8123-123456789abc"
            member.update(identity_root="/private/identities/" + reference, identity_reference=reference,
                          identity_ca_sha256="f" * 64)
        self.expected["members"] = [member]
        self.expected["sources"][project] = self.producer_sha
        self.expected["consumers"] = [r for r in self.expected["consumers"] if r["project"] not in
                                      ("nest/stage0", "nest/stage1", "nest/stage2", "nest/stage3", project)]
        self.expected["consumers"].append({"project": project, "decision": "rebuild", "reason": "Fixture only", "members": [member["id"]]})
        self.env.update(CI_PROJECT_PATH=project, CI_COMMIT_SHA=self.producer_sha,
                        CI_JOB_IMAGE=self.receipt["image"], CI_REGISTRY_IMAGE="registry.example/" + project)

    def cli(self, placement=None, **env):
        expected = self.root / "expectations.json"
        receipt = self.root / "receipt.json"
        expected.write_text(json.dumps(self.expected))
        receipt.write_text(json.dumps(self.receipt))
        extra = []
        if placement is not None:
            path = self.root / "placement.json"
            path.write_text(json.dumps(placement))
            extra = ["--stage3-placement", str(path)]
        return subprocess.run([sys.executable, str(self.project / "bin/ci-release-build"), "--expectations", str(expected),
                               "--executor-receipt", str(receipt), "--member", "fixture-member", "--output-dir", str(self.output)] + extra,
                              env=dict(self.env, **env), text=True, capture_output=True)

    def calls(self):
        path = self.root / "calls"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_stage0_stage1_stage2_execute_frozen_candidates_and_reopen_result(self):
        for stage in ("stage0", "stage1", "stage2"):
            self.select(stage, "refresh" if stage == "stage0" else "fresh")
            self.output = self.root / stage
            self.output.mkdir()
            result = self.cli()
            self.assertEqual(result.returncode, 0, result.stderr)
            row = json.loads((self.output / "fixture-member.json").read_text())
            self.assertEqual(row["expectations_digest"], MANIFEST["digest"](self.expected))
            self.assertEqual(row["executor_receipt"], self.receipt)
            self.assertEqual(row["output"]["member"], self.expected["members"][0])
            self.assertEqual(row["output"]["producer"]["job"], 902)
            candidate = {"schema": 1, "kind": "nest_release_candidate", "release": self.expected["release"],
                         "expectations_digest": row["expectations_digest"], "outputs": [row["output"]]}
            self.assertEqual(MANIFEST["validate"](self.expected, candidate)["candidate"], candidate)
            self.assertTrue(json.loads(result.stdout)["readback_verified"])
            call = self.calls()[-1]
            self.assertEqual(call["args"], ["plan", "run", "nest::build::" + stage, "--project", str(self.project), "--params", "-", "--format", "json"])
            params = call["params"]
            self.assertEqual(params["repo_revisions"], {"gentoo": "b" * 40, "nest": "a" * 40, "haskell": "c" * 40})
            self.assertEqual(params["candidate"], "p901-j902")
            self.assertTrue(params["build"] and params["deploy"] and params["init"])
            self.assertIsNone(params["registry_username"])
            self.assertNotIn("password", json.dumps(params))

    def test_job_or_image_identity_mismatch_stops_before_bolt(self):
        for env in ({"CI_COMMIT_SHA": "d" * 40}, {"CI_JOB_IMAGE": "registry.example/nest/config:latest"},
                    {"CI_PROJECT_PATH": "nest/stage2"}, {"CI_JOB_ID": "0"}, {"CI_PIPELINE_ID": "true"},
                    {"CI_REGISTRY_IMAGE": "other.example/nest/stage1"}):
            self.assertEqual(self.cli(**env).returncode, 1)
            self.assertEqual(self.calls(), [])

    def test_llama_tool_candidate_preserves_mode_and_retains_exact_project_digest(self):
        for mode in ("fresh", "refresh"):
            self.select("tool", mode)
            self.output = self.root / mode
            self.output.mkdir()
            result = self.cli()
            self.assertEqual(result.returncode, 0, result.stderr)
            call = self.calls()[-1]
            self.assertEqual(call["args"][2], "nest::build::tool")
            params = call["params"]
            self.assertEqual(params["tool"], "llama.cpp")
            self.assertEqual(params["base_variant"], "server")
            self.assertEqual(params["refresh"], mode == "refresh")
            self.assertEqual(params["from_image"], self.expected["members"][0]["bases"]["image"])
            self.assertNotIn("tag", params)
            row = json.loads((self.output / "fixture-member.json").read_text())
            self.assertEqual(row["output"]["artifacts"], {"image": "registry.example/nest/tools/llama.cpp@sha256:" + "c" * 64})
            candidate = {"schema": 1, "kind": "nest_release_candidate", "release": self.expected["release"],
                         "expectations_digest": row["expectations_digest"], "outputs": [row["output"]]}
            MANIFEST["validate"](self.expected, candidate)

    def test_openbolt_candidate_dispatches_specialized_wrapper_for_all_supported_cpus_and_modes(self):
        for cpu in ("haswell", "cortex-a53", "sifive-u74"):
            for mode in ("fresh", "refresh"):
                self.select("tool", mode, "bolt")
                self.expected["members"][0]["cpu"] = cpu
                self.output = self.root / ("bolt-" + cpu + "-" + mode)
                self.output.mkdir()
                result = self.cli()
                self.assertEqual(result.returncode, 0, result.stderr)
                call = self.calls()[-1]
                self.assertEqual(call["args"][2], "nest::build::bolt")
                params = call["params"]
                self.assertEqual(params["cpu"], cpu)
                self.assertEqual(params["refresh"], mode == "refresh")
                self.assertEqual(params["from_image"], self.expected["members"][0]["bases"]["image"])
                self.assertEqual(params["candidate"], "p901-j902")
                self.assertEqual(params["repo_revisions"], {"gentoo": "b" * 40, "nest": "a" * 40, "haskell": "c" * 40})
                self.assertTrue(params["build"] and params["deploy"] and params["init"])
                for key in ("tag", "tool", "base_variant", "registry_password"):
                    self.assertNotIn(key, params)
                row = json.loads((self.output / "fixture-member.json").read_text())
                self.assertEqual(row["output"]["artifacts"], {"image": "registry.example/nest/tools/bolt@sha256:" + "c" * 64})
                MANIFEST["validate"](self.expected, {"schema": 1, "kind": "nest_release_candidate",
                                                  "release": self.expected["release"],
                                                  "expectations_digest": row["expectations_digest"], "outputs": [row["output"]]})

    def test_openbolt_wrong_cpu_and_variant_refuse_before_bolt(self):
        self.select("tool", tool="bolt")
        for cpu, variant in (("zen5", "server"), ("haswell", "workstation")):
            self.expected["members"][0].update(cpu=cpu, variant=variant)
            self.assertEqual(self.cli().returncode, 1)
        self.assertEqual(self.calls(), [])

    def test_pdk_candidate_dispatches_specialized_wrapper_and_preserves_input_identity(self):
        for cpu in ("haswell", "cortex-a53", "sifive-u74"):
            for mode in ("fresh", "refresh"):
                self.select("tool", mode, "pdk")
                self.expected["members"][0]["cpu"] = cpu
                self.output = self.root / ("pdk-" + cpu + "-" + mode)
                self.output.mkdir()
                result = self.cli()
                self.assertEqual(result.returncode, 0, result.stderr)
                call = self.calls()[-1]
                self.assertEqual(call["args"][2], "nest::build::pdk")
                params = call["params"]
                self.assertEqual(params["cpu"], cpu)
                self.assertEqual(params["refresh"], mode == "refresh")
                self.assertEqual(params["from_image"], self.expected["members"][0]["bases"]["image"])
                self.assertEqual(params["repo_revisions"], {"gentoo": "b" * 40, "nest": "a" * 40, "haskell": "c" * 40})
                for key in ("tag", "tool", "base_variant", "registry_password"):
                    self.assertNotIn(key, params)
                row = json.loads((self.output / "fixture-member.json").read_text())
                self.assertEqual(row["output"]["artifacts"], {"image": "registry.example/nest/tools/pdk@sha256:" + "c" * 64})
                MANIFEST["validate"](self.expected, {"schema": 1, "kind": "nest_release_candidate",
                                                  "release": self.expected["release"],
                                                  "expectations_digest": row["expectations_digest"], "outputs": [row["output"]]})

    def test_pdk_wrong_cpu_variant_and_failed_publication_refuse(self):
        self.select("tool", tool="pdk")
        for cpu, variant in (("zen5", "server"), ("haswell", "workstation")):
            self.expected["members"][0].update(cpu=cpu, variant=variant)
            self.assertEqual(self.cli().returncode, 1)
        self.assertEqual(self.calls(), [])
        self.expected["members"][0].update(cpu="haswell", variant="server")
        self.assertEqual(self.cli(FAIL_BUILD="1").returncode, 1)
        self.assertFalse((self.output / "fixture-member.json").exists())
        count = len(self.calls())
        self.assertEqual(self.cli().returncode, 1)
        self.assertEqual(len(self.calls()), count)

    def test_agent_candidate_preserves_wrapper_mode_and_retained_digest(self):
        for mode in ("fresh", "refresh"):
            self.select("tool", mode, "agent")
            self.expected["members"][0]["cpu"] = "zen5"
            self.output = self.root / ("agent-" + mode)
            self.output.mkdir()
            result = self.cli()
            self.assertEqual(result.returncode, 0, result.stderr)
            call = self.calls()[-1]
            self.assertEqual(call["args"][2], "nest::build::agent")
            params = call["params"]
            self.assertEqual(params["cpu"], "zen5")
            self.assertEqual(params["refresh"], mode == "refresh")
            self.assertEqual(params["from_image"], self.expected["members"][0]["bases"]["image"])
            for key in ("tag", "tool", "base_variant", "registry_password"):
                self.assertNotIn(key, params)
            row = json.loads((self.output / "fixture-member.json").read_text())
            self.assertEqual(row["output"]["artifacts"], {"image": "registry.example/nest/tools/agent@sha256:" + "c" * 64})
            MANIFEST["validate"](self.expected, {"schema": 1, "kind": "nest_release_candidate",
                                              "release": self.expected["release"],
                                              "expectations_digest": row["expectations_digest"], "outputs": [row["output"]]})

    def test_browser_candidates_dispatch_specialized_wrappers_and_preserve_variant(self):
        for tool, variant in (("firefox", "workstation"), ("camofox", "server")):
            self.expected["consumers"] = [{"project": p, "decision": "defer", "reason": "Fixture only", "members": []}
                                          for p in sorted(MANIFEST["TOOL_CONSUMERS"])]
            for mode in ("fresh", "refresh"):
                self.select("tool", mode, tool)
                self.expected["members"][0].update(cpu="zen5", variant=variant)
                self.output = self.root / (tool + "-" + mode)
                self.output.mkdir()
                result = self.cli()
                self.assertEqual(result.returncode, 0, result.stderr)
                call = self.calls()[-1]
                self.assertEqual(call["args"][2], "nest::build::" + tool)
                self.assertEqual(call["params"]["refresh"], mode == "refresh")
                self.assertEqual(call["params"]["from_image"], self.expected["members"][0]["bases"]["image"])
                for key in ("tag", "tool", "base_variant", "registry_password"):
                    self.assertNotIn(key, call["params"])
                row = json.loads((self.output / "fixture-member.json").read_text())
                self.assertEqual(row["output"]["artifacts"], {"image": "registry.example/nest/tools/" + tool + "@sha256:" + "c" * 64})
                MANIFEST["validate"](self.expected, {"schema": 1, "kind": "nest_release_candidate",
                                                  "release": self.expected["release"],
                                                  "expectations_digest": row["expectations_digest"], "outputs": [row["output"]]})

    def test_browser_wrong_cpu_variant_and_failed_results_refuse(self):
        for tool, variant in (("firefox", "workstation"), ("camofox", "server")):
            self.expected["consumers"] = [{"project": p, "decision": "defer", "reason": "Fixture only", "members": []}
                                          for p in sorted(MANIFEST["TOOL_CONSUMERS"])]
            self.select("tool", tool=tool)
            member = self.expected["members"][0]
            for cpu, bad_variant in (("haswell", variant), ("zen5", "mobile")):
                member.update(cpu=cpu, variant=bad_variant)
                count = len(self.calls())
                self.assertEqual(self.cli().returncode, 1)
                self.assertEqual(len(self.calls()), count)
            member.update(cpu="zen5", variant=variant)
            for index, env in enumerate([{"FAIL_BUILD": "1"}] +
                                        [{"BAD_OUTPUT": bad} for bad in ("partial", "mutable", "wrong_repo", "same")]):
                self.output = self.root / (tool + "-fault-" + str(index))
                self.output.mkdir()
                result = self.cli(**env)
                self.assertEqual(result.returncode, 1, env)
                self.assertFalse((self.output / "fixture-member.json").exists())
                self.assertNotIn("private-secret", result.stderr)
                count = len(self.calls())
                self.assertEqual(self.cli().returncode, 1)
                self.assertEqual(len(self.calls()), count)

    def test_agent_wrong_cpu_variant_and_failed_output_never_replays(self):
        self.select("tool", tool="agent")
        for cpu, variant in (("haswell", "server"), ("zen5", "workstation")):
            self.expected["members"][0].update(cpu=cpu, variant=variant)
            self.assertEqual(self.cli().returncode, 1)
        self.assertEqual(self.calls(), [])
        self.expected["members"][0].update(cpu="zen5", variant="server")
        for index, env in enumerate([{"FAIL_BUILD": "1"}] +
                                    [{"BAD_OUTPUT": bad} for bad in ("partial", "mutable", "wrong_repo", "same")]):
            self.output = self.root / ("agent-fault-" + str(index))
            self.output.mkdir()
            result = self.cli(**env)
            self.assertEqual(result.returncode, 1, env)
            self.assertFalse((self.output / "fixture-member.json").exists())
            self.assertNotIn("private-secret", result.stderr)
            count = len(self.calls())
            self.assertEqual(self.cli().returncode, 1)
            self.assertEqual(len(self.calls()), count)

    def test_openbolt_failed_or_invalid_publication_never_retains_or_replays_result(self):
        self.select("tool", tool="bolt")
        for index, env in enumerate([{"FAIL_BUILD": "1"}] +
                                    [{"BAD_OUTPUT": bad} for bad in ("partial", "mutable", "wrong_repo", "same")]):
            self.output = self.root / ("bolt-fault-" + str(index))
            self.output.mkdir()
            result = self.cli(**env)
            self.assertEqual(result.returncode, 1, env)
            self.assertFalse((self.output / "fixture-member.json").exists())
            self.assertNotIn("private-secret", result.stderr)
            count = len(self.calls())
            self.assertEqual(self.cli().returncode, 1)
            self.assertEqual(len(self.calls()), count)

    def test_specialized_tools_wrong_variant_and_tool_placement_refuse_before_bolt(self):
        self.select("tool")
        self.assertEqual(self.cli(self.placement()).returncode, 1)
        self.expected["members"][0]["variant"] = "workstation"
        self.assertEqual(self.cli().returncode, 1)
        self.expected["members"][0]["variant"] = "server"
        for tool in ("r10k", "whisper.cpp"):
            project = "nest/tools/" + tool
            member = self.expected["members"][0]
            member["project"] = project
            self.expected["sources"][project] = self.producer_sha
            self.expected["consumers"] = [{"project": p, "decision": "rebuild" if p == project else "defer",
                                           "reason": "Fixture only", "members": [member["id"]] if p == project else []}
                                          for p in sorted(MANIFEST["TOOL_CONSUMERS"])]
            self.env.update(CI_PROJECT_PATH=project, CI_REGISTRY_IMAGE="registry.example/" + project)
            self.assertEqual(self.cli().returncode, 1, tool)
        self.assertEqual(self.calls(), [])

    def test_tool_failed_or_invalid_publication_never_emits_member(self):
        self.select("tool")
        for index, env in enumerate([{"FAIL_BUILD": "1"}] +
                                    [{"BAD_OUTPUT": bad} for bad in ("partial", "mutable", "wrong_repo", "same")]):
            self.output = self.root / ("tool-fault-" + str(index))
            self.output.mkdir()
            result = self.cli(**env)
            self.assertEqual(result.returncode, 1, env)
            self.assertFalse((self.output / "fixture-member.json").exists())
            self.assertNotIn("private-secret", result.stderr)
            count = len(self.calls())
            self.assertEqual(self.cli().returncode, 1)
            self.assertEqual(len(self.calls()), count)

    def test_changed_actual_module_stops_before_bolt(self):
        (self.project / ".modules/stdlib/data").write_text("changed")
        self.assertEqual(self.cli().returncode, 1)
        self.assertEqual(self.calls(), [])

    def test_changed_producer_checkout_stops_before_bolt(self):
        (self.root / "producer/gitlab-ci.yml").write_text("changed")
        self.assertEqual(self.cli().returncode, 1)
        self.assertEqual(self.calls(), [])

    def test_old_or_malformed_executor_receipt_stops_before_bolt(self):
        original = copy.deepcopy(self.receipt)
        for key, value in (("schema", 1), ("pipeline", True), ("sha", "d" * 40), ("image", 123),
                           ("image", "registry.example/nest/config:latest")):
            self.receipt = copy.deepcopy(original)
            self.receipt[key] = value
            self.assertEqual(self.cli().returncode, 1)
            self.assertEqual(self.calls(), [])

    def test_stage0_fresh_and_reuse_decision_refuse(self):
        self.select("stage0", "fresh")
        self.assertEqual(self.cli().returncode, 1)
        self.select("stage1")
        self.expected["consumers"][-1]["decision"] = "reuse"
        self.assertEqual(self.cli().returncode, 1)
        self.assertEqual(self.calls(), [])

    def test_failed_build_never_returns_or_replays_success(self):
        result = self.cli(FAIL_BUILD="1")
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("private-secret", result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertFalse((self.output / "fixture-member.json").exists())
        self.assertEqual(self.cli().returncode, 1)
        self.assertEqual(len(self.calls()), 1)

    def test_partial_mutable_wrong_repo_or_identical_outputs_refuse(self):
        for bad in ("partial", "mutable", "same", "wrong_repo"):
            self.output = self.root / bad
            self.output.mkdir()
            result = self.cli(BAD_OUTPUT=bad)
            self.assertEqual(result.returncode, 1, bad)
            self.assertFalse((self.output / "fixture-member.json").exists())

    def test_build_cannot_change_its_executor_and_emit_success(self):
        self.assertEqual(self.cli(CHANGE_MODULE="1").returncode, 1)
        self.assertFalse((self.output / "fixture-member.json").exists())

    def test_success_never_overwrites_or_runs_again(self):
        self.assertEqual(self.cli().returncode, 0)
        target = self.output / "fixture-member.json"
        original = target.read_bytes()
        self.assertEqual(self.cli().returncode, 1)
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(len(self.calls()), 1)


    def placement(self):
        return {"schema": 1, "kind": "nest_stage3_local_placement", "member": "fixture-member",
                "expectations_digest": MANIFEST["digest"](self.expected), "staging": "/private/staging",
                "staging_guid": "123", "receipts": "/private/receipts", "parent_guid": "234"}

    def test_stage3_binds_local_plan_and_independent_resource_readback_before_retention(self):
        self.select("stage3")
        placement = self.placement()
        result = self.cli(placement)
        self.assertEqual(result.returncode, 0, result.stderr)
        row = json.loads((self.output / "fixture-member.json").read_text())
        candidate = {"schema": 1, "kind": "nest_release_candidate", "release": self.expected["release"],
                     "expectations_digest": row["expectations_digest"], "outputs": [row["output"]]}
        MANIFEST["validate"](self.expected, candidate)
        params = self.calls()[0]["params"]
        self.assertEqual(params["hostname"], "fixture")
        self.assertFalse(params["deploy"])
        self.assertEqual(params["identityroot"], self.expected["members"][0]["identity_root"])
        self.assertEqual(params["stage2_image"], self.expected["members"][0]["bases"]["image"])
        self.assertEqual(params["catalog_inputs"], {"source": self.sha, "base": self.receipt["inputs"]["base_image"]})
        self.assertEqual(params["root_publication"], {"release": "fixture-only", "expectations": row["expectations_digest"],
                         **{k: placement[k] for k in ("staging", "staging_guid", "receipts", "parent_guid")}})
        for key in ("candidate", "cpu", "registry", "from_image", "puppet_environment"):
            self.assertNotIn(key, params)
        root = row["output"]["artifacts"]["root"]
        self.assertEqual(self.calls()[1]["root_check"], [root["path"], "fixture", "fixture-only", "456",
                         row["expectations_digest"], "--content-digest", root["content_digest"]])
        self.assertTrue(json.loads(result.stdout)["readback_verified"])
        self.assertEqual(self.cli(placement).returncode, 1)
        self.assertEqual(len(self.calls()), 2)

    def test_stage3_missing_wrong_or_unknown_placement_refuses_before_bolt(self):
        self.select("stage3")
        self.assertEqual(self.cli().returncode, 1)
        for key, value in (("member", "other"), ("expectations_digest", "sha256:" + "d" * 64),
                           ("schema", True), ("staging_guid", True), ("receipts", "relative"), ("unknown", "value")):
            placement = self.placement()
            placement[key] = value
            self.assertEqual(self.cli(placement).returncode, 1, key)
        self.assertEqual(self.calls(), [])

    def test_stage3_remote_placement_reopens_on_the_inventory_publication_host(self):
        self.select("stage3")
        placement = dict(self.placement(), kind="nest_stage3_remote_placement", target="falcon", archive="/private/transfer/root.tar")
        result = self.cli(placement)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertEqual(calls[0]["params"]["root_publication"]["target"], "falcon")
        self.assertEqual(calls[0]["params"]["root_publication"]["archive"], placement["archive"])
        self.assertEqual(calls[1]["args"][2], "nest::build::check_stage3_root")
        self.assertEqual(calls[1]["params"]["targets"], "falcon")
        self.assertEqual(calls[1]["params"]["arguments"][0], "/nest/releases/fixture-only/hosts/fixture")

    def test_stage3_remote_readback_faults_never_emit_or_replay_member(self):
        self.select("stage3")
        placement = dict(self.placement(), kind="nest_stage3_remote_placement", target="falcon", archive="/private/transfer/root.tar")
        for index, env in enumerate([{"FAIL_ROOT_CHECK": "1"}, {"CHANGE_ROOT_CHECK": "1"}]):
            self.output = self.root / ("remote-fault-" + str(index))
            self.output.mkdir()
            self.assertEqual(self.cli(placement, **env).returncode, 1)
            self.assertFalse((self.output / "fixture-member.json").exists())
            count = len(self.calls())
            self.assertEqual(self.cli(placement).returncode, 1)
            self.assertEqual(len(self.calls()), count)

    def test_stage3_remote_placement_rejects_missing_archive_and_raw_ssh_targets(self):
        self.select("stage3")
        placement = dict(self.placement(), kind="nest_stage3_remote_placement", target="falcon", archive="/private/transfer/root.tar")
        for key, value in [("target", "root@falcon"), ("target", "ssh://falcon"), ("archive", "relative.tar"), ("archive", "/private/not-tar")]:
            self.assertEqual(self.cli(dict(placement, **{key: value})).returncode, 1)
        del placement['archive']
        self.assertEqual(self.cli(placement).returncode, 1)
        self.assertEqual(self.calls(), [])

    def test_stage3_refresh_and_nonstage3_placement_refuse_before_bolt(self):
        self.select("stage3", "refresh")
        self.assertEqual(self.cli(self.placement()).returncode, 1)
        self.select("stage1")
        self.assertEqual(self.cli(self.placement()).returncode, 1)
        self.assertEqual(self.calls(), [])

    def test_stage3_bad_root_or_failed_or_changed_native_readback_never_emits_member(self):
        self.select("stage3")
        for index, env in enumerate([{"BAD_ROOT": value} for value in ("path", "guid", "digest", "extra")] +
                                    [{"FAIL_ROOT_CHECK": "1"}, {"CHANGE_ROOT_CHECK": "1"}, {"FAIL_BUILD": "1"}]):
            self.output = self.root / ("fault-" + str(index))
            self.output.mkdir()
            result = self.cli(self.placement(), **env)
            self.assertEqual(result.returncode, 1, env)
            self.assertNotIn("private-secret", result.stderr)
            self.assertFalse((self.output / "fixture-member.json").exists())
            count = len(self.calls())
            self.assertEqual(self.cli(self.placement()).returncode, 1)
            self.assertEqual(len(self.calls()), count)


if __name__ == "__main__":
    unittest.main()
