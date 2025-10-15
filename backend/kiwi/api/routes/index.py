from typing import Any

from fastapi import APIRouter, Depends

from kiwi.api.deps import (
    CurrentUser,
    SessionDep,
    get_current_active_superuser,
)
from kiwi.schemas import TrainingData
from kiwi.vector_store.base import VectorStore
from kiwi.vector_store.vector_store_manager import get_vector_store

router = APIRouter(
    prefix="/index",
    tags=["index"]
)


@router.get(
    "/get_training_data",
    dependencies=[Depends(get_current_active_superuser)]
)
async def get_training_data(
        user: CurrentUser,
        vector_store: VectorStore = Depends(get_vector_store)
):
    df = await vector_store.get_training_data()

    if df is None or len(df) == 0:
        return {
            "type": "error",
            "error": "No training data found. Please add some training data first.",
        }

    return {
        "type": "df",
        "id": "training_data",
        "df": df.to_json(orient="records"),
    }


@router.post(
    "/remove_training_data/{id}",
    dependencies=[Depends(get_current_active_superuser)]
)
async def remove_training_data(user: CurrentUser, id: str, vector_store: VectorStore = Depends(get_vector_store)):
    # Get id from the JSON body

    if id is None:
        return {"type": "error", "error": "No id provided"}

    if vector_store.remove_training_data(id=id):
        return {"success": True}
    else:
        return {"type": "error", "error": "Couldn't remove training data"}


@router.post(
    "/train",
    dependencies=[Depends(get_current_active_superuser)]
)
def add_training_data(user: CurrentUser, training_data: TrainingData,
                      vector_store: VectorStore = Depends(get_vector_store)):
    question = training_data.qa.question
    sql = training_data.qa.sql
    ddl = training_data.ddl
    documentation = training_data.documentation

    try:
        id = vector_store.train(
            question=question, sql=sql, ddl=ddl, documentation=documentation
        )

        return {"id": id}
    except Exception as e:
        print("TRAINING ERROR", e)
        return {"type": "error", "error": str(e)}


@router.get(
    "/",
    dependencies=[Depends(get_current_active_superuser)],
)
async def get_similar_question_sql(user: CurrentUser, skip: int = 0, limit: int = 100) -> Any:
    """
    Retrieve users.
    """
    raise NotImplementedError


@router.post(
    "/add_document",
    dependencies=[Depends(get_current_active_superuser)]
)
async def add_document(user: CurrentUser, document: Document) -> Any:
    """
    Add a document to the vector store.
    """
    raise NotImplementedError
