import json
import typing as tp
import uuid
from urllib.parse import urlencode

import fastapi
import pydantic
from dishka.integrations import fastapi as dishka_fastapi
from fastapi.responses import HTMLResponse

from taskiq_dashboard.api.templates import jinja_templates
from taskiq_dashboard.domain.dto.task_status import TaskStatus
from taskiq_dashboard.domain.repositories import AbstractTaskRepository


router = fastapi.APIRouter(
    prefix='',
    tags=['History'],
    route_class=dishka_fastapi.DishkaRoute,
)


class TaskFilter(pydantic.BaseModel):
    q: str = ''
    status: TaskStatus | None = None
    limit: int = 30
    offset: int = 0
    sort_by: tp.Literal['started_at', 'finished_at'] = 'started_at'
    sort_order: tp.Literal['asc', 'desc'] = 'desc'

    @pydantic.field_validator('status', mode='before')
    @classmethod
    def validate_status(
        cls,
        value: TaskStatus | str | None,
    ) -> TaskStatus | None:
        if isinstance(value, str) and value == 'null':
            return None
        return value  # ty: ignore[invalid-return-type]

    @pydantic.field_serializer('status', mode='plain')
    def serialize_status(
        self,
        value: TaskStatus | None,
    ) -> str | None:
        if value is None:
            return 'null'
        return str(value.value)

    model_config = pydantic.ConfigDict(
        extra='ignore',
    )


@router.get(
    '/',
    name='task_history_view',
    response_class=HTMLResponse,
)
async def handle_search_tasks(
    request: fastapi.Request,
    repository: dishka_fastapi.FromDishka[AbstractTaskRepository],
    query: tp.Annotated[TaskFilter, fastapi.Query(...)],
    hx_request: tp.Annotated[bool, fastapi.Header(description='Request from htmx')] = False,  # noqa: FBT002
) -> HTMLResponse:
    tasks = await repository.find_tasks(
        name=query.q,
        status=query.status,
        limit=query.limit,
        offset=query.offset,
        sort_by=query.sort_by,
        sort_order=query.sort_order,
    )
    headers: dict[str, str] = {}
    template_name = 'task_runs_page.html'
    if hx_request:
        push_url = request.url_for('task_history_view').path
        query_string = urlencode(query.model_dump(exclude={'limit', 'offset'}))
        if query_string:
            push_url = f'{push_url}?{query_string}'
        headers = {'HX-Push-Url': push_url}
        template_name = 'partial/task_list.html'
    return jinja_templates.TemplateResponse(
        request,
        template_name,
        {
            'request': request,
            'results': [task.model_dump() for task in tasks],
            **query.model_dump(),
        },
        headers=headers,
    )


@router.get(
    '/history/{task_id:uuid}',
    name='task_details_view',
    response_class=HTMLResponse,
)
async def handle_task_details(
    request: fastapi.Request,
    repository: dishka_fastapi.FromDishka[AbstractTaskRepository],
    task_id: uuid.UUID,
) -> HTMLResponse:
    """
    Display detailed information for a specific task.
    """
    task = await repository.get_task_by_id(task_id)
    if task is None:
        return jinja_templates.TemplateResponse(
            request,
            name='not_found_page.html',
            context={
                'request': request,
                'message': f'Task with ID {task_id} not found',
            },
            status_code=404,
        )
    result_json = None
    if task.result:
        result_json = json.dumps(task.result, indent=2, ensure_ascii=False)
    return jinja_templates.TemplateResponse(
        request,
        name='task_run_details_page.html',
        context={
            'request': request,
            'task': task,
            'task_result': result_json,
            'enable_actions': request.app.state.broker is not None,
            'enable_additional_actions': False,  # Placeholder for future features like retries with different args
        },
    )
