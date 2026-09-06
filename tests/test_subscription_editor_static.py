"""Static checks for the saved-subscription editor and original visual theme."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_saved_subscription_filters_are_editable_in_place():
    index = read("docs/index.html")
    app = read("docs/app.js")
    styles = read("docs/styles.css")

    assert 'id="modal-edit-sub"' in index
    assert "openSubscriptionEditor" in app
    assert "Edit filters" in app
    assert ".from('subscriptions').update(fields).eq('id', subscription.id)" in app
    assert ".edit-filter-choice" in styles


def test_original_ui_uses_flat_colors_instead_of_gradients():
    styles = read("docs/styles.css")

    assert "linear-gradient" not in styles
