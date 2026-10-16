"""Read Azure DevOps work items and map them into Story Guard records."""

import base64
import json
import os
import re
from dataclasses import asdict, dataclass
from html import unescape
from datetime import datetime, timezone
from json import JSONDecodeError
from typing import Any, Callable, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


class ADOClientError(Exception):
    """Base class for errors that a generation gate should fail closed on."""


class ADOConfigurationError(ADOClientError):
    """Raised when required ADO configuration is absent or invalid."""


class ADORequestError(ADOClientError):
    """Raised when ADO cannot complete a work-item request."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


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


def _require_work_item_id(work_item_id: int) -> None:
    if isinstance(work_item_id, bool) or not isinstance(work_item_id, int):
        raise ValueError("work_item_id must be an integer")
    if work_item_id <= 0:
        raise ValueError("work_item_id must be a positive integer")


def _plan_ids(items: List[Dict[str, Any]]) -> List[int]:
    plan_ids = []
    for item in items:
        if _work_item_type(item) != "Test Plan":
            continue
        item_id = item.get("id")
        if isinstance(item_id, bool) or not isinstance(item_id, int):
            continue
        plan_ids.append(item_id)
    return plan_ids


def _bugs_from_linked(items: List[Dict[str, Any]], story_id: str) -> List[Dict[str, Any]]:
    bugs = []
    for item in items:
        if _work_item_type(item) != "Bug":
            continue
        bug = map_ado_bug(item, story_id)
        if bug is not None:
            bugs.append(bug)
    return bugs


def _merge_direct_cases(
    cases: List[Dict[str, Any]],
    linked: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Add a Test Case that is linked on the story and is not already in a plan suite."""
    seen = {str(case.get("id")) for case in cases if isinstance(case, dict)}
    merged = list(cases)
    for item in linked:
        if _work_item_type(item) != "Test Case":
            continue
        item_id = item.get("id")
        if isinstance(item_id, bool) or not isinstance(item_id, int):
            continue
        key = str(item_id)
        if key in seen:
            continue
        seen.add(key)
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
        title = fields.get("System.Title")
        merged.append(
            {
                "id": key,
                "title": title if isinstance(title, str) else "",
                "type": "",
                "mapped_ac_ids": [],
                "last_result": "",
                "last_result_at": None,
                "linked_bug_ids": [],
            }
        )
    return merged


def _relation_work_item_id(relation: object) -> Optional[int]:
    if not isinstance(relation, dict):
        return None
    url = str(relation.get("url") or "")
    if "/workitems/" not in url.lower():
        return None
    target = url.rstrip("/").split("/")[-1]
    if not target.isdigit():
        return None
    return int(target)


def _plain_steps(value: object) -> str:
    """Turn an Azure DevOps steps field into one line of text."""
    if not isinstance(value, str):
        return ""
    text = unescape(value)
    text = re.sub(r"(?i)<br\s*/?>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _test_case_from_plan_row(
    row: object,
    suite: Dict[str, Any],
    plan_id: int,
) -> Dict[str, Any]:
    """Map one Test Plans row onto the fixture TestCase keys.

    Suite membership does not set mapped_ac_ids. The P/N/A title prefix is not type.
    """
    work_item = row.get("workItem") if isinstance(row, dict) else None
    if not isinstance(work_item, dict):
        raise ADOResponseError("ADO test case is missing its work item")
    item_id = work_item.get("id")
    title = work_item.get("name")
    if isinstance(item_id, bool) or not isinstance(item_id, int) or not isinstance(title, str):
        raise ADOResponseError("ADO test case is missing its id or title")
    suite_name = suite.get("name")
    suite_type = suite.get("suiteType")
    return {
        "id": str(item_id),
        "title": title,
        "type": "",
        "mapped_ac_ids": [],
        "last_result": "",
        "last_result_at": None,
        "linked_bug_ids": [],
        "suite_id": str(suite.get("id") or ""),
        "suite_name": suite_name if isinstance(suite_name, str) else "",
        "suite_type": suite_type if isinstance(suite_type, str) else "",
        "plan_id": str(plan_id),
    }


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


