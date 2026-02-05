from utils.naming import make_base_id


def test_make_base_id_is_stable():
    filename = "01 ITQ Office Equipment (MOF).pdf"
    first = make_base_id(filename)
    second = make_base_id(filename)
    assert first == second
    assert "__" in first


def test_make_base_id_normalizes_special_chars():
    value = make_base_id("### strange $$ procurement ::: file!!.docx")
    assert value.startswith("strange_procurement_file")
