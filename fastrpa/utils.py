from collections.abc import Callable, Iterable
from functools import wraps
from urllib.parse import urlparse

from requests import Session
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver import ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement

from fastrpa.exceptions import StaleElementException
from fastrpa.types import BrowserOptions, BrowserOptionsClass, WebDriver


def get_browser_options(
    options: list[str], options_class: BrowserOptionsClass = ChromeOptions
) -> BrowserOptions:
    instance = options_class()
    for opt in options:
        instance.add_argument(opt)
    return instance


def get_session(webdriver: WebDriver) -> Session:
    obj = Session()
    for cookie in webdriver.get_cookies():
        obj.cookies.set(
            name=cookie['name'],
            value=cookie['value'],
            domain=cookie['domain'],
            path=cookie['path'],
            secure=cookie['secure'],
        )
    return obj


def get_domain(webdriver: WebDriver) -> str:
    return urlparse(webdriver.current_url).netloc


def find_element(browsable: WebDriver | WebElement, xpath: str) -> WebElement:
    return browsable.find_element(By.XPATH, xpath)


def find_elements(
    browsable: WebDriver | WebElement, xpath: str
) -> list[WebElement]:
    return browsable.find_elements(By.XPATH, xpath)


def print_table(headers: Iterable[str], rows: Iterable[str]):
    try:
        from rich.console import Console
        from rich.table import Table

        rich_table = Table(*headers)
        for row in rows:
            rich_table.add_row(*row)
        Console().print(rich_table)

    except ImportError:
        raise OSError('You need to install rich to print tables.')


def print_list(name: str, values_dict: dict[str | None, str | None]):
    try:
        from rich.console import Console
        from rich.tree import Tree

        rich_tree = Tree(name.replace('[', r'\['))
        for id, value in values_dict.items():
            rich_tree.add(rf'\[{id}] {value}')
        Console().print(rich_tree)

    except ImportError:
        raise OSError('You need to install rich to print lists.')


def ensure_element(func: Callable, max_attempts: int = 3):
    @wraps(func)
    def wrapper(*args, **kwargs):
        attempt = 0
        last_error: StaleElementReferenceException | None = None
        while attempt < max_attempts:
            try:
                return func(*args, **kwargs)
            except StaleElementReferenceException as error:
                last_error = error
                attempt += 1

        xpath = kwargs.get('xpath')
        if xpath is None and len(args) > 1:
            xpath = args[1]
        raise StaleElementException(
            xpath or '<unknown>', func.__name__, attempt
        ) from last_error

    return wrapper
