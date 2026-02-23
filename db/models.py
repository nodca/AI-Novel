from sqlalchemy import Column, Integer, String, Text, Float, Boolean
from db.database import Base


class Character(Base):
    __tablename__ = "characters"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    role_type = Column(String)
    gender = Column(String)
    age = Column(String)
    appearance = Column(Text)
    personality = Column(Text)
    background = Column(Text)
    location = Column(String)
    physical_state = Column(String)
    mental_state = Column(String)
    cultivation_stage = Column(String)
    items = Column(Text)
    abilities = Column(Text)
    speech_style = Column(Text)
    dialogue_examples = Column(Text)
    voice_samples = Column(Text)
    is_active = Column(Boolean, default=True)


class CharacterRelationship(Base):
    __tablename__ = "character_relationships"
    id = Column(Integer, primary_key=True)
    from_character = Column(String, nullable=False)
    to_character = Column(String, nullable=False)
    type = Column(String)
    intimacy = Column(Integer, default=50)
    description = Column(Text)


class CharacterKnowledge(Base):
    __tablename__ = "character_knowledge"
    id = Column(Integer, primary_key=True)
    character = Column(String, index=True, nullable=False)
    fact = Column(Text)
    source = Column(String)
    learned_chapter = Column(Integer)
    confidence = Column(String)


class KnowledgeTriple(Base):
    __tablename__ = "knowledge_triples"
    id = Column(Integer, primary_key=True)
    subject = Column(String)
    predicate = Column(String)
    object = Column(String)
    subject_type = Column(String)
    object_type = Column(String)
    chapter_number = Column(Integer)


class Foreshadow(Base):
    __tablename__ = "foreshadows"
    id = Column(Integer, primary_key=True)
    title = Column(String)
    content = Column(Text)
    hint_text = Column(Text)
    chapter_planted = Column(Integer)
    chapter_resolved = Column(Integer, nullable=True)
    target_resolve_chapter = Column(Integer, nullable=True)
    is_long_term = Column(Boolean, default=False)
    importance = Column(Float, default=0.5)
    strength = Column(Integer, default=5)
    subtlety = Column(Integer, default=5)
    related_characters = Column(Text)
    category = Column(String)
    status = Column(String, default="planted")


class Summary(Base):
    __tablename__ = "summaries"
    id = Column(Integer, primary_key=True)
    level = Column(String)
    scope_start = Column(Integer, nullable=True)
    scope_end = Column(Integer, nullable=True)
    content = Column(Text)
