from sqlalchemy import Column, DateTime, ForeignKey, Numeric, String, Text

from app.models.base import Base, JSONType, TimestampMixin, UUIDType
import uuid


class CreativeHypothesis(TimestampMixin, Base):
    __tablename__ = "creative_hypotheses"

    hypothesis_id = Column(String(20), nullable=False, unique=True, index=True)  # HYP-001
    branch_name = Column(String(100), nullable=False, index=True)
    combo_id = Column(String(20), ForeignKey("ad_combos.combo_id", ondelete="SET NULL"), nullable=True, index=True)
    angle_id = Column(String(20), ForeignKey("ad_angles.angle_id", ondelete="SET NULL"), nullable=True)

    # Strategy context
    hypothesis_category = Column(String(50), nullable=True, index=True)
    # identity | decision_driver | emotional_trigger | travel_moment |
    # social_proof | experience | value_perception | brand_territory
    customer_insight = Column(Text, nullable=True)  # underlying belief from the pyramid
    human_desire = Column(String(100), nullable=True, index=True)
    creative_angle = Column(String(200), nullable=True)
    target_audience = Column(String(100), nullable=True)
    market = Column(String(10), nullable=True)

    # Hypothesis
    hypothesis = Column(Text, nullable=False)
    variable_tested = Column(Text, nullable=True)
    primary_kpi = Column(String(50), nullable=True)
    secondary_kpi = Column(String(50), nullable=True)
    expected_outcome = Column(Text, nullable=True)

    # Results
    actual_ctr = Column(Numeric(8, 4), nullable=True)
    actual_cvr = Column(Numeric(8, 4), nullable=True)
    actual_roas = Column(Numeric(8, 2), nullable=True)
    actual_spend = Column(Numeric(15, 2), nullable=True)

    # Statistical integrity
    confounding_factors = Column(JSONType, nullable=True)
    confidence_level = Column(String(10), nullable=True)  # low/medium/high
    confidence_score = Column(Numeric(5, 2), nullable=True)  # 0-100 numeric

    # 4-tier knowledge links
    principle_id = Column(UUIDType, ForeignKey("creative_principles.id", ondelete="SET NULL"), nullable=True, index=True)
    research_question_id = Column(UUIDType, ForeignKey("research_questions.id", ondelete="SET NULL"), nullable=True, index=True)
    knowledge_links = Column(JSONType, nullable=True, default=list)   # list of hypothesis_ids
    parent_hypothesis_id = Column(UUIDType, ForeignKey("creative_hypotheses.id", ondelete="SET NULL"), nullable=True)

    # Brief + script input for AI analysis
    brief_text = Column(Text, nullable=True)
    script_text = Column(Text, nullable=True)

    # AI-extracted deep analysis (from analyze-brief endpoint)
    evidence = Column(Text, nullable=True)          # what actually happened & why (qualitative)
    creative_principle = Column(Text, nullable=True) # abstracted principle, reusable across creatives
    why_it_worked = Column(Text, nullable=True)      # psychological/behavioral explanation
    human_moment = Column(String(200), nullable=True) # the specific human moment category

    # Outcome
    status = Column(String(20), nullable=False, default="pending", index=True)
    # pending | running | validated | refuted | inconclusive
    learning = Column(Text, nullable=True)
    result_notes = Column(Text, nullable=True)
    validated_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(String(200), nullable=True)
