def test_choose_how_long_read_articles_are_kept(reader):
    reader.js("location.hash = '#/settings'")
    select = "document.querySelector('[data-settings-field=read-retention]')"
    assert reader.wait_for(f"{select}?.value === '30'")
    reader.js(f"(() => {{ const s = {select}; s.value = '7'; s.dispatchEvent(new Event('change', {{ bubbles: true }})); }})()")
    assert reader.wait_for("reader.api('GET', '/api/me').then((me) => me.read_retention_days === 7)")

    reader.js("location.hash = '#/all'")
    reader.js("location.hash = '#/settings'")
    assert reader.wait_for(f"{select}?.value === '7'")
