import fastapi
from dishka.integrations import fastapi as dishka_fastapi
from fastapi.responses import HTMLResponse
from starlette import status

from taskiq_dashboard.api.helpers import get_signature
from taskiq_dashboard.api.templates import jinja_templates


router = fastapi.APIRouter(
    prefix='/tasks',
    tags=['Tasks'],
    route_class=dishka_fastapi.DishkaRoute,
)


@router.get(
    '/',
    name='task_list_view',
    response_class=HTMLResponse,
)
async def handle_list_registered_tasks(
    request: fastapi.Request,
) -> HTMLResponse:
    broker = request.app.state.broker
    if broker is None:
        return jinja_templates.TemplateResponse(
            request,
            name='not_found_page.html',
            context={
                'request': request,
                'message': 'Broker not configured.',
            },
            status_code=status.HTTP_404_NOT_FOUND,
        )
    tasks = [
        {
            'name': task_name,
            'labels': getattr(task, 'labels', {}) or {},
            'signature': get_signature(task).preview,
        }
        for task_name, task in sorted(broker.get_all_tasks().items())
    ]
    return jinja_templates.TemplateResponse(
        request,
        'tasks_page.html',
        {
            'request': request,
            'tasks': tasks,
        },
    )


@router.get(
    '/{task_name}/run',
    name='task_run_form',
    response_class=HTMLResponse,
)
async def handle_task_run_form(
    request: fastapi.Request,
    task_name: str,
) -> HTMLResponse:
    broker = request.app.state.broker
    if broker is None:
        return jinja_templates.TemplateResponse(
            request,
            name='not_found_page.html',
            context={'request': request, 'message': 'Broker not configured.'},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    task = broker.find_task(task_name)
    if task is None:
        return jinja_templates.TemplateResponse(
            request,
            name='not_found_page.html',
            context={'request': request, 'message': f'Task "{task_name}" is not registered'},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return jinja_templates.TemplateResponse(
        request,
        'task_details_page.html',
        {
            'request': request,
            'task_name': task_name,
            'signature': get_signature(task),
        },
    )
