import json
import typing as tp
import uuid
from logging import getLogger

import fastapi
import pydantic
from dishka.integrations import fastapi as dishka_fastapi
from fastapi.responses import RedirectResponse, Response
from starlette import status

from taskiq_dashboard.api.helpers import create_error_notification, get_signature
from taskiq_dashboard.api.templates import jinja_templates
from taskiq_dashboard.domain.repositories import AbstractTaskRepository


if tp.TYPE_CHECKING:
    from taskiq import AsyncBroker

router = fastapi.APIRouter(
    prefix='/actions',
    tags=['Action'],
    route_class=dishka_fastapi.DishkaRoute,
)
logger = getLogger(__name__)


class BulkTaskRequest(pydantic.BaseModel):
    task_ids: list[uuid.UUID]


@router.post(
    '/run/{task_name}',
    name='run_task',
)
async def handle_run_task(  # noqa: PLR0911 Too
    request: fastapi.Request,
    task_name: str,
    args: tp.Annotated[str, fastapi.Form()] = '[]',
    kwargs: tp.Annotated[str, fastapi.Form()] = '{}',
) -> Response:
    broker: AsyncBroker | None = request.app.state.broker
    if broker is None:
        return create_error_notification(request, 'No broker configured.')

    task = broker.find_task(task_name)
    if task is None:
        return create_error_notification(request, f'Task "{task_name}" is not registered.')

    try:
        parsed_args = json.loads(args)
        if not isinstance(parsed_args, list):
            return create_error_notification(request, 'Positional arguments must be a JSON array, e.g. [1, "two"].')
    except json.JSONDecodeError:
        return create_error_notification(request, 'Invalid JSON in "Positional arguments".')
    try:
        parsed_kwargs = json.loads(kwargs)
        if not isinstance(parsed_kwargs, dict):
            return create_error_notification(request, 'Keyword arguments must be a JSON object, e.g. {"key": "value"}.')
    except json.JSONDecodeError:
        return create_error_notification(request, 'Invalid JSON in "Keyword arguments".')

    missing = [
        param.name
        for index, param in enumerate(get_signature(task).params)
        if param.required and index >= len(parsed_args) and param.name not in parsed_kwargs
    ]
    if missing:
        return create_error_notification(request, f'Missing required arguments: {", ".join(missing)}.')

    new_task_id = str(uuid.uuid4())
    await task.kicker().with_task_id(new_task_id).kiq(*parsed_args, **parsed_kwargs)

    details_url = request.url_for('task_details_view', task_id=new_task_id).path
    return jinja_templates.TemplateResponse(
        request,
        'partial/notification.html',
        {
            'request': request,
            'message': (
                f"""
                Task started with ID
                <a class="underline hover:ctp-text-lavander" href="{details_url}">
                    {new_task_id}.
                </a>
                """
            ),
        },
        status_code=status.HTTP_200_OK,
    )


@router.post(
    '/rerun/{task_id}',
    name='rerun_task_run',
)
async def handle_rerun_task_run(
    request: fastapi.Request,
    task_id: uuid.UUID,
    repository: dishka_fastapi.FromDishka[AbstractTaskRepository],
) -> Response:
    broker: AsyncBroker | None = request.app.state.broker
    if broker is None:
        logger.error('No broker configured to handle task kick', extra={'task_id': task_id})
        return Response(status_code=status.HTTP_400_BAD_REQUEST, content=b'No broker configured')

    existing_task = await repository.get_task_by_id(task_id)
    if existing_task is None:
        logger.error('Task not found in repository', extra={'task_id': str(task_id)})
        return Response(status_code=status.HTTP_404_NOT_FOUND, content=b'Task not found')
    task = broker.find_task(existing_task.name)
    if not task:
        logger.error('Task not found in broker', extra={'task_name': existing_task.name})
        return Response(status_code=status.HTTP_404_NOT_FOUND, content=b'Task not found')
    new_task_id = str(uuid.uuid4())
    await (
        task.kicker()
        .with_task_id(new_task_id)
        .with_labels(**existing_task.labels)
        .kiq(
            *existing_task.args,
            **existing_task.kwargs,
        )
    )

    details_url = request.url_for('task_details_view', task_id=new_task_id).path
    return jinja_templates.TemplateResponse(
        request,
        'partial/notification.html',
        {
            'request': request,
            'message': (
                f"""
                Task rerun started with ID
                <a class="underline hover:ctp-text-lavander" href="{details_url}">
                    {new_task_id}.
                </a>
                """
            ),
        },
        status_code=status.HTTP_200_OK,
    )


