from pydantic import BaseModel


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str


class Problem(Exception):
    """Only explicit public messages may cross the API boundary."""

    def __init__(self, status: int, code: str, message: str) -> None:
        self.status = status
        self.code = code
        self.message = message
        super().__init__(code)
