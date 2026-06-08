from pydantic import BaseModel


class Source(BaseModel):
    title: str
    url: str
