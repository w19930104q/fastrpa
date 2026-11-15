import pytest
from fake_driver import (
    FakeActionChains,
    FakeWebDriver,
    FakeWebElement,
)
from selenium.common.exceptions import StaleElementReferenceException

from fastrpa.app import Web
from fastrpa.core.elements import ButtonElement
from fastrpa.core.elements_factory import ElementsFactory
from fastrpa.exceptions import StaleElementException


@pytest.fixture(autouse=True)
def fake_action_chains(monkeypatch):
    monkeypatch.setattr('fastrpa.core.elements.ActionChains', FakeActionChains)


BUTTON_HTML = """
<html><body>
  <div id="app"><button id="btn">OK</button></div>
</body></html>
"""

LISTS_HTML = """
<html><body>
  <ul id="l1">
    <li id="a1">A1</li>
    <li id="a2">A2</li>
    <li id="a3">A3
      <ul id="inner">
        <li id="n1">N1</li>
      </ul>
    </li>
  </ul>
  <ul id="l2">
    <li id="b1">B1</li>
    <li id="b2">B2</li>
  </ul>
</body></html>
"""

TABLES_HTML = """
<html><body>
  <table id="t1">
    <tr><th>H1</th><th>H2</th></tr>
    <tr><td>D1</td><td>D2</td></tr>
    <tr><td colspan="2">
      <table id="nested">
        <tr><th>NH</th></tr>
        <tr><td>ND</td></tr>
      </table>
    </td></tr>
  </table>
</body></html>
"""

FORMS_HTML = """
<html><body>
  <form id="f1">
    <input type="radio" name="choice" value="a" id="f1a">
    <label for="f1a">A</label>
    <input type="radio" name="choice" value="b" id="f1b">
    <label for="f1b">B</label>
  </form>
  <form id="f2">
    <input type="radio" name="choice" value="c" id="f2c">
    <label for="f2c">C</label>
    <input type="radio" name="choice" value="d" id="f2d">
    <label for="f2d">D</label>
  </form>
</body></html>
"""


def web_for(html: str) -> Web:
    return Web(FakeWebDriver(html), timeout=1)


def test_action_uses_one_stable_scope_and_relocates_when_replaced():
    driver = FakeWebDriver(BUTTON_HTML)
    factory = ElementsFactory(driver, timeout=1)
    button = factory.get('//button[@id="btn"]')

    # resolves and caches the source element
    assert button.tag == 'button'
    driver.replace_node('//button[@id="btn"]', '<button id="btn">OK</button>')

    button.click()

    current = driver.node('//button[@id="btn"]')
    # the whole action (scroll, move, click) landed on one single node,
    # explicitly relocated after the original one was replaced
    assert driver.action_log == [
        ('scroll', current),
        ('move', current),
        ('click', current),
    ]


def test_action_retries_when_node_is_replaced_in_the_middle():
    driver = FakeWebDriver(BUTTON_HTML)
    factory = ElementsFactory(driver, timeout=1)
    button = factory.get('//button[@id="btn"]')

    def replace_after_scroll(action, node):
        if action == 'scroll':
            driver.action_hook = None
            driver.replace_node(
                '//button[@id="btn"]', '<button id="btn">OK</button>'
            )

    driver.action_hook = replace_after_scroll
    button.click()

    current = driver.node('//button[@id="btn"]')
    # first attempt broke after scroll; the retried action ran fully
    # against the relocated node
    assert driver.action_log[-3:] == [
        ('scroll', current),
        ('move', current),
        ('click', current),
    ]
    assert all(node is current for _, node in driver.action_log[-3:])


def test_relocate_failure_raises_with_xpath_and_phase():
    class DetachedDriver(FakeWebDriver):
        def find_elements(self, by, value):
            self.find_count += 1
            detached = FakeWebDriver(BUTTON_HTML).node('//button')
            return [FakeWebElement(self, detached)]

    driver = DetachedDriver(BUTTON_HTML)
    button = ButtonElement('//button[@id="btn"]', driver)

    with pytest.raises(StaleElementException) as exc_info:
        button.click()

    error = exc_info.value
    assert error.xpath == '//button[@id="btn"]'
    assert error.phase == 'click'
    assert error.attempts == 3
    assert '//button[@id="btn"]' in str(error)
    assert 'click' in str(error)


def test_ensure_element_raises_instead_of_returning_none():
    class AlwaysStaleDriver(FakeWebDriver):
        def find_element(self, by, value):
            raise StaleElementReferenceException('always stale')

        def find_elements(self, by, value):
            raise StaleElementReferenceException('always stale')

    factory = ElementsFactory(AlwaysStaleDriver(BUTTON_HTML), timeout=1)

    with pytest.raises(StaleElementException) as exc_info:
        factory.get('//button[@id="btn"]')
    assert exc_info.value.xpath == '//button[@id="btn"]'
    assert exc_info.value.phase == 'get'
    assert exc_info.value.attempts == 3

    with pytest.raises(StaleElementException) as exc_info:
        factory.get_many('//button')
    assert exc_info.value.phase == 'get_many'

    with pytest.raises(StaleElementException) as exc_info:
        factory.get_when_available('//button')
    assert exc_info.value.phase == 'get_when_available'


def test_isomorphic_lists_do_not_leak_items_into_each_other():
    web = web_for(LISTS_HTML)

    first = web.list('//ul[@id="l1"]')
    second = web.list('//ul[@id="l2"]')
    inner = web.list('//ul[@id="inner"]')

    assert first.items_ids == ['a1', 'a2', 'a3']
    assert first.items_labels == ['A1', 'A2', 'A3 N1']
    assert second.items_ids == ['b1', 'b2']
    assert inner.items_ids == ['n1']

    assert 'B1' not in first
    assert 'b1' not in first.items_ids
    assert 'n1' not in first.items_ids


def test_list_click_in_item_stays_inside_own_container():
    driver = FakeWebDriver(LISTS_HTML)
    web = Web(driver, timeout=1)

    web.list('//ul[@id="l2"]').click_in_item(id='b2')

    assert driver.action_log == [('click', driver.node('//li[@id="b2"]'))]


def test_nested_tables_only_read_their_own_container():
    web = web_for(TABLES_HTML)

    table = web.table('//table[@id="t1"]')
    assert table.headers == ['H1', 'H2']
    assert table.rows == [['D1', 'D2'], ['NH ND']]
    assert 'ND' not in table
    assert table.column_values(name='H1') == ['D1', 'NH ND']

    nested = web.table('//table[@id="nested"]')
    assert nested.headers == ['NH']
    assert nested.rows == [['ND']]
    assert 'ND' in nested


def test_radio_groups_are_scoped_to_their_own_form():
    web = web_for(FORMS_HTML)

    first = web.radio_input('//form[@id="f1"]/input[1]')
    second = web.radio_input('//form[@id="f2"]/input[1]')

    assert first.options_values == ['a', 'b']
    assert first.options == {'a': 'A', 'b': 'B'}
    assert second.options_values == ['c', 'd']
    assert 'c' not in first


def test_form_submit_targets_its_own_container():
    driver = FakeWebDriver(FORMS_HTML)
    web = Web(driver, timeout=1)

    web.form('//form[@id="f1"]').submit()

    assert driver.action_log == [('submit', driver.node('//form[@id="f1"]'))]
