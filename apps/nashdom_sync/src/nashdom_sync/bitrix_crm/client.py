import logging
import re
from time import perf_counter
from typing import Any, Dict, List, Optional, cast

from platform_logging import log_event

from ._contracts import GatewayExecutionStatus, RetryPolicy
from ._gateway import GatewayHttpClient
from .exceptions import (
    BitrixGatewayError,
    BitrixRequestFailedError,
    BitrixRequestUnknownError,
)

logger = logging.getLogger(__name__)


def _safe_error_code(code: Optional[str]) -> Optional[str]:
    if code is not None and re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", code) is None:
        return "[скрыто]"
    return code


class ClientBitrixCRM:
    """Предоставляет синхронный CRM API через принадлежащий клиенту Gateway."""

    def __init__(self, gateway_url: str, timeout: float) -> None:
        self._gateway = GatewayHttpClient(base_url=gateway_url, timeout=timeout)

    def close(self) -> None:
        """Закрыть принадлежащие клиенту HTTP-ресурсы."""

        self._gateway.close()

    def _call(
        self, method: str, payload: Dict[str, Any], retry_policy: RetryPolicy
    ) -> Dict[str, Any]:
        started_at = perf_counter()
        context: Dict[str, Any] = {"method": method, "retry_policy": retry_policy.value}
        for source, target in (("entityTypeId", "entity_type_id"), ("start", "start")):
            if source in payload:
                context[target] = payload[source]
        log_event(logger, logging.DEBUG, "bitrix_call_started", **context)
        try:
            result = self._gateway.call(method, payload, retry_policy)
        except Exception as exc:
            log_event(
                logger,
                logging.DEBUG,
                "bitrix_call_failed",
                **context,
                exception_type=type(exc).__name__,
                duration_seconds=perf_counter() - started_at,
            )
            raise

        if result.status is GatewayExecutionStatus.SUCCESS:
            data = self._object(result.data, method)
            log_event(
                logger,
                logging.DEBUG,
                "bitrix_call_completed",
                **context,
                gateway_status=result.status.value,
                http_status=result.http_status,
                attempt_count=result.attempt_count,
                duration_seconds=perf_counter() - started_at,
            )
            return data

        # Произвольное сообщение сервера может содержать webhook, token или payload.
        # Не переносим его в исключение даже при отключённом логировании клиента.
        code = _safe_error_code(result.error_code)
        log_event(
            logger,
            logging.DEBUG,
            "bitrix_call_unsuccessful",
            **context,
            gateway_status=result.status.value,
            http_status=result.http_status,
            error_code=code,
            attempt_count=result.attempt_count,
            duration_seconds=perf_counter() - started_at,
        )
        diagnostic = (
            "{}: status={}, http_status={}, error_code={}, error_message=[скрыто], attempt_count={}"
        ).format(method, result.status.value, result.http_status, code, result.attempt_count)
        if result.status is GatewayExecutionStatus.FAILED:
            raise BitrixRequestFailedError(diagnostic)
        raise BitrixRequestUnknownError(diagnostic)

    @staticmethod
    def _object(value: Any, method: str) -> Dict[str, Any]:
        if not isinstance(value, dict):
            raise BitrixGatewayError("{}: ожидался объект в ответе".format(method))
        return cast(Dict[str, Any], value)

    @staticmethod
    def _records(value: Any, method: str) -> List[Dict[str, Any]]:
        if not isinstance(value, list):
            raise BitrixGatewayError("{}: ожидался список в ответе".format(method))
        entries = cast(List[Any], value)
        if any(not isinstance(entry, dict) for entry in entries):
            raise BitrixGatewayError("{}: ожидались объекты списка".format(method))
        return cast(List[Dict[str, Any]], entries)

    def _call_all_pages(
        self, method: str, payload: Dict[str, Any], *, items: bool = False
    ) -> List[Dict[str, Any]]:
        started_at = perf_counter()
        records: List[Dict[str, Any]] = []
        pages = 0
        start = 0
        context: Dict[str, Any] = {"method": method}
        if "entityTypeId" in payload:
            context["entity_type_id"] = payload["entityTypeId"]
        page_payload = dict(payload)
        try:
            while True:
                data = self._call(method, page_payload, RetryPolicy.SAFE)
                result: Any = data.get("result")
                if items:
                    result = self._object(result, method).get("items")
                records.extend(self._records(result, method))
                if "next" not in data:
                    pages += 1
                    break
                next_start: Any = data["next"]
                if type(next_start) is not int or next_start <= start:
                    raise BitrixGatewayError("{}: некорректный next в ответе".format(method))
                pages += 1
                start = next_start
                page_payload = dict(payload, start=start)
        except Exception as exc:
            log_event(
                logger,
                logging.DEBUG,
                "bitrix_pagination_failed",
                **context,
                pages_completed=pages,
                records_received=len(records),
                next_start=page_payload.get("start", 0),
                duration_seconds=perf_counter() - started_at,
                exception_type=type(exc).__name__,
            )
            raise
        log_event(
            logger,
            logging.DEBUG,
            "bitrix_pagination_completed",
            **context,
            pages=pages,
            records=len(records),
            duration_seconds=perf_counter() - started_at,
        )
        return records

    def profile(self) -> Dict[str, Any]:
        """Получить профиль пользователя Gateway."""

        return self._object(self._call("profile", {}, RetryPolicy.SAFE).get("result"), "profile")

    def list_items(
        self,
        entity_type_id: int,
        *,
        filter_: Optional[Dict[str, Any]] = None,
        select: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Получить все элементы CRM выбранного типа."""

        payload: Dict[str, Any] = {"entityTypeId": entity_type_id}
        if filter_ is not None:
            payload["filter"] = filter_
        if select is not None:
            payload["select"] = select
        return self._call_all_pages("crm.item.list", payload, items=True)

    def get_item_fields(self, entity_type_id: int) -> Dict[str, Any]:
        """Получить метаданные полей типа CRM."""

        method = "crm.item.fields"
        data = self._call(method, {"entityTypeId": entity_type_id}, RetryPolicy.SAFE)
        return self._object(self._object(data.get("result"), method).get("fields"), method)

    def list_statuses(self, entity_id: str) -> List[Dict[str, Any]]:
        """Получить справочник SOURCE, INDUSTRY, COMPANY_TYPE и аналогичные."""

        return self._call_all_pages("crm.status.list", {"filter": {"ENTITY_ID": entity_id}})

    def list_users(self, *, filter_: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Получить всех пользователей, удовлетворяющих фильтру."""

        return self._call_all_pages("user.get", {} if filter_ is None else {"FILTER": filter_})

    def search_users(self, query: str) -> List[Dict[str, Any]]:
        """Найти пользователей по FIND, получить все страницы с SAFE retry."""

        return self._call_all_pages("user.search", {"FILTER": {"FIND": query}})

    def list_requisite_presets(self) -> List[Dict[str, Any]]:
        """Получить шаблоны реквизитов."""

        return self._call_all_pages("crm.requisite.preset.list", {})

    def list_requisites(self, *, filter_: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Получить реквизиты по произвольному фильтру Bitrix."""

        return self._call_all_pages(
            "crm.requisite.list", {} if filter_ is None else {"filter": filter_}
        )

    def list_addresses(self, *, filter_: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Получить адреса по произвольному фильтру Bitrix."""

        return self._call_all_pages(
            "crm.address.list", {} if filter_ is None else {"filter": filter_}
        )

    def get_address_fields(self) -> Dict[str, Any]:
        """Получить метаданные полей адреса."""

        method = "crm.address.fields"
        return self._object(self._call(method, {}, RetryPolicy.SAFE).get("result"), method)

    def list_address_types(self) -> List[Dict[str, Any]]:
        """Получить справочник типов адресов без пагинации."""

        method = "crm.enum.addresstype"
        return self._records(self._call(method, {}, RetryPolicy.SAFE).get("result"), method)

    def list_owner_types(self) -> List[Dict[str, Any]]:
        """Получить типы владельцев, включая пользовательские типы CRM."""

        method = "crm.enum.ownertype"
        return self._records(self._call(method, {}, RetryPolicy.SAFE).get("result"), method)

    @staticmethod
    def _id(value: Any, method: str) -> int:
        if type(value) is not int or value <= 0:
            raise BitrixGatewayError("{}: ожидался положительный целочисленный ID".format(method))
        return value

    def add_item(self, entity_type_id: int, fields: Dict[str, Any]) -> int:
        """Создать элемент без повторов и вернуть его ID."""

        method = "crm.item.add"
        data = self._call(
            method, {"entityTypeId": entity_type_id, "fields": fields}, RetryPolicy.NEVER
        )
        item = self._object(self._object(data.get("result"), method).get("item"), method)
        return self._id(item.get("id"), method)

    def add_requisite(self, fields: Dict[str, Any]) -> int:
        """Создать реквизиты; ИНН, КПП, ОГРН передаются вызывающим кодом строками."""

        method = "crm.requisite.add"
        return self._id(
            self._call(method, {"fields": fields}, RetryPolicy.NEVER).get("result"), method
        )

    def add_address(self, fields: Dict[str, Any]) -> None:
        """Создать адрес без повторов, сохранив ADDRESS_2 и остальные поля."""

        method = "crm.address.add"
        if self._call(method, {"fields": fields}, RetryPolicy.NEVER).get("result") is not True:
            raise BitrixGatewayError("{}: ожидалось result=true".format(method))
