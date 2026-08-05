"""Shared fixtures/helpers for comment_graph unit tests."""

import textwrap
from pathlib import Path

import pytest


def write_l5x(path: Path, *, tags_xml: str = "", rungs_xml: str = "") -> Path:
    """Write a minimal but ``inventory_l5x``-compatible L5X file.

    ``tags_xml`` goes inside ``<Tags>``; ``rungs_xml`` inside the single
    MainProgram/MainRoutine ``<RLLContent>``.
    """
    content = textwrap.dedent(
        """\
        <?xml version="1.0" encoding="UTF-8"?>
        <RSLogix5000Content SchemaRevision="1.0">
          <Controller Name="Test">
            <Tags>
        {tags}
            </Tags>
            <Programs>
              <Program Name="MainProgram">
                <Routines>
                  <Routine Name="MainRoutine" Type="RLL">
                    <RLLContent>
        {rungs}
                    </RLLContent>
                  </Routine>
                </Routines>
              </Program>
            </Programs>
          </Controller>
        </RSLogix5000Content>
        """
    ).format(tags=tags_xml, rungs=rungs_xml)
    path.write_text(content, encoding="utf-8")
    return path


def rung_xml(number: int, text: str, comment: str = "") -> str:
    comment_el = f"<Comment><![CDATA[{comment}]]></Comment>" if comment else ""
    return (
        f'<Rung Number="{number}" Type="N">{comment_el}'
        f"<Text><![CDATA[{text}]]></Text></Rung>"
    )


def tag_xml(name: str, data_type: str = "INT", operand_comments: dict | None = None) -> str:
    comments = ""
    if operand_comments:
        inner = "".join(
            f'<Comment Operand="{op}"><![CDATA[{txt}]]></Comment>'
            for op, txt in operand_comments.items()
        )
        comments = f"<Comments>{inner}</Comments>"
    return f'<Tag Name="{name}" TagType="Base" DataType="{data_type}">{comments}</Tag>'


@pytest.fixture
def l5x_factory(tmp_path):
    counter = {"n": 0}

    def make(tags_xml: str = "", rungs_xml: str = "") -> Path:
        counter["n"] += 1
        path = tmp_path / f"synthetic_{counter['n']}.L5X"
        return write_l5x(path, tags_xml=tags_xml, rungs_xml=rungs_xml)

    return make
