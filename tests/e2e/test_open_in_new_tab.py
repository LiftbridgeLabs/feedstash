def test_titles_are_real_links_so_modifier_and_middle_clicks_open_a_tab(reader):
    first = "document.querySelector('#articles .item')"
    assert reader.js(f"{first}.querySelector('.item-link').href").startswith("http")
    assert reader.js(f"{first}.querySelector('.item-link').target") == "_blank"

    # Ctrl-click: the browser opens the link itself; the app only marks the article read and doesn't open it inline.
    reader.js(f"{first}.querySelector('.item-link').dispatchEvent(new MouseEvent('click', {{ bubbles: true, cancelable: true, ctrlKey: true }}))")
    assert reader.wait_for(f"{first}.classList.contains('read') && !{first}.classList.contains('open')")

    # Middle-click (an auxclick with button 1) marks the second article read the same way.
    second = "document.querySelectorAll('#articles .item')[1]"
    reader.js(f"{second}.querySelector('.item-link').dispatchEvent(new MouseEvent('auxclick', {{ bubbles: true, button: 1 }}))")
    assert reader.wait_for(f"{second}.classList.contains('read') && !{second}.classList.contains('open')")

    # A plain click still opens the article in place instead of leaving the page.
    third = "document.querySelectorAll('#articles .item')[2]"
    reader.js(f"{third}.querySelector('.item-link').click()")
    assert reader.wait_for(f"{third}.classList.contains('open')")
    assert reader.js("location.pathname") == "/"
