"""Read Azure DevOps work items and map them into Story Guard records."""

import base64
import json
import os
from dataclasses import asdict, dataclass
from json import JSONDecodeError
from typing import Any, Callable, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


WIQL_PAGE_SIZE = 100
WORK_ITEMS_BATCH_SIZE = 100
ADO_API_VERSION = "7.1"


class ADOClientError(Exception):
    """Base class for errors that a generation gate should fail closed on."""


class ADOConfigurationError(ADOClientError):
    """Raised when required ADO configuration is absent or invalid."""


class ADORequestError(ADOClientError):
    """Raised when ADO cannot complete a work-item request."""


class ADOResponseError(ADOClientError):
    """Raised when ADO returns an unusable work-item payload."""


class WorkItemNotFoundError(ADOClientError):
    """Raised when ADO does not contain the requested work item."""


class NonStoryWorkItemError(ADOClientError):
    """Raised when the requested work item is not a User Story."""


@dataclass(frozen=True)
class StoryRecord:
    id: str
    title: str
    type: str
    state: str
    description: str
    area: Optional[str]
    iteration: Optional[str]
    raw_ac_text: str
    acceptance_criteria: List[Dict[str, Any]]
    notes: List[str]

    def to_dict(self) -> Dict[str, Any]:
        """Return the record in the fixture schema's JSON shape."""
        return asdict(self)


def map_ado_work_item(payload: Dict[str, Any]) -> StoryRecord:
    """Map one ADO work-item response into the StoryRecord contract."""
    if not isinstance(payload, dict):
        raise ADOResponseError("ADO returned an invalid work-item payload")

    fields = payload.get("fields")
    if not isinstance(fields, dict):
        raise ADOResponseError("ADO work item is missing its fields object")

    work_item_type = fields.get("System.WorkItemType")
    if not isinstance(work_item_type, str):
        raise ADOResponseError("ADO work item is missing its work-item type")
    if work_item_type != "User Story":
        raise NonStoryWorkItemError(
            f"Work item {payload.get('id', 'unknown')} is not a User Story"
        )

    item_id = payload.get("id")
    title = fields.get("System.Title")
    state = fields.get("System.State")
    if item_id is None or not isinstance(title, str) or not isinstance(state, str):
        raise ADOResponseError("ADO work item is missing required story fields")

    raw_ac_text = fields.get("Microsoft.VSTS.Common.AcceptanceCriteria") or ""
    description = fields.get("System.Description") or ""
    if not isinstance(raw_ac_text, str) or not isinstance(description, str):
        raise ADOResponseError("ADO story text fields must be strings")

    area = fields.get("System.AreaPath")
    iteration = fields.get("System.IterationPath")
    if area is not None and not isinstance(area, str):
        raise ADOResponseError("ADO area path must be a string or null")
    if iteration is not None and not isinstance(iteration, str):
        raise ADOResponseError("ADO iteration path must be a string or null")

    return StoryRecord(
        id=str(item_id),
        title=title,
        type=work_item_type,
        state=state,
        description=description,
        area=area,
        iteration=iteration,
        raw_ac_text=raw_ac_text,
        acceptance_criteria=[],
        notes=[],
    )


