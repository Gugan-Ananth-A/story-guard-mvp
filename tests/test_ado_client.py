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
    ADOResponseError,
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


if __name__ == "__main__":
    unittest.main()
