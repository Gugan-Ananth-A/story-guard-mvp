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


WIQL_PAGE_SIZE = 100
WORK_ITEMS_BATCH_SIZE = 100
ADO_API_VERSION = "7.1"


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
    return _ids_of_type(items, "Test Plan")


def _suite_ids(items: List[Dict[str, Any]]) -> List[int]:
    return _ids_of_type(items, "Test Suite")


def _ids_of_type(items: List[Dict[str, Any]], work_item_type: str) -> List[int]:
    found = []
    for item in items:
        if _work_item_type(item) != work_item_type:
            continue
        item_id = item.get("id")
        if isinstance(item_id, bool) or not isinstance(item_id, int):
            continue
        found.append(item_id)
    return found


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


def _continuation_token(response: object) -> Optional[str]:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    token = headers.get("x-ms-continuationtoken")
    if not isinstance(token, str) or token == "":
        return None
    return token


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
    """Turn an Azure DevOps HTML or XML field into one line of text."""
    if not isinstance(value, str):
        return ""
    text = unescape(value)
    text = re.sub(r"(?i)<br\s*/?>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _element_text(element: object) -> str:
    raw = "".join(getattr(element, "itertext", lambda: [])())
    return " ".join(re.sub(r"<[^>]*>", " ", unescape(raw)).split())


def _step_pairs_from_xml(value: object) -> List[Dict[str, str]]:
    """Keep each step's action and expected result. Odd markup stays as an action."""
    if not isinstance(value, str) or not value.strip():
        return []
    from xml.etree import ElementTree

    try:
        root = ElementTree.fromstring(value)
    except ElementTree.ParseError:
        plain = _plain_steps(value)
        return [{"action": plain, "expected_result": ""}] if plain else []
    pairs = []
    for step in root.findall(".//step"):
        values = step.findall("parameterizedString")
        if len(values) >= 2:
            action = _element_text(values[0])
            expected = _element_text(values[1])
        else:
            action = _element_text(step)
            expected = ""
        if action or expected:
            pairs.append({"action": action, "expected_result": expected})
    return pairs


def _shared_step_ids(value: str) -> List[int]:
    """Work item ids referenced by shared-step tags. The order is the document order."""
    found: List[int] = []
    for token in re.findall(r'(?i)<compref\b[^>]*\bref="(\d+)"', value):
        number = int(token)
        if number not in found:
            found.append(number)
    return found


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
        "description": _plain_steps(fields.get("System.Description")),
        "repro_steps": _plain_steps(fields.get("Microsoft.VSTS.TCM.ReproSteps")),
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
        """Load a User Story, its linked bugs, and cases from a linked plan or suite.

        A related work item Azure DevOps no longer returns is skipped. A linked
        Test Plan contributes every suite in that plan. A linked Test Suite, or
        a suite id passed as test_plan_id, contributes only that suite. The link
        is not an acceptance-criteria mapping, so each case keeps an empty
        mapped_ac_ids list.
        """
        payload = self.get_work_item(story_id)
        story = map_ado_work_item(payload).to_dict()
        linked = self._linked_items(payload)
        cases: List[Dict[str, Any]] = []
        seen_case_ids = set()
        for plan_id, suite_id in self._resolve_case_sources(payload, test_plan_id, linked):
            for case in self.fetch_test_cases([plan_id], suite_id=suite_id):
                if case["id"] in seen_case_ids:
                    continue
                seen_case_ids.add(case["id"])
                cases.append(case)
        story["tests"] = _merge_direct_cases(cases, linked)
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

    def _resolve_case_sources(
        self,
        payload: Dict[str, Any],
        test_plan_id: Optional[int],
        linked: Optional[List[Dict[str, Any]]] = None,
    ) -> List[tuple[int, Optional[int]]]:
        """Return plan and suite pairs to read.

        A missing suite id means every suite in that plan. A Test Suite id,
        either passed in or linked from the story, is read from the plan that
        contains it even when the story does not link that plan.
        """
        if test_plan_id is None:
            items = linked if linked is not None else self._linked_items(payload)
            sources: List[tuple[int, Optional[int]]] = [
                (plan_id, None) for plan_id in _plan_ids(items)
            ]
            full_plans = {plan_id for plan_id, _suite_id in sources}
            for suite_id in _suite_ids(items):
                owner = self._plan_id_containing_suite(suite_id, prefer=list(full_plans))
                if owner is None or owner in full_plans:
                    continue
                sources.append((owner, suite_id))
            return sources
        _require_work_item_id(test_plan_id)
        if self._plan_suites(test_plan_id) is not None:
            return [(test_plan_id, None)]
        related = self.get_work_item(test_plan_id)
        fields = related.get("fields") if isinstance(related, dict) else None
        work_item_type = fields.get("System.WorkItemType") if isinstance(fields, dict) else ""
        if work_item_type != "Test Suite":
            raise ADORequestError(
                f"ADO work item {test_plan_id} is not a test plan or a test suite"
            )
        owner = self._plan_id_containing_suite(
            test_plan_id,
            prefer=self.linked_test_plan_ids(payload),
        )
        if owner is not None:
            return [(owner, test_plan_id)]
        title = fields.get("System.Title") if isinstance(fields, dict) else ""
        name = title if isinstance(title, str) and title else "test suite"
        raise ADORequestError(
            f"ADO work item {test_plan_id} is test suite {name}, "
            "and no test plan in this project contains it."
        )

    def _plan_id_containing_suite(
        self,
        suite_id: int,
        prefer: Optional[List[int]] = None,
    ) -> Optional[int]:
        """Return the plan that contains suite_id, checking linked plans first."""
        checked = set()
        for plan_id in prefer or []:
            checked.add(plan_id)
            if self._suite_in_plan(plan_id, suite_id):
                return plan_id
        for plan_id in self._project_plan_ids():
            if plan_id in checked:
                continue
            checked.add(plan_id)
            if self._suite_in_plan(plan_id, suite_id):
                return plan_id
        return None

    def _suite_in_plan(self, plan_id: int, suite_id: int) -> bool:
        suites = self._iter_suites(self._plan_suites(plan_id))
        return any(suite.get("id") == suite_id for suite in suites)

    def _project_plan_ids(self) -> List[int]:
        """Return test plan ids in this project. The read follows continuation pages."""
        ids: List[int] = []
        seen_ids = set()
        seen_tokens = set()
        token: Optional[str] = None
        while True:
            params = {"api-version": "7.1"}
            if token:
                params["continuationToken"] = token
            url = f"{self.project_url}/_apis/testplan/plans?{urlencode(params)}"
            payload, next_token = self._exchange(url)
            plans = payload.get("value") if isinstance(payload, dict) else None
            if not isinstance(plans, list):
                raise ADOResponseError("ADO test plan response is missing its value list")
            for plan in plans:
                if not isinstance(plan, dict):
                    continue
                plan_id = plan.get("id")
                if isinstance(plan_id, bool) or not isinstance(plan_id, int) or plan_id <= 0:
                    continue
                if plan_id in seen_ids:
                    continue
                seen_ids.add(plan_id)
                ids.append(plan_id)
            if not next_token or next_token in seen_tokens:
                break
            seen_tokens.add(next_token)
            token = next_token
        return ids

    def story_ids_for_iteration(self, iteration_path: str) -> List[str]:
        """Return User Story ids on one iteration path.

        WIQL is a read query. This POST does not update a work item.
        """
        path = iteration_path.strip()
        if path == "":
            raise ADORequestError("iteration path is blank")
        escaped = path.replace("'", "''")
        query = (
            "SELECT [System.Id] FROM WorkItems "
            "WHERE [System.WorkItemType] = 'User Story' "
            f"AND [System.IterationPath] = '{escaped}' "
            "ORDER BY [System.Id]"
        )
        payload = self._post_json(
            f"{self.project_url}/_apis/wit/wiql?api-version=7.1",
            {"query": query},
        )
        items = payload.get("workItems")
        if not isinstance(items, list):
            raise ADOResponseError("ADO sprint query is missing its work item list")
        ids: List[str] = []
        seen = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            if isinstance(item_id, bool) or not isinstance(item_id, int) or item_id <= 0:
                continue
            key = str(item_id)
            if key in seen:
                continue
            seen.add(key)
            ids.append(key)
        return ids

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

    def _iter_suites(self, suites: Optional[List[Any]]) -> List[Dict[str, Any]]:
        """Flatten a suite list, including children when the API returns a tree."""
        found: List[Dict[str, Any]] = []
        pending = list(suites or [])
        seen: set[int] = set()
        while pending:
            suite = pending.pop()
            if not isinstance(suite, dict):
                continue
            marker = id(suite)
            if marker in seen:
                continue
            seen.add(marker)
            found.append(suite)
            children = suite.get("children")
            if isinstance(children, list):
                pending.extend(children)
        return found

    def _attach_case_steps(self, cases: List[Dict[str, Any]]) -> None:
        """Copy the full case text onto each case. A missing case leaves the text blank.

        Title stays on the plan row. This adds the description, the steps, the
        parameters, and the text of any shared step the case points at.
        """
        for case in cases:
            if not isinstance(case, dict):
                continue
            case_id = str(case.get("id") or "")
            if not case_id.isdigit():
                case["steps"] = ""
                case["step_pairs"] = []
                case["description"] = ""
                case["parameters"] = ""
                continue
            try:
                item = self.get_work_item(int(case_id))
            except WorkItemNotFoundError:
                case["steps"] = ""
                case["step_pairs"] = []
                case["description"] = ""
                case["parameters"] = ""
                continue
            steps, description, parameters, pairs = self._case_text(item, {int(case_id)})
            case["steps"] = steps
            case["step_pairs"] = pairs
            case["description"] = description
            case["parameters"] = parameters

    def _case_text(
        self, item: Dict[str, Any], seen: set[int]
    ) -> tuple[str, str, str, List[Dict[str, str]]]:
        """Return steps, description, parameters, and action/expected pairs."""
        fields = item.get("fields") if isinstance(item, dict) else None
        if not isinstance(fields, dict):
            fields = {}
        raw_steps = fields.get("Microsoft.VSTS.TCM.Steps")
        if not isinstance(raw_steps, str):
            raw_steps = ""
        steps = _plain_steps(raw_steps)
        pairs = _step_pairs_from_xml(raw_steps)
        description = _plain_steps(fields.get("System.Description"))
        parameters = _plain_steps(fields.get("Microsoft.VSTS.TCM.LocalDataSource"))
        named = _plain_steps(fields.get("Microsoft.VSTS.TCM.Parameters"))
        if named:
            parameters = f"{parameters} {named}".strip()
        for shared_id in _shared_step_ids(raw_steps):
            if shared_id in seen:
                continue
            seen.add(shared_id)
            try:
                shared = self.get_work_item(shared_id)
            except WorkItemNotFoundError:
                continue
            (
                shared_steps,
                shared_description,
                shared_parameters,
                shared_pairs,
            ) = self._case_text(shared, seen)
            if shared_steps:
                steps = f"{steps} {shared_steps}".strip()
            pairs.extend(shared_pairs)
            if shared_description:
                description = f"{description} {shared_description}".strip()
            if shared_parameters:
                parameters = f"{parameters} {shared_parameters}".strip()
        return steps, description, parameters, pairs

    def _cases_in_plan(self, plan_id: int, suite_id: Optional[int] = None) -> List[Dict[str, Any]]:
        suites = self._plan_suites(plan_id)
        if suites is None:
            raise ADORequestError(
                f"ADO test plan {plan_id} was not found",
                status_code=404,
            )
        flat = self._iter_suites(suites)
        if suite_id is not None and not any(suite.get("id") == suite_id for suite in flat):
            raise ADORequestError(
                f"ADO test plan {plan_id} does not contain suite {suite_id}"
            )

        cases = []
        for suite in flat:
            if not isinstance(suite.get("id"), int):
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
        payload, _token = self._exchange(url, work_item_id=work_item_id)
        return payload

    def _post_json(self, url: str, body: Dict[str, Any]) -> Dict[str, Any]:
        payload, _token = self._exchange(url, body=body)
        return payload

    def _exchange(
        self,
        url: str,
        body: Optional[Dict[str, Any]] = None,
        work_item_id: Optional[int] = None,
    ) -> tuple[Dict[str, Any], Optional[str]]:
        credentials = base64.b64encode(f":{self.pat}".encode("utf-8")).decode("ascii")
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Authorization": f"Basic {credentials}",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            url,
            data=data,
            headers=headers,
            method="GET" if data is None else "POST",
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                payload = json.load(response)
                token = _continuation_token(response)
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
        return payload, token

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
        return self._open_json(
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
        payload = self._open_json(request, "iteration list")
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

    def test_case_plan_memberships(
        self, test_case_ids: List[int]
    ) -> Dict[str, List[int]]:
        """Map linked test cases to plans through their Test Point suite membership."""
        if not isinstance(test_case_ids, list) or any(
            isinstance(test_case_id, bool)
            or not isinstance(test_case_id, int)
            or test_case_id <= 0
            for test_case_id in test_case_ids
        ):
            raise ADOConfigurationError(
                "test case IDs must be a list of positive integers"
            )
        target_ids = {str(test_case_id) for test_case_id in test_case_ids}
        memberships: Dict[str, List[int]] = {test_case_id: [] for test_case_id in target_ids}
        if not target_ids:
            return memberships

        plans_query = urlencode({"api-version": "7.1-preview.1"})
        plans_request = Request(
            f"{self.project_url}/_apis/testplan/plans?{plans_query}",
            headers=self._headers(),
        )
        plans_payload = self._open_json(plans_request, "test plan list")
        plans = plans_payload.get("value")
        if not isinstance(plans, list):
            raise ADOResponseError("ADO test plan response is missing its value list")

        for plan in plans:
            if not isinstance(plan, dict):
                raise ADOResponseError("ADO test plan response contains an invalid plan")
            plan_id = plan.get("id")
            if isinstance(plan_id, bool) or not isinstance(plan_id, int) or plan_id <= 0:
                raise ADOResponseError("ADO test plan response contains an invalid ID")

            suite_query = urlencode(
                {"$depth": 14, "api-version": "7.1-preview.1"}
            )
            suite_request = Request(
                f"{self.project_url}/_apis/testplan/Plans/{plan_id}/suites?{suite_query}",
                headers=self._headers(),
            )
            suite_payload = self._open_json(suite_request, "test suite list")
            suites = suite_payload.get("value")
            if not isinstance(suites, list):
                raise ADOResponseError("ADO test suite response is missing its value list")

            pending = list(reversed(suites))
            suite_ids = []
            while pending:
                suite = pending.pop()
                if not isinstance(suite, dict):
                    raise ADOResponseError(
                        "ADO test suite response contains an invalid suite"
                    )
                suite_id = suite.get("id")
                if isinstance(suite_id, bool) or not isinstance(suite_id, int) or suite_id <= 0:
                    raise ADOResponseError("ADO test suite response contains an invalid ID")
                suite_ids.append(suite_id)
                children = suite.get("children", [])
                if not isinstance(children, list):
                    raise ADOResponseError(
                        "ADO test suite response contains an invalid children list"
                    )
                pending.extend(reversed(children))

            for suite_id in suite_ids:
                offset = 0
                page_size = 1000
                while True:
                    points_query = urlencode(
                        {
                            "$skip": offset,
                            "$top": page_size,
                            "api-version": ADO_API_VERSION,
                        }
                    )
                    points_request = Request(
                        f"{self.project_url}/_apis/test/Plans/{plan_id}/Suites/{suite_id}/points?{points_query}",
                        headers=self._headers(),
                    )
                    points_payload = self._open_json(
                        points_request, "test point list"
                    )
                    points = points_payload.get("value")
                    if not isinstance(points, list):
                        raise ADOResponseError(
                            "ADO test point response is missing its value list"
                        )
                    for point in points:
                        if not isinstance(point, dict):
                            raise ADOResponseError(
                                "ADO test point response contains an invalid point"
                            )
                        test_case = point.get("testCase")
                        if not isinstance(test_case, dict):
                            raise ADOResponseError(
                                "ADO test point is missing its test case"
                            )
                        test_case_id = test_case.get("id")
                        if isinstance(test_case_id, bool) or not isinstance(
                            test_case_id, (int, str)
                        ):
                            raise ADOResponseError(
                                "ADO test point contains an invalid test case ID"
                            )
                        key = str(test_case_id)
                        if key in target_ids and plan_id not in memberships[key]:
                            memberships[key].append(plan_id)
                    if len(points) < page_size:
                        break
                    offset += page_size

        return memberships

    def _headers(self) -> Dict[str, str]:
        credentials = base64.b64encode(f":{self.pat}".encode("utf-8")).decode("ascii")
        return {
            "Accept": "application/json",
            "Authorization": f"Basic {credentials}",
        }

    def _open_json(
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
        payload = self._open_json(request, "WIQL")
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
        payload = self._open_json(request, "work-item list")
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
