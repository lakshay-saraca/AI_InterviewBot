"""Regression guards for the JD-config feature.

WHY: The new flow must not weaken two existing invariants:
(1) malformed XML from the interviewer LLM still falls back to acknowledge + raw text;
(2) a score_update parsed from the LLM still propagates to running_scores -> final report.
"""
from src.services.llm.response_parser import parse_xml_response


def test_malformed_xml_falls_back_to_acknowledge():
    parsed = parse_xml_response("total garbage, no tags here")
    assert parsed.action == "acknowledge"
    assert parsed.spoken_text == "total garbage, no tags here"
    assert parsed.next_state == "questioning"


def test_score_update_is_parsed_and_propagates():
    raw = """
    <interviewer_response>
      <action>acknowledge</action>
      <spoken_text>Thanks.</spoken_text>
      <internal_notes>solid</internal_notes>
      <confidence>0.9</confidence>
      <score_update>
        <topic>python</topic>
        <score>8</score>
        <reasoning>clear</reasoning>
      </score_update>
      <next_state>questioning</next_state>
      <flags></flags>
    </interviewer_response>
    """
    parsed = parse_xml_response(raw)
    assert parsed.score == 8.0
    assert parsed.score_topic == "python"
    # turn_manager writes running_scores[topic] = score (see turn_manager.process_answer),
    # and llm_service.generate_final_evaluation passes question_results into the report.
