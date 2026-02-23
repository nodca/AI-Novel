from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

Base = declarative_base()


def get_engine(config):
    url = config.get("database", {}).get("url", "sqlite:///novel_state.db")
    return create_engine(url, echo=False)


def init_db(engine):
    from db.models import (Character, CharacterRelationship, CharacterKnowledge,
                           KnowledgeTriple, Foreshadow, Summary)
    Base.metadata.create_all(engine)


def get_session(engine):
    return sessionmaker(bind=engine)()
