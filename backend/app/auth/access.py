"""What one signed-in user may see. Built once per request and passed to every endpoint and agent tool."""

from dataclasses import dataclass, field

from app.auth.service import SPREADSHEETS, permissions_for

ALL = "*"
TOP_LEVEL = "/"  # folder grant for files directly in data/docs (not in a subfolder)


@dataclass(frozen=True)
class RowRule:
    """In <source>.<table>, <column> must match the user's <attribute>."""

    kind: str  # "spreadsheet" or "database"
    source: str  # "spreadsheets" or a database name
    table: str
    column: str
    attribute: str


@dataclass(frozen=True)
class Access:
    user_id: int
    username: str
    display_name: str
    is_admin: bool = False
    must_change_password: bool = False
    folders: frozenset[str] = field(default_factory=frozenset)  # "hr", "finance/reports", "/", "*"
    spreadsheets: frozenset[str] = field(default_factory=frozenset)  # table names or "*"
    databases: frozenset[str] = field(default_factory=frozenset)  # database names or "*"
    attributes: tuple[tuple[str, tuple[str, ...]], ...] = ()  # (("region", ("East",)), ...)
    row_rules: tuple[RowRule, ...] = ()

    def can_read_document(self, source: str) -> bool:
        """source is a path relative to data/docs, e.g. 'hr/handbook.docx' or 'iso27001.pdf'."""
        if self.is_admin or ALL in self.folders:
            return True
        folder = source.rsplit("/", 1)[0] if "/" in source else TOP_LEVEL
        for granted in self.folders:
            if granted == TOP_LEVEL and folder == TOP_LEVEL:
                return True
            if granted != TOP_LEVEL and (folder == granted or folder.startswith(granted + "/")):
                return True  # a folder grant includes its subfolders
        return False

    def can_use_spreadsheet(self, table: str) -> bool:
        return self.is_admin or ALL in self.spreadsheets or table.lower() in self.spreadsheets

    def can_use_database(self, name: str) -> bool:
        return self.is_admin or ALL in self.databases or name.lower() in self.databases

    def values(self, attribute: str) -> tuple[str, ...]:
        """The user's values for an attribute; empty if they don't have it."""
        return dict(self.attributes).get(attribute.lower(), ())

    def rules_for(self, kind: str, source: str) -> list[RowRule]:
        """Row rules that restrict this user in one source. Admins are never restricted."""
        if self.is_admin:
            return []
        source = SPREADSHEETS if kind == "spreadsheet" else source.lower()
        return [r for r in self.row_rules if r.kind == kind and r.source == source]

    def to_public(self) -> dict:
        """For /me: what the frontend may know about the user."""
        return {
            "username": self.username,
            "display_name": self.display_name,
            "is_admin": self.is_admin,
            "must_change_password": self.must_change_password,
            "folders": sorted(self.folders),
            "spreadsheets": sorted(self.spreadsheets),
            "databases": sorted(self.databases),
            "attributes": {name: list(values) for name, values in self.attributes},
        }


def load_access(user: dict) -> Access:
    p = permissions_for(user["id"])
    return Access(
        user_id=user["id"],
        username=user["username"],
        display_name=user["display_name"],
        is_admin=p["is_admin"],
        must_change_password=bool(user["must_change_password"]),
        folders=frozenset(p["grants"]["folder"]),
        spreadsheets=frozenset(v.lower() for v in p["grants"]["spreadsheet"]),
        databases=frozenset(v.lower() for v in p["grants"]["database"]),
        attributes=tuple(sorted((name, tuple(values)) for name, values in p["attributes"].items())),
        row_rules=tuple(
            RowRule(r["kind"], r["source"], r["table_name"], r["column_name"], r["attribute"]) for r in p["rules"]
        ),
    )
