import unittest

from story_guard.test_adapter import fetch_tests


class DummyTestAdapterTests(unittest.TestCase):
    def test_returns_the_18_fixture_tests_with_empty_mappings(self) -> None:
        tests = fetch_tests("121213")

        self.assertEqual(len(tests), 18)
        self.assertEqual(
            [test["id"] for test in tests],
            [str(test_id) for test_id in range(121216, 121234)],
        )
        self.assertTrue(
            all(set(test) == {"id", "title", "mapped_ac_ids"} for test in tests)
        )
        self.assertTrue(all(isinstance(test["title"], str) for test in tests))
        self.assertTrue(all(test["mapped_ac_ids"] == [] for test in tests))

    def test_other_story_ids_have_no_test_pack(self) -> None:
        self.assertEqual(fetch_tests("999999"), [])


if __name__ == "__main__":
    unittest.main()
