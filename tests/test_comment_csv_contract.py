import csv
from pathlib import Path

import pytest

from tag_analyzer.comment_pipeline import PLCCommentPipeline


@pytest.mark.parametrize('name,scope,want_name,want_specifier,want_scope', [
    ('B3[0].0', 'Controller', 'B3', 'B3[0].0', ''),
    ('Local:2:I.Ch02.Data', 'Controller', 'Local:2:I', 'Local:2:I.Ch02.Data', ''),
    ('Timer.ACC', 'MainProgram', 'Timer', 'Timer.ACC', 'MainProgram'),
])
def test_operand_csv_uses_full_specifier(tmp_path, name, scope, want_name, want_specifier, want_scope):
    result = PLCCommentPipeline().generate_deliverables(
        decisions=[{'TYPE': 'Comment', 'SCOPE': scope, 'NAME': name,
                    'PROPOSED_DESCRIPTION': 'Run request'}], output_dir=tmp_path)
    rows = list(csv.reader(Path(result['csv_delta']).open(encoding='cp1252')))
    assert rows[4] == ['COMMENT', want_scope, want_name, 'Run request', '', want_specifier, '']


def test_controller_name_scope_is_blank_with_reference(tmp_path):
    source = tmp_path / 'source.L5X'
    source.write_text('<RSLogix5000Content><Controller Name="Plant"><Tags>'
                      '<Tag Name="Motor" DataType="BOOL"/></Tags></Controller></RSLogix5000Content>')
    result = PLCCommentPipeline().generate_deliverables(
        decisions=[{'TYPE': 'Tag', 'SCOPE': 'Plant', 'NAME': 'Motor',
                    'PROPOSED_DESCRIPTION': 'Motor running'}], file_path=source,
        output_dir=tmp_path / 'out')
    rows = list(csv.reader(Path(result['csv_delta']).open(encoding='cp1252')))
    assert rows[4][0:3] == ['TAG', '', 'Motor']


def test_comment_edit_does_not_claim_to_write_acd(tmp_path):
    source = tmp_path / 'source.ACD'
    source.write_bytes(b'unchanged')
    result = PLCCommentPipeline().generate_deliverables(
        decisions=[{'TYPE': 'Tag', 'NAME': 'Motor', 'PROPOSED_DESCRIPTION': 'Running'}],
        output_dir=tmp_path / 'out', target_acd=source, edit_acd=True)
    assert 'updated_acd' not in result
    assert 'not supported' in result['updated_acd_error'].lower()
    assert source.read_bytes() == b'unchanged'


def test_reference_excludes_routine_names_and_recovers_operand_scope(tmp_path):
    source = tmp_path / 'source.L5X'
    source.write_text('<RSLogix5000Content><Controller Name="Plant"><Tags>'
                      '<Tag Name="Timer" DataType="TIMER"/></Tags><Programs>'
                      '<Program Name="MainProgram"><Routines><Routine Name="Run"/>'
                      '</Routines></Program></Programs></Controller></RSLogix5000Content>')
    result = PLCCommentPipeline().generate_deliverables(decisions=[
        {'TYPE': 'Tag', 'SCOPE': 'Operand', 'NAME': 'Timer.ACC', 'PROPOSED_DESCRIPTION': 'Elapsed'},
        {'TYPE': 'Tag', 'NAME': 'Run', 'PROPOSED_DESCRIPTION': 'Run routine'},
    ], file_path=source, output_dir=tmp_path / 'out')
    rows = list(csv.reader(Path(result['csv_delta']).open(encoding='cp1252')))
    assert rows[4:] == [['COMMENT', '', 'Timer', 'Elapsed', '', 'Timer.ACC', '']]
    assert result['csv_excluded_decisions'][0]['NAME'] == 'Run'


def test_csv_description_escapes_literal_dollar_and_quotes(tmp_path):
    result = PLCCommentPipeline().generate_deliverables(decisions=[{
        'TYPE': 'TAG', 'NAME': 'Motor', 'PROPOSED_DESCRIPTION': 'Cost $5 "run"\nNext',
    }], output_dir=tmp_path)
    rows = list(csv.reader(Path(result['csv_delta']).open(encoding='cp1252')))
    assert rows[4][3] == 'Cost $$5 $Qrun$Q$NNext'
