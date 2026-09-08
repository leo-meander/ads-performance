from sqlalchemy import Boolean, Column, String, Text

from app.models.base import Base, JSONType, TimestampMixin


class SpyAnalysisReport(TimestampMixin, Base):
    __tablename__ = "spy_analysis_reports"

    title = Column(String(500), nullable=False)
    analysis_type = Column(String(50), nullable=False, index=True)  # pattern_analysis, competitor_deep_dive, creative_trends
    input_ad_ids = Column(JSONType, nullable=True)  # Array of spy_saved_ad UUIDs
    input_params = Column(JSONType, nullable=True)  # Extra params
    result_markdown = Column(Text, nullable=True)  # Claude's analysis output
    # Structured twin of result_markdown for the pattern digest, so the UI
    # can rank and bar-chart patterns instead of re-parsing prose.
    result_json = Column(JSONType, nullable=True)
    model_used = Column(String(50), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
