from typing import List, Optional, Union

from pydantic import BaseModel, Field, validator, Extra
from .pepannot import Annotation
import peppy


class Model(BaseModel):
    class Config:
        allow_population_by_field_name = True


class ProjectModel(Model):
    name: str
    tag: str
    description: Optional[str]
    digest: str
    number_of_samples: int = Field(alias="n_samples")
    is_private: bool


class NamespaceModel(Model):
    number_of_projects: int = Field(alias="n_projects")
    number_of_samples: int = Field(alias="n_samples")
    namespace: str
    projects: List[ProjectModel]


class NamespacesResponseModel(Model):
    namespaces: Optional[List[NamespaceModel]]


class NamespaceSearchResultModel(Model):
    namespace: str
    number_of_projects: int
    number_of_samples: int


class ProjectSearchResultModel(Model):
    namespace: str
    name: str
    tag: str
    number_of_samples: Union[int, None]
    description: Union[str, None]
    digest: Union[str, None]
    is_private: Union[bool, None]

    @validator("is_private")
    def is_private_should_be_bool(cls, v):
        if not isinstance(v, bool):
            return False
        else:
            return v


class NamespaceSearchModel(Model):
    number_of_results: int
    limit: int
    offset: int
    results: List[NamespaceSearchResultModel]


class ProjectSearchModel(Model):
    namespace: str
    number_of_results: int
    limit: int
    offset: int
    results: List[ProjectSearchResultModel]


class RawPEPModel(BaseModel):
    name: str
    description: str
    _config: dict
    _sample_dict: dict
    _subsample_dict: Optional[list] = None

    class Config:
        extra = Extra.forbid


class UpdateItems(BaseModel):
    project_value: Optional[peppy.Project] = Field(alias="project")
    tag: Optional[str]
    private: Optional[bool] = Field(alias="is_private")
    name: Optional[str]

    # do not update
    # anno_info: Optional[Annotation] = Field(alias="annot")

    class Config:
        extra = Extra.forbid


# is Used only by pepdbagent. Don't use it outside
class UpdateModel(BaseModel):
    project_value: Optional[dict]
    name: Optional[str]
    tag: Optional[str]
    private: Optional[bool]
    digest: Optional[str]
    anno_info: Optional[Annotation]

    class Config:
        extra = Extra.forbid


class UploadResponse(Model):
    registry_path: str
    log_stage: str
    status: str
    info: str
