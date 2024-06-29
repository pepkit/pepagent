import datetime
import logging
from typing import List, Optional

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    FetchedValue,
    ForeignKey,
    Result,
    Select,
    String,
    UniqueConstraint,
    event,
    select,
)
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.engine import URL, create_engine
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

from pepdbagent.const import PKG_NAME, POSTGRES_DIALECT
from pepdbagent.exceptions import SchemaError

_LOGGER = logging.getLogger(PKG_NAME)


class BIGSERIAL(BigInteger):
    pass


@compiles(BIGSERIAL, POSTGRES_DIALECT)
def compile_bigserial_pg(type_, compiler, **kw):
    return "BIGSERIAL"


@compiles(JSON, POSTGRES_DIALECT)
def compile_jsonb_pg(type_, compiler, **kw):
    return "JSON"


class Base(DeclarativeBase):
    type_annotation_map = {datetime.datetime: TIMESTAMP(timezone=True)}


@event.listens_for(Base.metadata, "after_create")
def receive_after_create(target, connection, tables, **kw):
    """
    listen for the 'after_create' event
    """
    if tables:
        _LOGGER.info("A table was created")
    else:
        _LOGGER.info("A table was not created")


# def deliver_description(context):
#     return context.get_current_parameters()["config"]["description"]


def deliver_update_date(context):
    return datetime.datetime.now(datetime.timezone.utc)


class Projects(Base):
    """
    Projects table representation in the database
    """

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    namespace: Mapped[str] = mapped_column()
    name: Mapped[str] = mapped_column()
    tag: Mapped[str] = mapped_column()
    digest: Mapped[str] = mapped_column(String(32))
    description: Mapped[Optional[str]]
    config: Mapped[dict] = mapped_column(JSON, server_default=FetchedValue())
    private: Mapped[bool]
    number_of_samples: Mapped[int]
    number_of_stars: Mapped[int] = mapped_column(default=0)
    submission_date: Mapped[datetime.datetime]
    last_update_date: Mapped[Optional[datetime.datetime]] = mapped_column(
        default=deliver_update_date,  # onupdate=deliver_update_date, # This field should not be updated, while we are adding project to favorites
    )
    pep_schema: Mapped[Optional[str]]
    pop: Mapped[Optional[bool]] = mapped_column(default=False)
    samples_mapping: Mapped[List["Samples"]] = relationship(
        back_populates="project_mapping", cascade="all, delete-orphan"
    )
    subsamples_mapping: Mapped[List["Subsamples"]] = relationship(
        back_populates="subsample_mapping", cascade="all, delete-orphan"
    )
    stars_mapping: Mapped[List["Stars"]] = relationship(
        back_populates="project_mapping", cascade="all, delete-orphan"
    )
    views_mapping: Mapped[List["Views"]] = relationship(
        back_populates="project_mapping", cascade="all, delete-orphan"
    )

    # Self-referential relationship. The parent project is the one that was forked to create this one.
    forked_from_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    forked_from_mapping = relationship(
        "Projects",
        back_populates="forked_to_mapping",
        remote_side=[id],
        single_parent=True,
        cascade="all",
    )

    forked_to_mapping = relationship(
        "Projects", back_populates="forked_from_mapping", cascade="all"
    )

    __table_args__ = (UniqueConstraint("namespace", "name", "tag"),)


class Samples(Base):
    """
    Samples table representation in the database
    """

    __tablename__ = "samples"

    id: Mapped[int] = mapped_column(primary_key=True)
    sample: Mapped[dict] = mapped_column(JSON, server_default=FetchedValue())
    row_number: Mapped[int]  # TODO: should be removed
    project_id = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    project_mapping: Mapped["Projects"] = relationship(back_populates="samples_mapping")
    sample_name: Mapped[Optional[str]] = mapped_column()
    guid: Mapped[Optional[str]] = mapped_column(nullable=False, unique=True)

    parent_guid: Mapped[Optional[str]] = mapped_column(
        ForeignKey("samples.guid", ondelete="CASCADE"),
        nullable=True,
        doc="Parent sample id. Used to create a hierarchy of samples.",
    )

    parent_mapping: Mapped["Samples"] = relationship(
        "Samples", remote_side=guid, back_populates="child_mapping"
    )
    child_mapping: Mapped["Samples"] = relationship("Samples", back_populates="parent_mapping")

    views: Mapped[Optional[List["ViewSampleAssociation"]]] = relationship(
        back_populates="sample", cascade="all, delete-orphan"
    )


class Subsamples(Base):
    """
    Subsamples table representation in the database
    """

    __tablename__ = "subsamples"

    id: Mapped[int] = mapped_column(primary_key=True)
    subsample: Mapped[dict] = mapped_column(JSON, server_default=FetchedValue())
    subsample_number: Mapped[int]
    row_number: Mapped[int]
    project_id = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    subsample_mapping: Mapped["Projects"] = relationship(back_populates="subsamples_mapping")


