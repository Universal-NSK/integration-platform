import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple, cast
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from selenium.common.exceptions import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from nashdom_sync.contracts import (
    BaseExtractedDataclass,
    ExtractedDeveloper,
    ExtractedObject,
    NashDomExtractSettings,
    NashDomRegion,
)
from nashdom_sync.extract.exceptions import (
    NashDomClientError,
    NashDomUnavailableError,
)
from nashdom_sync.extract.nashdom.normalizer import NashDomDataNormalizer

_WAIT_TIMEOUT_SECONDS = 30
_API_BATCH_SIZE = 20
_API_ENDPOINT_MARKER = "/api/kn/object"
_DEVELOPER_API_BATCH_SIZE = 1000
_DEVELOPER_API_PATH = "/сервисы/api/erz/main/filter"
_BASE_URL = "https://xn--80az8a.xn--d1aqf.xn--p1ai"

_Locator = Tuple[str, str]
_LOAD_MORE_LOCATORS: Tuple[_Locator, ...] = (
    (By.CSS_SELECTOR, 'button[class*="Newbuildings__ButtonLoadMore"]'),
    (
        By.CSS_SELECTOR,
        'div[class*="Newbuildings__LoadMoreContainer"] > button',
    ),
    (
        By.XPATH,
        "//button[contains(normalize-space(.), 'Показать ещё') "
        "or contains(normalize-space(.), 'Показать еще')]",
    ),
)

_INSTALL_INTERCEPTOR_SCRIPT = """
return (() => {
    window.__nashdomObjectRequest = null;

    if (window.__nashdomObjectInterceptorInstalled != true) {
        const endpointMarker = "/api/kn/object";
        const originalOpen = XMLHttpRequest.prototype.open;
        const originalSend = XMLHttpRequest.prototype.send;
        const originalSetRequestHeader = XMLHttpRequest.prototype.setRequestHeader;

        XMLHttpRequest.prototype.open = function(method, url, ...args) {
            this.__nashdomObjectUrl = String(url);
            this.__nashdomObjectAuthorization = null;
            return originalOpen.call(this, method, url, ...args);
        };

        XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
            if (String(name).toLowerCase() === "authorization") {
                this.__nashdomObjectAuthorization = String(value);
            }
            return originalSetRequestHeader.call(this, name, value);
        };

        XMLHttpRequest.prototype.send = function(body) {
            this.addEventListener("loadend", function() {
                const requestUrl = this.responseURL || this.__nashdomObjectUrl || "";
                if (!requestUrl.includes(endpointMarker)) {
                    return;
                }

                window.__nashdomObjectRequest = {
                    requestUrl: requestUrl,
                    authorization: this.__nashdomObjectAuthorization,
                    status: this.status
                };
            });
            return originalSend.call(this, body);
        };

        window.__nashdomObjectInterceptorInstalled = true;
    }
    return true;
})();
"""

_BROWSER_FETCH_SCRIPT = """
const url = arguments[0];
const authorization = arguments[1];
const done = arguments[arguments.length - 1];

fetch(url, {
    method: "GET",
    credentials: "same-origin",
    headers: {
        "Accept": "application/json, text/plain, */*",
        "Authorization": authorization
    }
})
.then(async (response) => {
    const raw = await response.text();
    let body = null;

    try {
        body = JSON.parse(raw);
    } catch (_) {
        body = raw;
    }

    done({
        status: response.status,
        body: body
    });
})
.catch((error) => {
    done({
        status: null,
        error: String(error)
    });
});
"""

_PUBLIC_BROWSER_FETCH_SCRIPT = """
const url = arguments[0];
const done = arguments[arguments.length - 1];

fetch(url, {
    method: "GET",
    credentials: "same-origin",
    headers: {
        "Accept": "application/json, text/plain, */*"
    }
})
.then(async (response) => {
    const raw = await response.text();
    let body = null;

    try {
        body = JSON.parse(raw);
    } catch (_) {
        body = raw;
    }

    done({
        status: response.status,
        body: body
    });
})
.catch((error) => {
    done({
        status: null,
        error: String(error)
    });
});
"""

