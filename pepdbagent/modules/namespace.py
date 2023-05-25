from typing import Union, List
import logging

from sqlalchemy.orm import Session
from sqlalchemy import Engine
from sqlalchemy import insert, select, delete, update, func, distinct
from sqlalchemy import and_, or_

from pepdbagent.db_utils import Projects
from pepdbagent.const import (
    DEFAULT_LIMIT,
    DEFAULT_OFFSET,
)

from pepdbagent.models import Namespace, NamespaceList
from pepdbagent.utils import tuple_converter

_LOGGER = logging.getLogger("pepdbagent")


class PEPDatabaseNamespace:
    """
    Class that represents project Namespaces in Database.

    While using this class, user can retrieve all necessary metadata about PEPs
    """

    def __init__(self, engine: Engine):
        """
        :param engine: Connection to db represented by sqlalchemy engine
        """
        self._sa_engine = engine

    def get(
        self,
        query: str = "",
        admin: Union[List[str], str] = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = DEFAULT_OFFSET,
    ) -> NamespaceList:
        """
        Search available namespaces in the database
        :param query: search string
        :param admin: list of namespaces where user is admin
        :param offset: offset of the search
        :param limit: limit of the search
        :return: Search result:
            {
                total number of results
                search limit
                search offset
                search results
            }
        """
        _LOGGER.info(
            f"Getting namespaces annotation with provided info: (query: {query})"
        )
        admin_tuple = tuple_converter(admin)
        return NamespaceList(
            count=self._count_namespace(search_str=query, admin_nsp=admin_tuple),
            limit=limit,
            offset=offset,
            results=self._get_namespace(
                search_str=query, admin_nsp=admin_tuple, limit=limit, offset=offset
            ),
        )

    def _get_namespace(
        self,
        search_str: str,
        admin_nsp: tuple = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = DEFAULT_OFFSET,
    ) -> List[Namespace]:
        """
        Search for namespace by providing search string.
        :param search_str: string of symbols, words, keywords to search in the
            namespace name.
        :param admin_nsp: tuple of namespaces where project can be retrieved if they are privet
        :param limit: limit of return results
        :param offset: number of results off set (that were already showed)
        :return: list of dict with structure {
                namespace,
                number_of_projects,
                number_of_samples,
            }
        """
        statement = select(Projects.namespace,
                           func.count(Projects.name).label("number_of_projects"),
                           func.sum(Projects.number_of_samples).label("number_of_samples"),
                           ).group_by(Projects.namespace).select_from(Projects)

        if search_str:
            sql_search_str = f"%{search_str}%"
            statement = statement.where(
                or_(
                    Projects.namespace.ilike(sql_search_str),
                )
            )
        statement = statement.where(
            or_(Projects.private.is_(False), Projects.namespace.in_(admin_nsp))
        )
        statement = statement.limit(limit).offset(offset)
        with Session(self._sa_engine) as session:
            query_results = session.execute(statement).all()

        results_list = []
        for res in query_results:
            results_list.append(
                Namespace(
                    namespace=res.namespace,
                    number_of_projects=res.number_of_projects,
                    number_of_samples=res.number_of_samples,
                )
            )
        return results_list

    def _count_namespace(self, search_str: str = None, admin_nsp: tuple = None) -> int:
        """
        Get number of found namespace. [This function is related to _get_namespaces]
        :param search_str: string of symbols, words, keywords to search in the
            namespace name.
        :param admin_nsp: tuple of namespaces where project can be retrieved if they are privet
        :return: number of found namespaces
        """
        statement = select(func.count(distinct(Projects.namespace)).label("number_of_namespaces")).select_from(Projects)
        if search_str:
            sql_search_str = f"%{search_str}%"
            statement = statement.where(
                or_(
                    Projects.namespace.ilike(sql_search_str),
                )
            )
        statement = statement.where(
            or_(Projects.private.is_(False), Projects.namespace.in_(admin_nsp))
        )
        with Session(self._sa_engine) as session:
            query_results = session.execute(statement).first()

        return query_results.number_of_namespaces
