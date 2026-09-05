import unittest

from check_core_release import OPTIONAL_REGISTRY_TEST, core_regression_suite


class CoreRegressionScopeTests(unittest.TestCase):
    def test_only_optional_repository_registry_assertion_is_deferred(self):
        class Case(unittest.TestCase):
            def __init__(self, identifier):
                super().__init__()
                self.identifier = identifier

            def id(self):
                return self.identifier

            def runTest(self):
                pass

        retained = Case("test_validate_maker_announcements.ValidatorTests.test_bad_target")
        deferred = Case(OPTIONAL_REGISTRY_TEST)
        unrelated = Case("test_web_content.ContractTests.test_core_safety")
        full = unittest.TestSuite([unittest.TestSuite([retained, deferred]), unrelated])
        core = core_regression_suite(full)
        self.assertEqual([test.id() for test in core], [retained.id(), unrelated.id()])
        self.assertEqual(full.countTestCases(), 3)


if __name__ == "__main__":
    unittest.main()
