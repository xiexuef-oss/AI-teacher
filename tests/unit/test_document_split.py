from tutor_api.services.document_split import split_pages


def page(number, text, **extra):
    return {"number": number, "text": text, "warnings": [], **extra}


def test_numbered_questions_merge_across_pages_and_keep_locations():
    result = split_pages([page(1, "1. 第一题\n题面开头"), page(2, "题面续行\n2、第二题\n条件")])
    assert len(result) == 2
    assert result[0]["text"] == "1. 第一题\n题面开头\n题面续行"
    assert [loc["page"] for loc in result[0]["locations"]] == [1, 2]
    assert result[1]["text"] == "2、第二题\n条件"


def test_answer_section_is_not_appended_to_question_stem():
    result = split_pages([page(1, "1. 第一题\n2. 第二题"), page(2, "参考答案\n1. 4\n2. 8")])
    assert len(result) == 2
    assert all("4" not in item["text"] and "8" not in item["text"] for item in result)
    assert all(any("答案" in warning for warning in item["warnings"]) for item in result)


def test_unique_answer_number_suggests_source_location_without_filling_answer():
    result = split_pages([page(1, "1. 第一题"), page(2, "参考答案\n1. 4")])
    assert any("片段 2" in warning and "题号 1" in warning for warning in result[0]["warnings"])
    assert result[0]["payload"] is None and "4" not in result[0]["text"]


def test_subquestion_parentheses_do_not_split_and_unknown_order_is_warned():
    result = split_pages([page(1, "1. 主问题\n（1）小问\n(2) 小问\n3. 跳号题")])
    assert len(result) == 2 and "（1）" in result[0]["text"]
    assert any("题号" in warning for warning in result[1]["warnings"])


def test_json_payload_is_kept_and_blank_image_gets_manual_candidate():
    payload = {"example": True}
    result = split_pages([page(1, "题目", _payload=payload), page(2, "")])
    assert len(result) == 2 and result[0]["payload"] == payload
    assert result[1]["text"] == ""


def test_oversized_question_is_explicitly_split_for_manual_merge():
    result = split_pages([page(1, "1. " + "字" * 5000)])
    assert len(result) == 2 and max(len(item["text"]) for item in result) <= 4000
    assert all(any("超长" in warning for warning in item["warnings"]) for item in result)


def test_cross_file_continuation_keeps_distinct_same_page_locations():
    result = split_pages(
        [page(1, "1. 题干", _file_id="first"), page(1, "续行条件", _file_id="second")]
    )
    assert len(result) == 1 and result[0]["text"] == "1. 题干\n续行条件"
    assert result[0]["locations"] == [
        {"file_id": "first", "page": 1, "block": 1},
        {"file_id": "second", "page": 1, "block": 1},
    ]
    assert any("跨文件" in w and "人工" in w for w in result[0]["warnings"])


def test_separate_answer_file_suggests_file_page_and_block_without_leaking():
    result = split_pages(
        [
            page(1, "1. 题干", _file_id="question"),
            page(1, "1. secret-answer", _file_id="answer", _answer_file=True),
        ]
    )
    assert len(result) == 1 and "secret-answer" not in result[0]["text"]
    assert result[0]["payload"] is None
    assert any("answer" in w and "片段 1" in w and "行 1" in w for w in result[0]["warnings"])


def test_duplicate_question_numbers_suppress_even_unique_answer_suggestion():
    result = split_pages(
        [
            page(1, "1. 甲", _file_id="a"),
            page(1, "1. 乙", _file_id="b"),
            page(1, "参考答案\n1. secret", _file_id="c"),
        ]
    )
    assert len(result) == 2
    assert all(any("重复题号" in w for w in c["warnings"]) for c in result)
    assert all(not any("配对建议：" in w for w in c["warnings"]) for c in result)


def test_duplicate_answer_numbers_show_locations_without_guessing():
    result = split_pages(
        [
            page(1, "1. 题干", _file_id="question"),
            page(2, "1. secret-one", _file_id="answer", _answer_file=True),
            page(4, "续文\n1. secret-two", _file_id="answer", _answer_file=True),
        ]
    )
    assert len(result) == 1 and result[0]["text"] == "1. 题干"
    warning = next(w for w in result[0]["warnings"] if "答案区存在重复题号" in w)
    assert "answer 页/片段 2 行 1" in warning and "answer 页/片段 4 行 2" in warning
    assert "secret" not in warning and result[0]["payload"] is None


def test_unknown_file_order_does_not_merge_or_pair():
    result = split_pages(
        [
            page(1, "1. 甲", _file_id="a", _order_uncertain=True),
            page(1, "续文", _file_id="b", _order_uncertain=True),
            page(1, "参考答案\n1. secret", _file_id="c", _order_uncertain=True),
        ]
    )
    assert len(result) == 2
    assert all(any("顺序" in w for w in c["warnings"]) for c in result)
    assert all(not any("配对建议：" in w for w in c["warnings"]) for c in result)
