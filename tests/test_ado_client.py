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


if __name__ == "__main__":
    unittest.main()
