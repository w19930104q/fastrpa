from collections.abc import Callable
from time import sleep
from typing import Any, TypeVar

from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
)
from selenium.webdriver import ActionChains
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.ui import Select

from fastrpa.core.file import File
from fastrpa.exceptions import (
    FileNotDownloadableException,
    FormException,
    StaleElementException,
)
from fastrpa.types import WebDriver
from fastrpa.utils import (
    find_element,
    find_elements,
    print_list,
    print_table,
)

MAX_RELOCATE_ATTEMPTS = 3

T = TypeVar('T')


def own_descendants(
    source: WebElement, xpath: str, boundary_tag: str
) -> list[WebElement]:
    """Finds descendants of ``source`` that do not belong to a nested
    component of the same kind (e.g. rows of a nested table)."""
    elements = []
    for element in find_elements(source, xpath):
        nearest = find_element(element, f'./ancestor::{boundary_tag}[1]')
        if nearest == source:
            elements.append(element)
    return elements


class Element:
    def __init__(self, xpath: str, webdriver: WebDriver) -> None:
        self.xpath = xpath
        self.webdriver = webdriver
        self.file = File(self.webdriver)
        self.actions = ActionChains(self.webdriver)
        self._source: WebElement | None = None

    def _locate(self) -> WebElement:
        """Explicitly (re)locates the element by its original XPath."""
        self._source = find_element(self.webdriver, self.xpath)
        return self._source

    def _resolve(self) -> WebElement:
        if self._source is None:
            return self._locate()
        return self._source

    @property
    def source(self) -> WebElement:
        return self._resolve()

    def _run(self, phase: str, operation: Callable[[WebElement], T]) -> T:
        """Runs one RPA action against a single stable located element.

        If the node goes stale (replaced in the DOM) in the middle of the
        action, the element is explicitly relocated by its original XPath
        and the whole action is retried. When the attempts are exhausted,
        a StaleElementException carrying the XPath and the phase is raised.
        """
        last_error: StaleElementReferenceException | None = None
        for _ in range(MAX_RELOCATE_ATTEMPTS):
            try:
                return operation(self._resolve())
            except StaleElementReferenceException as error:
                last_error = error
                self._locate()
        raise StaleElementException(
            self.xpath, phase, MAX_RELOCATE_ATTEMPTS
        ) from last_error

    def attribute(self, name: str) -> str | None:
        return self._run('attribute', lambda el: el.get_attribute(name))

    @property
    def tag(self) -> str:
        return self._run('tag', lambda el: el.tag_name)

    @property
    def id(self) -> str | None:
        return self.attribute('id')

    @property
    def css_class(self) -> list[str] | None:
        if classes := self.attribute('class'):
            return classes.split(' ')
        return []

    @property
    def css_inline(self) -> dict[str, str]:
        to_return = {}
        if style := self.attribute('style'):
            for css in style.strip().split(';'):
                if css:
                    css_property, css_value = css.split(':')
                    to_return[css_property.strip()] = css_value.strip()
        return to_return

    @property
    def text(self) -> str | None:
        def read_text(source: WebElement) -> str | None:
            if source.text:
                return source.text
            if value := source.get_attribute('value'):
                return value
            return None

        return self._run('text', read_text)

    @property
    def is_visible(self) -> bool:
        return self._run('is_visible', lambda el: el.is_displayed())

    def focus(self):
        def do_focus(source: WebElement):
            self.actions.scroll_to_element(source)
            self.actions.move_to_element(source)
            self.actions.perform()

        self._run('focus', do_focus)

    def click(self):
        def do_click(source: WebElement):
            self.actions.scroll_to_element(source)
            self.actions.move_to_element(source)
            self.actions.click(source)
            self.actions.perform()

        self._run('click', do_click)

    def check(self, attribute: str, value: str) -> bool:
        return self.attribute(attribute) == value


class InputElement(Element):
    def clear(self):
        self._run('clear', lambda el: el.clear())

    def fill(self, value: str):
        self._run('fill', lambda el: el.send_keys(value))

    def fill_slowly(self, value: str, delay: float = 0.3):
        def do_fill(source: WebElement):
            for key in value:
                source.send_keys(key)
                sleep(delay)

        self._run('fill_slowly', do_fill)


class FileInputElement(Element):
    def attach_file(self, path: str):
        real_path = self.file.get_path(path)
        self._run('attach_file', lambda el: el.send_keys(real_path))


