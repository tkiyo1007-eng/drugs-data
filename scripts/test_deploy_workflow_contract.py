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

    def test_push_publication_requires_successful_main_validation_not_pr_or_fork(self):
        self.assertNotIn("\n  push:\n", self.deploy)
        for condition in ("workflows: ['Validate data pipeline']",
                          "github.event.workflow_run.conclusion == 'success'",
                          "github.event.workflow_run.head_branch == 'main'",
                          "github.event.workflow_run.head_repository.full_name == github.repository",
                          "github.event.workflow_run.event == 'push'",
                          "github.event.workflow_run.event == 'workflow_dispatch'"):
            self.assertIn(condition, self.deploy)

    def test_bot_daily_push_still_has_scheduled_validated_publication(self):
        self.assertIn('cron: "50 14 * * *"', self.deploy)
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

    def test_success_event_does_not_repeat_the_full_validation(self):
        self.assertIn("if: needs.target.outputs.sha != '' && github.event_name != 'workflow_run'", self.deploy)
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
        scripts = [textwrap.dedent(value) for value in re.findall(
            r"          script: \|\n((?:(?: {12}[^\n]*|)\n)+)", self.deploy)]
        self.assertEqual(len(scripts), 2)
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
              {script: 0, latest: 'b'},
              {script: 0, latest: 'b', scheduledSha: 'a'},
              {script: 1, latest: 'a', source: 'a'},
              {script: 1, latest: 'b', source: 'a'},
            ]) {
              const output = {};
              const github = {rest: {repos: {getBranch: async () => ({data: {commit: {sha: test.latest}}})}}};
              const context = {repo: {owner: 'owner', repo: 'repo'}, payload: {},
                               sha: test.scheduledSha || test.latest};
              if (test.validated) context.payload.workflow_run = {head_sha: test.validated};
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
            {"sha": "a"}, {}, {"sha": "b"}, {}, {"matches": "true"}, {"matches": "false"},
        ])


if __name__ == "__main__":
    unittest.main()
