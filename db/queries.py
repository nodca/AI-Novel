from sqlalchemy import or_
from db.models import Character, CharacterRelationship, CharacterKnowledge, Foreshadow, Summary


def get_characters(session, names=None):
    q = session.query(Character).filter(Character.is_active == True)
    if names:
        q = q.filter(Character.name.in_(names))
    return q.all()


def get_pov_knowledge(session, character_name, confidence_levels=("certain", "suspect")):
    return (session.query(CharacterKnowledge)
            .filter(CharacterKnowledge.character == character_name,
                    CharacterKnowledge.confidence.in_(confidence_levels))
            .all())


def get_relationships(session, character_names):
    return (session.query(CharacterRelationship)
            .filter(or_(CharacterRelationship.from_character.in_(character_names),
                        CharacterRelationship.to_character.in_(character_names)))
            .all())


def get_foreshadows_for_chapter(session, chapter_number):
    active = (session.query(Foreshadow)
              .filter(Foreshadow.status == "planted")
              .all())
    must_resolve = [f for f in active if f.target_resolve_chapter == chapter_number]
    overdue = [f for f in active
               if f.target_resolve_chapter is not None and f.target_resolve_chapter < chapter_number]
    upcoming = [f for f in active
                if f.target_resolve_chapter is not None and f.target_resolve_chapter > chapter_number]
    remaining = [f for f in active if f not in must_resolve and f not in overdue and f not in upcoming]
    return {"must_resolve": must_resolve, "overdue": overdue, "upcoming": upcoming, "active": remaining}


def get_summaries(session, chapter_number, arc_interval=10):
    global_summary = session.query(Summary).filter(Summary.level == "global").first()
    arc_start = ((chapter_number - 1) // arc_interval) * arc_interval + 1
    arc_end = arc_start + arc_interval - 1
    arc_summary = (session.query(Summary)
                   .filter(Summary.level == "arc",
                           Summary.scope_start == arc_start,
                           Summary.scope_end == arc_end)
                   .first())
    recent_chapters = (session.query(Summary)
                       .filter(Summary.level == "chapter",
                               Summary.scope_start <= chapter_number)
                       .order_by(Summary.scope_start.desc())
                       .limit(3)
                       .all())
    return {"global_summary": global_summary, "arc_summary": arc_summary, "recent_chapters": recent_chapters}


def get_world_summary(session):
    return session.query(Summary).filter(Summary.level == "world").first()
