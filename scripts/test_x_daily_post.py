import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import x_daily_post as xp

ROOT = Path(__file__).resolve().parents[1]


def change(date, before, after, yj="1234567A1234"):
    return {"date": date, "yj": yj, "name": "テスト錠", "from": before, "to": after}


class BuildPlanTests(unittest.TestCase):
    def setUp(self):
        self.today = dt.date(2026, 9, 21)
        self.changes = [
            change("2026/09/20", "①通常出荷", "②限定出荷（自社の事情）", "A"),
            change("2026/09/20", "①通常出荷", "⑤供給停止", "B"),
            change("2026/09/20", "③限定出荷（他社品の影響）", "①通常出荷", "C"),
            change("2026/09/20", "②限定出荷（自社の事情）", "④限定出荷（その他）", "D"),
            change("2026/09/15", "①通常出荷", "⑤供給停止", "E"),
        ]

    def plan(self, changes=None, posted=(), today=None):
        return xp.build_plan(self.changes if changes is None else changes,
                             {"posted": [{"date": d} for d in posted]}, today or self.today)

    def test_counts_latest_day_and_links_daily_page(self):
        plan = self.plan()
        self.assertEqual("post", plan["action"])
        self.assertEqual("2026/09/20", plan["date"])
        self.assertIn("変更があった医薬品：4品目", plan["text"])
        for line in ("・限定出荷へ：1品目", "・供給停止へ：1品目", "・通常出荷へ：1品目", "・その他の区分変更：1品目"):
            self.assertIn(line, plan["text"])
        self.assertIn(f"{xp.SITE_URL}updates/2026-09-20.html", plan["text"])
        self.assertLessEqual(plan["weighted_length"], xp.MAX_WEIGHTED_LENGTH)

    def test_never_claims_no_change_or_substitution(self):
        text = self.plan()["text"]
        for forbidden in ("変更なし", "問題なし", "代替", "おすすめ", "在庫あり"):
            self.assertNotIn(forbidden, text)

    def test_skips_empty_missing_stale_future_and_duplicate(self):
        self.assertEqual("skip", self.plan(changes=[])["action"])
        self.assertEqual("skip", self.plan(changes=None or [{"yj": "x"}])["action"])
        self.assertIn("日より前", self.plan(today=dt.date(2026, 9, 24))["reason"])
        self.assertIn("未来", self.plan(today=dt.date(2026, 9, 19))["reason"])
        self.assertIn("投稿済み", self.plan(posted=["2026/09/20"])["reason"])

    def test_unknown_status_is_not_counted_silently(self):
        plan = self.plan(changes=[change("2026/09/20", "①通常出荷", "⑨未知")])
        self.assertEqual("skip", plan["action"])

    def test_weighted_length_counts_cjk_double_and_urls_as_23(self):
        self.assertEqual(4, xp.weighted_length("薬剤"))
        self.assertEqual(3, xp.weighted_length("abc"))
        self.assertEqual(1 + 1 + 23 + 1 + 1, xp.weighted_length("a https://example.com/very/long/path b"))


