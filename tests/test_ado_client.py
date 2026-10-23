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
    ADOConfigurationError,
    ADORequestError,
    ADOResponseError,
    NonStoryWorkItemError,
    StoryRecord,
    WorkItemNotFoundError,
    map_ado_bug,
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

    def test_from_env_uses_only_the_configured_project_url_and_pat(self) -> None:
        project_url = "https://dev.azure.com/contoso/Orders%20Portal"
        captured = {}

        def opener(request, timeout):
            captured["request"] = request
            return BytesIO(json.dumps({"children": []}).encode("utf-8"))

        with patch.dict(
            "os.environ",
            {
                "ADO_PROJECT_URL": project_url,
                "ADO_PAT": "offline-test-pat",
            },
            clear=True,
        ), patch("story_guard.ado_client.urlopen", opener):
            client = ADOClient.from_env()
            self.assertEqual(client.list_iterations(), [])

        self.assertEqual(client.project_url, project_url)
        self.assertEqual(client.pat, "offline-test-pat")
        request_url = captured["request"].full_url
        self.assertTrue(request_url.startswith(project_url + "/_apis/"))
        self.assertNotIn("rootquotient", request_url)
        self.assertNotIn("Ecom", request_url)

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

    def test_list_iterations_returns_nested_paths_from_configured_project(self) -> None:
        project_url = "https://dev.azure.com/different-org/Commerce"
        requests = []
        payload = {
            "children": [
                {
                    "path": "Commerce\\Release 1",
                    "children": [
                        {"path": "Commerce\\Release 1\\Sprint 1"},
                        {"path": "Commerce\\Release 1\\Sprint 2"},
                    ],
                },
                {"path": "Commerce\\Backlog"},
            ]
        }

        def opener(request, timeout):
            requests.append(request)
            return BytesIO(json.dumps(payload).encode("utf-8"))

        client = ADOClient(project_url, "offline-test-pat", opener=opener)

        self.assertEqual(
            client.list_iterations(),
            [
                "Commerce\\Release 1",
                "Commerce\\Release 1\\Sprint 1",
                "Commerce\\Release 1\\Sprint 2",
                "Commerce\\Backlog",
            ],
        )
        self.assertEqual(len(requests), 1)
        self.assertTrue(requests[0].full_url.startswith(project_url))
        self.assertIn("/_apis/wit/classificationnodes/Iterations?", requests[0].full_url)
        self.assertEqual(requests[0].get_method(), "GET")

    def test_iteration_access_denied_is_a_configuration_error(self) -> None:
        def opener(request, timeout):
            raise HTTPError(request.full_url, 403, "Forbidden", {}, BytesIO())

        with self.assertRaisesRegex(ADOConfigurationError, "ADO_PAT cannot read"):
            self.make_client(opener).list_iterations()

    def test_test_case_plan_memberships_follow_each_cases_suite_and_plan(self) -> None:
        requests = []

        def opener(request, timeout):
            requests.append(request)
            path = urlsplit(request.full_url).path.lower()
            query = parse_qs(urlsplit(request.full_url).query)
            if path.endswith("/_apis/testplan/plans"):
                payload = {"value": [{"id": 121214}, {"id": 765432}]}
            elif path.endswith("/_apis/testplan/plans/121214/suites"):
                payload = {"value": [{"id": 121215, "children": [{"id": 121216}]}]}
            elif path.endswith("/_apis/testplan/plans/765432/suites"):
                payload = {"value": [{"id": 765433}]}
            elif path.endswith("/_apis/test/plans/121214/suites/121215/points"):
                payload = {
                    "value": [
                        {"testCase": {"id": 501}},
                        {"testCase": {"id": 999}},
                    ]
                }
            elif path.endswith("/_apis/test/plans/121214/suites/121216/points"):
                payload = {"value": [{"testCase": {"id": 502}}]}
            elif path.endswith("/_apis/test/plans/765432/suites/765433/points"):
                payload = {"value": [{"testCase": {"id": 777}}]}
            else:
                self.fail(f"unexpected request: {request.full_url}")
            self.assertEqual(query["api-version"][0], "7.1" if "/points" in path else "7.1-preview.1")
            return BytesIO(json.dumps(payload).encode("utf-8"))

        memberships = self.make_client(opener).test_case_plan_memberships([501, 502, 777])

        self.assertEqual(
            memberships,
            {"501": [121214], "502": [121214], "777": [765432]},
        )
        self.assertEqual(len(requests), 6)
        self.assertTrue(
            all(request.get_method() == "GET" for request in requests)
        )

    def test_test_case_plan_memberships_skips_project_lookup_for_empty_list(self) -> None:
        client = self.make_client(lambda request, timeout: self.fail("request ran"))

        self.assertEqual(client.test_case_plan_memberships([]), {})

    def test_list_user_stories_pages_by_id_and_excludes_other_types(self) -> None:
        requests = []
        pages = {0: [11, 12], 12: [13, 14], 14: []}
        records = {
            11: {"System.Title": "First story", "System.WorkItemType": "User Story"},
            12: {"System.Title": "A bug", "System.WorkItemType": "Bug"},
            13: {"System.Title": "A test plan", "System.WorkItemType": "Test Plan"},
            14: {"System.Title": "Last story", "System.WorkItemType": "User Story"},
        }

        def opener(request, timeout):
            requests.append(request)
            if request.get_method() == "POST":
                wiql = json.loads(request.data.decode("utf-8"))["query"]
                cursor = int(wiql.rsplit("[System.Id] > ", 1)[1].split()[0])
                return BytesIO(
                    json.dumps(
                        {"workItems": [{"id": item_id} for item_id in pages[cursor]]}
                    ).encode("utf-8")
                )

            query = parse_qs(urlsplit(request.full_url).query)
            ids = [int(item_id) for item_id in query["ids"][0].split(",")]
            values = [
                {"id": item_id, "fields": records[item_id]}
                for item_id in reversed(ids)
            ]
            return BytesIO(json.dumps({"value": values}).encode("utf-8"))

        with patch("story_guard.ado_client.WIQL_PAGE_SIZE", 2), patch(
            "story_guard.ado_client.WORK_ITEMS_BATCH_SIZE", 1
        ):
            stories = self.make_client(opener).list_user_stories(
                "Team Project\\Sprint '26"
            )

        self.assertEqual(
            stories,
            [
                {"id": "11", "title": "First story"},
                {"id": "14", "title": "Last story"},
            ],
        )
        methods = [request.get_method() for request in requests]
        self.assertTrue(set(methods).issubset({"POST", "GET"}))
        self.assertEqual(methods.count("POST"), 3)
        self.assertEqual(methods.count("GET"), 4)
        wiql_requests = [
            request for request in requests if request.get_method() == "POST"
        ]
        query = json.loads(wiql_requests[0].data.decode("utf-8"))["query"]
        self.assertIn("[System.WorkItemType] = 'User Story'", query)
        self.assertIn(r"[System.IterationPath] = 'Team Project\Sprint ''26'", query)
        self.assertNotIn(" UNDER ", query)
        self.assertIn("ORDER BY [System.Id] ASC", query)
        top = parse_qs(urlsplit(wiql_requests[0].full_url).query)["$top"]
        self.assertEqual(top, ["2"])
        project_url = self.make_client(opener).project_url
        self.assertTrue(
            all(request.full_url.startswith(project_url) for request in requests)
        )

    def test_list_user_stories_rejects_blank_iteration_path(self) -> None:
        client = self.make_client(lambda request, timeout: self.fail("request ran"))
        with self.assertRaises(ADOConfigurationError):
            client.list_user_stories("   ")

    def test_list_user_stories_rejects_invalid_wiql_response(self) -> None:
        opener = lambda request, timeout: BytesIO(
            json.dumps({"workItems": [{"id": "not-an-id"}]}).encode("utf-8")
        )
        with patch("story_guard.ado_client.WIQL_PAGE_SIZE", 1):
            with self.assertRaises(ADOResponseError):
                self.make_client(opener).list_user_stories("Project\\Sprint")


    def test_fetch_many_stories_records_expected_errors_and_continues(self) -> None:
        requests = []
        project_url = "https://dev.azure.com/storyguard/sample"
        story_payload = {
            "id": 10,
            "fields": {
                "System.WorkItemType": "User Story",
                "System.Title": "Login story",
                "System.State": "New",
                "System.Description": "A test story",
                "System.AreaPath": "Project",
                "System.IterationPath": "Project\\Sprint",
            },
            "relations": [
                {
                    "rel": "System.LinkTypes.Related",
                    "url": f"{project_url}/_apis/wit/workitems/301",
                },
                {
                    "rel": "Microsoft.VSTS.Common.TestedBy-Forward",
                    "url": f"{project_url}/_apis/wit/workitems/401",
                },
                {
                    "rel": "System.LinkTypes.Related",
                    "url": f"{project_url}/_apis/wit/workitems/402",
                },
            ],
        }
        payloads = {
            10: story_payload,
            301: {
                "id": 301,
                "fields": {
                    "System.WorkItemType": "Bug",
                    "System.Title": "Login validation defect",
                    "System.State": "Active",
                    "Microsoft.VSTS.Common.Severity": "2 - High",
                    "Microsoft.VSTS.Common.Priority": 2,
                    "Custom.Age": "12",
                    "System.AssignedTo": {"displayName": "QA Owner"},
                    "System.CreatedDate": "2026-10-01T00:00:00Z",
                },
            },
            401: {
                "id": 401,
                "fields": {
                    "System.WorkItemType": "Test Case",
                    "System.Title": "Submit valid login credentials",
                    "Microsoft.VSTS.TCM.Steps": (
                        "<steps><step><parameterizedString>Enter valid credentials"
                        "</parameterizedString><parameterizedString>Dashboard is shown"
                        "</parameterizedString></step></steps>"
                    ),
                },
            },
            402: {
                "id": 402,
                "fields": {
                    "System.WorkItemType": "Test Case",
                    "System.Title": "Unlinked suite case",
                },
            },
            30: {
                "id": 30,
                "fields": {"System.WorkItemType": "Bug", "System.Title": "Not a story"},
            },
            40: {
                "id": 40,
                "fields": {
                    "System.WorkItemType": "User Story",
                    "System.Title": "Following story",
                    "System.State": "New",
                    "System.Description": "",
                },
            },
            50: {
                "id": 50,
                "fields": {"System.WorkItemType": "Test Case", "System.Title": "Not a story"},
            },
        }

        def opener(request, timeout):
            requests.append(request)
            item_id = int(urlsplit(request.full_url).path.rsplit("/", 1)[-1])
            if item_id == 20:
                raise HTTPError(request.full_url, 404, "Not Found", {}, BytesIO())
            return BytesIO(json.dumps(payloads[item_id]).encode("utf-8"))

        client = self.make_client(opener)
        with patch.dict("os.environ", {}, clear=True):
            results = client.fetch_many_stories([10, 20, 30, 50, 40])

        self.assertEqual([result["id"] for result in results], ["10", "20", "50", "40"])
        self.assertEqual(results[0]["story"]["title"], "Login story")
        self.assertEqual([bug["id"] for bug in results[0]["bugs"]], ["301"])
        self.assertEqual(results[0]["bugs"][0]["linked_story_id"], "10")
        self.assertEqual(
            [case["id"] for case in results[0]["test_cases"]], ["401"]
        )
        self.assertEqual(
            results[0]["test_cases"][0]["steps"],
            [{"action": "Enter valid credentials", "expected_result": "Dashboard is shown"}],
        )
        self.assertEqual(results[1]["error"]["code"], "not_found")
        self.assertEqual(results[2]["error"]["code"], "not_user_story")
        self.assertEqual(results[3]["story"]["title"], "Following story")
        self.assertTrue(all(request.get_method() == "GET" for request in requests))
        self.assertEqual(
            [int(urlsplit(request.full_url).path.rsplit("/", 1)[-1]) for request in requests],
            [10, 301, 401, 402, 20, 30, 50, 40],
        )

    def test_fetch_many_stories_rejects_invalid_ids_before_request(self) -> None:
        client = self.make_client(lambda request, timeout: self.fail("request ran"))
        with self.assertRaises(ADOConfigurationError):
            client.fetch_many_stories([10, 0, 11])


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

    def test_suite_id_finds_its_plan_when_the_story_does_not_link_one(self) -> None:
        loaded = self._load_story_with_suite(test_plan_id=124304)

        self.assertEqual([case["id"] for case in loaded["tests"]], ["124307"])
        case = loaded["tests"][0]
        self.assertEqual(case["suite_id"], "124304")
        self.assertEqual(case["plan_id"], "121214")
        self.assertEqual(case["suite_name"], "US - 123086 , Deepseek TC")
        self.assertEqual(case["mapped_ac_ids"], [])

    def test_linked_test_suites_load_without_a_plan_link(self) -> None:
        loaded = self._load_story_with_suite(link_suite_ids=(124304, 124305))

        self.assertEqual([case["id"] for case in loaded["tests"]], ["124307", "124399"])
        self.assertEqual(
            [case["suite_id"] for case in loaded["tests"]],
            ["124304", "124305"],
        )
        self.assertEqual({case["plan_id"] for case in loaded["tests"]}, {"121214"})

    def test_suite_id_missing_from_every_plan_is_rejected(self) -> None:
        with self.assertRaises(ADORequestError) as caught:
            self._load_story_with_suite(test_plan_id=124304, include_target=False)
        message = str(caught.exception)
        self.assertIn("124304", message)
        self.assertIn("US - 123086 , Deepseek TC", message)
        self.assertIn("no test plan in this project contains it", message)

    def test_linked_suite_missing_from_every_plan_adds_no_tests(self) -> None:
        loaded = self._load_story_with_suite(link_suite_ids=(124304,), include_target=False)
        self.assertEqual(loaded["tests"], [])

    def _load_story_with_suite(
        self,
        test_plan_id: int | None = None,
        link_suite_ids: tuple[int, ...] = (),
        include_target: bool = True,
    ) -> dict:
        """Load a story whose suite sits in a plan the story does not link.

        The owning plan is on the second plans page, and the suite is a child
        of the plan root, so both continuation and the suite tree are required.
        """

        class Page(BytesIO):
            def __init__(self, payload: dict, token: str = "") -> None:
                super().__init__(json.dumps(payload).encode("utf-8"))
                self.headers = {"x-ms-continuationtoken": token} if token else {}

        story = {
            "id": 123086,
            "fields": {
                "System.Title": "SNAP Login Screen - Admin",
                "System.WorkItemType": "User Story",
                "System.State": "New",
                "System.Description": "",
                "Microsoft.VSTS.Common.AcceptanceCriteria": "",
            },
            "relations": [
                {
                    "rel": "System.LinkTypes.Related",
                    "url": f"https://dev.azure.com/example/_apis/wit/workItems/{suite_id}",
                }
                for suite_id in link_suite_ids
            ],
        }
        suites = {
            "124304": {
                "id": 124304,
                "fields": {
                    "System.Title": "US - 123086 , Deepseek TC",
                    "System.WorkItemType": "Test Suite",
                    "System.State": "In Progress",
                },
                "relations": [],
            },
            "124305": {
                "id": 124305,
                "fields": {
                    "System.Title": "Second suite",
                    "System.WorkItemType": "Test Suite",
                    "System.State": "In Progress",
                },
                "relations": [],
            },
        }
        children = []
        if include_target:
            children.append(
                {
                    "id": 124304,
                    "name": "US - 123086 , Deepseek TC",
                    "suiteType": "staticTestSuite",
                }
            )
        if 124305 in link_suite_ids:
            children.append(
                {"id": 124305, "name": "Second suite", "suiteType": "staticTestSuite"}
            )
        tree = {
            "value": [
                {
                    "id": 121215,
                    "name": "Story Guard - AI Agent",
                    "suiteType": "staticTestSuite",
                    "children": children,
                }
            ]
        }
        cases = {
            124304: {"value": [{"workItem": {"id": 124307, "name": "Valid login"}}]},
            124305: {"value": [{"workItem": {"id": 124399, "name": "Show password"}}]},
        }
        allowed = {test_plan_id} if test_plan_id is not None else set(link_suite_ids)
        if not include_target:
            allowed.discard(124304)

        def opener(request, timeout):
            url = request.full_url
            if "/plans/124304/" in url or "/plans/124305/" in url:
                raise HTTPError(url, 404, "Not Found", {}, BytesIO())
            if "/_apis/testplan/plans?" in url:
                if "continuationToken=page-2" in url:
                    body = {"value": [{"id": 121214, "name": "Story Guard - AI Agent"}]}
                    return Page(body)
                body = {"value": [{"id": 27251, "name": "Sprint 1"}]}
                return Page(body, "page-2")
            if "/plans/27251/suites?" in url:
                return Page({"value": [{"id": 27252, "name": "Sprint 1", "suiteType": "staticTestSuite"}]})
            if "/plans/121214/suites?" in url:
                return Page(tree)
            if "/testcase?" in url:
                for suite_id, body in cases.items():
                    if f"/suites/{suite_id}/testcase" in url and suite_id in allowed:
                        return Page(body)
                raise AssertionError(url)
            if "/workitems/124304" in url:
                return Page(suites["124304"])
            if "/workitems/124305" in url:
                return Page(suites["124305"])
            if "/workitems/124307" in url or "/workitems/124399" in url:
                return Page(
                    {
                        "id": 124307,
                        "fields": {
                            "System.Title": "Valid login",
                            "System.WorkItemType": "Test Case",
                        },
                        "relations": [],
                    }
                )
            return Page(story)

        return self.make_client(opener).load_live_story(123086, test_plan_id=test_plan_id)

    def test_sprint_query_reads_user_stories_on_the_iteration_path(self) -> None:
        captured = {}

        def opener(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            body = {"workItems": [{"id": 121213, "url": "https://example/121213"}, {"id": 123086}, {"id": 121213}]}
            return BytesIO(json.dumps(body).encode("utf-8"))

        path = "Ecom MVP\\Ecom phase 2.1 release\\Story Guard - AI Agent"
        ids = self.make_client(opener).story_ids_for_iteration(path)
        request = captured["request"]
        query = json.loads(request.data.decode("utf-8"))["query"]

        self.assertEqual(ids, ["121213", "123086"])
        self.assertEqual(request.get_method(), "POST")
        self.assertTrue(request.full_url.endswith("/_apis/wit/wiql?api-version=7.1"))
        self.assertNotIn("offline-test-pat", request.full_url)
        self.assertNotIn("offline-test-pat", request.data.decode("utf-8"))
        self.assertIn("[System.WorkItemType] = 'User Story'", query)
        self.assertIn(f"[System.IterationPath] = '{path}'", query)
        self.assertNotIn("/workitems/", request.full_url.lower())
        self.assertEqual(captured["timeout"], 15.0)

    def test_case_text_keeps_description_parameters_and_shared_steps(self) -> None:
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
        login_case = {
            "id": 121216,
            "fields": {
                "System.Title": "Valid login",
                "System.WorkItemType": "Test Case",
                "System.Description": "<div>Admin <b>login</b></div>",
                "Microsoft.VSTS.TCM.Steps": (
                    "<steps><step>"
                    "<parameterizedString>Enter email</parameterizedString>"
                    "<parameterizedString>Email is accepted</parameterizedString>"
                    "</step><compref id=\"2\" ref=\"555\"></compref></steps>"
                ),
                "Microsoft.VSTS.TCM.LocalDataSource": (
                    "<NewDataSet><Table1><email>admin@example.com</email></Table1></NewDataSet>"
                ),
            },
            "relations": [],
        }
        shared = {
            "id": 555,
            "fields": {
                "System.Title": "Open login",
                "System.WorkItemType": "Shared Steps",
                "System.Description": "Shared setup",
                "Microsoft.VSTS.TCM.Steps": "<steps><step>Open the login page</step></steps>",
            },
            "relations": [],
        }

        def opener(request, timeout):
            url = request.full_url
            if "/workitems/555" in url:
                body = shared
            elif "/workitems/121216" in url:
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
        case = loaded["tests"][0]

        self.assertIn("Enter email", case["steps"])
        self.assertIn("Email is accepted", case["steps"])
        self.assertIn("Open the login page", case["steps"])
        self.assertIn("Admin login", case["description"])
        self.assertIn("Shared setup", case["description"])
        self.assertIn("admin@example.com", case["parameters"])

    def test_bug_keeps_description_and_repro_steps(self) -> None:
        bug = map_ado_bug(
            {
                "id": 122590,
                "fields": {
                    "System.Title": "Password field rejects characters",
                    "System.WorkItemType": "Bug",
                    "System.State": "New",
                    "System.Description": "<div>The field rejects the typed character.</div>",
                    "Microsoft.VSTS.TCM.ReproSteps": "<div>Type a special character.</div>",
                },
            },
            "123086",
        )

        self.assertEqual(bug["description"], "The field rejects the typed character.")
        self.assertEqual(bug["repro_steps"], "Type a special character.")

    def test_sprint_query_escapes_a_quote_in_the_iteration_path(self) -> None:
        captured = {}

        def opener(request, timeout):
            captured["query"] = json.loads(request.data.decode("utf-8"))["query"]
            return BytesIO(json.dumps({"workItems": []}).encode("utf-8"))

        ids = self.make_client(opener).story_ids_for_iteration("Team's\\Sprint")

        self.assertEqual(ids, [])
        self.assertIn("[System.IterationPath] = 'Team''s\\Sprint'", captured["query"])


if __name__ == "__main__":
    unittest.main()
