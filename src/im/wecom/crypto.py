"""企业微信回调消息加解密（与官方 WXBizMsgCrypt 算法兼容）。"""

from __future__ import annotations

import base64
import hashlib
import os
import socket
import struct
import xml.etree.ElementTree as ET
from typing import Any

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class WeComCryptoError(ValueError):
    """验签或加解密失败。"""


class _PKCS7Encoder:
    """企微约定：填充到 32 字节倍数。"""

    block_size = 32

    def encode(self, text: bytes) -> bytes:
        amount = self.block_size - (len(text) % self.block_size)
        if amount == 0:
            amount = self.block_size
        pad = bytes([amount] * amount)
        return text + pad

    def decode(self, decrypted: bytes) -> bytes:
        if not decrypted:
            raise WeComCryptoError("解密结果为空")
        pad = decrypted[-1]
        if pad < 1 or pad > self.block_size:
            pad = 0
        return decrypted[:-pad]


class WeComCrypto:
    """Token + EncodingAESKey + receive_id(corp_id) 加解密。"""

    def __init__(self, token: str, encoding_aes_key: str, receive_id: str) -> None:
        self.token = (token or "").strip()
        self.receive_id = (receive_id or "").strip()
        key_b64 = (encoding_aes_key or "").strip()
        if not self.token or not key_b64 or not self.receive_id:
            raise WeComCryptoError("token / encoding_aes_key / corp_id 不能为空")
        try:
            self.aes_key = base64.b64decode(key_b64 + "=")
        except Exception as exc:
            raise WeComCryptoError("encoding_aes_key 无效") from exc
        if len(self.aes_key) != 32:
            raise WeComCryptoError("AESKey 长度须为 32 字节")
        self._iv = self.aes_key[:16]
        self._padder = _PKCS7Encoder()

    def _sign(self, *parts: str) -> str:
        items = sorted(str(p) for p in parts)
        return hashlib.sha1("".join(items).encode("utf-8")).hexdigest()

    def verify_signature(
        self,
        msg_signature: str,
        timestamp: str,
        nonce: str,
        encrypt: str,
    ) -> None:
        expect = self._sign(self.token, timestamp, nonce, encrypt)
        if expect != (msg_signature or "").strip():
            raise WeComCryptoError("msg_signature 校验失败")

    def _aes_decrypt(self, cipher_b64: str) -> bytes:
        try:
            cipher_bytes = base64.b64decode(cipher_b64)
        except Exception as exc:
            raise WeComCryptoError("Encrypt Base64 无效") from exc
        decryptor = Cipher(
            algorithms.AES(self.aes_key),
            modes.CBC(self._iv),
            backend=default_backend(),
        ).decryptor()
        plain = decryptor.update(cipher_bytes) + decryptor.finalize()
        return self._padder.decode(plain)

    def _aes_encrypt(self, raw: bytes) -> str:
        padded = self._padder.encode(raw)
        encryptor = Cipher(
            algorithms.AES(self.aes_key),
            modes.CBC(self._iv),
            backend=default_backend(),
        ).encryptor()
        cipher = encryptor.update(padded) + encryptor.finalize()
        return base64.b64encode(cipher).decode("utf-8")

    def decrypt(self, encrypt: str) -> str:
        """解密 Encrypt 字段，返回明文（XML 或 echostr）。"""
        content = self._aes_decrypt(encrypt)
        if len(content) < 20:
            raise WeComCryptoError("明文过短")
        msg_len = socket.ntohl(struct.unpack("I", content[16:20])[0])
        msg = content[20 : 20 + msg_len]
        from_receive = content[20 + msg_len :].decode("utf-8")
        if from_receive != self.receive_id:
            raise WeComCryptoError(
                f"receive_id 不匹配: expect={self.receive_id!r} got={from_receive!r}"
            )
        return msg.decode("utf-8")

    def encrypt(self, reply: str) -> str:
        """加密明文字符串，返回 Encrypt Base64。"""
        random16 = os.urandom(16)
        msg = (reply or "").encode("utf-8")
        msg_len = struct.pack("I", socket.htonl(len(msg)))
        receive = self.receive_id.encode("utf-8")
        raw = random16 + msg_len + msg + receive
        return self._aes_encrypt(raw)

    def verify_url(
        self,
        msg_signature: str,
        timestamp: str,
        nonce: str,
        echostr: str,
    ) -> str:
        """URL 验证：校验签名并解密 echostr，原样返回明文。"""
        self.verify_signature(msg_signature, timestamp, nonce, echostr)
        return self.decrypt(echostr)

    def decrypt_message(
        self,
        msg_signature: str,
        timestamp: str,
        nonce: str,
        post_data: str | bytes,
    ) -> str:
        """解密 POST 回调 XML，返回明文 XML。"""
        encrypt = extract_encrypt_from_xml(post_data)
        self.verify_signature(msg_signature, timestamp, nonce, encrypt)
        return self.decrypt(encrypt)


def extract_encrypt_from_xml(post_data: str | bytes) -> str:
    text = post_data.decode("utf-8") if isinstance(post_data, bytes) else post_data
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise WeComCryptoError("回调 XML 无法解析") from exc
    node = root.find("Encrypt")
    if node is None or not (node.text or "").strip():
        raise WeComCryptoError("回调 XML 缺少 Encrypt")
    return node.text.strip()


def parse_message_xml(plain_xml: str) -> dict[str, Any]:
    """解析解密后的消息 XML 为扁平 dict。"""
    try:
        root = ET.fromstring(plain_xml)
    except ET.ParseError as exc:
        raise WeComCryptoError("明文消息 XML 无法解析") from exc
    out: dict[str, Any] = {}
    for child in root:
        out[child.tag] = (child.text or "").strip()
    return out
