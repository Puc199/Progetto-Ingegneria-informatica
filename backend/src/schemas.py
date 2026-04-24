from pydantic import BaseModel, HttpUrl
from typing import List


class ParsePostRequest(BaseModel):
    url: HttpUrl
    html_text: str


class ParseResponse(BaseModel):
    url: HttpUrl
    domain: str
    title: str
    html_text: str
    parsed_text: str


class GoldStandardEntry(BaseModel):
    url: HttpUrl
    domain: str
    title: str
    html_text: str
    gold_text: str


class DomainsResponse(BaseModel):
    domains: List[str]


class FullGoldStandardResponse(BaseModel):
    gold_standard: List[GoldStandardEntry]


class EvaluateRequest(BaseModel):
    parsed_text: str
    gold_text: str


class TokenLevelEval(BaseModel):
    precision: float
    recall: float
    f1: float


class EvaluateResponse(BaseModel):
    token_level_eval: TokenLevelEval


class FullGSEvalResponse(BaseModel):
    token_level_eval: TokenLevelEval