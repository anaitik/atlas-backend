"""
Timestamp and soft-delete mixins for Beanie documents.
(Functionality is built into BaseDocument and SoftDeleteDocument,
 but this file is kept for explicit pack-03 ownership reference.)
"""

from app.models.base import BaseDocument, SoftDeleteDocument

__all__ = ["BaseDocument", "SoftDeleteDocument"]
