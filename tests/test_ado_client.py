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


if __name__ == "__main__":
    unittest.main()
