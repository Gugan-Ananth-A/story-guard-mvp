import base64
import copy
import json
import unittest
from io import BytesIO
from unittest.mock import patch
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from story_guard.ado_client import (
    ADOClient,
    ADOClientError,
    NonStoryWorkItemError,
    StoryRecord,
    WorkItemNotFoundError,
    map_ado_work_item,
)


FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "ado_work_item_121213.json"
)


class ADOClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def make_client(self, opener):
        return ADOClient(
            project_url="https://dev.azure.com/storyguard/sample",
            pat="offline-test-pat",
            opener=opener,
        )

    def test_maps_sanitized_work_item_to_story_record(self) -> None:
        story = map_ado_work_item(self.payload)

        self.assertEqual(
            story,
            StoryRecord(
                id="121213",
                title="Login Screen",
                type="User Story",
                state="New",
                description=self.payload["fields"]["System.Description"],
                area=None,
                iteration=None,
                raw_ac_text="",
                acceptance_criteria=[],
                notes=[],
            ),
        )

    def test_from_env_reads_project_url_and_pat(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "ADO_PROJECT_URL": "https://dev.azure.com/storyguard/sample",
                "ADO_PAT": "offline-test-pat",
            },
            clear=True,
        ):
            client = ADOClient.from_env()

        self.assertEqual(client.project_url, "https://dev.azure.com/storyguard/sample")
        self.assertEqual(client.pat, "offline-test-pat")

    def test_get_story_requests_relations_and_uses_pat_header(self) -> None:
        captured = {}

        def opener(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return BytesIO(json.dumps(self.payload).encode("utf-8"))

        story = self.make_client(opener).get_story(121213)
        request = captured["request"]
        query = parse_qs(urlsplit(request.full_url).query)
        expected_auth = base64.b64encode(b":offline-test-pat").decode("ascii")

        self.assertEqual(story.id, "121213")
        self.assertEqual(query["$expand"], ["relations"])
        self.assertEqual(query["api-version"], ["7.1"])
        self.assertEqual(request.get_header("Authorization"), f"Basic {expected_auth}")
        self.assertEqual(captured["timeout"], 15.0)

    def test_404_raises_typed_not_found_error(self) -> None:
        def opener(request, timeout):
            raise HTTPError(request.full_url, 404, "Not Found", {}, BytesIO())

        with self.assertRaises(WorkItemNotFoundError) as raised:
            self.make_client(opener).get_story(121213)

        self.assertIsInstance(raised.exception, ADOClientError)

    def test_non_story_raises_typed_error(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["fields"]["System.WorkItemType"] = "Bug"
        opener = lambda request, timeout: BytesIO(json.dumps(payload).encode("utf-8"))

        with self.assertRaises(NonStoryWorkItemError) as raised:
            self.make_client(opener).get_story(121213)

        self.assertIsInstance(raised.exception, ADOClientError)


    def test_load_live_story_follows_the_child_test_plan(self) -> None:
        story = {
            "id": 121213,
            "fields": {
                "System.Title": "Login Screen",
                "System.WorkItemType": "User Story",
                "System.State": "New",
                "System.Description": "Scenario: Successful login\nExpected: Dashboard",
                "Microsoft.VSTS.Common.AcceptanceCriteria": "",
            },
            "relations": [
                {
                    "rel": "System.LinkTypes.Hierarchy-Forward",
                    "url": "https://dev.azure.com/example/_apis/wit/workItems/121214",
                }
            ],
        }
        plan = {
            "id": 121214,
            "fields": {
                "System.Title": "Story Guard - AI Agent",
                "System.WorkItemType": "Test Plan",
                "System.State": "Active",
            },
            "relations": [],
        }
        suites = {
            "value": [
                {
                    "id": 121215,
                    "name": "Story Guard - AI Agent",
                    "suiteType": "staticTestSuite",
                }
            ]
        }
        cases = {
            "value": [
                {"workItem": {"id": 121216, "name": "[AUTH-102065-P01] Valid login"}},
                {"workItem": {"id": 121216, "name": "[AUTH-102065-P01] Valid login"}},
                {"workItem": {"id": 121228, "name": "Forgot password"}},
            ]
        }

        login_case = {
            "id": 121216,
            "fields": {
                "System.Title": "[AUTH-102065-P01] Valid login",
                "System.WorkItemType": "Test Case",
                "Microsoft.VSTS.TCM.Steps": "<steps><step>Click <b>Login</b></step></steps>",
            },
            "relations": [],
        }

        def opener(request, timeout):
            url = request.full_url
            if "/workitems/121216" in url:
                body = login_case
            elif "/workitems/121214" in url:
                body = plan
            elif "/testcase?" in url:
                body = cases
            elif "/suites?" in url:
                body = suites
            else:
                body = story
            return BytesIO(json.dumps(body).encode("utf-8"))

        loaded = self.make_client(opener).load_live_story(121213)

        self.assertEqual(loaded["id"], "121213")
        self.assertEqual([case["id"] for case in loaded["tests"]], ["121216", "121228"])
        self.assertEqual(loaded["tests"][0]["title"], "[AUTH-102065-P01] Valid login")
        self.assertEqual(loaded["tests"][0]["type"], "")
        self.assertEqual(loaded["tests"][0]["mapped_ac_ids"], [])
        self.assertEqual(loaded["tests"][0]["steps"], "Click Login")
        self.assertEqual(loaded["tests"][1]["steps"], "")
        self.assertEqual(loaded["tests"][0]["suite_id"], "121215")
        self.assertEqual(loaded["tests"][0]["plan_id"], "121214")
        self.assertEqual(loaded["bugs"], [])

    def test_missing_link_is_skipped_and_bugs_are_kept(self) -> None:
        story = {
            "id": 121213,
            "fields": {
                "System.Title": "Login Screen",
                "System.WorkItemType": "User Story",
                "System.State": "New",
                "System.Description": "",
                "Microsoft.VSTS.Common.AcceptanceCriteria": "",
            },
            "relations": [
                {
                    "rel": "System.LinkTypes.Related",
                    "url": "https://dev.azure.com/example/_apis/wit/workItems/999999",
                },
                {
                    "rel": "System.LinkTypes.Related",
                    "url": "https://dev.azure.com/example/_apis/wit/workItems/122590",
                },
                {
                    "rel": "System.LinkTypes.Related",
                    "url": "https://dev.azure.com/example/_apis/wit/workItems/121214",
                },
                {
                    "rel": "System.LinkTypes.Related",
                    "url": "https://dev.azure.com/example/_apis/wit/workItems/42",
                },
            ],
        }
        plan = {
            "id": 121214,
            "fields": {
                "System.Title": "Story Guard - AI Agent",
                "System.WorkItemType": "Test Plan",
                "System.State": "Active",
            },
            "relations": [],
        }
        bug = {
            "id": 122590,
            "fields": {
                "System.Title": "Password field is not accepting special characters",
                "System.WorkItemType": "Bug",
                "System.State": "New",
                "System.CreatedDate": "2026-10-09T10:12:32.593Z",
                "System.AssignedTo": {"displayName": "Gugan Ananth Anantha Selvan"},
                "System.AreaPath": "Ecom MVP",
                "Microsoft.VSTS.Common.Priority": 2,
                "Microsoft.VSTS.Common.Severity": "2 - High",
                "Custom.Environment": "Staging",
            },
            "relations": [],
        }
        direct_case = {
            "id": 42,
            "fields": {
                "System.Title": "Direct admin case",
                "System.WorkItemType": "Test Case",
                "System.State": "Design",
            },
            "relations": [],
        }
        suites = {
            "value": [
                {
                    "id": 121215,
                    "name": "Story Guard - AI Agent",
                    "suiteType": "staticTestSuite",
                }
            ]
        }
        cases = {"value": [{"workItem": {"id": 121216, "name": "Valid login"}}]}

        def opener(request, timeout):
            url = request.full_url
            if "/workitems/999999" in url:
                raise HTTPError(url, 404, "Not Found", {}, BytesIO())
            if "/workitems/122590" in url:
                body = bug
            elif "/workitems/42" in url:
                body = direct_case
            elif "/workitems/121214" in url:
                body = plan
            elif "/testcase?" in url:
                body = cases
            elif "/suites?" in url:
                body = suites
            else:
                body = story
            return BytesIO(json.dumps(body).encode("utf-8"))

        loaded = self.make_client(opener).load_live_story(121213)

        self.assertEqual([case["id"] for case in loaded["tests"]], ["121216", "42"])
        self.assertEqual(loaded["tests"][1]["title"], "Direct admin case")
        self.assertEqual(loaded["tests"][1]["mapped_ac_ids"], [])
        bug_row = loaded["bugs"][0]
        self.assertEqual(bug_row["id"], "122590")
        self.assertEqual(bug_row["title"], "Password field is not accepting special characters")
        self.assertEqual(bug_row["priority"], "P2")
        self.assertEqual(bug_row["severity"], "2 - High")
        self.assertEqual(bug_row["status"], "New")
        self.assertEqual(bug_row["found_in"], "Staging")
        self.assertEqual(bug_row["linked_story_id"], "121213")
        self.assertEqual(bug_row["assigned_to"], "Gugan Ananth Anantha Selvan")
        self.assertEqual(bug_row["created"], "2026-10-09")
        self.assertIsInstance(bug_row["age"], int)

    def test_explicit_plan_id_skips_relation_discovery(self) -> None:
        story = {
            "id": 555001,
            "fields": {
                "System.Title": "Other story",
                "System.WorkItemType": "User Story",
                "System.State": "New",
                "System.Description": "",
                "Microsoft.VSTS.Common.AcceptanceCriteria": "",
            },
            "relations": [],
        }
        suites = {"value": [{"id": 9, "suiteType": "staticTestSuite"}]}
        cases = {"value": [{"workItem": {"id": 42, "name": "Other case"}}]}

        def opener(request, timeout):
            url = request.full_url
            if "/testcase?" in url:
                self.assertIn("/plans/77/", url)
                body = cases
            elif "/suites?" in url:
                body = suites
            else:
                body = story
            return BytesIO(json.dumps(body).encode("utf-8"))

        loaded = self.make_client(opener).load_live_story(555001, test_plan_id=77)
        self.assertEqual([case["id"] for case in loaded["tests"]], ["42"])

    def test_suite_id_uses_the_plan_linked_from_the_story(self) -> None:
        story = {
            "id": 121213,
            "fields": {
                "System.Title": "Login Screen",
                "System.WorkItemType": "User Story",
                "System.State": "New",
                "System.Description": "",
                "Microsoft.VSTS.Common.AcceptanceCriteria": "",
            },
            "relations": [
                {
                    "rel": "System.LinkTypes.Hierarchy-Forward",
                    "url": "https://dev.azure.com/example/_apis/wit/workItems/121214",
                }
            ],
        }
        plan = {
            "id": 121214,
            "fields": {
                "System.Title": "Story Guard - AI Agent",
                "System.WorkItemType": "Test Plan",
                "System.State": "Active",
            },
            "relations": [],
        }
        suite_item = {
            "id": 121215,
            "fields": {
                "System.Title": "Story Guard - AI Agent",
                "System.WorkItemType": "Test Suite",
                "System.State": "In Progress",
            },
            "relations": [],
        }
        suites = {
            "value": [
                {
                    "id": 121215,
                    "name": "Story Guard - AI Agent",
                    "suiteType": "staticTestSuite",
                }
            ]
        }
        cases = {"value": [{"workItem": {"id": 121216, "name": "Valid login"}}]}

        def opener(request, timeout):
            url = request.full_url
            if "/plans/121215/" in url:
                raise HTTPError(url, 404, "Not Found", {}, BytesIO())
            if "/workitems/121215" in url:
                body = suite_item
            elif "/workitems/121214" in url:
                body = plan
            elif "/testcase?" in url:
                self.assertIn("/plans/121214/suites/121215/", url)
                body = cases
            elif "/suites?" in url:
                body = suites
            else:
                body = story
            return BytesIO(json.dumps(body).encode("utf-8"))

        loaded = self.make_client(opener).load_live_story(121213, test_plan_id=121215)
        self.assertEqual(loaded["tests"][0]["suite_id"], "121215")
        self.assertEqual(loaded["tests"][0]["plan_id"], "121214")
        self.assertEqual(loaded["tests"][0]["suite_name"], "Story Guard - AI Agent")


if __name__ == "__main__":
    unittest.main()
