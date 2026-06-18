"""SQLAlchemy ORM models (local beta).

Importing this package registers every model on ``Base.metadata`` so Alembic's
``--autogenerate`` and ``upgrade head`` see them. The package is imported from
``backend.db.__init__`` for that exact purpose.

Phase boundary: only the three foundation tables are included here
(``tenants``, ``users``, ``audit_logs``). Customers and other business tables
are intentionally out of scope for the local beta.
"""

from backend.db.models.tenant import Tenant  # noqa: F401
from backend.db.models.user import AccountUser  # noqa: F401
from backend.db.models.audit import AuditLog  # noqa: F401
from backend.db.models.customer import Customer  # noqa: F401
from backend.db.models.event import Event  # noqa: F401
from backend.db.models.memo import Memo  # noqa: F401
from backend.db.models.daily import DailyEntry, DailyBalance  # noqa: F401
from backend.db.models.task import ActiveTask, PlannedTask, CompletedTask  # noqa: F401
from backend.db.models.relationship import AccommodationProvider, GuarantorConnection  # noqa: F401
from backend.db.models.signature import (  # noqa: F401
    AgentSignature, CustomerSignature, TempSignatureSlot, SignaturePadToken,
)
from backend.db.models.board import BoardPost, BoardComment  # noqa: F401
from backend.db.models.marketing import MarketingPost  # noqa: F401
from backend.db.models.marketing_image import MarketingImage  # noqa: F401
from backend.db.models.certification import (  # noqa: F401
    CertVendor, CertDirection, CertGroup, CertRegion, CertPrice,
)
from backend.db.models.work_data import WorkReferenceSheet, WorkReferenceRow  # noqa: F401
from backend.db.models.document import DocumentMetadata  # noqa: F401
from backend.db.models.manual_update import (  # noqa: F401
    ManualBaseVersion, ManualBasePage, ManualBaseRef,
    ManualUpdateRun, ManualUpdateVersion, ManualUpdateChangedPage,
    ManualUpdateCandidate, ManualReviewDecision, ManualReviewDecisionArchive,
    ManualUpdateState, ManualPdfArtifact,
    ManualUpdateAlertEvent, ManualUpdateAlertDismissal,
)
from backend.db.models.finance import FixedExpense, MonthlyTaxSummary  # noqa: F401
from backend.db.models.guideline_category import GuidelineCategory, GuidelineCategoryOverride  # noqa: F401
from backend.db.models.user_session import UserSession  # noqa: F401
from backend.db.models.roi_preset import RoiPreset  # noqa: F401
from backend.db.models.doc_tree import DocTreeNode, DocRequiredDocument  # noqa: F401
from backend.db.models.login_attempt import LoginAttempt  # noqa: F401
from backend.db.models.terms import TermsVersion, UserTermsAcceptance  # noqa: F401
from backend.db.models.account_security import (  # noqa: F401
    LoginEvent, AccountSecurity, SecurityNotification,
)

__all__ = [
    "Tenant", "AccountUser", "AuditLog",
    "Customer", "Event", "Memo",
    "DailyEntry", "DailyBalance",
    "ActiveTask", "PlannedTask", "CompletedTask",
    "AccommodationProvider", "GuarantorConnection",
    "AgentSignature", "CustomerSignature", "TempSignatureSlot", "SignaturePadToken",
    "BoardPost", "BoardComment",
    "MarketingPost",
    "CertVendor", "CertDirection", "CertGroup", "CertRegion", "CertPrice",
    "WorkReferenceSheet", "WorkReferenceRow",
    "DocumentMetadata",
    "ManualBaseVersion", "ManualBasePage", "ManualBaseRef",
    "ManualUpdateRun", "ManualUpdateVersion", "ManualUpdateChangedPage",
    "ManualUpdateCandidate", "ManualReviewDecision", "ManualReviewDecisionArchive",
    "ManualUpdateState", "ManualPdfArtifact",
    "FixedExpense", "MonthlyTaxSummary",
    "GuidelineCategory", "GuidelineCategoryOverride",
    "UserSession", "RoiPreset",
    "DocTreeNode", "DocRequiredDocument",
    "LoginAttempt", "TermsVersion", "UserTermsAcceptance",
    "LoginEvent", "AccountSecurity", "SecurityNotification",
]
