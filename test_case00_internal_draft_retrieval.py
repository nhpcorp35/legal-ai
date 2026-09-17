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
