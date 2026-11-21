"""保守的题号切分建议；答案区保留在原文，不自动拼入题面或结构化答案。"""

import re

NUMBER = re.compile(r"^\s*(\d{1,3})\s*[.．、](?!\d)\s*\S")
ANSWER_HEADING = re.compile(
    r"^\s*(?:参考答案|答案(?:与解析|及解析)?|参考解析|试题解析)\s*[:：]?\s*$"
)
INSTRUCTIONS_HEADING = re.compile(r"^\s*注意事项\s*[:：]?\s*$")
QUESTION_SECTION = re.compile(r"^\s*[一二三四五六七八九十]+、\s*(?:选择题|填空题|解答题)\s*[:：]")


def _answer_location(location):
    return f"文件 {location.get('file_id', '当前文件')} 页/片段 {location['page']} 行 {location['block']}"


def split_pages(pages):
    results, current, last_number = [], None, None
    answer_section = False
    answer_locations = {}
    question_numbers = {}
    previous_file = None
    saw_answers = False
    uncertain_order = any(page.get("_order_uncertain") for page in pages)

    def location(page, block):
        return {
            **({"file_id": page["_file_id"]} if "_file_id" in page else {}),
            "page": page["number"],
            "block": block,
        }

    def flush():
        nonlocal current
        if current is not None:
            current["text"] = current["text"].strip()
            results.append(current)
        current = None

    def fresh(page, block):
        return {
            "text": "",
            "locations": [location(page, block)],
            "warnings": list(page["warnings"]),
            "payload": page.get("_payload"),
        }

    for page in pages:
        file_id = page.get("_file_id")
        if file_id != previous_file:
            if uncertain_order or answer_section or page.get("_answer_file"):
                flush()
            elif current is not None:
                current["warnings"].append(
                    "跨文件续题建议：按上传顺序连接，须人工核对边界与文件顺序。"
                )
            answer_section = bool(page.get("_answer_file"))
            previous_file = file_id
        if answer_section:
            saw_answers = True
        if "_payload" in page:
            flush()
            item = fresh(page, None)
            item["text"] = page["text"]
            results.append(item)
            continue
        if not page["text"].strip() and not answer_section:
            flush()
            results.append(fresh(page, None))
            continue
        lines = list(enumerate(page["text"].splitlines(), start=1))
        instruction_starts = set()
        instruction_blocks = set()
        start = None
        for block, line in lines:
            if ANSWER_HEADING.match(line):
                start = None
            elif INSTRUCTIONS_HEADING.match(line):
                start = block
            elif start is not None and QUESTION_SECTION.match(line):
                instruction_starts.add(start)
                instruction_blocks.update(range(start, block + 1))
                start = None
        for block, line in lines:
            if ANSWER_HEADING.match(line):
                flush()
                answer_section = True
                saw_answers = True
            if answer_section:
                answer_number = NUMBER.match(line)
                if answer_number:
                    answer_locations.setdefault(int(answer_number[1]), []).append(
                        location(page, block)
                    )
                continue
            if block in instruction_starts:
                flush()
                current = fresh(page, block)
                current["warnings"].append("作答说明片段，请人工核对，无需作为题目导入。")
            match = NUMBER.match(line) if block not in instruction_blocks else None
            if match:
                flush()
                current = fresh(page, block)
                number = int(match[1])
                question_numbers[number] = question_numbers.get(number, 0) + 1
                if last_number is not None and number != last_number + 1:
                    current["warnings"].append("题号跳号或重复，请核对双栏阅读顺序与题目边界。")
                last_number = number
            if current is None:
                current = fresh(page, block)
                current["warnings"].append("未识别到明确题号，请人工确定边界。")
            if not any(
                loc["page"] == page["number"] and loc.get("file_id") == file_id
                for loc in current["locations"]
            ):
                current["locations"].append(location(page, block))
            current["warnings"] = list(dict.fromkeys(current["warnings"] + page["warnings"]))
            current["text"] += ("\n" if current["text"] else "") + line
    flush()
    bounded = []
    for item in results:
        if uncertain_order:
            item["warnings"].append("文件上传顺序无法确认，不自动跨文件合并或配答，请人工核对。")
        if saw_answers:
            item["warnings"].append(
                "检测到独立答案区：请在原文中人工核对题号并配对答案，尚未自动填入。"
            )
            number = NUMBER.match(item["text"])
            matches = answer_locations.get(int(number[1]), []) if number else []
            duplicate = number and question_numbers.get(int(number[1]), 0) > 1
            if duplicate:
                item["warnings"].append("题面存在重复题号，无法确定答案配对，请人工核对。")
            elif len(matches) == 1 and not uncertain_order:
                item["warnings"].append(
                    f"题号 {number[1]} 的答案配对建议：查看{_answer_location(matches[0])}，须人工确认，尚未填入答案。"
                )
            elif len(matches) > 1:
                refs = "；".join(_answer_location(match) for match in matches[:3])
                item["warnings"].append(
                    f"答案区存在重复题号，共 {len(matches)} 处，无法确定配对。请从以下位置人工核对：{refs}。"
                )
        if len(item["text"]) > 4000:
            item["warnings"].append("超长题已分成片段，请人工拆分为合规题目；不要直接逐片段导入。")
        for start in range(0, max(1, len(item["text"])), 4000):
            bounded.append({**item, "text": item["text"][start : start + 4000]})
    return bounded