class ADOClient:
    """Fetch User Story work items from an Azure DevOps project."""

    def __init__(
        self,
        project_url: str,
        pat: str,
        opener: Optional[Callable[..., Any]] = None,
        timeout: float = 15.0,
    ) -> None:
        parsed_url = urlsplit(project_url)
        if (
            parsed_url.scheme != "https"
            or not parsed_url.netloc
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise ADOConfigurationError(
                "ADO_PROJECT_URL must be an HTTPS project URL without a query or fragment"
            )
        if not pat.strip():
            raise ADOConfigurationError("ADO_PAT must not be empty")

        self.project_url = project_url.rstrip("/")
        self.pat = pat
        self.opener = opener or urlopen
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "ADOClient":
        """Build a client from ADO_PROJECT_URL and ADO_PAT environment variables."""
        project_url = os.environ.get("ADO_PROJECT_URL")
        pat = os.environ.get("ADO_PAT")
        missing = [
            name
            for name, value in (
                ("ADO_PROJECT_URL", project_url),
                ("ADO_PAT", pat),
            )
            if not value
        ]
        if missing:
            raise ADOConfigurationError(
                "Missing required environment variable(s): " + ", ".join(missing)
            )
        return cls(project_url=project_url, pat=pat)

    def get_story(self, work_item_id: int) -> StoryRecord:
        """Fetch a work item with relations and require it to be a User Story."""
        payload = self._get_work_item_payload(work_item_id, expand_relations=True)
        return map_ado_work_item(payload)

    def fetch_many_stories(self, story_ids: List[int]) -> List[Dict[str, Any]]:
        """Fetch each story and its direct linked Bugs and Tested By cases."""
        if not isinstance(story_ids, list) or any(
            isinstance(story_id, bool)
            or not isinstance(story_id, int)
            or story_id <= 0
            for story_id in story_ids
        ):
            raise ADOConfigurationError("story IDs must be a list of positive integers")

        results = []
        for story_id in story_ids:
            try:
                payload = self._get_work_item_payload(
                    story_id, expand_relations=True
                )
                story = map_ado_work_item(payload)
            except WorkItemNotFoundError as error:
                results.append(
                    {
                        "id": str(story_id),
                        "error": {"code": "not_found", "message": str(error)},
                    }
                )
                continue
            except NonStoryWorkItemError as error:
                results.append(
                    {
                        "id": str(story_id),
                        "error": {"code": "not_user_story", "message": str(error)},
                    }
                )
                continue

            bugs, test_cases = self._linked_records(payload, story.id)
            results.append(
                {
                    "id": story.id,
                    "story": story.to_dict(),
                    "bugs": bugs,
                    "test_cases": test_cases,
                }
            )
        return results

    def _get_work_item_payload(
        self,
        work_item_id: int,
        expand_relations: bool = False,
    ) -> Dict[str, Any]:
        if isinstance(work_item_id, bool) or not isinstance(work_item_id, int):
            raise ValueError("work_item_id must be an integer")
        if work_item_id <= 0:
            raise ValueError("work_item_id must be a positive integer")

        params = {"api-version": ADO_API_VERSION}
        if expand_relations:
            params["$expand"] = "relations"
        query = urlencode(params)
        url = f"{self.project_url}/_apis/wit/workitems/{work_item_id}?{query}"
        request = Request(url, headers=self._headers())
        return self._request_json(
            request,
            "work-item",
            not_found_message=f"ADO work item {work_item_id} was not found",
        )

    def _linked_records(
        self,
        story_payload: Dict[str, Any],
        story_id: str,
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        relations = story_payload.get("relations") or []
        if not isinstance(relations, list):
            raise ADOResponseError("ADO story relations are not a list")

        targets: Dict[int, bool] = {}
        for relation in relations:
            if not isinstance(relation, dict):
                raise ADOResponseError("ADO story relation is not an object")
            relation_type = relation.get("rel")
            if not isinstance(relation_type, str):
                continue
            relation_name = relation_type.lower()
            is_tested_by = "testedby" in relation_name
            if "system.linktypes." not in relation_name and not is_tested_by:
                continue
            target_id = self._relation_target_id(relation.get("url"))
            if target_id is None:
                continue
            targets[target_id] = targets.get(target_id, False) or is_tested_by

        bugs = []
        test_cases = []
        for work_item_id, is_tested_by in targets.items():
            payload = self._get_work_item_payload(work_item_id)
            fields = payload.get("fields")
            if not isinstance(fields, dict):
                raise ADOResponseError(
                    f"Linked work item {work_item_id} is missing its fields object"
                )
            work_item_type = fields.get("System.WorkItemType")
            if not isinstance(work_item_type, str):
                raise ADOResponseError(
                    f"Linked work item {work_item_id} is missing its type"
                )
            if work_item_type == "Bug":
                bugs.append(self._bug_record(payload, story_id))
            elif work_item_type == "Test Case" and is_tested_by:
                test_cases.append(self._test_case(payload))
        return bugs, test_cases

    @staticmethod
    def _relation_target_id(url: object) -> Optional[int]:
        if not isinstance(url, str):
            return None
        final_segment = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
        if not final_segment.isdigit():
            return None
        return int(final_segment)

    @staticmethod
    def _string_value(value: object) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
        return ""

    @staticmethod
    def _record_id(payload: Dict[str, Any]) -> str:
        work_item_id = payload.get("id")
        if isinstance(work_item_id, bool) or not isinstance(work_item_id, int):
            raise ADOResponseError("ADO linked work item has an invalid ID")
        return str(work_item_id)

    @staticmethod
    def _bug_record(payload: Dict[str, Any], story_id: str) -> Dict[str, Any]:
        fields = payload["fields"]
        title = fields.get("System.Title")
        if not isinstance(title, str):
            raise ADOResponseError("ADO Bug is missing its title")

        priority_value = fields.get("Microsoft.VSTS.Common.Priority")
        priority_text = ADOClient._string_value(priority_value)
        if priority_text in {"1", "2", "3", "4"}:
            priority_text = f"P{priority_text}"
        elif priority_text not in {"P1", "P2", "P3", "P4"}:
            priority_text = ""

        assigned_to = fields.get("System.AssignedTo")
        if isinstance(assigned_to, dict):
            assigned_to = assigned_to.get("displayName", "")

        age = fields.get("Custom.Age", "")
        if isinstance(age, bool) or not isinstance(age, (int, str)):
            age = ""
        return {
            "id": ADOClient._record_id(payload),
            "title": title,
            "severity": ADOClient._string_value(
                fields.get("Microsoft.VSTS.Common.Severity")
            ),
            "priority": priority_text,
            "status": ADOClient._string_value(fields.get("System.State")),
            "age": age,
            "found_in": ADOClient._string_value(
                fields.get("Microsoft.VSTS.Build.FoundIn")
            ),
            "linked_story_id": story_id,
            "linked_tc_id": "",
            "assigned_to": ADOClient._string_value(assigned_to),
            "application": ADOClient._string_value(fields.get("Custom.Application")),
            "created": ADOClient._string_value(fields.get("System.CreatedDate")),
        }

    @staticmethod
    def _test_case(payload: Dict[str, Any]) -> Dict[str, Any]:
        fields = payload["fields"]
        title = fields.get("System.Title")
        if not isinstance(title, str):
            raise ADOResponseError("ADO Test Case is missing its title")

        type_value = fields.get("Custom.TestType", "")
        if not isinstance(type_value, str) or type_value not in {
            "happy",
            "negative",
            "edge",
            "security",
            "adhoc",
            "",
        }:
            type_value = ""
        return {
            "id": ADOClient._record_id(payload),
            "title": title,
            "type": type_value,
            "mapped_ac_ids": [],
            "last_result": "",
            "last_result_at": None,
            "linked_bug_ids": [],
            "steps": ADOClient._test_steps(
                fields.get("Microsoft.VSTS.TCM.Steps")
            ),
        }

    @staticmethod
    def _test_steps(value: object) -> List[Dict[str, str]]:
        if value is None or value == "":
            return []
        if not isinstance(value, str):
            raise ADOResponseError("ADO test-case steps are not text")

        from html import unescape
        from re import sub
        from xml.etree import ElementTree

        try:
            root = ElementTree.fromstring(value)
        except ElementTree.ParseError as error:
            raise ADOResponseError("ADO test-case steps are invalid XML") from error

        def text(element) -> str:
            raw = "".join(element.itertext())
            return " ".join(sub(r"<[^>]*>", " ", unescape(raw)).split())

        steps = []
        for step in root.findall(".//step"):
            values = step.findall("parameterizedString")
            if len(values) < 2:
                raise ADOResponseError("ADO test-case step is missing action or expected result")
            steps.append(
                {"action": text(values[0]), "expected_result": text(values[1])}
            )
        return steps

    def list_iterations(self) -> List[str]:
        """Return iteration paths configured for the current project."""
        query = urlencode({"$depth": 14, "api-version": ADO_API_VERSION})
        request = Request(
            f"{self.project_url}/_apis/wit/classificationnodes/Iterations?{query}",
            headers=self._headers(),
        )
        payload = self._request_json(request, "iteration list")
        children = payload.get("children", [])
        if not isinstance(children, list):
            raise ADOResponseError("ADO iteration response is missing its children list")

        paths = []
        pending = list(reversed(children))
        while pending:
            node = pending.pop()
            if not isinstance(node, dict) or not isinstance(node.get("path"), str):
                raise ADOResponseError("ADO iteration response contains an invalid node")
            paths.append(node["path"])
            node_children = node.get("children", [])
            if not isinstance(node_children, list):
                raise ADOResponseError("ADO iteration response contains an invalid children list")
            pending.extend(reversed(node_children))
        return paths

    def list_user_stories(self, iteration_path: str) -> List[Dict[str, str]]:
        """Return all User Stories in the exact iteration path, ordered by ID."""
        if not isinstance(iteration_path, str) or not iteration_path.strip():
            raise ADOConfigurationError("iteration path must not be empty")

        escaped_path = iteration_path.replace("'", "''")
        cursor = 0
        stories = []
        while True:
            wiql = (
                "SELECT [System.Id] FROM WorkItems "
                "WHERE [System.WorkItemType] = 'User Story' "
                f"AND [System.IterationPath] = '{escaped_path}' "
                f"AND [System.Id] > {cursor} "
                "ORDER BY [System.Id] ASC"
            )
            page_ids = self._query_wiql(wiql)
            if not page_ids:
                break
            if len(page_ids) > WIQL_PAGE_SIZE or any(
                work_item_id <= cursor for work_item_id in page_ids
            ) or page_ids != sorted(set(page_ids)):
                raise ADOResponseError("ADO returned an invalid WIQL page")

            details = {}
            for offset in range(0, len(page_ids), WORK_ITEMS_BATCH_SIZE):
                batch = page_ids[offset : offset + WORK_ITEMS_BATCH_SIZE]
                details.update(self._get_work_items(batch))

            for work_item_id in page_ids:
                item = details.get(work_item_id)
                if item is None:
                    raise ADOResponseError(
                        f"ADO did not return queried work item {work_item_id}"
                    )
                if item["type"] == "User Story":
                    stories.append(
                        {"id": str(work_item_id), "title": item["title"]}
                    )

            cursor = page_ids[-1]
            if len(page_ids) < WIQL_PAGE_SIZE:
                break

        return stories

    def _headers(self) -> Dict[str, str]:
        credentials = base64.b64encode(f":{self.pat}".encode("utf-8")).decode("ascii")
        return {
            "Accept": "application/json",
            "Authorization": f"Basic {credentials}",
        }

    def _request_json(
        self,
        request: Request,
        operation: str,
        not_found_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            with self.opener(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except HTTPError as error:
            if error.code == 404 and not_found_message:
                raise WorkItemNotFoundError(not_found_message) from error
            if error.code in {401, 403}:
                raise ADOConfigurationError(
                    "ADO configuration error: ADO_PAT cannot read the configured project; "
                    "check the PAT and project permissions"
                ) from error
            raise ADORequestError(
                f"ADO {operation} request failed with HTTP status {error.code}"
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise ADORequestError(f"ADO {operation} request failed") from error
        except JSONDecodeError as error:
            raise ADOResponseError("ADO returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise ADOResponseError(f"ADO {operation} response was not an object")
        return payload

    def _query_wiql(self, wiql: str) -> List[int]:
        query = urlencode({"$top": WIQL_PAGE_SIZE, "api-version": ADO_API_VERSION})
        request = Request(
            f"{self.project_url}/_apis/wit/wiql?{query}",
            data=json.dumps({"query": wiql}).encode("utf-8"),
            headers={**self._headers(), "Content-Type": "application/json"},
            method="POST",
        )
        payload = self._request_json(request, "WIQL")
        items = payload.get("workItems")
        if not isinstance(items, list):
            raise ADOResponseError("ADO WIQL response is missing its workItems list")

        ids = []
        for item in items:
            work_item_id = item.get("id") if isinstance(item, dict) else None
            if (
                isinstance(work_item_id, bool)
                or not isinstance(work_item_id, int)
                or work_item_id <= 0
            ):
                raise ADOResponseError("ADO WIQL response contains an invalid work item ID")
            ids.append(work_item_id)
        return ids

    def _get_work_items(self, work_item_ids: List[int]) -> Dict[int, Dict[str, str]]:
        query = urlencode(
            {
                "ids": ",".join(str(work_item_id) for work_item_id in work_item_ids),
                "fields": "System.Id,System.Title,System.WorkItemType",
                "api-version": ADO_API_VERSION,
            }
        )
        request = Request(
            f"{self.project_url}/_apis/wit/workitems?{query}",
            headers=self._headers(),
        )
        payload = self._request_json(request, "work-item list")
        items = payload.get("value")
        if not isinstance(items, list):
            raise ADOResponseError("ADO work-item list response is missing its value list")

        details = {}
        requested_ids = set(work_item_ids)
        for item in items:
            work_item_id = item.get("id") if isinstance(item, dict) else None
            fields = item.get("fields") if isinstance(item, dict) else None
            if (
                isinstance(work_item_id, bool)
                or not isinstance(work_item_id, int)
                or work_item_id not in requested_ids
                or work_item_id in details
                or not isinstance(fields, dict)
            ):
                raise ADOResponseError("ADO returned an invalid work-item list entry")
            work_item_type = fields.get("System.WorkItemType")
            if not isinstance(work_item_type, str):
                raise ADOResponseError("ADO work item is missing its type")
            title = fields.get("System.Title")
            if work_item_type == "User Story" and not isinstance(title, str):
                raise ADOResponseError("ADO User Story is missing its title")
            details[work_item_id] = {
                "type": work_item_type,
                "title": title if isinstance(title, str) else "",
            }
        return details
