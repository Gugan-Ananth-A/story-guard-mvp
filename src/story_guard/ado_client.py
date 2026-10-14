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
        if isinstance(work_item_id, bool) or not isinstance(work_item_id, int):
            raise ValueError("work_item_id must be an integer")
        if work_item_id <= 0:
            raise ValueError("work_item_id must be a positive integer")

        query = urlencode(
            {"$expand": "relations", "api-version": ADO_API_VERSION}
        )
        url = f"{self.project_url}/_apis/wit/workitems/{work_item_id}?{query}"
        request = Request(url, headers=self._headers())
        payload = self._request_json(
            request,
            "work-item",
            not_found_message=f"ADO work item {work_item_id} was not found",
        )
        return map_ado_work_item(payload)

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