_CHALLENGE_MARKERS = (
    "captcha-container",
    "cf-chl-",
    '<noscript><meta http-equiv="refresh"',
    "подтвердите, что вы не робот",
    "проверка браузера",
    "too many requests",
)
_SERVER_ERROR_MARKERS = (
    "500 internal server error",
    "502 bad gateway",
    "503 service unavailable",
    "504 gateway timeout",
)


@dataclass(frozen=True)
class _CapturedRequest:
    request_url: str
    authorization: str = field(repr=False)


@dataclass(frozen=True)
class _ApiBatch:
    items: List[Dict[str, Any]]
    total: int


@dataclass(frozen=True)
class _DeveloperApiBatch:
    items: List[Dict[str, Any]]
    count: int


class NashDomClient:
    """Получает данные NashDom в переданной браузерной сессии."""

    def __init__(self, driver: WebDriver) -> None:
        self._driver = driver
        self._normalizer = NashDomDataNormalizer()

    def get_objects(
        self,
        settings: NashDomExtractSettings,
    ) -> List[ExtractedObject]:
        """Получить не более заданного числа объектов для каждого региона."""
        self._configure_timeouts()
        objects: List[ExtractedObject] = []

        for region in settings.regions:
            objects.extend(
                self._get_region_objects(
                    region,
                    settings.objects_to_parse_count,
                )
            )

        return objects

    def get_developers(self, developer_ids: Set[int]) -> List[ExtractedDeveloper]:
        """Получить запрошенных застройщиков через bulk ERZ с detail fallback."""
        if not developer_ids:
            return []

        self._configure_timeouts()
        self._ensure_nashdom_context()
        raw_developers = self._collect_bulk_developers(developer_ids)

        missing_ids = developer_ids - set(raw_developers)
        for developer_id in sorted(missing_ids):
            raw_developers[developer_id] = self._read_detail_developer(developer_id)

        normalized_developers = self._normalizer.normalize_developers(
            [raw_developers[developer_id] for developer_id in sorted(developer_ids)]
        )
        return sorted(normalized_developers, key=lambda developer: developer.id)

    def get_company_groups(
        self,
        company_group_ids: Set[int],
    ) -> List[BaseExtractedDataclass]:
        """Получение групп компаний будет реализовано в следующей итерации."""
        raise NotImplementedError("Извлечение групп компаний NashDom ещё не реализовано")

    def _collect_bulk_developers(
        self,
        developer_ids: Set[int],
    ) -> Dict[int, Dict[str, Any]]:
        registry_index: Dict[int, Dict[str, Any]] = {}
        requested_developers: Dict[int, Dict[str, Any]] = {}
        offset = 0

        while True:
            batch = self._fetch_developer_batch(
                offset=offset,
                limit=_DEVELOPER_API_BATCH_SIZE,
            )
            if batch.count == 0 and batch.items:
                raise NashDomClientError(
                    "ERZ bulk API вернул застройщиков при data.count=0"
                )

            has_new_registry_record = False
            for raw_developer in batch.items:
                developer_id = self._read_raw_developer_id(raw_developer)
                existing_developer = registry_index.get(developer_id)
                if (
                    existing_developer is not None
                    and existing_developer != raw_developer
                ):
                    raise NashDomClientError(
                        "ERZ bulk API вернул различающиеся записи "
                        f"для повторного devId={developer_id}"
                    )

                if existing_developer is None:
                    registry_index[developer_id] = raw_developer
                    has_new_registry_record = True
                if developer_id in developer_ids:
                    requested_developers[developer_id] = raw_developer

            if developer_ids.issubset(requested_developers):
                break
            if not batch.items or len(batch.items) < _DEVELOPER_API_BATCH_SIZE:
                break
            if not has_new_registry_record:
                break

            offset += len(batch.items)

        return requested_developers

    def _fetch_developer_batch(
        self,
        *,
        offset: int,
        limit: int,
    ) -> _DeveloperApiBatch:
        url = self._build_developers_api_url(offset, limit)
        raw_result_value: object = None
        fetch_failure: Optional[str] = None
        try:
            raw_result_value = cast(
                object,
                self._driver.execute_async_script(  # pyright: ignore[reportUnknownMemberType]
                    _PUBLIC_BROWSER_FETCH_SCRIPT,
                    url,
                ),
            )
        except TimeoutException:
            fetch_failure = "timeout"
        except WebDriverException:
            fetch_failure = "webdriver"

        if fetch_failure == "timeout":
            raise NashDomUnavailableError(
                f"NashDom не ответил на ERZ bulk fetch с offset={offset}"
            )
        if fetch_failure == "webdriver":
            raise NashDomClientError(
                f"Не удалось выполнить ERZ bulk fetch с offset={offset}"
            )

        if not isinstance(raw_result_value, dict):
            raise NashDomClientError("ERZ bulk fetch вернул неожиданный результат")

        raw_result = cast(Dict[str, Any], raw_result_value)
        status = raw_result.get("status")
        body = raw_result.get("body")
        if status is None:
            raise NashDomUnavailableError(
                f"Сетевая ошибка ERZ bulk fetch с offset={offset}"
            )
        if not isinstance(status, int) or isinstance(status, bool):
            raise NashDomClientError("ERZ bulk fetch вернул некорректный HTTP status")

        self._raise_for_http_status(status, body, f"ERZ bulk fetch offset={offset}")
        if self._contains_challenge(body):
            raise NashDomUnavailableError(
                f"NashDom вернул anti-bot/challenge во время ERZ bulk fetch offset={offset}"
            )
        if not isinstance(body, dict):
            raise NashDomClientError("ERZ bulk API вернул не JSON-объект")
        body_mapping = cast(Dict[str, Any], body)
        if body_mapping.get("errcode") != "0":
            raise NashDomClientError("ERZ bulk API вернул неожиданный errcode")

        data = body_mapping.get("data")
        if not isinstance(data, dict):
            raise NashDomClientError("В ответе ERZ bulk API отсутствует объект data")

        data_mapping = cast(Dict[str, Any], data)
        raw_items = data_mapping.get("developers")
        count = data_mapping.get("count")
        if not isinstance(raw_items, list):
            raise NashDomClientError(
                "В ответе ERZ bulk API data.developers не является списком"
            )
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise NashDomClientError(
                "В ответе ERZ bulk API data.count имеет неверный тип"
            )

        items: List[Dict[str, Any]] = []
        for raw_item in cast(List[Any], raw_items):
            if not isinstance(raw_item, dict):
                raise NashDomClientError(
                    "ERZ bulk data.developers содержит не объект JSON"
                )
            items.append(cast(Dict[str, Any], raw_item))
        return _DeveloperApiBatch(items=items, count=count)

    @staticmethod
    def _build_developers_api_url(offset: int, limit: int) -> str:
        query = urlencode(
            {
                "offset": offset,
                "limit": limit,
                "sortField": "devShortNm",
                "sortType": "asc",
                "objStatus": 0,
            }
        )
        return f"{_BASE_URL}{_DEVELOPER_API_PATH}?{query}"

    @staticmethod
    def _read_raw_developer_id(raw_developer: Dict[str, Any]) -> int:
        developer_id = raw_developer.get("devId")
        if not isinstance(developer_id, int) or isinstance(developer_id, bool):
            raise NashDomClientError(
                "Запись застройщика не содержит целочисленный devId"
            )
        return developer_id

    def _ensure_nashdom_context(self) -> None:
        try:
            current_url = self._driver.current_url
        except WebDriverException as exc:
            raise NashDomClientError(
                "Не удалось проверить browser-context перед ERZ bulk fetch"
            ) from exc

        if urlsplit(current_url).netloc == urlsplit(_BASE_URL).netloc:
            return

        try:
            self._driver.get(_BASE_URL)
        except TimeoutException as exc:
            raise NashDomUnavailableError(
                "NashDom не ответил при подготовке browser-context для ERZ API"
            ) from exc
        except WebDriverException as exc:
            error_text = str(exc).lower()
            if "net::err_" in error_text or "timed out" in error_text or "timeout" in error_text:
                raise NashDomUnavailableError(
                    "Сетевая ошибка при подготовке browser-context для ERZ API"
                ) from exc
            raise NashDomClientError(
                "Браузер не смог подготовить browser-context для ERZ API"
            ) from exc

        self._raise_if_unavailable_developer_page("подготовки ERZ API")

    def _read_detail_developer(self, developer_id: int) -> Dict[str, Any]:
        self._open_developer_detail(developer_id)
        next_data = self._read_developer_next_data(developer_id)

        props = next_data.get("props")
        if not isinstance(props, dict):
            raise NashDomClientError(
                "В detail __NEXT_DATA__ застройщика отсутствует props"
            )
        props_mapping = cast(Dict[str, Any], props)
        page_props = props_mapping.get("pageProps")
        if not isinstance(page_props, dict):
            raise NashDomClientError(
                "В detail __NEXT_DATA__ застройщика отсутствует props.pageProps"
            )
        page_props_mapping = cast(Dict[str, Any], page_props)

        if "statusCode" in page_props_mapping:
            status_code = page_props_mapping["statusCode"]
            if not isinstance(status_code, int) or isinstance(status_code, bool):
                raise NashDomClientError(
                    "props.pageProps.statusCode застройщика имеет неверный тип"
                )
            self._raise_for_http_status(
                status_code,
                next_data,
                f"detail SSR застройщика {developer_id}",
            )

        if "id" in page_props_mapping:
            page_developer_id = page_props_mapping["id"]
            if (
                not isinstance(page_developer_id, int)
                or isinstance(page_developer_id, bool)
                or page_developer_id != developer_id
            ):
                raise NashDomClientError(
                    "props.pageProps.id не соответствует запрошенному застройщику "
                    f"{developer_id}"
                )

        initial_state = props_mapping.get("initialState")
        if not isinstance(initial_state, dict):
            raise NashDomClientError(
                "В detail __NEXT_DATA__ застройщика отсутствует props.initialState"
            )
        erz = cast(Dict[str, Any], initial_state).get("erz")
        if not isinstance(erz, dict):
            raise NashDomClientError(
                "В detail __NEXT_DATA__ застройщика отсутствует initialState.erz"
            )
        builder_state = cast(Dict[str, Any], erz).get("builder")
        if not isinstance(builder_state, dict):
            raise NashDomClientError(
                "В detail __NEXT_DATA__ застройщика отсутствует erz.builder"
            )
        raw_developer = cast(Dict[str, Any], builder_state).get("builder")
        if not isinstance(raw_developer, dict):
            raise NashDomClientError(
                "В detail __NEXT_DATA__ застройщика отсутствует erz.builder.builder"
            )

        typed_raw_developer = cast(Dict[str, Any], raw_developer)
        raw_developer_id = self._read_raw_developer_id(typed_raw_developer)
        if raw_developer_id != developer_id:
            raise NashDomClientError(
                f"Detail SSR вернул devId={raw_developer_id} вместо {developer_id}"
            )
        return typed_raw_developer

    def _open_developer_detail(self, developer_id: int) -> None:
        try:
            self._driver.get(f"{_BASE_URL}/developer/{developer_id}")
        except TimeoutException as exc:
            raise NashDomUnavailableError(
                f"NashDom не ответил при открытии застройщика {developer_id}"
            ) from exc
        except WebDriverException as exc:
            error_text = str(exc).lower()
            if "net::err_" in error_text or "timed out" in error_text or "timeout" in error_text:
                raise NashDomUnavailableError(
                    f"Сетевая ошибка при открытии застройщика {developer_id}"
                ) from exc
            raise NashDomClientError(
                f"Браузер не смог открыть страницу застройщика {developer_id}"
            ) from exc

        self._raise_if_unavailable_developer_page(f"застройщика {developer_id}")

    def _raise_if_unavailable_developer_page(self, operation: str) -> None:
        try:
            page_text = f"{self._driver.title}\n{self._driver.page_source[:200000]}".lower()
        except WebDriverException as exc:
            raise NashDomClientError(
                f"Не удалось проверить страницу NashDom во время {operation}"
            ) from exc

        if any(marker in page_text for marker in _SERVER_ERROR_MARKERS):
            raise NashDomUnavailableError(
                f"NashDom вернул серверную ошибку во время {operation}"
            )
        if any(marker in page_text for marker in _CHALLENGE_MARKERS):
            raise NashDomUnavailableError(
                f"NashDom показал anti-bot/challenge во время {operation}"
            )

    def _read_developer_next_data(self, developer_id: int) -> Dict[str, Any]:
        try:
            element = WebDriverWait(self._driver, _WAIT_TIMEOUT_SECONDS).until(
                EC.presence_of_element_located((By.ID, "__NEXT_DATA__"))
            )
        except TimeoutException as exc:
            raise NashDomClientError(
                f"На странице застройщика {developer_id} не найден __NEXT_DATA__"
            ) from exc

        try:
            raw_next_data: Optional[str] = element.get_attribute(  # pyright: ignore[reportUnknownMemberType]
                "textContent"
            )
        except WebDriverException as exc:
            raise NashDomClientError(
                f"Не удалось прочитать __NEXT_DATA__ застройщика {developer_id}"
            ) from exc
        if not raw_next_data:
            raise NashDomClientError(
                f"__NEXT_DATA__ застройщика {developer_id} не содержит данных"
            )

        try:
            next_data = json.loads(raw_next_data)
        except json.JSONDecodeError as exc:
            raise NashDomClientError(
                f"Не удалось разобрать __NEXT_DATA__ застройщика {developer_id}"
            ) from exc
        if not isinstance(next_data, dict):
            raise NashDomClientError(
                f"__NEXT_DATA__ застройщика {developer_id} имеет неожиданный тип"
            )
        return cast(Dict[str, Any], next_data)

    def _get_region_objects(
        self,
        region: NashDomRegion,
        target_count: int,
    ) -> List[ExtractedObject]:
        self._open_region(region)
        ssr_objects = self._read_ssr_objects()

        if len(ssr_objects) >= target_count:
            return self._normalizer.normalize_objects(ssr_objects[:target_count])

        load_more_locator = self._find_load_more_locator()
        if load_more_locator is None:
            return self._normalizer.normalize_objects(ssr_objects)

        captured_request = self._bootstrap_api_request(load_more_locator)
        xhr_objects = self._collect_api_objects(captured_request, target_count)
        return self._normalizer.normalize_objects(xhr_objects)

    def _configure_timeouts(self) -> None:
        try:
            self._driver.set_page_load_timeout(_WAIT_TIMEOUT_SECONDS)
            self._driver.set_script_timeout(_WAIT_TIMEOUT_SECONDS)
        except WebDriverException as exc:
            raise NashDomClientError("Не удалось настроить таймауты браузера") from exc

    def _open_region(self, region: NashDomRegion) -> None:
        url = self._build_region_url(region.slug)
        try:
            self._driver.get(url)
        except TimeoutException as exc:
            raise NashDomUnavailableError(
                f"NashDom не ответил вовремя при открытии региона {region.code}"
            ) from exc
        except WebDriverException as exc:
            error_text = str(exc).lower()
            if "net::err_" in error_text or "timed out" in error_text or "timeout" in error_text:
                raise NashDomUnavailableError(
                    f"Сетевая ошибка при открытии NashDom для региона {region.code}"
                ) from exc
            raise NashDomClientError(
                f"Браузер не смог открыть страницу NashDom для региона {region.code}"
            ) from exc

        self._raise_if_unavailable_page(region.code)

    @staticmethod
    def _build_region_url(slug: str) -> str:
        encoded_slug = quote(slug.strip(), safe="")
        return (
            f"{_BASE_URL}/новостройки/строящиеся/{encoded_slug}/"
            "?sortName=objPublDt&sortDirection=desc"
        )

    def _raise_if_unavailable_page(self, region_id: int) -> None:
        try:
            page_text = f"{self._driver.title}\n{self._driver.page_source[:200000]}".lower()
        except WebDriverException as exc:
            raise NashDomClientError("Не удалось проверить состояние страницы NashDom") from exc

        if any(marker in page_text for marker in _SERVER_ERROR_MARKERS):
            raise NashDomUnavailableError(
                f"NashDom вернул серверную ошибку для региона {region_id}"
            )
        if any(marker in page_text for marker in _CHALLENGE_MARKERS):
            raise NashDomUnavailableError(
                f"NashDom показал anti-bot/challenge для региона {region_id}"
            )

    def _read_ssr_objects(self) -> List[Dict[str, Any]]:
        try:
            element = WebDriverWait(self._driver, _WAIT_TIMEOUT_SECONDS).until(
                EC.presence_of_element_located((By.ID, "__NEXT_DATA__"))
            )
        except TimeoutException as exc:
            raise NashDomClientError(
                "На странице NashDom не найден ожидаемый __NEXT_DATA__"
            ) from exc

        try:
            raw_next_data: Optional[str] = element.get_attribute(  # pyright: ignore[reportUnknownMemberType]
                "textContent"
            )
        except WebDriverException as exc:
            raise NashDomClientError("Не удалось прочитать __NEXT_DATA__") from exc
        if not raw_next_data:
            raise NashDomClientError("__NEXT_DATA__ найден, но не содержит данных")

        try:
            next_data = json.loads(raw_next_data)
        except json.JSONDecodeError as exc:
            raise NashDomClientError("Не удалось разобрать __NEXT_DATA__ как JSON") from exc

        if not isinstance(next_data, dict):
            raise NashDomClientError("__NEXT_DATA__ имеет неожиданный тип")

        next_data_mapping = cast(Dict[str, Any], next_data)
        props = next_data_mapping.get("props")
        if not isinstance(props, dict):
            raise NashDomClientError(
                "В __NEXT_DATA__ отсутствует props.pageProps.houses"
            )
        props_mapping = cast(Dict[str, Any], props)
        page_props = props_mapping.get("pageProps")
        if not isinstance(page_props, dict):
            raise NashDomClientError(
                "В __NEXT_DATA__ отсутствует props.pageProps.houses"
            )
        page_props_mapping = cast(Dict[str, Any], page_props)
        houses: Any = page_props_mapping.get("houses")

        if not isinstance(houses, list):
            raise NashDomClientError("props.pageProps.houses не является списком")

        raw_objects: List[Dict[str, Any]] = []
        for raw_object in cast(List[Any], houses):
            if not isinstance(raw_object, dict):
                raise NashDomClientError("SSR-список houses содержит не объект JSON")
            raw_objects.append(cast(Dict[str, Any], raw_object))
        return raw_objects

    def _find_load_more_locator(self) -> Optional[_Locator]:
        for locator in _LOAD_MORE_LOCATORS:
            try:
                elements = self._driver.find_elements(*locator)
                if len(elements) > 1:
                    raise NashDomClientError(
                        "Кнопка «Показать ещё» определена неоднозначно: "
                        f"локатор нашёл {len(elements)} элементов"
                    )
                if (
                    len(elements) == 1
                    and elements[0].is_displayed()
                    and elements[0].is_enabled()
                ):
                    return locator
            except NashDomClientError:
                raise
            except WebDriverException as exc:
                raise NashDomClientError("Не удалось найти кнопку «Показать ещё»") from exc

        return None

    def _bootstrap_api_request(self, locator: _Locator) -> _CapturedRequest:
        self._install_interceptor()
        self._click_load_more(locator)
        return self._wait_for_captured_request()

    def _install_interceptor(self) -> None:
        try:
            installed = cast(
                object,
                self._driver.execute_script(  # pyright: ignore[reportUnknownMemberType]
                    _INSTALL_INTERCEPTOR_SCRIPT
                ),
            )
        except WebDriverException as exc:
            raise NashDomClientError("Не удалось установить XHR interceptor") from exc

        if installed is not True:
            raise NashDomClientError("XHR interceptor не подтвердил установку")

    def _click_load_more(self, locator: _Locator) -> None:
        try:
            button = WebDriverWait(self._driver, _WAIT_TIMEOUT_SECONDS).until(
                EC.element_to_be_clickable(locator)
            )
            self._driver.execute_script(  # pyright: ignore[reportUnknownMemberType]
                "arguments[0].scrollIntoView({block: 'center', inline: 'center'});",
                button,
            )
            try:
                button.click()
            except (ElementClickInterceptedException, ElementNotInteractableException):
                self._driver.execute_script(  # pyright: ignore[reportUnknownMemberType]
                    "arguments[0].click();", button
                )
        except TimeoutException as exc:
            raise NashDomClientError(
                "Кнопка «Показать ещё» найдена, но не стала доступна для клика"
            ) from exc
        except WebDriverException as exc:
            raise NashDomClientError("Не удалось нажать кнопку «Показать ещё»") from exc

    def _wait_for_captured_request(self) -> _CapturedRequest:
        def request_captured(current_driver: WebDriver) -> bool:
            result = cast(
                object,
                current_driver.execute_script(  # pyright: ignore[reportUnknownMemberType]
                    """
                    const request = window.__nashdomObjectRequest;
                    return Boolean(
                        request &&
                        request.requestUrl &&
                        request.authorization &&
                        Number.isInteger(request.status)
                    );
                    """
                ),
            )
            return result is True

        try:
            WebDriverWait(self._driver, _WAIT_TIMEOUT_SECONDS).until(request_captured)
            raw_request_value = cast(
                object,
                self._driver.execute_script(  # pyright: ignore[reportUnknownMemberType]
                    "return window.__nashdomObjectRequest;"
                ),
            )
        except TimeoutException as exc:
            raise NashDomClientError(
                "Кнопка «Показать ещё» нажата, но ожидаемый XHR не был получен"
            ) from exc
        except WebDriverException as exc:
            raise NashDomClientError("Не удалось прочитать перехваченный XHR") from exc

        if not isinstance(raw_request_value, dict):
            raise NashDomClientError("Перехваченный XHR имеет неожиданный формат")

        raw_request = cast(Dict[str, Any], raw_request_value)
        request_url = raw_request.get("requestUrl")
        authorization = raw_request.get("authorization")
        status = raw_request.get("status")
        if not isinstance(request_url, str) or _API_ENDPOINT_MARKER not in request_url:
            raise NashDomClientError("Перехвачен неожиданный URL вместо /api/kn/object")
        if not isinstance(authorization, str) or not authorization:
            raise NashDomClientError("В штатном XHR отсутствует Authorization")
        if not isinstance(status, int) or isinstance(status, bool):
            raise NashDomClientError("Штатный XHR не содержит корректный HTTP status")

        self._raise_for_http_status(status, None, "штатного XHR")
        return _CapturedRequest(
            request_url=request_url,
            authorization=authorization,
        )

    def _collect_api_objects(
        self,
        captured_request: _CapturedRequest,
        target_count: int,
    ) -> List[Dict[str, Any]]:
        objects: List[Dict[str, Any]] = []
        seen_ids: Set[int] = set()
        api_total: Optional[int] = None
        offset = 0

        while api_total is None or len(objects) < min(target_count, api_total):
            remaining = (
                target_count
                if api_total is None
                else min(target_count, api_total) - len(objects)
            )
            batch = self._fetch_api_batch(
                captured_request,
                offset=offset,
                limit=min(_API_BATCH_SIZE, remaining),
            )

            if api_total is None:
                api_total = batch.total
            if api_total == 0:
                if batch.items:
                    raise NashDomClientError("XHR вернул объекты при total=0")
                return []
            if not batch.items:
                raise NashDomClientError(
                    "XHR вернул пустую порцию до достижения заявленного total"
                )

            batch_ids = [self._read_raw_object_id(item) for item in batch.items]
            if not any(object_id not in seen_ids for object_id in batch_ids):
                raise NashDomClientError("XHR-порция не содержит новых objId")
            seen_ids.update(batch_ids)

            effective_target = min(target_count, api_total)
            objects.extend(batch.items[: effective_target - len(objects)])
            offset += len(batch.items)

        return objects

    def _fetch_api_batch(
        self,
        captured_request: _CapturedRequest,
        *,
        offset: int,
        limit: int,
    ) -> _ApiBatch:
        url = self._build_api_url(captured_request.request_url, offset, limit)
        raw_result_value: object = None
        fetch_failure: Optional[str] = None
        try:
            raw_result_value = cast(
                object,
                self._driver.execute_async_script(  # pyright: ignore[reportUnknownMemberType]
                    _BROWSER_FETCH_SCRIPT,
                    url,
                    captured_request.authorization,
                ),
            )
        except TimeoutException:
            fetch_failure = "timeout"
        except WebDriverException:
            fetch_failure = "webdriver"

        if fetch_failure == "timeout":
            raise NashDomUnavailableError(
                f"NashDom не ответил на browser-context fetch с offset={offset}"
            )
        if fetch_failure == "webdriver":
            raise NashDomClientError(
                f"Не удалось выполнить browser-context fetch с offset={offset}"
            )

        if not isinstance(raw_result_value, dict):
            raise NashDomClientError("Browser-context fetch вернул неожиданный результат")

        raw_result = cast(Dict[str, Any], raw_result_value)
        status = raw_result.get("status")
        body = raw_result.get("body")
        if status is None:
            raise NashDomUnavailableError(
                f"Сетевая ошибка browser-context fetch с offset={offset}"
            )
        if not isinstance(status, int) or isinstance(status, bool):
            raise NashDomClientError("Browser-context fetch вернул некорректный HTTP status")

        self._raise_for_http_status(status, body, f"browser-context fetch offset={offset}")
        if not isinstance(body, dict):
            raise NashDomClientError("API NashDom вернул не JSON-объект")
        body_mapping = cast(Dict[str, Any], body)
        if body_mapping.get("errcode") != "0":
            raise NashDomClientError("API NashDom вернул неожиданный errcode")

        data = body_mapping.get("data")
        if not isinstance(data, dict):
            raise NashDomClientError("В ответе API NashDom отсутствует объект data")

        data_mapping = cast(Dict[str, Any], data)
        raw_items = data_mapping.get("list")
        total = data_mapping.get("total")
        if not isinstance(raw_items, list):
            raise NashDomClientError("В ответе API NashDom data.list не является списком")
        if not isinstance(total, int) or isinstance(total, bool) or total < 0:
            raise NashDomClientError("В ответе API NashDom data.total имеет неверный тип")

        items: List[Dict[str, Any]] = []
        for raw_item in cast(List[Any], raw_items):
            if not isinstance(raw_item, dict):
                raise NashDomClientError("XHR data.list содержит не объект JSON")
            items.append(cast(Dict[str, Any], raw_item))
        return _ApiBatch(items=items, total=total)

    @staticmethod
    def _build_api_url(captured_url: str, offset: int, limit: int) -> str:
        parsed_url = urlsplit(captured_url)
        if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
            raise NashDomClientError("Перехваченный URL API имеет неверный формат")
        if _API_ENDPOINT_MARKER not in parsed_url.path:
            raise NashDomClientError("Перехваченный URL не относится к /api/kn/object")

        query = dict(parse_qsl(parsed_url.query, keep_blank_values=True))
        query["offset"] = str(offset)
        query["limit"] = str(limit)
        return urlunsplit(
            (
                parsed_url.scheme,
                parsed_url.netloc,
                parsed_url.path,
                urlencode(query),
                "",
            )
        )

    @staticmethod
    def _read_raw_object_id(raw_object: Dict[str, Any]) -> int:
        object_id = raw_object.get("objId")
        if not isinstance(object_id, int) or isinstance(object_id, bool):
            raise NashDomClientError("XHR-объект не содержит целочисленный objId")
        return object_id

    @staticmethod
    def _raise_for_http_status(status: int, body: Any, operation: str) -> None:
        if status == 200:
            return
        if status == 429 or status >= 500 or status == 0:
            raise NashDomUnavailableError(
                f"NashDom временно недоступен во время {operation}: HTTP {status}"
            )
        if status == 403 and NashDomClient._contains_challenge(body):
            raise NashDomUnavailableError(
                f"NashDom вернул anti-bot/challenge во время {operation}"
            )
        raise NashDomClientError(
            f"NashDom вернул неожиданный HTTP status во время {operation}: {status}"
        )

    @staticmethod
    def _contains_challenge(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            serialized = value.lower()
        else:
            try:
                serialized = json.dumps(value, ensure_ascii=False).lower()
            except (TypeError, ValueError):
                return False
        return any(marker in serialized for marker in _CHALLENGE_MARKERS)
