"""문서자동작성 선택 트리 + 필요서류 — 관리자 편집형 설정(Phase I-1J-6O).

기존 ``backend/routers/quick_doc.py`` 의 하드코딩 상수
(CATEGORY_OPTIONS / MINWON_OPTIONS / TYPE_OPTIONS / SUBTYPE_OPTIONS / REQUIRED_DOCS)
를 DB 설정으로 이관한다. 내부 구조는 기존과 동일하게
**category → petition(민원) → type(종류) → subtype(세부)** 4단계를 유지하며,
가변 깊이(H2/E7/국적/신고처럼 세부가 없는 종류)는 self-referential
``doc_tree_nodes`` 한 테이블로 표현한다.

설계 메모(트리를 단일 self-ref 테이블로 둔 이유):
- 종류에 따라 세부 유무가 달라(F=1~6 있음, H2/E7 없음) 4개 테이블로 나누면 빈
  단계 처리가 번거롭다. ``level`` 컬럼 + ``parent_id`` 면 동일 구조를 더 단순히
  표현하고, 그대로 트리로 렌더링된다.
- 필요서류는 가장 깊은 노드(세부가 있으면 세부, 없으면 종류; 사증 준비중처럼
  종류가 무의미하면 민원)에 ``doc_required_documents`` 로 연결한다.

테넌트 구분: 현행 하드코딩 트리는 전 테넌트 공용이므로 ``tenant_id`` 는 nullable
(NULL = 전역/공용)로 두되, 향후 테넌트별 오버라이드 여지를 남긴다. 시드/실사용은 전역.

삭제 정책: hard delete 대신 ``is_active=False`` soft delete(과거 생성 이력 보호).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey, Integer, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


# level 값: 4단계 트리의 어느 단계인지
DOC_NODE_LEVELS = ("category", "petition", "type", "subtype")
DOC_GROUPS = ("main", "agent")


class DocTreeNode(Base):
    """선택 트리 노드(구분/민원/종류/세부) — self-referential."""

    __tablename__ = "doc_tree_nodes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # NULL = 전역/공용 트리. 향후 테넌트별 오버라이드 대비 컬럼만 둔다.
    tenant_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("tenants.tenant_id", onupdate="CASCADE"), nullable=True
    )
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("doc_tree_nodes.id", ondelete="CASCADE"), nullable=True
    )
    level: Mapped[str] = mapped_column(Text, nullable=False)  # category|petition|type|subtype
    name: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class DocRequiredDocument(Base):
    """선택 조합(노드)에 연결된 필요서류 — 민원서류(main)/행정사서류(agent)."""

    __tablename__ = "doc_required_documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    node_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("doc_tree_nodes.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    doc_group: Mapped[str] = mapped_column(Text, nullable=False, default="main")  # main|agent
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # templates/ 폴더의 PDF 파일명(확장자 포함). 자동매핑 성공 시 채워짐. 빈 값 = 미매핑.
    template_filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    # mapped | missing — 문서 생성 가능 여부 표시용
    template_status: Mapped[str] = mapped_column(Text, nullable=False, default="missing")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
