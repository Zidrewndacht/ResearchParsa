# tests/e2e/test_certainty_rendering.py
"""
Certainty / conflict rendering.

Tests the USER-VISIBLE contract:
  - conflict  → user sees ⚠️, does NOT see a status emoji
  - partial   → user sees a translucent emoji (CSS class present)
  - solid     → user sees a full-opacity emoji, no warning
  - PDF icons → correct emoji per state

Does NOT assert whether the emoji span exists in the DOM but is hidden
vs. absent from the DOM.  That is a rendering-mechanism detail that
changed with the SSR→SPA migration.
"""
from playwright.sync_api import expect


class TestCertaintyRendering:

    def test_conflict_shows_warning_and_hides_status(self, page):
        """p2 is_test_bool has certainty='conflict'.
        The user must see ⚠️ and must NOT see ✔️ / ❌ / ❔."""
        cell = page.locator("tr[data-paper-id='p2'] [data-field='is_test_bool']")

        # ⚠️ is present and visible
        warning = cell.locator(".conflict-warning")
        expect(warning).to_be_visible()
        assert warning.text_content().strip() == "⚠️"

        # The status emoji must NOT be visible to the user.
        # It may be absent from the DOM (Jinja) or present but hidden (JS).
        emoji = cell.locator(".emoji-content")
        if emoji.count() > 0:
            expect(emoji).not_to_be_visible()
        # If count == 0 the span simply doesn't exist – also correct.

    def test_partial_certainty_has_class(self, page):
        """p5 is_test_bool has certainty='80' → translucent emoji."""
        cell = page.locator("tr[data-paper-id='p5'] [data-field='is_test_bool']")
        assert cell.evaluate("el => el.classList.contains('certainty-80')")
        # The emoji itself must be visible
        expect(cell.locator(".emoji-content")).to_be_visible()

    def test_solid_certainty_no_warning(self, page):
        """p1 is_offtopic is solid → plain emoji, no ⚠️."""
        cell = page.locator("tr[data-paper-id='p1'] [data-field='is_offtopic']")
        assert cell.locator(".conflict-warning").count() == 0
        emoji = cell.locator(".emoji-content")
        expect(emoji).to_be_visible()
        assert emoji.text_content().strip() == "❌"

    def test_pdf_state_icons(self, page):
        """PDF column shows the correct icon per state."""
        # p1: PDF present → 📕
        p1_pdf = page.locator("tr[data-paper-id='p1'] td.pdf-status")
        expect(p1_pdf).to_contain_text("📕")

        # p4: paywalled → 💰
        p4_pdf = page.locator("tr[data-paper-id='p4'] td.pdf-status")
        expect(p4_pdf).to_contain_text("💰")

        # p5: annotated → 📗
        p5_pdf = page.locator("tr[data-paper-id='p5'] td.pdf-status")
        expect(p5_pdf).to_contain_text("📗")

        # p2, p6: none → ❔
        for pid in ("p2", "p6"):
            cell = page.locator(f"tr[data-paper-id='{pid}'] td.pdf-status")
            expect(cell).to_contain_text("❔")