"""Design B: two independent readings, answer only when they agree, and the output number check (2-3)."""

import copy
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

import run_eval  # noqa: E402
from dart_review import crosscheck  # noqa: E402
from dart_review.baseline import read  # noqa: E402
from dart_review.cache import ResponseCache  # noqa: E402
from dart_review.client import DartClient  # noqa: E402
from dart_review.companies import DEV_COMPANIES, FS_DIVS  # noqa: E402
from dart_review.crosscheck import ReadingError, canonical, describe, model_to_reading, parse_model_reading  # noqa: E402
from dart_review.llm import Reply, ScriptedChat  # noqa: E402

QUESTIONS, GOLD = run_eval.load_questions("dev")
SPEC = {question["id"]: question for question in QUESTIONS}


def model_reading(question_id, **changes):
    """The structured reading a correct model would give for a development question."""
    expected = SPEC[question_id]["expected"]
    company = DEV_COMPANIES[expected["corp_code"]]
    if expected["action"] == "side_by_side":
        data = {"action": "side_by_side", "company": company, "basis": "연결", "account": expected["account"],
                "current_period": expected["period"], "base_period": expected["period"], "clarify_accounts": []}
    elif expected["action"] == "clarify":
        data = {"action": "clarify", "company": company, "basis": "연결", "account": "operating_income",
                "current_period": expected["current"], "base_period": expected["base"], "clarify_accounts": expected["options"]}
    else:
        data = {"action": "compare", "company": company, "basis": FS_DIVS[expected["fs_div"]], "account": expected["account"],
                "current_period": expected["current"], "base_period": expected["base"], "clarify_accounts": []}
    data.update(changes)
    return data


def reply(data):
    return Reply(json.dumps(data, ensure_ascii=False))


class ReadingTests(unittest.TestCase):
    def test_parse_model_reading(self):
        self.assertEqual(parse_model_reading(json.dumps(model_reading("dev01"), ensure_ascii=False))["action"], "compare")
        self.assertEqual(parse_model_reading(json.dumps(model_reading("dev01", action="unsupported")))["action"], "unsupported")
        for bad in ("x", "{}", json.dumps({**model_reading("dev01"), "action": "answer"}),
                    json.dumps({**model_reading("dev01"), "clarify_accounts": ["profit"]}),
                    # review B2: wrong types used to pass and crash canonical() with an unhashable list
                    *(json.dumps({**model_reading("dev01"), field: value}, ensure_ascii=False)
                      for field, value in (("account", []), ("basis", []), ("action", ["compare"]), ("company", 3),
                                           ("account", "profit"), ("basis", "합계"), ("current_period", "2025"),
                                           ("base_period", None)))):
            with self.subTest(bad=bad):
                with self.assertRaises(ReadingError):
                    parse_model_reading(bad)

    def test_same_reading_from_rules_and_model(self):
        for question_id in ("dev01", "dev02", "dev05", "dev06", "dev12"):
            with self.subTest(question_id=question_id):
                rule = read(SPEC[question_id]["question"])
                model = model_to_reading(model_reading(question_id))
                key = canonical(rule.kind, rule.arguments, rule.company, rule.options)
                self.assertIsNotNone(key)
                self.assertEqual(key, canonical(model.kind, model.arguments, model.company, model.options))

    def test_clarifying_readings_must_offer_the_same_candidates(self):
        # review B5: ("clarify", company) used to match any two candidate lists
        rule = read(SPEC["dev12"]["question"])
        same = model_to_reading(model_reading("dev12", clarify_accounts=["net_income", "operating_income"]))
        other = model_to_reading(model_reading("dev12", clarify_accounts=["revenue", "total_assets"]))
        rule_key = canonical(rule.kind, rule.arguments, rule.company, rule.options)
        self.assertEqual(rule_key, canonical(same.kind, same.arguments, same.company, same.options))
        self.assertNotEqual(rule_key, canonical(other.kind, other.arguments, other.company, other.options))
        self.assertIsNone(canonical("clarify", None, rule.company, ["net_income"]))  # one candidate is not a question

    def test_disagreement_names_the_company_when_the_readings_differ_in_it(self):
        samsung = model_to_reading(model_reading("dev01"))
        kakao = model_to_reading(model_reading("dev01", company="카카오"))
        question = crosscheck.disagreement_answer(samsung.company, samsung, kakao)["clarifying_question"]
        self.assertIn("① 삼성전자, ", question)
        self.assertIn("② 카카오, ", question)
        other_period = model_to_reading(model_reading("dev01", base_period={"kind": "year_to_date", "year": 2023, "month": 12}))
        self.assertNotIn("삼성전자", crosscheck.disagreement_answer(samsung.company, samsung, other_period)["clarifying_question"])

    def test_a_different_base_period_is_a_different_reading(self):
        rule = read(SPEC["dev01"]["question"])
        model = model_to_reading(model_reading("dev01", base_period={"kind": "year_to_date", "year": 2023, "month": 12}))
        self.assertNotEqual(canonical(rule.kind, rule.arguments, rule.company), canonical(model.kind, model.arguments, model.company))

    def test_readings_are_described_relative_to_the_current_period(self):
        self.assertIn("전년 같은 기간과", describe(read(SPEC["dev01"]["question"])))
        self.assertIn("직전 분기와", describe(read(SPEC["dev06"]["question"])))
        self.assertIn("나란히", describe(read(SPEC["dev05"]["question"])))

    def test_companies_outside_the_development_set(self):
        # EVAL_DESIGN 12.3: an evaluation company, another company, or several companies are out of scope
        for company in ("NAVER", "카카오뱅크", "카카오, 셀트리온"):
            with self.subTest(company=company):
                self.assertEqual(canonical("compare", model_reading("dev01"), company), ("unsupported", "company"))
        self.assertEqual(canonical("compare", model_reading("dev01"), "삼성"), ("clarify_company", "삼성"))
        self.assertIsNone(canonical("compare", model_reading("dev01"), "어느 회사"))


