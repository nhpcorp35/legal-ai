"""Case-00 internal drafts reserve foundational pleading coverage."""

from scripts import run_case00_internal_draft as draft


def _page(filename, page_number, text):
    return {
        "source_filename": filename,
        "page_number": page_number,
        "text": text,
    }


def test_foundational_question_reserves_each_pleading_before_exhibits():
    pages = [
        _page("SUMMONS_AND_COMPLAINT_1.pdf", 1, "SUPREME COURT Plaintiff v Defendant"),
        _page("SUMMONS_AND_COMPLAINT_1.pdf", 7, "FIRST CAUSE OF ACTION and WHEREFORE relief"),
        _page("ANSWER_WITH_COUNTERCLAIMS_18.pdf", 1, "ANSWER of defendant"),
        _page("ANSWER_WITH_COUNTERCLAIMS_18.pdf", 5, "AFFIRMATIVE DEFENSES and COUNTERCLAIM"),
        _page("THIRD_PARTY_COMPLAINT_27.pdf", 1, "THIRD-PARTY COMPLAINT"),
        _page("THIRD_PARTY_COMPLAINT_27.pdf", 4, "CAUSE OF ACTION and WHEREFORE relief"),
    ]
    pages.extend(
        _page(
            f"EXHIBIT_{index}.pdf",
            1,
            "litigation claims defenses relief " * 20,
        )
        for index in range(60)
    )

    selected = draft.select_evidence_pages(
        pages,
        "Map the litigation parties, claims, defenses, counterclaims, third-party claims, and requested relief.",
    )
    identities = {(item["filename"], item["page_number"]) for item in selected}

    assert ("SUMMONS_AND_COMPLAINT_1.pdf", 1) in identities
    assert ("SUMMONS_AND_COMPLAINT_1.pdf", 7) in identities
    assert ("ANSWER_WITH_COUNTERCLAIMS_18.pdf", 1) in identities
    assert ("ANSWER_WITH_COUNTERCLAIMS_18.pdf", 5) in identities
    assert ("THIRD_PARTY_COMPLAINT_27.pdf", 1) in identities
    assert ("THIRD_PARTY_COMPLAINT_27.pdf", 4) in identities
    assert len(selected) <= draft.MAX_PAGES


def test_foundational_question_reserves_unmarked_closing_relief_page():
    pages = [
        _page("ANSWER_18.pdf", 1, "ANSWER of Farrington Realty LLC"),
        _page("ANSWER_18.pdf", 2, "denies the allegations"),
        _page("ANSWER_18.pdf", 3, "affirmative defenses"),
        _page("ANSWER_18.pdf", 4, "further answering the complaint"),
        _page("ANSWER_18.pdf", 5, "costs disbursements and such other relief"),
    ]
    pages.extend(
        _page(f"EXHIBIT_{index}.pdf", 1, "litigation claims defenses relief " * 20)
        for index in range(60)
    )

    selected = draft.select_evidence_pages(
        pages,
        "Map the litigation parties, claims, defenses, and requested relief.",
    )

    assert ("ANSWER_18.pdf", 5) in {
        (item["filename"], item["page_number"]) for item in selected
    }


def test_case00_composite_schema_allows_map_plus_five_ranked_findings():
    schema = draft.composite_schema(
        {"filename": {"type": "string"}, "page_number": {"type": "integer"}},
    )

    assert schema["properties"]["findings"]["minItems"] == 8
    assert schema["properties"]["findings"]["maxItems"] == 8
    assert schema["properties"]["findings"]["items"]["properties"]["section"]["enum"] == list(draft.COMPOSITE_SECTIONS)


def _composite_result():
    findings=[]
    for section in draft.COMPOSITE_SECTIONS:
        findings.append({
            "section":section,
            "statement":f"{section} — Complete finding.",
            "citations":[{"filename":"ANSWER_18.pdf","page_number":1}],
            "authority_citations":[],
        })
    return {"summary":"Complete overview.","findings":findings,"missing_information":[],"limitations":[]}


def test_composite_validation_rejects_missing_or_truncated_sections():
    pages=[{"filename":"ANSWER_18.pdf","page_number":1,"text":"answer"}]
    result=_composite_result()
    assert draft.validate(result,pages,(),composite=True) == result

    result=_composite_result()
    result["findings"].pop()
    try:
        draft.validate(result,pages,(),composite=True)
    except ValueError as exc:
        assert str(exc) == "incomplete composite output"
    else:
        raise AssertionError("missing section was accepted")

    result=_composite_result()
    result["findings"][3]["statement"]="Rank 1 — truncated"
    try:
        draft.validate(result,pages,(),composite=True)
    except ValueError as exc:
        assert str(exc) == "truncated composite output"
    else:
        raise AssertionError("truncated finding was accepted")


def test_composite_validation_rejects_bounded_pages_as_missing():
    pages=[{"filename":"ANSWER_18.pdf","page_number":1,"text":"answer"}]
    result=_composite_result()
    result["missing_information"]=["Complaint pages 2–18 were not supplied."]

    try:
        draft.validate(result,pages,(),composite=True)
    except ValueError as exc:
        assert str(exc) == "bounded retrieval mislabeled as missing evidence"
    else:
        raise AssertionError("bounded page omission was accepted as missing evidence")
