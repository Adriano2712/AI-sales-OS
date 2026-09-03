import enum


class Role(str, enum.Enum):
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    SDR = "SDR"
    ANALYST = "ANALYST"
    VIEWER = "VIEWER"


# MVP authorization: coarse-grained. ADMIN/MANAGER act on anything; SDR can approve
# and contact; ANALYST/VIEWER are read-only. Revisit if per-resource permissions
# are needed later.
WRITE_ROLES = {Role.ADMIN, Role.MANAGER, Role.SDR}