class SelectElement(Element):
    @property
    def select_source(self) -> Select:
        return Select(self.source)

    @property
    def options_values(self) -> list[str | None]:
        def read(source: WebElement) -> list[str | None]:
            return [
                option.get_attribute('value')
                for option in Select(source).options
            ]

        return self._run('options_values', read)

    @property
    def options_labels(self) -> list[str | None]:
        def read(source: WebElement) -> list[str | None]:
            return [
                option.get_attribute('innerText')
                for option in Select(source).options
            ]

        return self._run('options_labels', read)

    @property
    def options(self) -> dict[str | None, str | None]:
        def read(source: WebElement) -> dict[str | None, str | None]:
            return {
                option.get_attribute('value'): option.get_attribute('innerText')
                for option in Select(source).options
            }

        return self._run('options', read)

    @property
    def current(self) -> tuple[str | None, str | None]:
        if value_id := self.attribute('value'):
            return value_id, self.options[value_id]
        return None, None

    def select(self, label: str | None = None, value: str | None = None):
        if label:
            self._run(
                'select',
                lambda el: Select(el).select_by_visible_text(label),
            )
        elif value:
            self._run('select', lambda el: Select(el).select_by_value(value))
        else:
            raise ValueError('You must provide at least "label" or "value"!')

    def has_option(self, label: str | None = None, value: str | None = None):
        if label:
            return label in self.options_labels
        elif value:
            return value in self.options_values
        raise ValueError('You must provide at least "label" or "value"!')

    def __contains__(self, key: Any) -> bool:
        return self.has_option(label=key) or self.has_option(value=key)

    def print(self):
        identifier = f'[@id="{self.id}"]' if self.id else self.xpath
        print_list(f'{identifier}', self.options)


class RadioInputElement(Element):
    def _radio_scope(self, source: WebElement) -> WebDriver | WebElement:
        """Scopes the radio group to the form that contains the input,
        so two forms with the same radio name do not mix options."""
        try:
            return find_element(source, './ancestor::form[1]')
        except NoSuchElementException:
            return self.webdriver

    def _radio_sources(self, source: WebElement) -> list[WebElement]:
        name = source.get_attribute('name')
        scope = self._radio_scope(source)
        prefix = '//' if scope is self.webdriver else './/'
        xpath = f'{prefix}input[@type="radio"][@name="{name}"][not(@disabled)]'
        return find_elements(scope, xpath)

    @property
    def radio_sources(self) -> list[WebElement]:
        return self._run('radio_sources', self._radio_sources)

    @property
    def options_values(self) -> list[str]:
        def read(source: WebElement) -> list[str]:
            return [
                value
                for element in self._radio_sources(source)
                if (value := element.get_attribute('value'))
            ]

        return self._run('options_values', read)

    @property
    def options_labels(self) -> list[str]:
        def read(source: WebElement) -> list[str]:
            labels = []
            for element in self._radio_sources(source):
                if element_id := element.get_attribute('id'):
                    label = find_element(
                        self.webdriver, f'//label[@for="{element_id}"]'
                    )
                    labels.append(label.text)
            return labels

        return self._run('options_labels', read)

    @property
    def options(self) -> dict[str, str]:
        return {
            value: label
            for value, label in zip(self.options_values, self.options_labels)
        }

    def select(self, label: str | None = None, value: str | None = None):
        if label:
            index = self.options_labels.index(label)
        elif value:
            index = self.options_values.index(value)
        else:
            raise ValueError('You must provide at least "label" or "value"!')

        def do_select(_: WebElement):
            element = self.radio_sources[index]
            self.actions.move_to_element(element)
            self.actions.click(element)
            self.actions.perform()

        self._run('select', do_select)

    def has_option(self, label: str | None = None, value: str | None = None):
        if label:
            return label in self.options_labels
        elif value:
            return value in self.options_values
        raise ValueError('You must provide at least "label" or "value"!')

    def __contains__(self, key: Any) -> bool:
        return self.has_option(label=key) or self.has_option(value=key)

    def print(self):
        identifier = f'[@id="{self.id}"]' if self.id else self.xpath
        print_list(f'{identifier}', self.options)


class CheckboxElement(Element):
    @property
    def is_checked(self) -> bool:
        return self._run('is_checked', lambda el: el.is_selected())

    def check(self):
        if not self.is_checked:
            self.click()

    def uncheck(self):
        if self.is_checked:
            self.click()

    def switch(self):
        self.click()


class ListElement(Element):
    @property
    def items_sources(self) -> list[WebElement]:
        def read(source: WebElement) -> list[WebElement]:
            return find_elements(source, './li')

        return self._run('items_sources', read)

    @property
    def is_ordered(self) -> bool:
        return self.tag == 'ol'

    @property
    def items(self) -> dict[str | None, str | None]:
        def read(source: WebElement) -> dict[str | None, str | None]:
            return {
                item.get_attribute('id'): item.get_attribute('innerText')
                for item in find_elements(source, './li')
            }

        return self._run('items', read)

    @property
    def items_ids(self) -> list[str | None]:
        def read(source: WebElement) -> list[str | None]:
            return [
                item.get_attribute('id')
                for item in find_elements(source, './li')
            ]

        return self._run('items_ids', read)

    @property
    def items_labels(self) -> list[str | None]:
        def read(source: WebElement) -> list[str | None]:
            return [
                item.get_attribute('innerText')
                for item in find_elements(source, './li')
            ]

        return self._run('items_labels', read)

    def click_in_item(self, label: str | None = None, id: str | None = None):
        if not (label or id):
            raise ValueError('You must provide at least "label" or "id"!')

        def do_click(source: WebElement):
            for item in find_elements(source, './li'):
                if label and label == item.get_attribute('innerText'):
                    self.actions.click(item)
                    self.actions.perform()
                    return

                if id and id == item.get_attribute('id'):
                    self.actions.click(item)
                    self.actions.perform()
                    return

            raise ValueError('Item not found!')

        self._run('click_in_item', do_click)

    def has_item(self, label: str | None = None, id: str | None = None):
        if label:
            return label in self.items_labels
        elif id:
            return id in self.items_ids
        raise ValueError('You must provide at least "label" or "id"!')

    def __contains__(self, key: Any) -> bool:
        return self.has_item(label=key) or self.has_item(id=key)

    def print(self):
        identifier = f'[@id="{self.id}"]' if self.id else self.xpath
        print_list(identifier, self.items)


