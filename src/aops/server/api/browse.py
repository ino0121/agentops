"""Lists for the new-agent screen, read with the requester's own token: their tables, warehouses and Genie spaces.

Unity Catalog decides what each list holds. A table shows up only if the requester may SELECT it, so a
dev Genie space made from the picked tables (with the same token) can read them.
"""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..common import DBX, command
from ..dbx import caller_of, service_for

router = APIRouter(tags=["프로젝트"])

SCREEN = "새 에이전트 (노코드: 테이블·warehouse·Genie 고르기)"


class CatalogItem(BaseModel):
    name: str = Field(examples=["main"])
    comment: str | None = None
    type: str | None = Field(None, examples=["MANAGED_CATALOG"])


class SchemaItem(BaseModel):
    name: str = Field(examples=["sales"])
    full_name: str = Field(examples=["main.sales"])
    comment: str | None = None


class TableItem(BaseModel):
    name: str = Field(examples=["orders"])
    full_name: str = Field(examples=["main.sales.orders"])
    table_type: str | None = Field(None, examples=["MANAGED", "VIEW", "METRIC_VIEW"])
    kind: Literal["table", "metric_view"] = Field(description="Genie 정의에서 들어가는 곳 (tables · metric_views)")
    comment: str | None = None


class Listing(BaseModel):
    truncated: bool = Field(False, description="너무 많아 앞부분만 보냄 (스키마를 좁혀 고르세요)")


class Catalogs(Listing):
    items: list[CatalogItem]


class Schemas(Listing):
    items: list[SchemaItem]


class Tables(Listing):
    items: list[TableItem]


class Column(BaseModel):
    name: str | None = None
    type: str | None = Field(None, examples=["bigint"])
    comment: str | None = None


class TableDetail(BaseModel):
    full_name: str
    table_type: str | None = None
    kind: Literal["table", "metric_view"]
    comment: str | None = None
    owner: str | None = None
    columns: list[Column] = Field(default_factory=list)


class Warehouse(BaseModel):
    id: str = Field(examples=["abcdef0123456789"])
    name: str
    state: str | None = Field(None, examples=["RUNNING", "STOPPED"])
    size: str | None = Field(None, examples=["2X-Small"])
    serverless: bool = False
    default: bool = Field(False, description="aops 서버의 warehouse")


class Warehouses(BaseModel):
    items: list[Warehouse]
    default: str | None = Field(None, description="aops 서버의 warehouse ID (비워 두면 이것을 씀)")


class TableAccessRequest(BaseModel):
    tables: list[str] = Field(examples=[["main.sales.orders"]], description="고른 테이블·메트릭 뷰 (30개까지)")


class TableAccess(BaseModel):
    full_name: str
    status: Literal["ok", "missing", "unknown"] = Field(description="aops 서비스 주체의 SELECT: 있음 · 없음 · 확인 못함")
    detail: str


class Principal(BaseModel):
    principal: str = Field(examples=["lead@example.com", "group:agent-approvers"], description="SPEC.md approvers에 쓰는 값")
    kind: Literal["user", "group"]
    name: str = Field(examples=["Lead Kim", "agent-approvers"])


class GenieSpaceItem(BaseModel):
    space_id: str = Field(examples=["01f1def700b81b648961b653785305ee"])
    title: str
    description: str | None = None
    warehouse_id: str | None = None


class GenieSpaces(Listing):
    items: list[GenieSpaceItem]


@router.get("/me/catalogs", summary="내가 쓸 수 있는 카탈로그", **command(None, DBX, screen=SCREEN))
def my_catalogs(request: Request) -> Catalogs:
    svc = service_for(None)
    return Catalogs(**svc.my_catalogs(caller_of(request, svc)))


@router.get("/me/catalogs/{catalog}/schemas", summary="카탈로그의 스키마 (내 권한)", **command(None, DBX, screen=SCREEN))
def my_schemas(catalog: str, request: Request) -> Schemas:
    svc = service_for(None)
    return Schemas(**svc.my_schemas(caller_of(request, svc), catalog))


@router.get("/me/catalogs/{catalog}/schemas/{schema}/tables", summary="스키마의 테이블 (내가 SELECT할 수 있는 것)",
            **command(None, DBX, screen=SCREEN))
def my_tables(catalog: str, schema: str, request: Request) -> Tables:
    svc = service_for(None)
    return Tables(**svc.my_tables(caller_of(request, svc), catalog, schema))


@router.get("/me/tables/{full_name}", summary="테이블 컬럼 (고르기 전에 보기)", **command(None, DBX, screen=SCREEN))
def my_table(full_name: str, request: Request) -> TableDetail:
    svc = service_for(None)
    return TableDetail(**svc.my_table(caller_of(request, svc), full_name))


@router.get("/me/warehouses", summary="내가 볼 수 있는 SQL warehouse", **command(None, DBX, screen=SCREEN))
def my_warehouses(request: Request) -> Warehouses:
    svc = service_for(None)
    return Warehouses(**svc.my_warehouses(caller_of(request, svc)))


@router.post("/no-code/table-access", summary="고른 테이블을 aops 서비스 주체가 읽을 수 있는지",
             **command(None, DBX, screen=SCREEN, note="운영용 Genie는 서비스 주체 권한으로 만들고 돈다. SELECT가 없으면 첫 배포가 막히므로 만들 때 미리 알린다."))
def table_access(body: TableAccessRequest, request: Request) -> list[TableAccess]:
    svc = service_for(None)
    return [TableAccess(**row) for row in svc.service_table_access(caller_of(request, svc), body.tables)]


@router.get("/directory", summary="승인자 고르기: 워크스페이스 사용자·그룹 찾기",
            **command(None, DBX, screen="새 에이전트 (승인자)", note="이름·이메일에 q가 들어간 사용자와 그룹 (aops 서비스 주체가 SCIM으로 찾는다). 못 찾으면 직접 적는다."))
def directory(request: Request, q: str = "") -> list[Principal]:
    svc = service_for(None)
    caller_of(request, svc)
    return [Principal(**row) for row in svc.search_directory(q)]


@router.get("/genie/spaces", summary="내가 열 수 있는 Genie 스페이스 (복사·옮기기용)",
            **command("aops init --type no-code", DBX, screen=SCREEN))
def list_genie_spaces(request: Request, q: str | None = None) -> GenieSpaces:
    svc = service_for("aops init --type no-code")
    return GenieSpaces(**svc.my_genie_spaces(caller_of(request, svc), q))