@router.get(
    '/delete/{task_id}',
    name='delete_task_run',
)
async def handle_delete_task_run(
    request: fastapi.Request,
    task_id: uuid.UUID,
    repository: dishka_fastapi.FromDishka[AbstractTaskRepository],
) -> Response:
    await repository.delete_task(task_id)
    return RedirectResponse(
        url=request.url_for('task_history_view').path,
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )


@router.post(
    '/bulk/rerun',
    name='bulk_rerun_task_runs',
)
async def handle_bulk_rerun_task_runs(
    request: fastapi.Request,
    body: BulkTaskRequest,
    repository: dishka_fastapi.FromDishka[AbstractTaskRepository],
) -> Response:
    broker: AsyncBroker | None = request.app.state.broker
    if broker is None:
        logger.error('No broker configured to handle bulk task rerun')
        return Response(status_code=status.HTTP_400_BAD_REQUEST, content=b'No broker configured')

    if not body.task_ids:
        return Response(status_code=status.HTTP_400_BAD_REQUEST, content=b'No task IDs provided')

    rerun_results = []
    errors = []

    for task_id in body.task_ids:
        try:
            existing_task = await repository.get_task_by_id(task_id)
            if existing_task is None:
                errors.append(f'Task {task_id} not found')
                continue

            task = broker.find_task(existing_task.name)
            if not task:
                errors.append(f'Task {existing_task.name} not found in broker')
                continue

            new_task_id = str(uuid.uuid4())
            await (
                task.kicker()
                .with_task_id(new_task_id)
                .with_labels(**existing_task.labels)
                .kiq(
                    *existing_task.args,
                    **existing_task.kwargs,
                )
            )
            rerun_results.append((task_id, new_task_id))
        except Exception as e:
            logger.exception('Error rerunning task', extra={'task_id': str(task_id)})
            errors.append(f'Error rerunning task {task_id}: {e!r}')

    success_count = len(rerun_results)
    total_count = len(body.task_ids)

    message_parts = [f'Rerun {success_count} of {total_count} tasks.']
    if errors:
        number_of_errors_to_show = min(5, len(errors))
        message_parts.append(f'Errors: {len(errors)}')
        message_parts.extend(
            [f'<div class="text-ctp-red">{error}</div>' for error in errors[:number_of_errors_to_show]]
        )
        if len(errors) > number_of_errors_to_show:
            message_parts.append(f'<div>... and {len(errors) - number_of_errors_to_show} more errors</div>')

    return jinja_templates.TemplateResponse(
        request,
        'partial/notification.html',
        {
            'request': request,
            'message': '<br>'.join(message_parts),
        },
        status_code=status.HTTP_200_OK,
    )


@router.post(
    '/bulk/delete',
    name='bulk_delete_task_runs',
)
async def handle_bulk_delete_task_runs(
    _: fastapi.Request,
    body: BulkTaskRequest,
    repository: dishka_fastapi.FromDishka[AbstractTaskRepository],
) -> Response:
    if not body.task_ids:
        return Response(status_code=status.HTTP_400_BAD_REQUEST, content=b'No task IDs provided')
    await repository.delete_tasks(body.task_ids)
    # Return success response - client will reload the page
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
    )
