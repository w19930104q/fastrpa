"""A fake Selenium WebDriver/WebElement pair backed by lxml.

It runs against local HTML strings (no real browser) and supports
controlled node replacement: once a node is detached from the document,
every command issued against it raises StaleElementReferenceException,
exactly like a real browser does when the framework re-renders a node.
"""

from lxml import html as lxml_html
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
)
from selenium.webdriver.common.by import By


class FakeWebElement:
    def __init__(self, driver: 'FakeWebDriver', node):
        self.driver = driver
        self.node = node
        self.id = f'element-{id(node)}'

    def __eq__(self, other):
        return isinstance(other, FakeWebElement) and self.node is other.node

    def __hash__(self):
        return hash(self.id)

    def _assert_fresh(self):
        root = self.node
        while root.getparent() is not None:
            root = root.getparent()
        if root is not self.driver.root:
            raise StaleElementReferenceException(
                'element is not attached to the page document'
            )

    def _text_content(self) -> str:
        return ' '.join(self.node.text_content().split())

    @property
    def tag_name(self) -> str:
        self._assert_fresh()
        return self.node.tag

    @property
    def text(self) -> str:
        self._assert_fresh()
        return self._text_content()

    def get_attribute(self, name: str):
        self._assert_fresh()
        if name == 'innerText':
            return self._text_content()
        return self.node.get(name)

    def get_dom_attribute(self, name: str):
        return self.get_attribute(name)

    def is_displayed(self) -> bool:
        self._assert_fresh()
        return True

    def is_enabled(self) -> bool:
        self._assert_fresh()
        return self.node.get('disabled') is None

    def is_selected(self) -> bool:
        self._assert_fresh()
        return self.node.get('checked') is not None

    def find_elements(self, by, value):
        self._assert_fresh()
        if by == By.TAG_NAME:
            value = f'.//{value}'
        return [
            FakeWebElement(self.driver, node) for node in self.node.xpath(value)
        ]

    def find_element(self, by, value):
        elements = self.find_elements(by, value)
        if not elements:
            raise NoSuchElementException(f'Cannot locate {value}')
        return elements[0]

    def _record(self, action: str):
        self._assert_fresh()
        self.driver.action_log.append((action, self.node))
        if self.driver.action_hook is not None:
            self.driver.action_hook(action, self.node)

    def click(self):
        self._record('click')

    def clear(self):
        self._record('clear')

    def send_keys(self, value):
        self._record(f'send_keys:{value}')

    def submit(self):
        self._record('submit')


class FakeWebDriver:
    def __init__(self, html: str):
        self.root = lxml_html.document_fromstring(html)
        self.action_log: list = []
        self.action_hook = None
        self.find_count = 0
        self.current_url = 'about:blank'

    @property
    def page_source(self) -> str:
        return lxml_html.tostring(self.root).decode()

    def find_elements(self, by, value):
        self.find_count += 1
        return [FakeWebElement(self, node) for node in self.root.xpath(value)]

    def find_element(self, by, value):
        elements = self.find_elements(by, value)
        if not elements:
            raise NoSuchElementException(f'Cannot locate {value}')
        return elements[0]

    def node(self, xpath: str):
        """Current node in the (possibly mutated) document for an XPath."""
        return self.root.xpath(xpath)[0]

    def replace_node(self, xpath: str, new_html: str):
        """Controlled node replacement, like a framework re-render."""
        old = self.root.xpath(xpath)[0]
        new = lxml_html.fragment_fromstring(new_html)
        old.getparent().replace(old, new)


class FakeActionChains:
    """Executes queued actions immediately against the fake elements,
    recording the physical node each action landed on."""

    def __init__(self, driver):
        self.driver = driver
        self._queue = []

    def _enqueue(self, action, element):
        self._queue.append((action, element))
        return self

    def scroll_to_element(self, element):
        return self._enqueue('scroll', element)

    def move_to_element(self, element):
        return self._enqueue('move', element)

    def click(self, element=None):
        return self._enqueue('click', element)

    def double_click(self, element=None):
        return self._enqueue('double_click', element)

    def perform(self):
        queue, self._queue = self._queue, []
        for action, element in queue:
            element._record(action)
