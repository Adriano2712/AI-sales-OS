import enum


class PageType(str, enum.Enum):
    HOMEPAGE = "HOMEPAGE"
    CONTACT = "CONTACT"
    ABOUT = "ABOUT"
    SERVICES = "SERVICES"
    SCHEDULING = "SCHEDULING"
    OTHER = "OTHER"
