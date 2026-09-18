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
    suggest: bool = Field(
        default=False,
        description="Also compute fix suggestions for missing_target diagnostics",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "suggest": True,
                    "files": [
                        {
                            "path": "README.md",
                            "content": "# Project\n\nSee the [guide](docs/guid.md#usag).\n",
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


class CandidateOut(BaseModel):
    path: str = Field(..., description="Normalized path of the candidate file")
    score: int = Field(..., description="path_distance + anchor_distance (lower is better)")
    path_distance: int = Field(..., description="Edit distance between the two basenames")
    anchor_distance: int = Field(..., description="Best edit distance between the "
                                                  "link's fragment and the candidate's anchors")
    anchor: str | None = Field(None, description="The candidate's closest anchor slug")


class SuggestionOut(BaseModel):
    kind: str = Field(..., description="auto_suggestion | ambiguous")
    candidates: list[CandidateOut] = Field(..., description="Up to 3 candidates, sorted "
                                                            "by score then full path")


class DiagnosticOut(BaseModel):
    type: str = Field(..., description="missing_target | duplicate_anchor | "
                                       "path_escape | self_reference")
    source: str = Field(..., description="File containing the offending link/heading")
    line: int = Field(..., description="1-based line number in the source file")
    link: str = Field(..., description="The link exactly as written in the document")
    resolved: str | None = Field(None, description="Normalized target path, if resolvable")
    message: str
    suggestion: SuggestionOut | None = Field(
        None, description="Fix suggestion, present on missing_target diagnostics "
                          "when the check ran with suggest=true")


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
