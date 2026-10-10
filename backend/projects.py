"""Project creation and retrieval without unfinished generation records."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.database import Database


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value):
        return value.strip() if isinstance(value, str) else value


class Project(BaseModel):
    id: int
    name: str
    initial_image_path: str | None
    created_at: str
    updated_at: str
    generation_count: int


QUERY = """
SELECT p.*, (SELECT COUNT(*) FROM generations g WHERE g.project_id = p.id)
    AS generation_count FROM projects p
"""


def project_from_row(row) -> Project:
    values = dict(row)
    values["initial_image_path"] = values["initial_image_path"] or None
    return Project(**values)


def project_router(database: Database) -> APIRouter:
    router = APIRouter(prefix="/api/projects", tags=["projects"])

    @router.post("", response_model=Project, status_code=201)
    def create_project(payload: ProjectCreate) -> Project:
        with database.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO projects (name, initial_image_path) VALUES (?, '')", (payload.name,)
            )
            row = connection.execute(QUERY + " WHERE p.id = ?", (cursor.lastrowid,)).fetchone()
            return project_from_row(row)

    @router.get("", response_model=list[Project])
    def list_projects() -> list[Project]:
        with database.connect() as connection:
            rows = connection.execute(QUERY + " ORDER BY p.updated_at DESC, p.id DESC").fetchall()
            return [project_from_row(row) for row in rows]

    @router.get("/{project_id}", response_model=Project)
    def get_project(project_id: int) -> Project:
        with database.connect() as connection:
            row = connection.execute(QUERY + " WHERE p.id = ?", (project_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Project not found")
            return project_from_row(row)

    return router
