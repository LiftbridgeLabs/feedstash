def test_connecting_a_mailbox_offers_providers_and_fills_in_the_server(reader):
    page = reader
    page.js("location.hash = '#/settings'")
    assert page.wait_for("!!document.querySelector('[data-mail-form]')", timeout=10)
    assert page.js("document.querySelector('[data-mail-form] input[name=host]').value") == "imap.gmail.com"

    page.js("""(() => {
      const select = document.querySelector('[data-mail-form] select[name=provider]');
      select.value = 'icloud';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    })()""")
    assert page.wait_for("document.querySelector('[data-mail-form] input[name=host]').value === 'imap.mail.me.com'")
    assert "app-specific password" in page.js("document.querySelector('[data-provider-hint]').textContent")

    # "Something else" leaves the server blank and opens the details, since there's nothing to prefill.
    page.js("""(() => {
      const select = document.querySelector('[data-mail-form] select[name=provider]');
      select.value = 'other';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    })()""")
    assert page.wait_for("document.querySelector('[data-mail-form] details').open === true")