@unittest.skipUnless(run_eval.CACHE.exists(), "run scripts/fetch_dev_cache.py first")
class CrosscheckRunTests(unittest.TestCase):
    def setUp(self):
        self.client = DartClient(ResponseCache(run_eval.CACHE), key_loader=lambda: (_ for _ in ()).throw(AssertionError()), offline=True)

    def tearDown(self):
        self.assertEqual(self.client.network_requests, 0)

    def case(self, question_id, chat, question_text=None):
        question = copy.deepcopy(SPEC[question_id])
        if question_text:
            question["question"] = question_text
        return run_eval.run_case("crosscheck", question, GOLD[question_id], self.client, chat)

    def test_correct_readings_answer_every_question_with_one_request(self):
        def play(messages, tools, schema):
            question_id = next(key for key, value in SPEC.items() if value["question"] == messages[1]["content"])
            return reply(model_reading(question_id))

        cases, summary = run_eval.run("crosscheck", ScriptedChat(play), self.client)
        self.assertEqual(summary["automatic_passed"], {"correct": 13, "total": 13}, summary["failed"])
        self.assertEqual((summary["model_attempts"], summary["confident_wrong"], summary["ungrounded_numbers"]), (13, [], 0))
        self.assertTrue(all(case["readings"]["used"] == "both" for case in cases))

    def test_disagreement_asks_back_instead_of_answering(self):
        # the rules do not know "바로 앞 분기" and read a year-over-year comparison; a correct model reads the previous
        # quarter. (p06's "7~9월 … 4~6월보다" was this example until the rules learned two named periods.)
        record = self.case("dev06", ScriptedChat([reply(model_reading("dev06"))]), "카카오의 2023년 3분기 매출은 바로 앞 분기보다 얼마나 늘었어?")
        self.assertFalse(record["readings"]["agree"])
        self.assertEqual(record["answer"]["status"], "되묻기")
        self.assertIn("전년 같은 기간과", record["answer"]["clarifying_question"])
        self.assertIn("직전 분기와", record["answer"]["clarifying_question"])
        self.assertEqual(record["tool_call_count"], 0)
        summary = run_eval.summarize([record])
        self.assertEqual((summary["confident_wrong"], summary["asked_back_instead"]), ([], ["dev06"]))

    def test_rules_alone_do_not_answer_when_the_model_fails(self):
        # policy 2026-10-08 (review B4): with p06's wording the rules alone gave a confident wrong comparison
        for content in ("not json", json.dumps(model_reading("dev01", account=[]))):
            with self.subTest(content=content):
                record = self.case("dev06", ScriptedChat([Reply(content)]), "카카오의 2023년 3분기 매출은 바로 앞 분기보다 얼마나 늘었어?")
                self.assertEqual(record["readings"]["used"], "rule only (withheld)")
                self.assertIsNone(record["answer"])
                self.assertTrue(record["no_result"])
                self.assertEqual(record["tool_call_count"], 0)
                self.assertIn("모델 해석을 얻지 못해", record["withheld_reason"])

    def test_model_only_answers_start_with_the_reading(self):
        question = "삼성전자 2025년 판매 실적, 전년과 비교해 줘"  # the rules find no account ("판매 실적")
        record = self.case("dev01", ScriptedChat([reply(model_reading("dev01"))]), question)
        self.assertEqual(record["readings"]["used"], "model only")
        text = record["answer"]["answer"]
        self.assertTrue(text.startswith("이렇게 이해했습니다: 연결 기준 매출액, 2025년 연간(1~12월)을 전년 같은 기간과 비교."), text)
        self.assertNotIn("output_blocked", record)
        self.assertEqual(record["proposed_years"], [2024, 2025])

    def test_explicit_rules_only_mode_answers_with_a_note(self):
        record = {"tool_calls": [], "tool_call_count": 0, "seen": [], "no_result": False, "answer": None}
        crosscheck.crosscheck_turn(SPEC["dev01"]["question"], self.client, record, None)
        self.assertEqual(record["readings"]["used"], "rules only (--no-model)")
        self.assertIn("규칙 해석 하나로만", record["answer"]["answer"])
        self.assertEqual(record["answer"]["status"], "비교 가능")

    def test_the_reference_date_is_in_the_prompt_and_the_record(self):
        from datetime import date
        chat = ScriptedChat([reply(model_reading("dev01"))])
        record = {"tool_calls": [], "tool_call_count": 0, "seen": [], "no_result": False, "answer": None}
        crosscheck.crosscheck_turn(SPEC["dev01"]["question"], self.client, record, chat.chat, date(2026, 10, 8))
        system = chat.calls[0]["messages"][0]["content"] if hasattr(chat, "calls") and chat.calls else crosscheck.reading_prompt(date(2026, 10, 8))
        self.assertIn("기준 날짜는 2026-10-08이다", system)
        self.assertNotIn("{reference_date}", system)
        self.assertEqual(record["readings"]["reference_date"], "2026-10-08")


    def test_both_readings_fail(self):
        record = self.case("dev01", ScriptedChat([Reply("not json")]), "삼성전자 매출 알려줘")
        self.assertTrue(record["no_result"])
        self.assertFalse(record["score"]["automatic_passed"])

    def test_an_injected_number_is_withheld(self):
        # roadmap 2-3 completion criterion: an ungrounded number never reaches the output
        original = crosscheck.structured_answer

        def injected(result, explanation=None):
            answer = original(result, explanation)
            answer["answer"] += "\n영업이익률은 99.9%입니다."
            return answer

        with mock.patch.object(crosscheck, "structured_answer", injected):
            record = self.case("dev01", ScriptedChat([reply(model_reading("dev01"))]))
        self.assertEqual(record["output_blocked"], ["99.9%"])
        self.assertIsNone(record["answer"])
        self.assertIn("output withheld", record["score"]["format_error"])

    def test_markdown_report_has_only_grounded_numbers(self):
        from dart_review.render import markdown_report
        from dart_review.crosscheck import ungrounded_in_answer
        for question_id in SPEC:
            with self.subTest(question_id=question_id):
                record = self.case(question_id, ScriptedChat([reply(model_reading(question_id))]))
                result = record["seen"][-1] if record["seen"] else None
                report = markdown_report(record["answer"], result)
                self.assertIn("**검증 상태:**", report)
                as_answer = {"answer": report, "clarifying_question": None}
                self.assertEqual(ungrounded_in_answer(as_answer, record["seen"], SPEC[question_id]["question"]), [])
        record = self.case("dev01", ScriptedChat([reply(model_reading("dev01"))]))
        report = markdown_report(record["answer"], record["seen"][-1])
        self.assertIn("| 비교 기간 | 연결 | 2025년 연간(1~12월) | 333,605,938,000,000 |", report)

    def test_confident_wrong_answers_are_counted(self):
        question = copy.deepcopy(SPEC["dev06"])
        question["question"] = "카카오의 2023년 3분기 매출은 바로 앞 분기보다 얼마나 늘었어?"
        case = run_eval.run_case("baseline", question, GOLD["dev06"], self.client)
        self.assertEqual(run_eval.summarize([case])["confident_wrong"], ["dev06"])