class User(Base):
    """
    User table representation in the database
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    namespace: Mapped[str] = mapped_column(nullable=False, unique=True)
    stars_mapping: Mapped[List["Stars"]] = relationship(
        back_populates="user_mapping",
        cascade="all, delete-orphan",
        order_by="Stars.star_date.desc()",
    )


class Stars(Base):
    """
    FavoriteProjects table representation in the database
    """

    __tablename__ = "stars"

    user_id = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    project_id = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    user_mapping: Mapped[List["User"]] = relationship(back_populates="stars_mapping")
    project_mapping: Mapped["Projects"] = relationship(back_populates="stars_mapping")
    star_date: Mapped[datetime.datetime] = mapped_column(
        onupdate=deliver_update_date, default=deliver_update_date
    )


class Views(Base):
    """
    Views table representation in the database
    """

    __tablename__ = "views"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column()
    description: Mapped[Optional[str]]

    project_id = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    project_mapping = relationship("Projects", back_populates="views_mapping")

    samples: Mapped[List["ViewSampleAssociation"]] = relationship(
        back_populates="view", cascade="all, delete-orphan"
    )

    _table_args__ = (UniqueConstraint("name", "project_id"),)


class ViewSampleAssociation(Base):
    """
    Association table between views and samples
    """

    __tablename__ = "views_samples"

    sample_id = mapped_column(ForeignKey("samples.id", ondelete="CASCADE"), primary_key=True)
    view_id = mapped_column(ForeignKey("views.id", ondelete="CASCADE"), primary_key=True)
    sample: Mapped["Samples"] = relationship(back_populates="views")
    view: Mapped["Views"] = relationship(back_populates="samples")


class SchemaTags(Base):
    """
    Tags associated with schemas in the database
    """

    __tablename__ = "schema_tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    tag: Mapped[str] = mapped_column(nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(nullable=False)

    schemas_mapping: Mapped[List["Schemas"]] = relationship(back_populates="tag_mapping")


class Schemas(Base):
    """
    Table representation of schemas in the database
    """

    __tablename__ = "schemas"

    id: Mapped[int] = mapped_column(primary_key=True)
    namespace: Mapped[str] = mapped_column(ForeignKey("users.namespace", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(nullable=False)
    tag_id: Mapped[int] = mapped_column(ForeignKey("schema_tags.id", ondelete="CASCADE"))
    tag_mapping: Mapped["SchemaTags"] = relationship(back_populates="schemas_mapping")

    schema_dict: Mapped[dict] = mapped_column(JSON, server_default=FetchedValue())

    __table_args__ = (UniqueConstraint("namespace", "name"),)


class BaseEngine:
    """
    A class with base methods, that are used in several classes. e.g. fetch_one or fetch_all
    """

    def __init__(
        self,
        *,
        host: str = "localhost",
        port: int = 5432,
        database: str = "pep-db",
        user: str = None,
        password: str = None,
        drivername: str = POSTGRES_DIALECT,
        dsn: str = None,
        echo: bool = False,
    ):
        """
        Initialize connection to the pep_db database. You can use The basic connection parameters
        or libpq connection string.
        :param host: database server address e.g., localhost or an IP address.
        :param port: the port number that defaults to 5432 if it is not provided.
        :param database: the name of the database that you want to connect.
        :param user: the username used to authenticate.
        :param password: password used to authenticate.
        :param drivername: driver used in
        :param dsn: libpq connection string using the dsn parameter
        (e.g. 'postgresql://user_name:password@host_name:port/db_name')
        """
        if not dsn:
            dsn = URL.create(
                host=host,
                port=port,
                database=database,
                username=user,
                password=password,
                drivername=drivername,
            )

        self._engine = create_engine(dsn, echo=echo)
        self.create_schema(self._engine)
        self.check_db_connection()

    def create_schema(self, engine=None):
        """
        Create sql schema in the database.

        :param engine: sqlalchemy engine [Default: None]
        :return: None
        """
        if not engine:
            engine = self._engine
        Base.metadata.create_all(engine)
        return None

    def session_execute(self, statement: Select) -> Result:
        """
        Execute statement using sqlalchemy statement

        :param statement: SQL query or a SQL expression that is constructed using
            SQLAlchemy's SQL expression language
        :return: query result represented with declarative base
        """
        _LOGGER.debug(f"Executing statement: {statement}")
        with Session(self._engine) as session:
            query_result = session.execute(statement)

        return query_result

    @property
    def session(self):
        """
        :return: started sqlalchemy session
        """
        return self._start_session()

    @property
    def engine(self):
        return self._engine

    def _start_session(self):
        session = Session(self.engine)
        try:
            session.execute(select(Projects).limit(1))
        except ProgrammingError:
            raise SchemaError()

        return session

    def check_db_connection(self):
        try:
            self.session_execute(select(Projects).limit(1))
        except ProgrammingError:
            raise SchemaError()

    def delete_schema(self, engine=None) -> None:
        """
        Delete sql schema in the database.

        :param engine: sqlalchemy engine [Default: None]
        :return: None
        """
        if not engine:
            engine = self._engine
        Base.metadata.drop_all(engine)
        return None
