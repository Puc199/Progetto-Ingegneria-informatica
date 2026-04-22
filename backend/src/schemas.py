from pydantic import BaseModel
from typing import Optional

class ParseResponse(BaseModel):
    url: str
    domain: str
    title: str
    htmltext: str
    parsedtext: str

class ParsePostRequest(BaseModel):
    url: str
    htmltext: str

class ErrorResponse(BaseModel):
    error: str