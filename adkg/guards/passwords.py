"""口令哈希（spec §2）：stdlib scrypt——内存难解、零新依赖。

格式 `scrypt$<salt-b64>$<hash-b64>`（N=2^14, r=8, p=1, dklen=32）。
verify 对畸形存储串一律 False（不抛），登录侧另做等时哑校验防用户名探测。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

_N, _R, _P, _DKLEN = 2 ** 14, 8, 1, 32


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


# 等时哑校验锚点：用户名不存在时也跑一次同代价 verify，抹平响应时延差
DUMMY_HASH = hash_password("adkg-dummy-verify-anchor")


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_b64, hash_b64 = stored.split("$")
        digest = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64),
                                n=_N, r=_R, p=_P, dklen=_DKLEN)
        return hmac.compare_digest(digest, base64.b64decode(hash_b64))
    except Exception:
        return False
