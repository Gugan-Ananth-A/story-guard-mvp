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

        query = urlencode({"$expand": "relations", "api-version": "7.1"})
        url = (
            f"{self.project_url}/_apis/wit/workitems/"
            f"{work_item_id}?{query}"
        )
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
            if error.code == 404:
                raise WorkItemNotFoundError(
                    f"ADO work item {work_item_id} was not found"
                ) from error
            raise ADORequestError(
                f"ADO request failed with HTTP status {error.code}"
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise ADORequestError("ADO work-item request failed") from error
        except JSONDecodeError as error:
            raise ADOResponseError("ADO returned invalid JSON") from error

        return map_ado_work_item(payload)
