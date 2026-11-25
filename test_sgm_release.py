from check_sgm_release import find_latest_release, parse_label

HTML = '''
<a href="/sites/default/files/2024-10/202409_Core%20Static%20Grid%20Mode_6th%20release.zip">6</a>
<a href="/sites/default/files/2025-10/outdated_202503_Core%20Static%20Grid%20Model_7th%20release.zip">7</a>
<a href="/sites/default/files/2025-10/202509_Core%20Static%20Grid%20Model_8th%20release.zip">8</a>
<a href="/sites/default/files/2026-06/202603_Core%20Static%20Grid%20Model_9th%20release.zip">9</a>
<a href="/sites/default/files/x/outdated_Core%20Static%20Grid%20Model%20%E2%80%93%2012th%20release.zip">alt</a>
'''


def test_latest_release_ignores_outdated_and_picks_highest_number():
    r = find_latest_release(HTML)
    assert r["release"] == 9 and r["ym"] == "202603"
    assert r["url"].startswith("https://www.jao.eu/sites/default/files/2026-06/")
    assert r["label"] == "202603, release 9"


def test_markdown_style_links_also_work():
    md = "[x](https://www.jao.eu/sites/default/files/2026-06/202603_Core%20Static%20Grid%20Model_9th%20release.zip)"
    assert find_latest_release(md)["release"] == 9


def test_parse_label_and_new_release_logic():
    assert parse_label("202603, release 9") == 9 and parse_label("202603 - 9. Release") == 9
    assert parse_label("") is None
    assert find_latest_release(HTML)["release"] > parse_label("202509, release 8")
