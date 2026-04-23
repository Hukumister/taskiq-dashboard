import enum

import pydantic


class FieldWidget(str, enum.Enum):
    INPUT = 'input'
    TEXTAREA = 'textarea'
    SELECT = 'select'


class SignatureField(pydantic.BaseModel):
    name: str
    annotation: str = ''
    default: str = ''
    required: bool
    widget: FieldWidget
    choices: list[str] = pydantic.Field(default_factory=list)


class TaskSignature(pydantic.BaseModel):
    params: list[SignatureField] = pydantic.Field(default_factory=list)
    preview: str = ''
    has_var_args: bool = False
    has_var_kwargs: bool = False
