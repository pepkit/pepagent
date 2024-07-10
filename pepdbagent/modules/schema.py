import datetime
import json
import logging
from typing import Dict, List, NoReturn, Union

import numpy as np
import peppy
from peppy.const import (
    CONFIG_KEY,
    SAMPLE_NAME_ATTR,
    SAMPLE_RAW_DICT_KEY,
    SAMPLE_TABLE_INDEX_KEY,
    SUBSAMPLE_RAW_LIST_KEY,
)
from sqlalchemy import Select, and_, delete, select, or_, func
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.exc import IntegrityError, NoResultFound

from pepdbagent.const import (
    DEFAULT_TAG,
    DESCRIPTION_KEY,
    MAX_HISTORY_SAMPLES_NUMBER,
    NAME_KEY,
    PEPHUB_SAMPLE_ID_KEY,
    PKG_NAME,
)
from pepdbagent.db_utils import (
    BaseEngine,
    Schemas,
    SchemaGroups,
    SchemaGroupRelations,
)
from pepdbagent.exceptions import (
    SchemaAlreadyExistsError,
    SchemaDoesNotExistError,
    SchemaGroupAlreadyExistsError,
    SchemaGroupDoesNotExistError,
)
from pepdbagent.models import (
    SchemaAnnotation,
    SchemaSearchResult,
    SchemaGroupAnnotation,
    SchemaGroupSearchResult,
)
from pepdbagent.utils import create_digest, generate_guid, order_samples, registry_path_converter

_LOGGER = logging.getLogger(PKG_NAME)


