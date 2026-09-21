# tests/e2e/test_row_expansion.py
"""
Detail and History row expansion.

SPA revision:
  - Tests wait for CONTENT VISIBILITY, not for a specific AJAX endpoint.
  - In the SSR build, expansion triggered GET /get_detail_row.
    In the SPA build, content may be rendered client-side from the store.
    Either way the user sees the form / history table.
"""
from playwright.sync_api import expect
from conftest import expand_detail, expand_history


class TestDetailRow:

    def test_expand_and_collapse(self, page):
        toggle = page.locator("tr[data-paper-id='p1'] .toggle-btn:not(.history-btn)")
        assert "Show" in toggle.text_content()

        toggle.click()
        page.wait_for_timeout(1000)

        # Detail row should now be expanded
        detail = page.locator("tr[data-paper-id='p1'] + tr.detail-row")
        assert detail.evaluate("el => el.classList.contains('expanded')"), \
            "Detail row should have 'expanded' class after opening"

        # Button text changes to Hide
        assert "Hide" in toggle.text_content()

        # Collapse
        toggle.click()
        page.wait_for_timeout(300)
        assert not detail.evaluate("el => el.classList.contains('expanded')")

    def test_detail_loads_form_fields(self, page):
        toggle = page.locator("tr[data-paper-id='p1'] .toggle-btn:not(.history-btn)")
        toggle.click()
        page.wait_for_timeout(1000)
        # Should contain the detail form with editable fields
        form = page.locator("tr.detail-row.expanded form")
        assert form.count() == 1

    def test_detail_and_history_mutually_exclusive(self, page):
        detail_btn = page.locator("tr[data-paper-id='p2'] .toggle-btn:not(.history-btn)")
        detail_btn.click()
        page.wait_for_timeout(800)

        hist_btn = page.locator("tr[data-paper-id='p2'] .history-btn")
        hist_btn.click()
        page.wait_for_timeout(800)

        detail_expanded = page.evaluate("""() => {
            const main = document.querySelector("tr[data-paper-id='p2']");
            const detail = main.nextElementSibling;
            return detail ? detail.classList.contains('expanded') : false;
        }""")
        assert not detail_expanded, "Detail should close when History opens"


class TestHistoryRow:

    def test_history_opens_and_closes(self, page):
        toggle = page.locator("tr[data-paper-id='p2'] .history-btn")
        toggle.scroll_into_view_if_needed()
        toggle.click()
        page.wait_for_timeout(1000)

        expanded = page.evaluate("""() => {
            const m = document.querySelector("tr[data-paper-id='p2']");
            const d = m ? m.nextElementSibling : null;
            const h = d ? d.nextElementSibling : null;
            return h ? h.classList.contains('expanded') : false;
        }""")
        assert expanded


class TestHistoryTabs:

    def test_tab_switching(self, page):
        expand_history(page, "p2")
        tabs = page.locator(".history-tab-btn[data-paper-id='p2']")
        assert tabs.count() == 4

        tabs.nth(1).scroll_into_view_if_needed()
        tabs.nth(1).click(force=True)
        page.wait_for_timeout(300)

        active = page.locator(".history-tab-panel.active[data-paper-id='p2']")
        assert active.get_attribute("data-tab-panel") == "set1"