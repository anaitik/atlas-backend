"""Service package.

The package intentionally avoids eager imports to keep startup fast and avoid
import cycles. Consumers should import needed modules explicitly, e.g.
`from app.services import metric_service`.
"""

