import sqlparse
from sqlparse.sql import IdentifierList, Identifier, Function
from sqlparse.tokens import Keyword, DML


class SQLValidator:
    ALLOWED_KEYWORDS = {"SELECT", "WITH", "FROM", "WHERE", "GROUP", "ORDER", "LIMIT", "JOIN"}
    BLACKLISTED_KEYWORDS = {"DROP", "DELETE", "TRUNCATE", "ALTER", "GRANT", "INSERT", "UPDATE"}

    @classmethod
    def validate(cls, sql: str):
        # 解析SQL
        parsed = sqlparse.parse(sql)

        for stmt in parsed:
            # 检查是否包含危险操作
            for token in stmt.tokens:
                if token.ttype is DML and token.value.upper() != "SELECT":
                    raise ValueError("Only SELECT queries are allowed")

                if token.ttype is Keyword and token.value.upper() in cls.BLACKLISTED_KEYWORDS:
                    raise ValueError(f"Dangerous keyword detected: {token.value}")

            # 检查白名单关键字
            keywords = [t.value.upper() for t in stmt.tokens if t.ttype is Keyword]
            if any(kw not in cls.ALLOWED_KEYWORDS for kw in keywords):
                invalid = [kw for kw in keywords if kw not in cls.ALLOWED_KEYWORDS]
                raise ValueError(f"Disallowed SQL keywords: {', '.join(invalid)}")