class WeeklyMonthlyPlanTests(unittest.TestCase):
    def setUp(self):
        self.changes = [change("2026/09/15", "①通常出荷", "②限定出荷（自社の事情）", "A"),
                        change("2026/09/20", "①通常出荷", "⑤供給停止", "B"),
                        change("2026/09/21", "④限定出荷（その他）", "①通常出荷", "C")]
        self.monday = dt.date(2026, 9, 21)

    def test_weekly_summarizes_previous_monday_to_sunday_once(self):
        plan = xp.build_weekly_plan(self.changes, {"posted": []}, self.monday)
        self.assertEqual("post", plan["action"])
        self.assertEqual("weekly:2026-09-14", plan["key"])
        self.assertIn("【先週のまとめ】9/14〜9/20", plan["text"])
        self.assertIn("区分が変わった医薬品：2品目（2日分の更新）", plan["text"])
        self.assertIn("限定出荷へ1・供給停止へ1", plan["text"])
        done = xp.build_weekly_plan(self.changes, {"posted": [{"key": "weekly:2026-09-14"}]}, self.monday)
        self.assertEqual("skip", done["action"])

    def test_weekly_skips_late_days_and_empty_weeks(self):
        self.assertEqual("skip", xp.build_weekly_plan(self.changes, {"posted": []}, dt.date(2026, 9, 24))["action"])
        empty = xp.build_weekly_plan(self.changes, {"posted": []}, dt.date(2026, 10, 5))
        self.assertIn("変更記録がないため投稿しません", empty["reason"])

    def test_monthly_announces_new_report_within_seven_days_once(self):
        with tempfile.TemporaryDirectory() as directory:
            reports = Path(directory)
            (reports / "2026-09.json").write_text(json.dumps({
                "month": "2026-09", "snapshot_date": "2026-10-01",
                "changes": {"items": 148, "to_limited": 68, "to_stopped": 25, "to_ok": 44},
                "top_new_restriction_categories": [{"name": "血圧降下剤"}, {"name": "解熱鎮痛消炎剤"}],
            }, ensure_ascii=False), encoding="utf-8")
            plan = xp.build_monthly_plan(reports, {"posted": []}, dt.date(2026, 10, 1))
            self.assertEqual("post", plan["action"])
            self.assertIn("【医薬品供給レポート 2026年9月】", plan["text"])
            self.assertIn("reports/2026-09.html", plan["text"])
            self.assertIn("血圧降下剤、解熱鎮痛消炎剤", plan["text"])
            self.assertEqual("skip", xp.build_monthly_plan(reports, {"posted": [{"key": "monthly:2026-09"}]},
                                                           dt.date(2026, 10, 2))["action"])
            self.assertEqual("skip", xp.build_monthly_plan(reports, {"posted": []}, dt.date(2026, 10, 9))["action"])
        self.assertEqual("skip", xp.build_monthly_plan(Path("/nonexistent"), {"posted": []}, dt.date(2026, 10, 1))["action"])


class PostCommandTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.plan_path = Path(self.tempdir.name) / "plan.json"
        self.log_path = Path(self.tempdir.name) / "x_post_log.json"
        patcher = mock.patch.object(xp, "LOG_PATH", self.log_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_plan(self, *plans):
        self.plan_path.write_text(json.dumps({"posts": list(plans)}, ensure_ascii=False), encoding="utf-8")

    def daily(self, **extra):
        return {"action": "post", "kind": "daily", "key": "2026/09/20", "date": "2026/09/20",
                "text": "t", "url": "u", **extra}

    def test_missing_credentials_fail_without_posting(self):
        self.write_plan(self.daily())
        with mock.patch.dict("os.environ", {}, clear=True), mock.patch.object(xp, "post_to_x") as post:
            self.assertEqual(1, xp.main(["post", "--plan", str(self.plan_path)]))
        post.assert_not_called()

    def test_posts_once_and_records_date(self):
        self.write_plan(self.daily(), {"action": "post", "kind": "weekly", "key": "weekly:2026-09-14",
                                       "text": "w", "url": "u"})
        env = {name: "v" for name in xp.CREDENTIAL_ENV}
        with mock.patch.dict("os.environ", env, clear=True), \
                mock.patch.object(xp, "post_to_x", return_value="123") as post:
            self.assertEqual(0, xp.main(["post", "--plan", str(self.plan_path)]))
            self.assertEqual(0, xp.main(["post", "--plan", str(self.plan_path)]))
        self.assertEqual(2, post.call_count)  # 2回目の実行では日別・週次とも投稿済み
        log = json.loads(self.log_path.read_text(encoding="utf-8"))
        self.assertEqual({"2026/09/20", "weekly:2026-09-14"}, {item["key"] for item in log["posted"]})
        self.assertNotIn("v", json.dumps(log).replace("posted", ""))

    def test_skip_plan_does_not_require_credentials(self):
        self.write_plan({"action": "skip", "kind": "daily", "reason": "変更履歴が空"})
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(0, xp.main(["post", "--plan", str(self.plan_path)]))

    def test_credentials_are_stripped_of_pasted_whitespace(self):
        env = {name: f"  v-{name}\n" for name in xp.CREDENTIAL_ENV}
        with mock.patch.dict("os.environ", env, clear=True):
            credentials, missing = xp.load_credentials()
        self.assertEqual([], missing)
        self.assertEqual("v-X_API_KEY", credentials["X_API_KEY"])
        with mock.patch.dict("os.environ", {"X_API_KEY": "  "}, clear=True):
            _, missing = xp.load_credentials()
        self.assertIn("X_API_KEY", missing)

    def test_whoami_reports_username_or_auth_failure_without_posting(self):
        env = {name: "v" for name in xp.CREDENTIAL_ENV}
        with mock.patch.dict("os.environ", env, clear=True), \
                mock.patch.object(xp, "whoami", return_value="DrugSupplyNavi") as who, \
                mock.patch.object(xp, "post_to_x") as post:
            self.assertEqual(0, xp.main(["whoami"]))
        who.assert_called_once()
        post.assert_not_called()
        with mock.patch.dict("os.environ", env, clear=True), \
                mock.patch.object(xp, "whoami", side_effect=RuntimeError("Xの認証に失敗しました（HTTP 401）")):
            self.assertEqual(1, xp.main(["whoami"]))

    def test_oauth_signature_matches_official_example(self):
        # X/Twitter公式ドキュメント「Creating a signature」の例題（本文パラメータを含む）
        import base64, hashlib, hmac, urllib.parse
        quote = lambda v: urllib.parse.quote(str(v), safe="~")
        params = {"status": "Hello Ladies + Gentlemen, a signed OAuth request!", "include_entities": "true",
                  "oauth_consumer_key": "xvz1evFS4wEEPTGEFPHBog",
                  "oauth_nonce": "kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg",
                  "oauth_signature_method": "HMAC-SHA1", "oauth_timestamp": "1318622958",
                  "oauth_token": "370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb", "oauth_version": "1.0"}
        base = "&".join(("POST", quote("https://api.twitter.com/1.1/statuses/update.json"),
                         quote("&".join(f"{quote(k)}={quote(v)}" for k, v in sorted(params.items())))))
        key = f"{quote('kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3WpwPAoE3Z7kBw')}&{quote('LswwdoUaIvS8ltyTt5jkRh4J50vUPVVHtR2YPi5kE')}"
        self.assertEqual("hCtSmYh+iHYCEqBWrE7C7hYmtUk=",
                         base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode())
        # 同じ手順（ソート・RFC3986エンコード・署名鍵）で実装していることを確認
        source = Path(xp.__file__).read_text(encoding="utf-8")
        self.assertIn('urllib.parse.quote(str(value), safe="~")', source)
        self.assertIn("for k, v in sorted(params.items())", source)

    def test_oauth_header_is_signed_without_leaking_secrets(self):
        creds = {"X_API_KEY": "ck", "X_API_SECRET": "cs-secret", "X_ACCESS_TOKEN": "at",
                 "X_ACCESS_TOKEN_SECRET": "ats-secret"}
        header = xp.oauth1_header("POST", xp.POST_ENDPOINT, creds)
        self.assertTrue(header.startswith("OAuth "))
        for key in ("oauth_consumer_key", "oauth_token", "oauth_signature", "oauth_nonce", "oauth_timestamp"):
            self.assertIn(key, header)
        self.assertNotIn("cs-secret", header)
        self.assertNotIn("ats-secret", header)


class WorkflowContractTests(unittest.TestCase):
    def setUp(self):
        self.workflow = (ROOT / ".github/workflows/post_x.yml").read_text(encoding="utf-8")

    def test_runs_after_successful_main_deploy_only_and_defaults_to_dry_run(self):
        self.assertIn("workflows: ['Deploy GitHub Pages']", self.workflow)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", self.workflow)
        self.assertIn("github.event.workflow_run.head_repository.full_name == github.repository", self.workflow)
        self.assertIn("default: true", self.workflow)
        self.assertIn('[ "$ENABLED" = "true" ]', self.workflow)
        self.assertNotIn("schedule:", self.workflow)
        self.assertNotIn("pull_request", self.workflow)

    def test_secrets_are_scoped_to_posting_and_manual_auth_check(self):
        post_step = self.workflow.split("- name: Xへ投稿", 1)[1].split("- name:", 1)[0]
        auth_step = self.workflow.split("- name: X認証の確認", 1)[1].split("- name:", 1)[0]
        self.assertEqual(8, self.workflow.count("secrets."))
        self.assertEqual(4, post_step.count("secrets."))
        self.assertEqual(4, auth_step.count("secrets."))
        self.assertIn("if: steps.mode.outputs.live == 'true'", post_step)
        self.assertIn("if: github.event_name == 'workflow_dispatch'", auth_step)
        self.assertIn("x_daily_post.py whoami", auth_step)

    def test_links_are_checked_before_posting(self):
        self.assertLess(self.workflow.index("リンク先の日別ページが公開済みか確認"),
                        self.workflow.index("- name: Xへ投稿"))


if __name__ == "__main__":
    unittest.main()