class PEPDatabaseSchemas:
    """
    Class that represents Schemas in Database.

    While using this class, user can create, retrieve, delete, and update schemas from database
    """

    def __init__(self, pep_db_engine: BaseEngine):
        """
        :param pep_db_engine: pepdbengine object with sa engine
        """
        self._sa_engine = pep_db_engine.engine
        self._pep_db_engine = pep_db_engine

    def get(self, namespace: str, name: str) -> dict:
        """
        Get schema from the database.

        :param namespace: user namespace
        :param name: schema name

        :return: schema dict
        """

        with Session(self._sa_engine) as session:
            schema_obj = session.scalar(
                select(Schemas).where(and_(Schemas.namespace == namespace, Schemas.name == name))
            )

            if not schema_obj:
                raise SchemaDoesNotExistError(f"Schema '{name}' does not exist in the database")

            return schema_obj.schema_json

    def info(self, namespace: str, name: str) -> SchemaAnnotation:
        """
        Get schema information from the database.

        :param namespace: user namespace
        :param name: schema name

        :return: SchemaAnnotation object:
                    - namespace: schema namespace
                    - name: schema name
                    - last_update_date: last update date
                    - submission_date: submission date
                    - description: schema description
        """

        with Session(self._sa_engine) as session:
            schema_obj = session.scalar(
                select(Schemas).where(and_(Schemas.namespace == namespace, Schemas.name == name))
            )

            if not schema_obj:
                raise SchemaDoesNotExistError(f"Schema '{name}' does not exist in the database")

            return SchemaAnnotation(
                namespace=schema_obj.namespace,
                name=schema_obj.name,
                last_update_date=schema_obj.last_update_date,
                submission_date=schema_obj.submission_date,
                description=schema_obj.description,
            )

    def search(
        self, namespace: str = None, search_str: str = "", limit: int = 100, offset: int = 0
    ) -> SchemaSearchResult:
        """
        Search schemas in the database.

        :param namespace: user namespace [Default: None]. If None, search in all namespaces
        :param search_str: query string. [Default: ""]. If empty, return all schemas
        :param limit: limit number of schemas [Default: 100]
        :param offset: offset number of schemas [Default: 0]

        :return: list of schema dicts
        """

        statement = select(Schemas)
        statement = self._add_condition(statement, namespace, search_str)
        statement = statement.limit(limit).offset(offset)

        return_list = []

        with Session(self._sa_engine) as session:
            results = session.scalars(statement)

            for result in results:
                return_list.append(
                    SchemaAnnotation(
                        namespace=result.namespace,
                        name=result.name,
                        last_update_date=result.last_update_date,
                        submission_date=result.submission_date,
                        description=result.description,
                    )
                )

        return SchemaSearchResult(
            count=self._count_search(namespace=namespace, search_str=search_str),
            limit=limit,
            offset=offset,
            results=return_list,
        )

    def _count_search(self, namespace: str = None, search_str: str = "") -> int:
        """
        Count number of found schemas

        :param namespace: user namespace [Default: None]. If None, search in all namespaces
        :param search_str: query string. [Default: ""]. If empty, return all schemas

        :return: list of schema dicts
        """
        statement = select(func.count(Schemas.id))

        statement = self._add_condition(statement, namespace, search_str)

        with Session(self._sa_engine) as session:
            result = session.execute(statement).one()

            return result[0]

    @staticmethod
    def _add_condition(
        statement: Select,
        namespace: str = None,
        search_str: str = None,
    ) -> Select:
        if search_str:
            sql_search_str = f"%{search_str}%"
            search_query = or_(
                Schemas.name.ilike(sql_search_str),
                Schemas.description.ilike(sql_search_str),
            )
            statement = statement.where(search_query)
        if namespace:
            statement = statement.where(Schemas.namespace == namespace)
        return statement

    def create(
        self,
        namespace: str,
        name: str,
        schema: dict,
        description: str = "",
        # private: bool = False, # TODO: for simplicity was not implemented yet
        overwrite: bool = False,
        update_only: bool = False,
    ) -> None:
        """
        Create or update schema in the database.

        :param namespace: user namespace
        :param name: schema name
        :param schema: schema dict
        :param description: schema description [Default: ""]
        :param overwrite: overwrite schema if exists [Default: False]
        :param update_only: update only schema if exists [Default: False]
        """

        if self.exist(namespace, name):
            if overwrite:
                self.update(namespace, name, schema, description)
                return None
            elif update_only:
                self.update(namespace, name, schema, description)
                return None
            else:
                raise SchemaAlreadyExistsError(f"Schema '{name}' already exists in the database")

        if update_only:
            raise SchemaDoesNotExistError(
                f"Schema '{name}' does not exist in the database"
                f"Cannot update schema that does not exist"
            )

        with Session(self._sa_engine) as session:
            schema_obj = Schemas(
                namespace=namespace,
                name=name,
                schema_json=schema,
                description=description,
            )
            session.add(schema_obj)
            session.commit()

    def update(
        self,
        namespace: str,
        name: str,
        schema: dict,
        description: str = "",
        # private: bool = False, # TODO: for simplicity was not implemented yet
    ) -> None:
        """
        Update schema in the database.

        :param namespace: user namespace
        :param name: schema name
        :param schema: schema dict
        :param description: schema description [Default: ""]

        :return: None
        """

        with Session(self._sa_engine) as session:
            schema_obj = session.scalar(
                select(Schemas).where(and_(Schemas.namespace == namespace, Schemas.name == name))
            )

            if not schema_obj:
                raise SchemaDoesNotExistError(f"Schema '{name}' does not exist in the database")

            schema_obj.schema_json = schema
            schema_obj.description = description
            flag_modified(schema_obj, "schema_json")

            session.commit()

    def delete(self, namespace: str, name: str) -> None:
        """
        Delete schema from the database.

        :param namespace: user namespace
        :param name: schema name

        :return: None
        """

        with Session(self._sa_engine) as session:
            schema_obj = session.scalar(
                select(Schemas).where(and_(Schemas.namespace == namespace, Schemas.name == name))
            )

            if not schema_obj:
                raise SchemaDoesNotExistError(f"Schema '{name}' does not exist in the database")

            session.delete(schema_obj)

            session.commit()

    def exist(self, namespace: str, name: str) -> bool:
        """
        Check if schema exists in the database.

        :param namespace: user namespace
        :param name: schema name

        :return: True if schema exists, False otherwise
        """

        with Session(self._sa_engine) as session:
            schema_obj = session.scalar(
                select(Schemas).where(and_(Schemas.namespace == namespace, Schemas.name == name))
            )
            return True if schema_obj else False

    def group_create(self, namespace: str, name: str, description: str = "") -> None:
        """
        Create schema group in the database.

        :param namespace: user namespace
        :param name: schema group name
        :param description: schema group description [Default: ""]

        :return: None
        """
        try:
            with Session(self._sa_engine) as session:
                session.add(
                    SchemaGroups(
                        namespace=namespace,
                        name=name,
                        description=description,
                    )
                )
                session.commit()

        except IntegrityError:
            raise SchemaGroupAlreadyExistsError

    def group_get(self, namespace: str, name: str) -> SchemaGroupAnnotation:
        """
        Get schema group from the database.

        :param namespace: user namespace
        :param name: schema group name

        :return: SchemaGroupAnnotation object:
            - namespace: schema group namespace
            - name: schema group name
            - description: schema group description
            - schemas: list of SchemaAnnotation objects
        """

        with Session(self._sa_engine) as session:
            schema_group_obj = session.scalar(
                select(SchemaGroups).where(
                    and_(SchemaGroups.namespace == namespace, SchemaGroups.name == name)
                )
            )

            if not schema_group_obj:
                raise SchemaGroupDoesNotExistError(
                    f"Schema group '{name}' does not exist in the database"
                )

            schemas = []
            for schema_relation in schema_group_obj.schema_relation_mapping:
                schema_annotation = schema_relation.schema_mapping
                schemas.append(
                    SchemaAnnotation(
                        namespace=schema_annotation.namespace,
                        name=schema_annotation.name,
                        last_update_date=schema_annotation.last_update_date,
                        submission_date=schema_annotation.submission_date,
                        desciription=schema_annotation.description,
                    )
                )

            return SchemaGroupAnnotation(
                namespace=schema_group_obj.namespace,
                name=schema_group_obj.name,
                description=schema_group_obj.description,
                schemas=schemas,
            )

    def group_search(
        self, namespace: str = None, search_str: str = "", limit: int = 100, offset: int = 0
    ) -> SchemaGroupSearchResult:
        """
        Search schema groups in the database.

        :param namespace: user namespace [Default: None]. If None, search in all namespaces
        :param search_str: query string. [Default: ""]. If empty, return all schema groups
        :param limit: limit of the search
        :param offset: offset of the search

        :return: SchemaGroupSearchResult object:
            - count: number of found schema groups
            - limit: limit number of schema groups
            - offset: offset number of schema groups
            - results: list of SchemaGroupAnnotation objects
        """

        statement = select(SchemaGroups)
        statement = self._add_group_condition(
            statement=statement, namespace=namespace, search_str=search_str
        )

        with Session(self._sa_engine) as session:
            results = session.scalars(statement)

            return_results = []
            for result in results:
                return_results.append(
                    SchemaGroupAnnotation(
                        namespace=result.namespace,
                        name=result.name,
                        description=result.description,
                        schemas=[],
                    )
                )

        return SchemaGroupSearchResult(
            count=self._group_search_count(namespace, search_str),
            limit=limit,
            offset=offset,
            results=return_results,
        )

    @staticmethod
    def _add_group_condition(
        statement: Select,
        namespace: str = None,
        search_str: str = "",
    ) -> Select:
        """
        Add query condition to statement in group search

        :param statement: Select statement
        :param namespace: Namespace of schema group [Default: None]. If none set, all search in all namespaces
        :param search_str: Search string to look for schemas. Search in name and description of the group
        """
        if search_str:
            sql_search_str = f"%{search_str}%"
            search_query = or_(
                SchemaGroups.name.ilike(sql_search_str),
                SchemaGroups.description.ilike(sql_search_str),
            )
            statement = statement.where(search_query)
        if namespace:
            statement = statement.where(SchemaGroups.namespace == namespace)
        return statement

    def _group_search_count(self, namespace: str = None, search_str: str = ""):
        """
        Count number of found group of schemas

        :param namespace: user namespace [Default: None]. If None, search in all namespaces
        :param search_str: query string. [Default: ""]. If empty, return all schemas

        :return: list of schema dicts
        """
        statement = select(func.count(SchemaGroups.id))

        statement = self._add_condition(statement, namespace, search_str)

        with Session(self._sa_engine) as session:
            result = session.execute(statement).one()

            return result[0]

    def group_delete(self, namespace: str, name: str) -> None:
        """
        Delete schema group from the database.

        :param namespace: user namespace
        :param name: schema group name

        :return: None
        """

        if self.group_exist(namespace, name):
            raise SchemaGroupDoesNotExistError(
                f"Schema group '{name}' does not exist in the database"
            )

        with Session(self._sa_engine) as session:
            session.execute(
                delete(SchemaGroups).where(
                    and_(SchemaGroups.namespace == namespace, SchemaGroups.name == name)
                )
            )

            session.commit()

    def group_add_schema(
        self, namespace: str, name: str, schema_namespace: str, schema_name: str
    ) -> None:
        """
        Add schema to the schema group.

        :param namespace: user namespace
        :param name: schema group name
        :param schema_namespace: schema namespace
        :param schema_name: schema name

        :return: None
        """
        ...

    def group_remove_schema(
        self, namespace: str, name: str, schema_namespace: str, schema_name: str
    ) -> None:
        """
        Remove schema from the schema group.

        :param namespace: user namespace
        :param name: schema group name
        :param schema_namespace: schema namespace
        :param schema_name: schema name

        :return: None
        """
        ...

    def group_exist(self, namespace: str, name: str) -> bool:
        """
        Check if schema group exists in the database.

        :param namespace: user namespace
        :param name: schema group name

        :return: True if schema group exists, False otherwise
        """

        with Session(self._sa_engine) as session:
            schema_group_obj = session.scalar(
                select(SchemaGroups).where(
                    and_(SchemaGroups.namespace == namespace, SchemaGroups.name == name)
                )
            )
            return True if schema_group_obj else False