class ButtonElement(Element):
    @property
    def is_link(self) -> bool:
        return self.tag == 'a'

    @property
    def reference(self) -> str | None:
        if self.is_link:
            return self.attribute('href')
        return None

    def double_click(self):
        def do_double_click(source: WebElement):
            self.actions.move_to_element(source)
            self.actions.double_click(source)
            self.actions.perform()

        self._run('double_click', do_double_click)


class FormElement(Element):
    _success_redirect_url: str | None = None
    _success_elements_to_find: list[str] = []
    _success_text_to_find: list[str] = []

    def _check_success_conditions(self):
        if self._success_redirect_url is not None:
            if self.webdriver.current_url != self._success_redirect_url:
                raise FormException('redirect_url', self._success_redirect_url)

        for element in self._success_elements_to_find:
            try:
                find_element(self.webdriver, element)
            except NoSuchElementException:
                raise FormException('elements_to_find', element)

        for text in self._success_text_to_find:
            if text not in self.webdriver.page_source:
                raise FormException('text_to_find', text)

    @property
    def method(self) -> str:
        if gotten_method := self.attribute('method'):
            return gotten_method.upper()
        return 'GET'

    @property
    def action(self) -> str | None:
        return self.attribute('action')

    @property
    def type(self) -> str:
        if gotten_type := self.attribute('enctype'):
            return gotten_type
        return 'application/x-www-form-urlencoded'

    def set_success_condition(
        self,
        redirect_url: str | None = None,
        elements_to_find: list[str] = [],
        text_to_find: list[str] = [],
    ):
        self._success_redirect_url = redirect_url
        self._success_elements_to_find = elements_to_find
        self._success_text_to_find = text_to_find

    def submit(self, button_xpath: str | None = None):
        if not button_xpath:
            self._run('submit', lambda el: el.submit())
        else:
            button = ButtonElement(button_xpath, self.webdriver)
            button.click()
        self._check_success_conditions()


class TableElement(Element):
    def _own_rows(self, source: WebElement) -> list[WebElement]:
        return own_descendants(source, './/tr', 'table')

    def _own_cells(
        self, source: WebElement, row: WebElement
    ) -> list[WebElement]:
        return [
            cell
            for cell in find_elements(row, './/td | .//th')
            if find_element(cell, './ancestor::table[1]') == source
        ]

    @property
    def headers_sources(self) -> list[WebElement]:
        def read(source: WebElement) -> list[WebElement]:
            rows = self._own_rows(source)
            if not rows:
                return []
            return [
                cell
                for cell in self._own_cells(source, rows[0])
                if cell.tag_name == 'th'
            ]

        return self._run('headers_sources', read)

    @property
    def headers(self) -> list[str | None]:
        return [
            header.get_attribute('innerText') if header else None
            for header in self.headers_sources
        ]

    @property
    def rows_sources(self) -> list[WebElement]:
        def read(source: WebElement) -> list[WebElement]:
            rows = self._own_rows(source)
            if self.headers:
                del rows[0]
            return rows

        return self._run('rows_sources', read)

    @property
    def rows(self) -> list[list[str | None]]:
        def read(source: WebElement) -> list[list[str | None]]:
            rows_content = []
            for row in self.rows_sources:
                rows_content.append(
                    [
                        cell.get_attribute('innerText')
                        for cell in self._own_cells(source, row)
                    ]
                )
            return rows_content

        return self._run('rows', read)

    def column_values(
        self, name: str | None = None, index: int | None = None
    ) -> list[str | None]:
        if (not name) and (index is None):
            raise ValueError('You must provide at least "name" or "index"!')

        if index is None:
            index = self.headers.index(name)

        return [row[index] for row in self.rows]

    def has_content(self, value: str) -> bool:
        def read(source: WebElement) -> bool:
            cells_content = [
                cell.get_attribute('innerText')
                for cell in own_descendants(source, './/td', 'table')
            ]
            return value in cells_content

        return self._run('has_content', read)

    def __contains__(self, value: Any) -> bool:
        return self.has_content(value)

    def print(self):
        print_table(self.headers, self.rows)


class ImageElement(Element):
    @property
    def text(self) -> str | None:
        return self.attribute('alt')

    @property
    def reference(self) -> str | None:
        return self.attribute('src')

    def save(self, path: str | None = None):
        if not self.reference:
            raise FileNotDownloadableException(self.reference, self.xpath)
        if path is not None:
            self.file.download_file(self.reference, path)
        else:
            self.file.download_file_to_cwd(self.reference)
