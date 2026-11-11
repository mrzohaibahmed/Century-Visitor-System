"""Classifies SQL Server driver errors (pyodbc, possibly wrapped by SQLAlchemy) without quoting them."""
import re

from sqlalchemy.exc import IntegrityError

UNIQUE_VIOLATIONS = frozenset({2601, 2627})   # duplicate key in a unique index / a UNIQUE or PRIMARY KEY
DEADLOCK = 1205                                # chosen as the deadlock victim: safe to retry the transaction
# pyodbc ends each message with the native number, then the ODBC call: "... value is (x). (2627) (SQLExecute)";
# several messages are joined with "; ". Only a number in that position counts (not a quoted data value).
_NATIVE_CODE = re.compile(r"\((\d{1,6})\)(?=\s*(?:\(SQL[A-Za-z]+\)|;|$))")


def native_errors(error: BaseException) -> set[int]:
    """SQL Server error numbers in a driver error (pyodbc puts them in the message, e.g. "... (2627)")."""
    orig = getattr(error, "orig", error)
    return {int(code) for arg in getattr(orig, "args", ()) if isinstance(arg, str)
            for code in _NATIVE_CODE.findall(arg)}


def sqlstate(error: BaseException) -> str | None:
    orig = getattr(error, "orig", error)
    args = getattr(orig, "args", ())
    return args[0] if args and isinstance(args[0], str) and len(args[0]) == 5 else None


def is_duplicate_key(error: BaseException) -> bool:
    return isinstance(error, IntegrityError) and bool(native_errors(error) & UNIQUE_VIOLATIONS)


def is_deadlock(error: BaseException) -> bool:
    return sqlstate(error) == "40001" or DEADLOCK in native_errors(error)


def describe_error(error: BaseException) -> str:
    """For logs and the console: the driver error's type and SQLSTATE, never its message (which can quote
    data values or the server) and never the connection string."""
    orig = getattr(error, "orig", error)
    state = sqlstate(error)
    return f"{type(orig).__name__}{f' (SQLSTATE {state})' if state else ''}"
