# tests/e2e/test_detail_persistence.py
"""
Detail-row editing: save, persist across reload, Ctrl+S, paywall trigger,
verification reset.

SPA revision:
  - No more td.hidden-data-cell assertions.
  - Persistence is verified by re-opening the detail form after reload
    and reading the input/textarea values, plus checking the visible
    "Commented" column icon.
"""
from playwright.sync_api import expect
from conftest import expand_detail


class TestFormSaveCorners:

    def test_numeric_fields_and_paywall_trigger(self, page):
        page.locator("#hide-offtopic-checkbox").uncheck(force=True)
        page.wait_for_timeout(500)

        form = expand_detail(page, "p3")
        form.locator("input[name='page_count']").fill("42")
        form.locator("input[name='relevance']").fill("8.5")
        form.locator("textarea[name='user_trace']").fill("This article is paywalled")

        with page.expect_response(
            lambda r: "/update_paper" in r.url and r.status == 200
        ) as resp_info:
            form.locator(".save-btn").click()
        assert resp_info.value.json()["status"] == "success"
        page.wait_for_timeout(500)

        page.reload(wait_until="networkidle")
        page.wait_for_timeout(600)
        page.locator("#hide-offtopic-checkbox").uncheck(force=True)
        page.wait_for_timeout(500)

        p3 = page.locator("tr[data-paper-id='p3']")
        expect(p3).to_be_visible()

        # Numeric fields visible in the main table
        expect(p3.locator("[data-field='page_count']")).to_have_text("42")
        expect(p3.locator("[data-field='relevance']")).to_have_text("8.5")

        # Paywall state machine → 💰 in the PDF column
        expect(p3.locator("td").first).to_have_text("💰")

        # Verify through the detail form (replaces hidden-data-cell check)
        form = expand_detail(page, "p3")
        assert form.locator("textarea[name='user_trace']").input_value() == "This article is paywalled"


class TestCellClickCorners:

    def test_cycle_yaml_none_and_inclusion_fields(self, page):
        """Clicking inferred cells writes dot-notation paths to the server."""
        # technique.method_x (group filter_type='none')
        none_cell = page.locator(
            "tr[data-paper-id='p1'] [data-field='technique.method_x'] .emoji-content"
        )
        none_cell.scroll_into_view_if_needed()
        assert none_cell.text_content().strip() == "✔️"
        none_cell.click()
        page.wait_for_timeout(800)
        assert none_cell.text_content().strip() == "❌"

        # features.feat_a (group filter_type='inclusion')
        incl_cell = page.locator(
            "tr[data-paper-id='p1'] [data-field='features.feat_a'] .emoji-content"
        )
        assert incl_cell.text_content().strip() == "✔️"
        incl_cell.click()
        page.wait_for_timeout(800)
        assert incl_cell.text_content().strip() == "❌"

        # Reload → both persisted
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(600)
        p1 = page.locator("tr[data-paper-id='p1']")
        expect(p1.locator("[data-field='technique.method_x'] .emoji-content")).to_have_text("❌")
        expect(p1.locator("[data-field='features.feat_a'] .emoji-content")).to_have_text("❌")


class TestVerificationResetLogic:

    def test_inferred_edit_resets_verification(self, page):
        """Editing an inferred field resets LLM verification."""
        form = expand_detail(page, "p1")
        form.locator("input[name='test_text']").fill("Changed inferred data")

        with page.expect_response(
            lambda r: "/update_paper" in r.url and r.status == 200
        ):
            form.locator(".save-btn").click()
        page.wait_for_timeout(500)

        page.reload(wait_until="networkidle")
        page.wait_for_timeout(600)
        p1 = page.locator("tr[data-paper-id='p1']")
        expect(p1.locator("[data-field='verified'] .emoji-content")).to_have_text("❔")
        expect(p1.locator("[data-field='verified_by']")).to_contain_text("❔")


class TestDetailPersistence:

    def test_save_and_persist_after_reload(self, page):
        """Edits survive a full page reload.  Verified through the detail
        form and visible UI state, not hidden DOM cells."""
        unique_comment = "E2E Persistence Test Comment 99"
        unique_text    = "E2E Test Text Value 42"

        form = expand_detail(page, "p1")
        form.locator("textarea[name='user_trace']").fill(unique_comment)
        form.locator("input[name='test_text']").fill(unique_text)

        with page.expect_response(
            lambda r: "/update_paper" in r.url and r.status == 200
        ) as resp_info:
            form.locator(".save-btn").click()
        assert resp_info.value.json()["status"] == "success"
        page.wait_for_timeout(500)

        # ── reload ──
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(600)

        p1 = page.locator("tr[data-paper-id='p1']")

        # 1. "Commented" column shows ✔️  (user-visible derived state)
        expect(p1.locator("[data-field='user_comment_state']")).to_contain_text("✔️")

        # 2. Re-open the detail form and verify field values
        form = expand_detail(page, "p1")
        assert form.locator("textarea[name='user_trace']").input_value() == unique_comment
        assert form.locator("input[name='test_text']").input_value() == unique_text

    def test_ctrl_s_shortcut_saves(self, page):
        form = expand_detail(page, "p4")
        ta = form.locator("textarea[name='user_trace']")
        ta.fill("Ctrl+S save test")

        with page.expect_response(
            lambda r: "/update_paper" in r.url and r.status == 200
        ):
            ta.press("Control+s")

        page.reload(wait_until="networkidle")
        page.wait_for_timeout(600)

        form = expand_detail(page, "p4")
        assert form.locator("textarea[name='user_trace']").input_value() == "Ctrl+S save test"