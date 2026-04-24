from pydantic import BaseModel, HttpUrl
from typing import List, Optional


class ParsePostRequest(BaseModel):
    url: HttpUrl
    htmltext: str


class ParseResponse(BaseModel):
    url: HttpUrl
    domain: str
    title: str
    htmltext: str
    parsedtext: str


class GoldStandardEntry(BaseModel):
    url: HttpUrl
    domain: str
    title: str
    htmltext: str
    goldtext: str


class DomainsResponse(BaseModel):
    domains: List[str]


class FullGoldStandardResponse(BaseModel):
    goldstandard: List[GoldStandardEntry]


class EvaluateRequest(BaseModel):
    parsedtext: str
    goldtext: str


class TokenLevelEval(BaseModel):
    precision: float
    recall: float
    f1: float


class EvaluateResponse(BaseModel):
    tokenleveleval: TokenLevelEval


class FullGSEvalEntry(BaseModel):
    url: HttpUrl
    precision: float
    recall: float
    f1: float


class FullGSEvalResponse(BaseModel):
    domain: str
    results: List[FullGSEvalEntry]
    average_precision: float
    average_recall: float
    average_f1: float