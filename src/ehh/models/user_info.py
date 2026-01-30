from dataclasses import dataclass

from .school_info import SchoolInfo


@dataclass
class UserInfo:
    id: str
    username: str
    full_name: str
    type: int
    school: SchoolInfo
