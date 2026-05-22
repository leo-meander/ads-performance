from sqlalchemy import Column, ForeignKey, String, UniqueConstraint

from app.models.base import Base, TimestampMixin, UUIDType


class UserPagePermission(Base, TimestampMixin):
    """Per-user, per-page access level — finer-grained than user_permissions.

    A `page` is one navigable screen within a section (e.g. 'keypoints' lives
    under section 'meta_ads'). Page access is global per user (NOT per branch):
    branch×section still governs WHICH DATA is visible, while page rows govern
    WHICH SCREENS the user can open.

    Semantics (see app.core.permissions):
    - No page rows for a section  => user sees ALL pages of that section
      (this keeps existing users unchanged — nobody has page rows by default).
    - Some page rows for a section => user sees ONLY those pages, each at its
      own level. level='view' => can open; level='edit' => open + write.
    Admin role bypasses this table entirely.
    """

    __tablename__ = "user_page_permissions"
    __table_args__ = (
        UniqueConstraint("user_id", "page", name="uq_user_page_perm_user_page"),
    )

    user_id = Column(
        UUIDType,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page = Column(String(40), nullable=False)  # canonical page key, see PAGES registry
    level = Column(String(10), nullable=False)  # 'view' | 'edit'
