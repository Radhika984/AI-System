from app import precheck as P


def codes(flags):
    return {f.code for f in flags}


def test_r017_already_fixed(qof, reps):
    assert "already_fixed" in codes(P.check_report(reps["R017"], qof("R017")))


def test_already_fixed_not_triggered_without_history(qof, reps):
    assert "already_fixed" not in codes(P.check_report(reps["R022"], qof("R022")))


def test_r015_identical_options(qof):
    assert P.check_question(qof("R015")).has("options_identical")


def test_r025_missing_figure(qof):
    assert P.check_question(qof("R025")).has("figure_missing")


def test_r020_r021_malformed_keys(qof):
    a = P.check_question(qof("R020"))
    b = P.check_question(qof("R021"))
    assert a.has("answer_malformed") and a.normalized_answer == ["A", "B", "D"]
    assert b.has("answer_malformed") and b.normalized_answer == ["B"]


def test_r027_injection(qof, reps):
    assert "injection" in codes(P.check_report(reps["R027"], qof("R027")))


def test_ordinary_comments_not_injection(qof, reps):
    for rid, r in reps.items():
        if rid != "R027":
            assert "injection" not in codes(P.check_report(r, qof(rid))), rid


def test_r041_gibberish(qof, reps):
    assert "gibberish" in codes(P.check_report(reps["R041"], qof("R041")))
    assert "gibberish" not in codes(P.check_report(reps["R040"], qof("R040")))  # "wrong" is vague, not gibberish


def test_missing_and_blank_options(qof):
    assert P.check_question(qof("R009")).has("option_missing")
    c = P.check_question(qof("R011"))
    assert c.has("option_blank") and c.has("key_points_to_blank_option")


def test_raw_latex_and_exam_reference(qof):
    assert P.check_question(qof("R014")).has("raw_latex")
    assert P.check_question(qof("R013")).has("exam_reference")


def test_language_and_app_hints(qof, reps):
    assert "language_request" in codes(P.check_report(reps["R039"], qof("R039")))
    assert "app_behaviour" in codes(P.check_report(reps["R038"], qof("R038")))
    assert "display_hint" in codes(P.check_report(reps["R037"], qof("R037")))


def test_clean_question_has_no_structural_flags(qof):
    c = P.check_question(qof("R029"))
    assert not {"option_missing", "option_blank", "options_identical", "answer_malformed"} & {f.code for f in c.flags}
