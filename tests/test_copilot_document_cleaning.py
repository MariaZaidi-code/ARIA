from copilot.pipeline import _clean_document_passage


def test_docx_section_text_table_is_readable_without_losing_content():
    passage = (
        "Key information\n"
        "| Section | Text |\n"
        "| --- | --- |\n"
        "| Revenue | Revenue rose by 12% |\n"
    )

    cleaned = _clean_document_passage(passage)

    assert cleaned == "Key information Section: Revenue; Text: Revenue rose by 12%"
    assert "|" not in cleaned


def test_non_table_document_passage_is_only_whitespace_normalized():
    passage = "A document passage\n\nwith useful context."

    assert _clean_document_passage(passage) == "A document passage with useful context."
