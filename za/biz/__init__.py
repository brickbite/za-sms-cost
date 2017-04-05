import threading
import contextlib
import sqlalchemy
import sqlalchemy.ext.serializer
import sqlalchemy.ext.declarative
import za

# TODO use a UUID custom type
# TODO use an E.164 custom type
# TODO use an ISO 4217 custom type

sa = sqlalchemy
no_arg = object()
logger = za.get_logger(__name__)


class DomainBaseBase(object):
    def __str__(self):
        try:
            return "{}(id={})".format(type(self).__name__, self.id)
        except:
            logger.exception("failed in __str__()")

            return object.__str__(self)

    @property
    def session(self):
        return sa.inspect(self).session

    @classmethod
    def from_id(class_, id_):
        return g.session.query(class_).get(id_)


def _generate_columns_names(constraint, table, referred=False):
    def name_for_column(column):
        if isinstance(column, basestring):
            assert column in table.columns

            return column
        else:
            return column.name

    return "_".join(sorted(map(name_for_column, constraint.columns)))


def _generate_foreign_names(constraint, table):
    def yield_names():
        for column in constraint.columns:
            if isinstance(column, basestring):
                column = table.columns[column]

            for key in column.foreign_keys:
                yield key.target_fullname.replace(".", "_")

    return "__".join(sorted(yield_names()))

convention = {
    "column_names": _generate_columns_names,
    "foreign_names": _generate_foreign_names,
    "ix": "ix_%(table_name)s_%(column_names)s",
    "uq": "uq_%(table_name)s_%(column_names)s",
    "ck": "ck_%(table_name)s_%(column_names)s",
    "fk": "fk_%(table_name)s_%(column_names)s__%(foreign_names)s",
    "pk": "pk_%(table_name)s_%(column_names)s"}
DomainBase = sa.ext.declarative.declarative_base(
    name="DomainBase",
    metadata=sa.MetaData(naming_convention=convention),
    cls=DomainBaseBase)


def named_record_type(type_names):
    def decorator(class_):
        if not issubclass(class_, DomainBase):
            raise Exception("{} is not a record class".format(class_.__name__))

        # update type name registry
        name = class_.__mapper_args__["polymorphic_identity"]

        assert name not in type_names

        type_names[name] = class_

        return class_

    return decorator


#
# GLOBAL CONTEXT
#

def change_global_proxy(proxy):
    global g

    g = proxy

    return g

g = threading.local()


def set_global(session):
    if getattr(g, "session", None) is not None:
        raise Exception("set_global() called again without remove_global()")

    g.session = session


def remove_global():
    remove()

    g.session = None


@contextlib.contextmanager
def global_context(*args, **kwargs):
    set_global(*args, **kwargs)

    try:
        yield
    finally:
        remove_global()


#
# TRANSACTION CONTROL
#

def flush():
    """Flush the pending transaction."""
    g.session.flush()


def commit():
    """Commit the pending transaction."""
    g.session.commit()


def remove():
    """Remove the pending transaction."""
    g.session.remove()
