from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from gateway.domain.models import RefundTask


class RefundMessage(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    schema_version: Literal[1] = 1
    operation_id: str
    ticket_uid: UUID
    username: Annotated[str, Field(min_length=1, max_length=80, pattern=r".*\S.*")]

    @model_validator(mode="after")
    def valid_operation_id(self) -> "RefundMessage":
        if self.operation_id != self.to_domain().operation_id:
            raise ValueError("Operation ID does not match ticket UID")
        return self

    def to_domain(self) -> RefundTask:
        return RefundTask(self.ticket_uid, self.username)

    @classmethod
    def from_domain(cls, task: RefundTask) -> "RefundMessage":
        return cls(
            operation_id=task.operation_id, ticket_uid=task.ticket_uid, username=task.username
        )
