"""Pydantic request/response models for the API."""
from __future__ import annotations

from pydantic import BaseModel, Field


class FileInput(BaseModel):
    path: str = Field(..., min_length=1,
                      description="Repo-relative POSIX path, e.g. docs/guide.md")
    content: str = Field(default="", description="Markdown source of the file")


class CheckRequest(BaseModel):
    files: list[FileInput] = Field(..., min_length=1,
                                   description="The Markdown file collection to check")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "files": [
                        {
                            "path": "README.md",
                            "content": "# Project\n\nSee the [guide](docs/guide.md#usage).\n",
                        },
                        {
                            "path": "docs/guide.md",
                            "content": "# Guide\n\n## Usage\n\nBack to [home](../README.md#project).\n",
                        },
                    ]
                }
            ]
        }
    }


class DiagnosticOut(BaseModel):
    type: str = Field(..., description="missing_target | duplicate_anchor | "
                                       "path_escape | self_reference")
    source: str = Field(..., description="File containing the offending link/heading")
    line: int = Field(..., description="1-based line number in the source file")
    link: str = Field(..., description="The link exactly as written in the document")
    resolved: str | None = Field(None, description="Normalized target path, if resolvable")
    message: str


class CheckOut(BaseModel):
    check_id: str
    created_at: str
    file_count: int
    diagnostic_count: int
    summary: dict[str, int]
    diagnostics: list[DiagnosticOut]


class CheckSummary(BaseModel):
    check_id: str
    created_at: str
    file_count: int
    diagnostic_count: int
    summary: dict[str, int]
