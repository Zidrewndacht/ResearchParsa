# tests/e2e/test_sort_matrix.py
# CHANGED: removed INITIAL_DOM_ORDER import; initial-order test asserts set only.

import pytest
from conftest import EXPECTED_ASC, visible_ids

SORT_COLUMNS = list(EXPECTED_ASC.keys())


@pytest.mark.parametrize("sort_key", SORT_COLUMNS)
def test_sort_desc_then_asc(page, target, sort_key):
    header = page.locator(f"th[data-sort='{sort_key}']")
    header.click()
    page.wait_for_timeout(600)
    desc_got = visible_ids(page)
    header.click()
    page.wait_for_timeout(600)
    asc_got = visible_ids(page)
    expected_asc = EXPECTED_ASC[sort_key]
    # REMOVED: the export pdf-link special case.
    # Unified weights make live and export identical.
    assert asc_got == expected_asc, \
        f"{sort_key} ASC: got {asc_got}, want {expected_asc}"
    assert desc_got == list(reversed(asc_got)), \
        f"{sort_key} DESC: got {desc_got}, want {list(reversed(asc_got))}"
    indicator = header.locator(".sort-indicator").text_content()
    assert indicator == "▲", f"ASC should show ▲, got '{indicator}'"

def test_sort_state_persisted_in_url_and_restored(page, target):
    page.locator("th[data-sort='year']").click()
    page.wait_for_timeout(600)
    assert "sort_by=year" in page.url
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(900)
    
    # Verify it restored the DESC state
    page.locator("th[data-sort='year']").click() # Click to ASC
    page.wait_for_timeout(600)
    assert visible_ids(page) == EXPECTED_ASC["year"]

def test_detail_and_history_rows_follow_main_row(page, target):
    toggle = page.locator("tr[data-paper-id='p1'] .toggle-btn:not(.history-btn)")
    toggle.click()
    page.wait_for_timeout(900)
    page.locator("th[data-sort='year']").click()
    page.wait_for_timeout(600)
    is_followed = page.evaluate("""() => {
        const main = document.querySelector("tr[data-paper-id='p1']");
        const next = main ? main.nextElementSibling : null;
        return !!(next && next.classList.contains('detail-row'));
    }""")
    assert is_followed, "Detail row detached from main row after sort"

def test_alternating_shading_reapplied_after_sort(page, target):
    page.locator("th[data-sort='year']").click()
    page.wait_for_timeout(600)
    shades = page.eval_on_selector_all(
        "tr[data-paper-id]:not(.filter-hidden)",
        """rows => rows.map(r =>
            r.classList.contains('alt-shade-1') ? '1' :
            r.classList.contains('alt-shade-2') ? '2' : 'none')"""
    )
    assert any(s in ("1", "2") for s in shades)
    assert shades.count("none") == 0

def test_duplicate_journal_shading(page, target):
    """p1 and p6 share 'IEEE Trans' -> both journal cells get shaded."""
    # Ensure the rows are rendered (virtual scroll may delay them)
    page.wait_for_selector("tr[data-paper-id='p1']", timeout=10000)
    page.wait_for_selector("tr[data-paper-id='p6']", timeout=10000)
    page.wait_for_function("""() => {
        const p1 = document.querySelector("tr[data-paper-id='p1']");
        return p1 && p1.cells[4] && p1.cells[4].style.backgroundColor !== '';
    }""", timeout=10000)
    shaded = page.eval_on_selector_all(
        "tr[data-paper-id]:not(.filter-hidden)",
        """rows => rows.filter(r => {
            const c = r.cells[4];
            return c && c.style.backgroundColor !== '';
        }).map(r => r.getAttribute('data-paper-id'))"""
    )
    assert set(shaded) == {"p1", "p6"}