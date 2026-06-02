from sqlalchemy.orm import Session

from app.models.query import Query
from app.research import repository


def handle_query(db: Session, user_id: int, prompt: str) -> Query:
    # report generation (placeholder for now):
    report = f"This is stub report for: {prompt}"

    # write the full query row to the db:
    query = repository.create_query(
        db=db, user_id=user_id, prompt=prompt, report=report
    )

    return query
