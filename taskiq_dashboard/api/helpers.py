import enum
import inspect
import typing as tp

import fastapi
from fastapi.responses import Response
from starlette import status
from taskiq import AsyncTaskiqDecoratedTask

from taskiq_dashboard.api.templates import jinja_templates
from taskiq_dashboard.domain.dto.signature import FieldWidget, SignatureField, TaskSignature


def create_error_notification(request: fastapi.Request, message: str) -> Response:
    return jinja_templates.TemplateResponse(
        request,
        'partial/notification.html',
        {'request': request, 'message': message, 'level': 'error'},
        status_code=status.HTTP_200_OK,
    )


def _annotation_name(annotation: tp.Any) -> str:
    if annotation is inspect.Parameter.empty:
        return ''
    if tp.get_origin(annotation) is not None:
        return str(annotation).replace('typing.', '')
    name = getattr(annotation, '__name__', None)
    if name:
        return name
    return str(annotation).replace('typing.', '')


def _is_enum(annotation: tp.Any) -> bool:
    return inspect.isclass(annotation) and issubclass(annotation, enum.Enum)


def _widget_for(annotation: tp.Any) -> FieldWidget:
    if annotation is inspect.Parameter.empty:
        return FieldWidget.INPUT
    if _is_enum(annotation):
        return FieldWidget.SELECT
    origin = tp.get_origin(annotation)
    if origin in {list, dict} or annotation in {list, dict}:
        return FieldWidget.TEXTAREA
    return FieldWidget.INPUT


def _choices_for(annotation: tp.Any) -> list[str]:
    if _is_enum(annotation):
        return [member.name for member in annotation]
    return []


def get_signature(task: AsyncTaskiqDecoratedTask) -> TaskSignature:
    signature = inspect.signature(task.original_func)
    params: list[SignatureField] = []
    preview_parts: list[str] = []

    has_var_args = False
    has_var_kwargs = False

    for parameter in signature.parameters.values():
        if parameter.kind is inspect.Parameter.VAR_POSITIONAL:
            has_var_args = True
            preview_parts.append(f'*{parameter.name}')
            continue

        if parameter.kind is inspect.Parameter.VAR_KEYWORD:
            has_var_kwargs = True
            preview_parts.append(f'**{parameter.name}')
            continue

        annotation = _annotation_name(parameter.annotation)
        default_repr = '' if parameter.default is inspect.Parameter.empty else repr(parameter.default)
        required = parameter.default is inspect.Parameter.empty
        params.append(
            SignatureField(
                name=parameter.name,
                annotation=annotation,
                default=default_repr,
                required=required,
                widget=_widget_for(parameter.annotation),
                choices=_choices_for(parameter.annotation),
            ),
        )
        preview_parts.append(parameter.name + (f': {annotation}' if annotation else ''))
    return TaskSignature(
        params=params,
        preview=', '.join(preview_parts),
        has_var_args=has_var_args,
        has_var_kwargs=has_var_kwargs,
    )