@unittest.skipUnless(run_eval.CACHE.exists(), "run scripts/fetch_dev_cache.py first")
class UnsupportedAccountTests(unittest.TestCase):
    """Review B7/C1: an account outside the six is refused, never read as a supported one."""

    def setUp(self):
        self.client = DartClient(ResponseCache(run_eval.CACHE), key_loader=lambda: (_ for _ in ()).throw(AssertionError()), offline=True)

    def tearDown(self):
        self.assertEqual(self.client.network_requests, 0)

    def turn(self, question, content):
        record = {"tool_calls": [], "tool_call_count": 0, "seen": [], "no_result": False, "answer": None}
        crosscheck.crosscheck_turn(question, self.client, record, ScriptedChat([Reply(content)]).chat)
        return record

    def test_both_refuse(self):
        record = self.turn("삼성전자 2025년 유동자산을 전년 말과 비교해 줘.", json.dumps(model_reading("dev01", action="unsupported")))
        self.assertEqual(record["readings"]["used"], "both")
        self.assertEqual(record["answer"]["status"], "범위 밖")
        self.assertIn("다루지 않는 계정이라 답하지 않습니다: 유동자산", record["answer"]["answer"])
        self.assertEqual(record["tool_call_count"], 0)

    def test_the_review_counterexample_is_no_longer_answered(self):
        # the rules used to read 투자활동현금흐름 as 영업활동현금흐름; a model with the same misreading made it an answer
        record = self.turn("삼성전자 2025년 투자활동현금흐름을 전년과 비교해 줘", json.dumps(model_reading("dev01", account="operating_cash_flow")))
        self.assertEqual(record["readings"]["rule"]["kind"], "unsupported")
        self.assertEqual(record["readings"]["used"], "neither (asked back)")
        self.assertEqual(record["answer"]["status"], "되묻기")
        self.assertIn("다루지 않는 계정(투자활동현금흐름)을 묻는 질문", record["answer"]["clarifying_question"])
        self.assertEqual(record["tool_call_count"], 0)

    def test_a_model_refusal_against_a_rule_reading_asks_back(self):
        record = self.turn(SPEC["dev01"]["question"], json.dumps(model_reading("dev01", action="unsupported")))
        self.assertEqual(record["answer"]["status"], "되묻기")
        self.assertIn("다루지 않는 계정을 묻는 질문", record["answer"]["clarifying_question"])

    def test_the_rules_refuse_before_looking_for_a_year(self):
        record = self.turn("삼성전자 작년 이익잉여금이 재작년보다 늘었어?", json.dumps(model_reading("dev01", action="unsupported")))
        self.assertEqual(record["readings"]["rule"]["reason"], "지원하지 않는 계정: 이익잉여금")
        self.assertEqual(record["readings"]["used"], "both")

    def test_model_only_refusal(self):
        record = self.turn("Samsung Electronics 2025년 유동자산 전년 대비", json.dumps(model_reading("dev01", action="unsupported")))
        self.assertEqual(record["readings"]["rule"]["reason"], "회사 이름을 찾지 못함")
        self.assertEqual(record["readings"]["used"], "model only")
        self.assertEqual(record["answer"]["status"], "범위 밖")
        self.assertTrue(record["answer"]["answer"].startswith("이렇게 이해했습니다: 다루지 않는 계정을 묻는 질문."))


if __name__ == "__main__":
    unittest.main()
