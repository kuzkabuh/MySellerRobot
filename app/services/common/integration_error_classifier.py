"""version: 1.0.0
description: Classify marketplace integration errors and return seller-friendly recommendations.
updated: 2026-05-15
"""

from dataclasses import dataclass
from enum import StrEnum


class IntegrationErrorKind(StrEnum):
    AUTH = "AUTH"
    PERMISSION = "PERMISSION"
    RATE_LIMIT = "RATE_LIMIT"
    TEMPORARY_API = "TEMPORARY_API"
    INTERNAL = "INTERNAL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class IntegrationErrorAdvice:
    kind: IntegrationErrorKind
    title: str
    recommendation: str


def classify_integration_error(message: str | None) -> IntegrationErrorAdvice:
    """Return a compact Russian recommendation for an integration error message."""

    text = (message or "").lower()
    if any(marker in text for marker in ("401", "unauthorized", "invalid token", "token")):
        return IntegrationErrorAdvice(
            kind=IntegrationErrorKind.AUTH,
            title="ошибка авторизации",
            recommendation="проверьте актуальность API-ключа и переподключите кабинет.",
        )
    if any(marker in text for marker in ("403", "forbidden", "permission", "access denied")):
        return IntegrationErrorAdvice(
            kind=IntegrationErrorKind.PERMISSION,
            title="недостаточно прав",
            recommendation="создайте ключ с правами на заказы, товары, остатки и финансы.",
        )
    if any(marker in text for marker in ("429", "rate limit", "too many requests")):
        return IntegrationErrorAdvice(
            kind=IntegrationErrorKind.RATE_LIMIT,
            title="лимит API",
            recommendation="сервис повторит попытку автоматически, проверьте позже.",
        )
    if any(marker in text for marker in ("timeout", "temporar", "502", "503", "504", "empty")):
        return IntegrationErrorAdvice(
            kind=IntegrationErrorKind.TEMPORARY_API,
            title="временная ошибка API",
            recommendation="внешний API нестабилен, повторная синхронизация будет выполнена позже.",
        )
    if any(
        marker in text
        for marker in (
            "traceback",
            "valueerror",
            "keyerror",
            "typeerror",
            "missinggreenlet",
            "greenlet_spawn has not been called",
        )
    ):
        return IntegrationErrorAdvice(
            kind=IntegrationErrorKind.INTERNAL,
            title="ошибка обработки",
            recommendation="проверьте логи синхронизации или обратитесь к администратору.",
        )
    return IntegrationErrorAdvice(
        kind=IntegrationErrorKind.UNKNOWN,
        title="неизвестная ошибка",
        recommendation="проверьте кабинет и повторите синхронизацию позже.",
    )
