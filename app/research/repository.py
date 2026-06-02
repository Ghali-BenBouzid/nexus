from sqlalchemy.orm import Session

from app.models.query import Query


def create_query(db: Session, user_id: int, prompt: str, report: str | None) -> Query:
    query = Query(user_id=user_id, prompt=prompt, report=report)

    db.add(query)
    db.commit()
    db.refresh(query)

    return query
