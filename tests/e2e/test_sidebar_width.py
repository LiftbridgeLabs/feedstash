SIDEBAR_WIDTH = "document.querySelector('.sidebar').getBoundingClientRect().width"


def test_the_sidebar_edge_drags_narrower_and_the_width_sticks(reader):
    assert reader.js(SIDEBAR_WIDTH) == 272
    reader.js("""(() => {
      const h = document.getElementById('sidebar-resize');
      const at = (type, x) => h.dispatchEvent(new PointerEvent(type, { bubbles: true, button: 0, pointerId: 1, clientX: x }));
      at('pointerdown', 272); at('pointermove', 230); at('pointerup', 230);
    })()""")
    assert reader.js(SIDEBAR_WIDTH) == 230

    reader.js("location.reload()")
    assert reader.wait_for("!!window.reader && document.querySelectorAll('.item').length > 0", timeout=20)
    assert reader.js(SIDEBAR_WIDTH) == 230  # remembered

    # It can't go below the minimum, and a double-click puts it back.
    reader.js("""(() => {
      const h = document.getElementById('sidebar-resize');
      const at = (type, x) => h.dispatchEvent(new PointerEvent(type, { bubbles: true, button: 0, pointerId: 2, clientX: x }));
      at('pointerdown', 230); at('pointermove', 40); at('pointerup', 40);
    })()""")
    assert reader.js(SIDEBAR_WIDTH) == 200
    reader.js("document.getElementById('sidebar-resize').dispatchEvent(new MouseEvent('dblclick', { bubbles: true }))")
    assert reader.js(SIDEBAR_WIDTH) == 272
