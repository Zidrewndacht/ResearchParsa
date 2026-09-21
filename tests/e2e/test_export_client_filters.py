# tests/e2e/test_export_client_filters.py
"""
Client-side filters in the static HTML export.

SPA revision:
  - TestServerVsExportStructuralDifference is DELETED.  It tested an
    SSR-only implementation accident: the live server used to REMOVE
    rows from the DOM while the export HID them.  In the SPA both paths
    are client-side; the user sees the same result either way.
  - The export-only tests are kept because the export embeds ALL data
    and filters purely client-side.  This is still true and worth testing.
"""
from conftest import goto_export, visible_ids


class TestExportClientYearFilter:

    def test_year_from_narrows(self, page, app_server):
        goto_export(page, app_server, hide_offtopic=0)
        assert len(visible_ids(page)) == 6

        page.fill("#year-from", "2023")
        page.wait_for_timeout(700)
        assert set(visible_ids(page)) == {"p1", "p2", "p5"}

    def test_year_range_both_bounds(self, page, app_server):
        goto_export(page, app_server, hide_offtopic=0)
        page.fill("#year-from", "2021")
        page.fill("#year-to", "2023")
        page.wait_for_timeout(700)
        assert set(visible_ids(page)) == {"p2", "p3", "p4"}

    def test_clearing_year_inputs_restores_all(self, page, app_server):
        goto_export(page, app_server, hide_offtopic=0)
        page.fill("#year-from", "2025")
        page.wait_for_timeout(600)
        assert visible_ids(page) == ["p5"]

        page.fill("#year-from", "")
        page.wait_for_timeout(600)
        assert len(visible_ids(page)) == 6


class TestExportClientMinPageCount:

    def test_min_page_count_filters(self, page, app_server):
        goto_export(page, app_server, hide_offtopic=0)
        page.fill("#min-page-count", "9")
        page.wait_for_timeout(700)
        assert set(visible_ids(page)) == {"p1", "p4", "p6"}

    def test_min_page_count_zero_disables(self, page, app_server):
        goto_export(page, app_server, hide_offtopic=0)
        page.fill("#min-page-count", "9")
        page.wait_for_timeout(500)
        page.fill("#min-page-count", "0")
        page.wait_for_timeout(600)
        assert len(visible_ids(page)) == 6


class TestExportClientHideOfftopic:

    def test_checkbox_hides_and_restores_offtopic(self, page, app_server):
        goto_export(page, app_server, hide_offtopic=0)
        assert "p3" in visible_ids(page)

        page.locator("#hide-offtopic-checkbox").check(force=True)
        page.wait_for_timeout(600)
        assert "p3" not in visible_ids(page)

        page.locator("#hide-offtopic-checkbox").uncheck(force=True)
        page.wait_for_timeout(600)
        assert "p3" in visible_ids(page)

    def test_exported_with_hide_offtopic_1_starts_checked_disabled(self, page, app_server):
        goto_export(page, app_server, hide_offtopic=1)
        cb = page.locator("#hide-offtopic-checkbox")
        assert cb.is_checked()
        assert cb.is_disabled()
        assert "p3" not in visible_ids(page)


class TestExportCombinedClientFilters:

    def test_year_minpages_and_offtopic_together(self, page, app_server):
        goto_export(page, app_server, hide_offtopic=0)
        page.fill("#year-from", "2021")
        page.fill("#min-page-count", "9")
        page.locator("#hide-offtopic-checkbox").check(force=True)
        page.wait_for_timeout(800)
        assert set(visible_ids(page)) == {"p1", "p4"}


class TestLiveServerFilters:
    """Server-side filters in the live SPA still work via /api/papers.
    We test the USER-VISIBLE result, not the endpoint or DOM mechanics."""

    def test_year_filter_shows_only_matching(self, page, app_server):
        from conftest import goto_live
        goto_live(page, app_server)

        page.fill("#year-from", "2023")
        page.evaluate("""() => {
            const b = document.getElementById('apply-serverside-filters');
            if (b) { b.style.opacity='1'; b.style.pointerEvents='auto'; }
        }""")
        page.click("#apply-serverside-filters")
        page.wait_for_timeout(1000)

        assert set(visible_ids(page)) == {"p1", "p2", "p5"}

    def test_enter_key_applies_filter(self, page, app_server):
        from conftest import goto_live
        goto_live(page, app_server)

        page.fill("#year-to", "2024")
        page.locator("#year-to").press("Enter")
        page.wait_for_timeout(1000)

        ids = set(visible_ids(page))
        assert "p5" not in ids  # p5 is 2025

    def test_hide_offtopic_checkbox_server_side(self, page, app_server):
        from conftest import goto_live
        goto_live(page, app_server)
        assert "p3" not in visible_ids(page)

        page.locator("#hide-offtopic-checkbox").uncheck()
        page.wait_for_timeout(1000)
        assert "p3" in visible_ids(page)