def map_ado_bug(payload: Dict[str, Any], story_id: str) -> Optional[Dict[str, Any]]:
    """Map a Bug work item into the fixture bug record. A payload without an id is skipped."""
    if not isinstance(payload, dict):
        return None
    item_id = payload.get("id")
    if isinstance(item_id, bool) or not isinstance(item_id, int):
        return None
    fields = payload.get("fields")
    if not isinstance(fields, dict):
        fields = {}
    title = fields.get("System.Title")
    state = fields.get("System.State")
    created = fields.get("System.CreatedDate") or ""
    return {
        "id": str(item_id),
        "title": title if isinstance(title, str) else "",
        "severity": _text(fields.get("Microsoft.VSTS.Common.Severity")),
        "priority": _priority_label(fields.get("Microsoft.VSTS.Common.Priority")),
        "status": state if isinstance(state, str) else "",
        "age": _age_days(created),
        "found_in": _text(fields.get("Custom.Environment")),
        "linked_story_id": story_id,
        "linked_tc_id": "",
        "assigned_to": _person_name(fields.get("System.AssignedTo")),
        "application": _text(fields.get("System.AreaPath")),
        "created": _created_date(created),
    }


def _work_item_type(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    fields = payload.get("fields")
    if not isinstance(fields, dict):
        return ""
    value = fields.get("System.WorkItemType")
    return value if isinstance(value, str) else ""


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _priority_label(value: object) -> str:
    """ADO stores priority as 1–4. The score reads the P1–P4 token."""
    if isinstance(value, bool):
        return ""
    if isinstance(value, int) and 1 <= value <= 4:
        return f"P{value}"
    text = str(value or "").strip().upper()
    if text in {"1", "2", "3", "4"}:
        return f"P{text}"
    if text in {"P1", "P2", "P3", "P4"}:
        return text
    return ""


def _person_name(value: object) -> str:
    if isinstance(value, dict):
        name = value.get("displayName") or value.get("uniqueName") or ""
        return str(name)
    if isinstance(value, str):
        return value
    return ""


def _created_date(value: object) -> str:
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else ""


def _age_days(value: object) -> int | str:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        created = datetime.fromisoformat(text)
    except ValueError:
        return ""
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - created).days)


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
        from story_guard.envfile import load_env_file

        load_env_file()
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
        return map_ado_work_item(self.get_work_item(work_item_id))

    def get_work_item(self, work_item_id: int) -> Dict[str, Any]:
        """Fetch one work item, including its relations."""
        _require_work_item_id(work_item_id)
        query = urlencode({"$expand": "relations", "api-version": "7.1"})
        url = f"{self.project_url}/_apis/wit/workitems/{work_item_id}?{query}"
        return self._get_json(url, work_item_id=work_item_id)

    def load_live_story(
        self,
        story_id: int,
        test_plan_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Load a User Story, its linked bugs, and cases from a linked test plan.

        A related work item Azure DevOps no longer returns is skipped. The plan
        link puts those cases on the story. It is not an acceptance-criteria
        mapping, so each case keeps an empty mapped_ac_ids list.
        """
        payload = self.get_work_item(story_id)
        story = map_ado_work_item(payload).to_dict()
        linked = self._linked_items(payload)
        plan_ids, suite_id = self._resolve_plan_ids(payload, test_plan_id, linked)
        story["tests"] = _merge_direct_cases(
            self.fetch_test_cases(plan_ids, suite_id=suite_id),
            linked,
        )
        self._attach_case_steps(story["tests"])
        story["bugs"] = _bugs_from_linked(linked, story["id"])
        return story

    def linked_test_plan_ids(self, payload: Dict[str, Any]) -> List[int]:
        """Return related work items whose type is Test Plan."""
        return _plan_ids(self._linked_items(payload))

    def _linked_items(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fetch related work items. A missing link is skipped."""
        if not isinstance(payload, dict):
            raise ADOResponseError("ADO returned an invalid work-item payload")
        items = []
        seen = set()
        for relation in payload.get("relations") or []:
            target_id = _relation_work_item_id(relation)
            if target_id is None or target_id in seen:
                continue
            seen.add(target_id)
            try:
                items.append(self.get_work_item(target_id))
            except WorkItemNotFoundError:
                continue
        return items

    def _resolve_plan_ids(
        self,
        payload: Dict[str, Any],
        test_plan_id: Optional[int],
        linked: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[List[int], Optional[int]]:
        """Return plan ids and, when the caller passed a suite id, that suite."""
        if test_plan_id is None:
            items = linked if linked is not None else self._linked_items(payload)
            return _plan_ids(items), None
        _require_work_item_id(test_plan_id)
        if self._plan_suites(test_plan_id) is not None:
            return [test_plan_id], None
        related = self.get_work_item(test_plan_id)
        fields = related.get("fields") if isinstance(related, dict) else None
        work_item_type = fields.get("System.WorkItemType") if isinstance(fields, dict) else ""
        if work_item_type != "Test Suite":
            raise ADORequestError(
                f"ADO work item {test_plan_id} is not a test plan or a test suite"
            )
        for plan_id in self.linked_test_plan_ids(payload):
            suites = self._plan_suites(plan_id) or []
            if any(isinstance(suite, dict) and suite.get("id") == test_plan_id for suite in suites):
                return [plan_id], test_plan_id
        title = fields.get("System.Title") if isinstance(fields, dict) else ""
        name = title if isinstance(title, str) and title else "test suite"
        raise ADORequestError(
            f"ADO work item {test_plan_id} is test suite {name}, not a test plan. "
            "Link its test plan to the story, or pass that plan id."
        )

    def fetch_test_cases(
        self,
        plan_ids: List[int],
        suite_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Load the cases in each plan's suites. The same case id is kept once."""
        cases = []
        seen = set()
        for plan_id in plan_ids:
            _require_work_item_id(plan_id)
            for case in self._cases_in_plan(plan_id, suite_id=suite_id):
                if case["id"] in seen:
                    continue
                seen.add(case["id"])
                cases.append(case)
        return cases

    def _plan_suites(self, plan_id: int) -> Optional[List[Any]]:
        suites_url = (
            f"{self.project_url}/_apis/testplan/plans/{plan_id}/suites"
            "?api-version=7.1"
        )
        try:
            suites_payload = self._get_json(suites_url)
        except ADORequestError as error:
            if error.status_code == 404:
                return None
            raise
        suites = suites_payload.get("value") if isinstance(suites_payload, dict) else None
        if not isinstance(suites, list):
            raise ADOResponseError("ADO test plan suites payload is missing its value list")
        return suites

    def _attach_case_steps(self, cases: List[Dict[str, Any]]) -> None:
        """Copy plain test steps onto each case. A missing case leaves the steps blank."""
        for case in cases:
            if not isinstance(case, dict):
                continue
            case_id = str(case.get("id") or "")
            if not case_id.isdigit():
                case["steps"] = ""
                continue
            try:
                item = self.get_work_item(int(case_id))
            except WorkItemNotFoundError:
                case["steps"] = ""
                continue
            fields = item.get("fields") if isinstance(item, dict) else None
            raw = fields.get("Microsoft.VSTS.TCM.Steps") if isinstance(fields, dict) else ""
            case["steps"] = _plain_steps(raw)

    def _cases_in_plan(self, plan_id: int, suite_id: Optional[int] = None) -> List[Dict[str, Any]]:
        suites = self._plan_suites(plan_id)
        if suites is None:
            raise ADORequestError(
                f"ADO test plan {plan_id} was not found",
                status_code=404,
            )
        if suite_id is not None and not any(
            isinstance(suite, dict) and suite.get("id") == suite_id for suite in suites
        ):
            raise ADORequestError(
                f"ADO test plan {plan_id} does not contain suite {suite_id}"
            )

        cases = []
        for suite in suites:
            if not isinstance(suite, dict) or not isinstance(suite.get("id"), int):
                continue
            if suite_id is not None and suite["id"] != suite_id:
                continue
            cases_url = (
                f"{self.project_url}/_apis/testplan/plans/{plan_id}/suites/"
                f"{suite['id']}/testcase?api-version=7.1"
            )
            case_payload = self._get_json(cases_url)
            rows = case_payload.get("value") if isinstance(case_payload, dict) else None
            if not isinstance(rows, list):
                raise ADOResponseError("ADO test case payload is missing its value list")
            for row in rows:
                cases.append(_test_case_from_plan_row(row, suite, plan_id))
        return cases

    def _get_json(self, url: str, work_item_id: Optional[int] = None) -> Dict[str, Any]:
        credentials = base64.b64encode(f":{self.pat}".encode("utf-8")).decode("ascii")
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Basic {credentials}",
            },
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except HTTPError as error:
            if error.code == 404 and work_item_id is not None:
                raise WorkItemNotFoundError(
                    f"ADO work item {work_item_id} was not found"
                ) from error
            raise ADORequestError(
                f"ADO request failed with HTTP status {error.code}",
                status_code=error.code,
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise ADORequestError("ADO work-item request failed") from error
        except JSONDecodeError as error:
            raise ADOResponseError("ADO returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise ADOResponseError("ADO returned an invalid JSON payload")
        return payload
