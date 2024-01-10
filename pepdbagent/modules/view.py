# View of the PEP. In other words, it is a part of the PEP, or subset of the samples in the PEP.

import logging
from typing import Union, List

import peppy
from sqlalchemy import select, and_, delete
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError


from pepdbagent.const import (
    DEFAULT_TAG,
    PKG_NAME,
)
from pepdbagent.exceptions import ViewNotFoundError, SampleAlreadyInView

from pepdbagent.db_utils import BaseEngine, Samples, Projects, Views, ViewSampleAssociation
from pepdbagent.models import ViewAnnotation, CreateViewDictModel

_LOGGER = logging.getLogger(PKG_NAME)


class PEPDatabaseView:
    """
    Class that represents Project in Database.

    While using this class, user can create, retrieve, delete, and update projects from database
    """

    def __init__(self, pep_db_engine: BaseEngine):
        """
        :param pep_db_engine: pepdbengine object with sa engine
        """
        self._sa_engine = pep_db_engine.engine
        self._pep_db_engine = pep_db_engine

    def get(
        self,
        namespace: str,
        name: str,
        tag: str = DEFAULT_TAG,
        view_name: str = None,
        raw: bool = False,
    ) -> Union[peppy.Project, dict, None]:
        """
        Retrieve view of the project from the database.
        View is a subset of the samples in the project. e.g. bed-db project has all the samples in bedbase,
        bedset is a view of the bedbase project with only the samples in the bedset.

        :param namespace: namespace of the project
        :param name: name of the project (Default: name is taken from the project object)
        :param tag: tag of the project (Default: tag is taken from the project object)
        :param view_name: name of the view
        :param raw: retrieve unprocessed (raw) PEP dict.
        :return: peppy.Project object with found project or dict with unprocessed
            PEP elements: {
                name: str
                description: str
                _config: dict
                _sample_dict: dict
                _subsample_dict: dict
            }
        """
        view_statement = select(Views).where(
            and_(
                Views.project_mapping.has(namespace=namespace, name=name, tag=tag),
                Views.name == view_name,
            )
        )

        with Session(self._sa_engine) as sa_session:
            view = sa_session.scalar(view_statement)
            if not view:
                raise ViewNotFoundError(
                    f"View {view_name} of the project {namespace}/{name}:{tag} does not exist"
                )
            samples = [sample.sample.sample for sample in view.samples]
            config = view.project_mapping.config
        sub_project_dict = {"_config": config, "_sample_dict": samples, "_subsample_dict": None}
        if raw:
            return sub_project_dict
        else:
            return peppy.Project.from_dict(sub_project_dict)

    def get_annotation(
        self, namespace: str, name: str, tag: str = DEFAULT_TAG, view_name: str = None
    ) -> ViewAnnotation:
        """
        Get annotation of the view.

        :param namespace: namespace of the project
        :param name: name of the project
        :param tag: tag of the project
        :param view_name: name of the sample
        :return: ViewAnnotation object:
            {project_namespace: str,
             project_name: str,
             project_tag: str,
             name: str,
             description: str,
             number_of_samples: int}
        """
        view_statement = select(Views).where(
            and_(
                Views.project_mapping.has(namespace=namespace, name=name, tag=tag),
                Views.name == view_name,
            )
        )

        with Session(self._sa_engine) as sa_session:
            view = sa_session.scalar(view_statement)
            if not view:
                raise ViewNotFoundError(
                    f"View {name} of the project {namespace}/{name}:{tag} does not exist"
                )
            return ViewAnnotation(
                project_namespace=namespace,
                project_name=name,
                project_tag=tag,
                name=view.name,
                description=view.description,
                number_of_samples=len(view.samples),
            )

    def create(
        self,
        view_name: str,
        view_dict: Union[dict, CreateViewDictModel],
        description: str = None,
    ) -> None:
        """
        Create a view of the project in the database.

        :param view_name: namespace of the project
        :param view_dict: dict or CreateViewDictModel object with view samples.
            Dict should have the following structure:
                {
                    project_namespace: str
                    project_name: str
                    project_tag: str
                    sample_list: List[str] # list of sample names
                }
        :param description: description of the view
        retrun: None
        """
        if isinstance(view_dict, dict):
            view_dict = CreateViewDictModel(**view_dict)

        project_statement = select(Projects).where(
            and_(
                Projects.namespace == view_dict.project_namespace,
                Projects.name == view_dict.project_name,
                Projects.tag == view_dict.project_tag,
            )
        )

        with Session(self._sa_engine) as sa_session:
            project = sa_session.scalar(project_statement)
            if not project:
                raise ValueError(
                    f"Project {view_dict.project_namespace}/{view_dict.project_name}:{view_dict.project_tag} does not exist"
                )
            view = Views(
                name=view_name,
                description=description,
                project_mapping=project,
            )
            sa_session.add(view)

            for sample_name in view_dict.sample_list:
                sample_statement = select(Samples.id).where(
                    and_(
                        Samples.project_id == project.id,
                        Samples.sample_name == sample_name,
                    )
                )
                sample_id = sa_session.execute(sample_statement).one()[0]
                if not sample_id:
                    raise ValueError(
                        f"Sample {view_dict.project_namespace}/{view_dict.project_name}:{view_dict.project_tag}:{sample_name} does not exist"
                    )
                sa_session.add(ViewSampleAssociation(sample_id=sample_id, view=view))

            sa_session.commit()

    def delete(
        self,
        project_namespace: str,
        project_name: str,
        project_tag: str = DEFAULT_TAG,
        view_name: str = None,
    ) -> None:
        """
        Delete a view of the project in the database.

        :param project_namespace: namespace of the project
        :param project_name: name of the project
        :param project_tag: tag of the project
        :param view_name: name of the view
        :return: None
        """
        view_statement = select(Views).where(
            and_(
                Views.project_mapping.has(
                    namespace=project_namespace, name=project_name, tag=project_tag
                ),
                Views.name == view_name,
            )
        )

        with Session(self._sa_engine) as sa_session:
            view = sa_session.scalar(view_statement)
            if not view:
                raise ViewNotFoundError(
                    f"View {view_name} of the project {project_namespace}/{project_name}:{project_tag} does not exist"
                )
            sa_session.delete(view)
            sa_session.commit()

    def add_sample(
        self,
        namespace: str,
        name: str,
        tag: str,
        view_name: str,
        sample_name: Union[str, List[str]],
    ):
        """
        Add sample to the view.

        :param namespace: namespace of the project
        :param name: name of the project
        :param tag: tag of the project
        :param view_name: name of the view
        :param sample_name: sample name
        :return: None
        """
        if isinstance(sample_name, str):
            sample_name = [sample_name]
        view_statement = select(Views).where(
            and_(
                Views.project_mapping.has(namespace=namespace, name=name, tag=tag),
                Views.name == view_name,
            )
        )

        with Session(self._sa_engine) as sa_session:
            view = sa_session.scalar(view_statement)
            if not view:
                raise ViewNotFoundError(
                    f"View {view_name} of the project {namespace}/{name}:{tag} does not exist"
                )
            for sample_name_one in sample_name:
                sample_statement = select(Samples).where(
                    and_(
                        Samples.project_id == view.project_mapping.id,
                        Samples.sample_name == sample_name_one,
                    )
                )
                sample = sa_session.scalar(sample_statement)
                if not sample:
                    raise ValueError(
                        f"Sample {namespace}/{name}:{tag}:{sample_name} does not exist"
                    )
                try:
                    sa_session.add(ViewSampleAssociation(sample=sample, view=view))
                    sa_session.commit()
                except IntegrityError:
                    raise SampleAlreadyInView(
                        f"Sample {namespace}/{name}:{tag}:{sample_name} already in view {view_name}"
                    )

        return None

    def remove_sample(
        self,
        namespace: str,
        name: str,
        tag: str,
        view_name: str,
        sample_name: str,
    ) -> None:
        """
        Remove sample from the view.

        :param namespace: namespace of the project
        :param name: name of the project
        :param tag: tag of the project
        :param view_name: name of the view
        :param sample_name: sample name
        :return: None
        """
        view_statement = select(Views).where(
            and_(
                Views.project_mapping.has(namespace=namespace, name=name, tag=tag),
                Views.name == view_name,
            )
        )

        with Session(self._sa_engine) as sa_session:
            view = sa_session.scalar(view_statement)
            if not view:
                raise ViewNotFoundError(
                    f"View {view_name} of the project {namespace}/{name}:{tag} does not exist"
                )
            sample_statement = select(Samples).where(
                and_(
                    Samples.project_id == view.project_mapping.id,
                    Samples.sample_name == sample_name,
                )
            )
            sample = sa_session.scalar(sample_statement)
            delete_statement = delete(ViewSampleAssociation).where(
                and_(
                    ViewSampleAssociation.sample_id == sample.id,
                    ViewSampleAssociation.view_id == view.id,
                )
            )
            sa_session.execute(delete_statement)
            sa_session.commit()

        return None

    def get_snap_view(
        self, namespace: str, name: str, tag: str, sample_name_list: List[str], raw: bool = False
    ) -> Union[peppy.Project, dict]:
        """
        Get a snap view of the project. Snap view is a view of the project
        with only the samples in the list. This view won't be saved in the database.

        :param namespace: project namespace
        :param name: name of the project
        :param tag: tag of the project
        :param sample_name_list: list of sample names e.g. ["sample1", "sample2"]
        :param raw: retrieve unprocessed (raw) PEP dict.
        :return: peppy.Project object
        """
        project_statement = select(Projects).where(
            and_(
                Projects.namespace == namespace,
                Projects.name == name,
                Projects.tag == tag,
            )
        )
        with Session(self._sa_engine) as sa_session:
            project = sa_session.scalar(project_statement)
            if not project:
                raise ValueError(f"Project {namespace}/{name}:{tag} does not exist")
            samples = []
            for sample_name in sample_name_list:
                sample_statement = select(Samples).where(
                    and_(
                        Samples.project_id == project.id,
                        Samples.sample_name == sample_name,
                    )
                )
                sample = sa_session.scalar(sample_statement)
                if not sample:
                    raise ValueError(
                        f"Sample {namespace}/{name}:{tag}:{sample_name} does not exist"
                    )
                samples.append(sample.sample)
            config = project.config

        if raw:
            return {"_config": config, "_sample_dict": samples, "_subsample_dict": None}
        else:
            return peppy.Project.from_dict(
                {"_config": config, "_sample_dict": samples, "_subsample_dict": None}
            )
