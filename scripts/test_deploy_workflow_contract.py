import unittest
import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path


class DeployWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1] / ".github" / "workflows"
        cls.deploy = (root / "deploy_pages.yml").read_text(encoding="utf-8")
        cls.validate = (root / "validate.yml").read_text(encoding="utf-8")
        cls.scripts = [textwrap.dedent(value) for value in re.findall(
            r"          script: \|\n((?:(?: {12}[^\n]*|)\n)+)", cls.deploy)]

    def test_push_publication_requires_successful_main_validation_not_pr_or_fork(self):
        self.assertNotIn("\n  push:\n", self.deploy)
        for condition in ("workflows: ['Validate data pipeline', '毎日データ更新']",
                          "github.event.workflow_run.conclusion == 'success'",
                          "github.event.workflow_run.head_branch == 'main'",
                          "github.event.workflow_run.head_repository.full_name == github.repository",
                          "github.event.workflow_run.event == 'push'",
                          "github.event.workflow_run.event == 'workflow_dispatch'"):
            self.assertIn(condition, self.deploy)

    def test_bot_daily_update_starts_validated_publication_without_waiting_for_clock(self):
        self.assertIn("github.event.workflow_run.name == '毎日データ更新'", self.deploy)
        self.assertIn("github.event.workflow_run.event == 'schedule'", self.deploy)
        self.assertIn("github.event.workflow_run.conclusion == 'failure'", self.deploy)
        self.assertNotIn("\n  schedule:\n", self.deploy)
        self.assertIn("workflow_dispatch:", self.deploy)
        self.assertIn("github.ref == 'refs/heads/main'", self.deploy)
        self.assertIn("uses: ./.github/workflows/validate.yml", self.deploy)
        self.assertIn("needs.validate.result == 'success'", self.deploy)
        self.assertIn("ref: ${{ needs.target.outputs.sha }}", self.deploy)
        self.assertIn("workflow_call:", self.validate)
        self.assertIn("ref: ${{ inputs.ref || github.sha }}", self.validate)
        self.assertIn("core_release: true", self.deploy)
        self.assertIn("core_release:", self.validate)
        self.assertIn("default: false", self.validate)
        self.assertIn("scripts/check_core_release.py --run-regressions", self.validate)
        self.assertIn("scripts/check_core_release.py --min-count 300", self.validate)

    def test_core_mode_keeps_csv_history_lifecycle_shared_and_page_validation_mandatory(self):
        for step in ("現行供給CSV品質検査", "変更履歴の型・日付・供給区分検査",
                     "販売中止・包装変更データ品質検査", "供給情報差異データ品質検査",
                     "Web・iOS共通設定の検査", "話題・注目製品・供給確認ガイドの再生成確認"):
            section = self.validate.split("- name: " + step, 1)[1].split("- name:", 1)[0]
            self.assertNotIn("if:", section)
        self.assertIn("if: ${{ !inputs.core_release }}\n        run: python3 scripts/validate_maker_announcements.py", self.validate)

    def test_success_event_does_not_repeat_the_full_validation_but_daily_update_does(self):
        self.assertIn("github.event.workflow_run.name == '毎日データ更新'", self.deploy)
        self.assertIn("github.event_name == 'workflow_run' && needs.validate.result == 'skipped'", self.deploy)

    def test_stale_sha_is_rejected_before_checkout_and_again_before_publication(self):
        self.assertIn("validated !== current", self.deploy)
        self.assertIn("branch.commit.sha === process.env.SOURCE_COMMIT", self.deploy)
        self.assertIn("if: steps.current.outputs.matches == 'true'", self.deploy)
        self.assertLess(self.deploy.index("validated !== current"), self.deploy.index("actions/checkout@"))
        self.assertLess(self.deploy.index("公開直前にmainの一致を再確認"), self.deploy.index("actions/deploy-pages@"))
        self.assertIn("cancel-in-progress: true", self.deploy)

    def test_manifest_is_created_only_for_the_checked_out_artifact(self):
        self.assertIn("--commit \"$SOURCE_COMMIT\" --output public-data-manifest.json", self.deploy)
        self.assertLess(self.deploy.index("scripts/public_data_manifest.py"), self.deploy.index("actions/upload-pages-artifact@"))
        self.assertNotIn("secrets.", self.deploy)
        self.assertNotIn("contents: write", self.deploy)
        self.assertNotIn("actions: write", self.deploy)

    @unittest.skipUnless(shutil.which("node"), "Workflow内JavaScriptの隔離実行にはNodeが必要")
    def test_actual_workflow_scripts_pin_main_and_reject_stale_results(self):
        self.assertEqual(len(self.scripts), 3)
        scripts = [self.scripts[0], self.scripts[2]]
        harness = r"""
          let input = '';
          process.stdin.on('data', chunk => { input += chunk; });
          process.stdin.on('end', async () => {
            const scripts = JSON.parse(input);
            const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
            const outputs = [];
            for (const test of [
              {script: 0, latest: 'a', validated: 'a'},
              {script: 0, latest: 'b', validated: 'a'},
              {script: 0, latest: 'b', validated: 'a', daily: true},
              {script: 0, latest: 'b'},
              {script: 0, latest: 'b', scheduledSha: 'a'},
              {script: 1, latest: 'a', source: 'a'},
              {script: 1, latest: 'b', source: 'a'},
            ]) {
              const output = {};
              const github = {rest: {repos: {getBranch: async () => ({data: {commit: {sha: test.latest}}})}}};
              const context = {repo: {owner: 'owner', repo: 'repo'}, payload: {},
                               sha: test.scheduledSha || test.latest};
              if (test.validated) context.payload.workflow_run = {
                head_sha: test.validated,
                name: test.daily ? '毎日データ更新' : 'Validate data pipeline',
              };
              const core = {notice: () => {}, setOutput: (key, value) => {output[key] = value;}};
              await new AsyncFunction('github', 'context', 'core', 'process', scripts[test.script])(
                github, context, core, {env: {SOURCE_COMMIT: test.source}});
              outputs.push(output);
            }
            console.log(JSON.stringify(outputs));
          });
        """
        result = subprocess.run([shutil.which("node"), "-e", harness], input=json.dumps(scripts),
                                capture_output=True, text=True, check=True, timeout=15)
        self.assertEqual(json.loads(result.stdout), [
            {"sha": "a"}, {}, {"sha": "b"}, {"sha": "b"}, {}, {"matches": "true"}, {"matches": "false"},
        ])

    @unittest.skipUnless(shutil.which("node"), "Workflow内JavaScriptの隔離実行にはNodeが必要")
    def test_publication_waits_for_this_attempts_artifact_and_rejects_ambiguity(self):
        self.assertIn("PAGES_ARTIFACT_NAME: github-pages-${{ github.run_attempt }}", self.deploy)
        self.assertIn("name: ${{ env.PAGES_ARTIFACT_NAME }}", self.deploy)
        self.assertIn("artifact_name: ${{ env.PAGES_ARTIFACT_NAME }}", self.deploy)
        harness = r"""
          const assert = require('node:assert/strict');
          const fs = require('node:fs');
          const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
          const script = new AsyncFunction('github', 'context', 'core', 'process', 'setTimeout',
            fs.readFileSync(0, 'utf8'));
          const uploaded = {id: 42, expired: false};
          async function run(results) {
            let requests = 0;
            const github = {rest: {actions: {listWorkflowRunArtifacts: async options => {
              assert.equal(options.run_id, 17);
              assert.equal(options.name, 'github-pages-2');
              const artifacts = results[Math.min(requests++, results.length - 1)];
              return {data: {artifacts, total_count: artifacts.length}};
            }}}};
            const context = {repo: {owner: 'owner', repo: 'repo'}, runId: 17};
            const core = {info: () => {}};
            const process = {env: {PAGES_ARTIFACT_NAME: 'github-pages-2', PAGES_ARTIFACT_ID: '42'}};
            await script(github, context, core, process, resolve => resolve());
            return requests;
          }
          (async () => {
            assert.equal(await run([[], [uploaded]]), 2);
            await assert.rejects(run([[]]), /参照可能になりません/);
            await assert.rejects(run([[uploaded, {id: 43}]]), /複数/);
            await assert.rejects(run([[{id: 43, expired: false}]]), /一致しない/);
            await assert.rejects(run([[{id: 42, expired: true}]]), /有効期限切れ/);
          })().catch(error => { console.error(error); process.exitCode = 1; });
        """
        subprocess.run([shutil.which("node"), "-e", harness], input=self.scripts[1],
                       text=True, check=True, timeout=15)


if __name__ == "__main__":
    unittest.main()
