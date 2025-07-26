import duckdb
from fastapi import APIRouter, Depends, Request, HTTPException

from kiwi.schemas import QueryRequest
from kiwi.core.services.federation_query_engine import FederationQueryEngine
from kiwi.api.deps import (
    CurrentUser,
    SessionDep,
    get_current_active_superuser,
)

router = APIRouter(prefix="/query", tags=["sql"])


@router.post("/sql")
async def execute_select(
        query: QueryRequest,
        db: SessionDep,
        current_user: CurrentUser
):
    try:
        result = await FederationQueryEngine.execute_query(
            db,
            query.project_id,
            query.sql,
            query.dataset_id,
            query.format
        )
        return result

    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except duckdb.Error as e:
        raise HTTPException(
            status_code=400,
            detail=f"Query execution error: {str(e)}"
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/manager/sql", dependencies=[Depends(get_current_active_superuser)])
async def execute_query(
        query: QueryRequest,
        db: SessionDep,
        current_user: CurrentUser
):
    try:
        result = await FederationQueryEngine.execute_query(
            db,
            query.project_id,
            query.sql,
            query.dataset_id,
            query.format
        )
        return result

    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except duckdb.Error as e:
        raise HTTPException(
            status_code=400,
            detail=f"Query execution error: {str(e)}"
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
