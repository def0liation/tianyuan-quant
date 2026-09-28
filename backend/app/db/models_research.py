from sqlalchemy import Column, ForeignKey, Integer, JSON, String, Text

from .models_case_library import utcnow
from .session import Base


class ResearchLoopDB(Base):
    __tablename__ = "research_loops"

    id = Column(Integer, primary_key=True, autoincrement=True)
    loop_id = Column(String(128), unique=True, nullable=False, index=True)
    title = Column(String(256), nullable=False)
    objective = Column(Text, nullable=False)
    status = Column(String(32), default="ACTIVE", index=True)
    action_target = Column(String(64), default="factor")
    owner = Column(String(64), default="human")
    tags = Column(JSON, default=list)
    linked_projects = Column(JSON, default=list)
    source = Column(String(64), default="super")
    current_iteration_id = Column(String(128), nullable=True, index=True)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(String(64), default=utcnow)
    updated_at = Column(String(64), default=utcnow)
    completed_at = Column(String(64), nullable=True)


class ResearchIterationDB(Base):
    __tablename__ = "research_iterations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    iteration_id = Column(String(128), unique=True, nullable=False, index=True)
    loop_id = Column(String(128), ForeignKey("research_loops.loop_id"), nullable=False, index=True)
    iteration_number = Column(Integer, nullable=False)
    status = Column(String(32), default="DRAFT", index=True)
    hypothesis = Column(Text, nullable=False)
    plan = Column(Text, default="")
    target_modules = Column(JSON, default=list)
    linked_run_id = Column(String(128), nullable=True, index=True)
    linked_backtest_id = Column(String(128), nullable=True, index=True)
    linked_case_id = Column(String(128), nullable=True, index=True)
    linked_knowledge_item_id = Column(String(128), nullable=True, index=True)
    linked_patch_id = Column(String(128), nullable=True, index=True)
    metrics = Column(JSON, default=dict)
    evidence_links = Column(JSON, default=list)
    feedback_events = Column(JSON, default=list)
    verdict = Column(String(32), default="PENDING", index=True)
    artifact_status = Column(String(32), default="ACTIVE")
    error = Column(Text, default="")
    created_at = Column(String(64), default=utcnow)
    updated_at = Column(String(64), default=utcnow)
    completed_at = Column(String(64), nullable=True)


class ResearchEvidenceLinkDB(Base):
    __tablename__ = "research_evidence_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    link_id = Column(String(128), unique=True, nullable=False, index=True)
    loop_id = Column(String(128), ForeignKey("research_loops.loop_id"), nullable=False, index=True)
    iteration_id = Column(String(128), ForeignKey("research_iterations.iteration_id"), nullable=False, index=True)
    source_type = Column(String(64), nullable=False, index=True)
    source_id = Column(String(128), nullable=False, index=True)
    label = Column(String(256), default="")
    quality = Column(String(32), default="UNKNOWN", index=True)
    summary_json = Column(JSON, default=dict)
    created_at = Column(String(64), default=utcnow)


class ResearchFeedbackEventDB(Base):
    __tablename__ = "research_feedback_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    feedback_id = Column(String(128), unique=True, nullable=False, index=True)
    loop_id = Column(String(128), ForeignKey("research_loops.loop_id"), nullable=False, index=True)
    iteration_id = Column(String(128), ForeignKey("research_iterations.iteration_id"), nullable=False, index=True)
    action = Column(String(64), default="REVIEW", index=True)
    verdict = Column(String(32), default="PENDING", index=True)
    note = Column(Text, default="")
    reviewer = Column(String(64), default="human")
    observations_json = Column(JSON, default=list)
    knowledge_item_id = Column(String(128), nullable=True, index=True)
    patch_id = Column(String(128), nullable=True, index=True)
    audit_id = Column(String(128), nullable=True, index=True)
    created_at = Column(String(64), default=utcnow)


class ResearchArtifactMaterializationDB(Base):
    __tablename__ = "research_artifact_materializations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    iteration_id = Column(String(128), unique=True, nullable=False, index=True)
    status = Column(String(32), default="COMPLETED", index=True)
    owner_token = Column(String(64), default="", index=True)
    request_json = Column(JSON, default=dict)
    artifact_links = Column(JSON, default=dict)
    error = Column(Text, default="")
    started_at = Column(String(64), default=utcnow)
    updated_at = Column(String(64), default=utcnow)
    completed_at = Column(String(64), nullable=True)


class ResearchHypothesisDraftDB(Base):
    __tablename__ = "research_hypothesis_drafts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    draft_id = Column(String(128), unique=True, nullable=False, index=True)
    loop_id = Column(String(128), ForeignKey("research_loops.loop_id"), nullable=False, index=True)
    source_iteration_id = Column(String(128), nullable=True, index=True)
    status = Column(String(32), default="DRAFT", index=True)
    selected_action_target = Column(String(64), default="factor")
    action_selection = Column(JSON, default=dict)
    drafts_json = Column(JSON, default=list)
    request_json = Column(JSON, default=dict)
    prompt_provenance = Column(JSON, default=dict)
    token_usage = Column(JSON, default=dict)
    llm_status = Column(String(32), default="NOT_REQUESTED")
    llm_error = Column(Text, default="")
    confirmed_iteration_id = Column(String(128), nullable=True, index=True)
    created_at = Column(String(64), default=utcnow)
    updated_at = Column(String(64), default=utcnow)
    confirmed_at = Column(String(64), nullable=True)
