from dataclasses import dataclass

from .user_info import UserInfo


@dataclass
class Token:
    access_token: str
    type: str
    refresh_token: str
    expires_in: int
    scope: str
    jti: str
    user_info: UserInfo
